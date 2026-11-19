import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import perf_counter

from . import change_analyzer
from .adapters.defects4j import Defects4J, lines
from .adapters.process import CommandError
from .baselines import rankings
from .core import Element, RankingInput, TestProfile
from .dataset import encode_profile
from .evaluation import evaluate
from .history_analyzer import execution_cost
from .prioritization import carp
from .reporting import write_json, write_metrics


@dataclass(frozen=True)
class Case:
    project: str
    bug: int

    def __post_init__(self):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", self.project) is None or self.bug < 1:
            raise ValueError(f"Caso inválido: {self.project}-{self.bug}")


@dataclass(frozen=True)
class Settings:
    seeds: tuple[int, ...]
    repeats: int
    schedule_seed: int
    timeout: float
    encoding: str
    manifest: tuple[str, ...] | None = None


def rank(data, seeds):
    return {"carp": carp(data), **rankings(data, seeds)}


def run_case(case: Case, settings: Settings, out: Path, executable: str) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    logs = out / "logs"
    logs.mkdir()
    state = {"project": case.project, "bug": case.bug, "status": "running",
             "phase": "environment", "settings": settings, "python": platform.python_version(),
             "platform": platform.platform(), "warnings": [], "excluded_fixed": {}}
    started = perf_counter()
    write_json(out / "status.json", state)
    try:
        adapter = Defects4J(executable, settings.timeout, logs)
        with TemporaryDirectory(prefix="qsminer-") as temp:
            work = Path(temp).resolve()
            # A implementação Perl chama Ant e Git por shell com caminhos sem aspas.
            if os.name == "posix" and any(
                not re.fullmatch(r"[-A-Za-z0-9_./]+", str(path))
                for path in (work, adapter.executable)
            ):
                raise CommandError("Instalação do Defects4J e TMPDIR precisam de caminhos compatíveis com o shell do framework")
            state = experiment(adapter, case, settings, work, out, state)
    except (OSError, RuntimeError, ValueError) as exc:
        state.update(status="infrastructure_error", error=str(exc))
    state["elapsed_seconds"] = perf_counter() - started
    write_json(out / "status.json", state)
    return state


