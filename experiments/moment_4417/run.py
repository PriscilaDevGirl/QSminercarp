"""Reproduza o piloto real do defeito Moment.js #4417 com Node.js."""

import argparse
from base64 import b64decode
from hashlib import sha1
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from qsminer.benchmark import rank
from qsminer.change_analyzer import analyze, fixed_lines
from qsminer.core import Element, RankingInput, TestProfile
from qsminer.dataset import encode_profile
from qsminer.evaluation import Outcome, evaluate
from qsminer.history_analyzer import execution_cost
from qsminer.reporting import write_json, write_metrics


TESTS = tuple(f"t{i:02d}" for i in range(1, 10))
VERSIONS = {
    "buggy": ("2.22.2", "1c18684e35ee095982cfbcbf65b07202c51af49c"),
    "fixed": ("2.23.0", "3ec5d3d54b3779c6338ee1b79500f330326af6ee"),
}
HARNESS = Path(__file__).resolve().with_name("cases.cjs")
SEEDS = (17, 23, 47, 83, 101)


def prepare(source, destination, blob):
    content = source.read_bytes()
    if source.suffix == ".b64":
        content = b64decode(content)
    git_prefix = f"blob {len(content)}".encode() + bytes([0])
    if sha1(git_prefix + content).hexdigest() != blob:
        raise ValueError(f"Hash do artefato oficial não confere: {source}")
    destination.mkdir()
    (destination / "moment.js").write_bytes(content)


def invoke(root, test, *options, harness=HARNESS):
    env = {key: val for key, val in os.environ.items()
           if key not in {"NODE_OPTIONS", "NODE_V8_COVERAGE"}}
    env.update(QSMINER_MOMENT=str(root / "moment.js"), TZ="UTC")
    return subprocess.run(
        ["node", "--test", f"--test-name-pattern=^{test}$", *options, str(harness)],
        cwd=root, env=env, capture_output=True, encoding="utf-8", timeout=20,
    )


def outcome(root, test, harness=HARNESS):
    result = invoke(root, test, "--test-reporter=tap", harness=harness)
    output = result.stdout
    one_test = re.search(r"^# tests 1$", output, re.M)
    selected = re.search(rf"^(?:not )?ok 1 - {test}$", output, re.M)
    duration = re.search(r"^  duration_ms: ([0-9]+(?:\.[0-9]+)?)$", output, re.M)
    if not (one_test and selected and duration):
        raise RuntimeError(f"Falha do executor para {test}:\n{output}\n{result.stderr}")
    failed = selected[0].startswith("not ok")
    consistent_status = result.returncode == int(failed)
    assertion_failed = re.search(r"^  code: 'ERR_ASSERTION'$", output, re.M)
    if not consistent_status or (failed and not assertion_failed):
        raise RuntimeError(f"Falha fora das asserções em {test}:\n{output}\n{result.stderr}")
    return Outcome(test, float(duration[1]) / 1000, (test,) if failed else ())


def lcov(root, test, harness=HARNESS):
    result = invoke(root, test, "--experimental-test-coverage",
                    "--test-coverage-include=moment.js", "--test-reporter=lcov", harness=harness)
    if result.returncode:
        raise RuntimeError(f"Falha na cobertura de {test}:\n{result.stdout}\n{result.stderr}")
    active = False
    counts = {}
    for line in result.stdout.splitlines():
        if line.startswith("SF:"):
            active = Path(line[3:]).name == "moment.js"
        elif active and line.startswith("DA:"):
            number, hits, *_ = line[3:].split(",")
            counts[Element("moment.js", int(number))] = int(hits)
        elif line == "end_of_record":
            active = False
    if not counts or not any(counts.values()):
        raise RuntimeError(f"Relatório LCOV de produção ausente para {test}")
    return counts, result.stdout


def run(fixed, buggy, out):
    out.mkdir(parents=True, exist_ok=False)
    raw_dir = out / "lcov"
    raw_dir.mkdir()
    node = subprocess.check_output(["node", "--version"], text=True).strip()
    with TemporaryDirectory(prefix="qsminer-moment-") as folder:
        roots = {name: Path(folder) / name for name in VERSIONS}
        prepare(buggy, roots["buggy"], VERSIONS["buggy"][1])
        prepare(fixed, roots["fixed"], VERSIONS["fixed"][1])

        changes = analyze(roots["buggy"], roots["fixed"], ".js")
        changed = fixed_lines(changes)
        samples, profiles, executable = {}, [], set()
        for test in TESTS:
            measured = [outcome(roots["fixed"], test) for _ in range(5)]
            if any(row.failures for row in measured):
                raise RuntimeError(f"{test} falhou na versão fixed")
            samples[test] = [row.seconds for row in measured]
            counts, raw_lcov = lcov(roots["fixed"], test)
            (raw_dir / f"{test}.info").write_text(raw_lcov, encoding="utf-8")
            executable.update(counts)
            covered = frozenset(element for element, hits in counts.items() if hits > 0)
            profiles.append(TestProfile(test, execution_cost(samples[test]), covered))

        data = RankingInput(tuple(profiles), changed & executable)
        orders = rank(data, SEEDS)
        write_json(out / "changes.json", changes)
        write_json(out / "fixed_timings.json", samples)
        write_json(out / "profile.json", encode_profile(data))
        write_json(out / "rankings.json", orders)
        write_json(out / "provenance.json", {
            "project": "moment/moment", "issue": 4417, "node": node,
            "case_selection": "Projeto presente na mineração. Correção histórica escolhida fora dos merges minerados.",
            "versions": {name: {"tag": tag, "moment_js_blob": blob}
                         for name, (tag, blob) in VERSIONS.items()},
            "test_count": len(TESTS), "changed_lines": len(changed),
            "changed_lines_in_lcov": len(data.changed),
            "timing": "Duração da subprova reportada pelo node:test. Mediana de cinco medições para fixed.",
        })

        # O changelog descreve datas inválidas em isBetween. As três asserções
        # correspondentes formam o oráculo do mesmo defeito, usado só na avaliação.
        oracle = {"t05", "t08", "t09"}
        write_json(out / "oracle.json", sorted(oracle))
        rows, executions = [], {}
        for strategy, order in orders.items():
            observations = [outcome(roots["buggy"], test) for test in order]
            observed = {failure for row in observations for failure in row.failures}
            if observed != oracle:
                raise RuntimeError(f"Reprodução inesperada em {strategy}: {sorted(observed)}")
            executions[strategy] = observations
            rows.append({"strategy": strategy, **evaluate(order, observations, oracle)})
        write_json(out / "executions.json", executions)
        write_metrics(out / "metrics.csv", rows)
        for row in rows:
            print(f"{row['strategy']:18} posição {row['first_rank']} | APFD {row['apfd']:.4f}")
        print(f"Resultados gravados em {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--buggy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.fixed, args.buggy, args.out)


if __name__ == "__main__":
    main()