def experiment(adapter, case, settings, work, out, state):
    # O status é gravado antes de cada fase para tornar interrupções visíveis.
    phase_started = perf_counter()
    durations = state.setdefault("phase_seconds", {})

    def phase(name):
        nonlocal phase_started
        now = perf_counter()
        previous = state.get("phase", "environment")
        durations[previous] = now - phase_started
        phase_started = now
        state["phase"] = name
        write_json(out / "status.json", state)

    env = adapter.command("env")
    state["defects4j_environment"] = (env.stdout + env.stderr).strip()
    phase("checkout")
    buggy, fixed = work / "buggy", work / "fixed"
    adapter.checkout(case.project, f"{case.bug}b", buggy)
    adapter.checkout(case.project, f"{case.bug}f", fixed)
    adapter.command("compile", cwd=fixed)
    adapter.command("compile", cwd=buggy)

    phase("changes")
    old_root = adapter.exports_path("dir.src.classes", buggy)
    new_root = adapter.exports_path("dir.src.classes", fixed)
    changes = change_analyzer.analyze(old_root, new_root)
    changed = change_analyzer.fixed_lines(changes)
    methods = {}
    for label, root in (("buggy", old_root), ("fixed", new_root)):
        try:
            methods[label] = changed_methods(adapter, changes, label, root, work, settings.encoding)
        except CommandError as exc:
            state["warnings"].append(f"Métodos {label}: {exc}")
            methods[label] = None
    write_json(out / "changes.json", {"files": changes, "methods": methods})

    phase("discover")
    all_fixed = set(lines(adapter.export("tests.all", fixed)))
    all_buggy = set(lines(adapter.export("tests.all", buggy)))
    if settings.manifest is None:
        candidates, skipped = adapter.discover(fixed)
        state["unsupported_test_events"] = skipped
    else:
        candidates = list(settings.manifest)
    common_classes = all_fixed & all_buggy
    tests = [test for test in candidates if test.partition("::")[0] in common_classes]
    state["candidate_source"] = "fixed all_tests" if settings.manifest is None else "manifest"
    state["classes_missing_from_exports"] = sorted(set(candidates) - set(tests))
    if not tests:
        raise CommandError("Nenhum teste individual selecionável nas duas versões")

    phase("profile")
    samples = {}
    # Todas as medições são feitas antes de o Cobertura modificar a área fixed.
    for test in tests:
        try:
            observations = [adapter.test(fixed, test) for _ in range(settings.repeats)]
            if any(row.failures for row in observations):
                raise CommandError("falha de teste na versão fixed")
            samples[test] = [row.seconds for row in observations]
        except CommandError as exc:
            state["excluded_fixed"][test] = str(exc)
    write_json(out / "fixed_timings.json", samples)
    bytecode = adapter.exports_path("dir.bin.classes", fixed)
    classes = sorted(".".join(path.relative_to(bytecode).with_suffix("").parts)
                     for path in bytecode.rglob("*.class")
                     if path.is_file() and path.stem not in {"package-info", "module-info"})
    instrument = work / "instrument.txt"
    if not classes:
        raise CommandError("O diretório de bytecode de produção está vazio")
    instrument.write_bytes(("\n".join(classes) + "\n").encode("utf-8"))
    (out / "instrument.txt").write_bytes(instrument.read_bytes())

    profiles, executable, branches = [], set(), set()
    for test, times in samples.items():
        try:
            report = adapter.coverage(fixed, test, instrument)
        except CommandError as exc:
            state["excluded_fixed"][test] = str(exc)
            continue
        profiles.append(TestProfile(test, execution_cost(times), report.covered))
        executable.update(report.executable)
        branches.update(report.branch_lines)
    if not profiles:
        raise CommandError("Nenhum teste obteve duração e cobertura válidas em fixed")
    data = RankingInput(tuple(profiles), changed & executable)
    write_json(out / "profile.json", encode_profile(data))
    write_json(out / "coverage_scope.json", {
        "executable": sorted(executable), "changed_executable": sorted(data.changed),
        "changed_unmapped": sorted(changed - executable), "changed_branch_lines": sorted(changed & branches),
    })
    state["comparable_tests"] = len(profiles)
    if not data.changed:
        state["warnings"].append("Nenhuma linha alterada executável mapeada em fixed")

    phase("ranking")
    orders = rank(data, settings.seeds)
    write_json(out / "rankings.json", orders)

    phase("evaluation")
    # Estes resultados e metadados só são consultados depois de gravar a ordem.
    oracle = set(lines(adapter.export("tests.trigger", buggy)))
    if not oracle:
        raise CommandError("O benchmark forneceu um oráculo vazio")
    state["oracle_outside_profile"] = sorted(oracle - {p.test for p in data.tests})
    write_json(out / "oracle.json", sorted(oracle))
    try:
        modified = lines(adapter.export("classes.modified", fixed))
        relevant = lines(adapter.export("tests.relevant", fixed))
        write_json(out / "benchmark_metadata.json", {"modified_classes": modified, "relevant_tests": relevant})
    except CommandError as exc:
        state["warnings"].append(str(exc))

    schedule = list(orders)
    Random(settings.schedule_seed).shuffle(schedule)
    state["schedule"] = schedule
    status = "completed"
    failure_sets = []
    metrics = []
    for index, method in enumerate(schedule, 1):
        order = orders[method]
        outcomes = []
        try:
            for test in order:
                outcomes.append(adapter.test(buggy, test))
        finally:
            write_json(out / f"executions-{index:02d}.json", {
                "strategy": method, "planned_size": len(order), "outcomes": outcomes,
            })
        failure_sets.append(frozenset(failure for row in outcomes for failure in row.failures))
        metrics.append({"project": case.project, "bug": case.bug, "strategy": method,
                        **evaluate(order, outcomes, oracle)})
    if len(set(failure_sets)) > 1:
        status = "unstable"
    elif not any(row["detected"] for row in metrics):
        status = "not_reproduced"
    elif state["oracle_outside_profile"] or not oracle <= failure_sets[0]:
        status = "partially_reproduced"
    for row in metrics:
        row["case_status"] = status
    write_metrics(out / "metrics.csv", metrics)
    phase("finished")
    state["status"] = status
    return state


def changed_methods(adapter, changes, label, root, scratch, encoding):
    is_fixed = label == "fixed"
    files = {change.path: change for change in changes
             if (change.new_exists if is_fixed else change.old_exists)}
    records = adapter.inspect_java([root / path for path in files],
                                   scratch / f"{label}-sources.txt", root, encoding=encoding)
    methods = []
    for row in records:
        tag, filename, first, last, signature = row.split("\t", 4)
        if tag != "METHOD":
            raise ValueError(f"Registro Java inválido: {tag}")
        path = Path(filename).relative_to(root).as_posix()
        change = files[path]
        for region in change.regions:
            start, count = ((region.new_start, region.new_count) if is_fixed
                            else (region.old_start, region.old_count))
            if count and int(first) < start + count and int(last) >= start:
                methods.append({"path": path, "start": int(first), "end": int(last),
                                "signature": signature})
                break
    return sorted(methods, key=lambda row: (row["path"], row["start"], row["signature"]))
