import os
import re
import shutil
from collections import Counter
from pathlib import Path

from ..coverage_mapper import read_cobertura
from ..evaluation import Outcome
from .process import CommandError, run

JAVA_ID = r"[A-Za-z_][A-Za-z_0-9]*"
CLASS_ID = rf"{JAVA_ID}(?:\.{JAVA_ID})*"
TEST_ID = re.compile(rf"{CLASS_ID}::{JAVA_ID}")
JUNIT_DISPLAY = re.compile(rf"({JAVA_ID})\(({CLASS_ID})\)")
HELPER = Path(__file__).with_name("InspectJava.java")

PERL_MODULES = ("DBD::CSV", "DBI", "JSON", "JSON::Parse", "List::Util",
                "Perl::Critic", "String::Interpolate", "URI")
TOOLS = {
    "java": ("-version",), "javac": ("-version",), "git": ("--version",),
    "svn": ("--version", "--quiet"), "perl": ("-e", "print $^V"), "cpanm": ("--version",),
    "ant": ("-version",),
}


def lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def check_environment(executable: str) -> dict:
    checks = {}
    for name, args in TOOLS.items():
        try:
            result = run([name, *args], timeout=15)
            output = lines(result.stdout + result.stderr)
            checks[name] = {"ok": True, "version": output[0] if output else "",
                            "path": shutil.which(name)}
        except CommandError as exc:
            checks[name] = {"ok": False, "reason": str(exc)}
    modules = {}
    if checks["perl"]["ok"]:
        for name in PERL_MODULES:
            try:
                run(["perl", f"-M{name}", "-e", "1"], timeout=15)
                modules[name] = True
            except CommandError:
                modules[name] = False
    java_11 = bool(re.search(r'\bversion "11(?:[."]|$)', checks["java"].get("version", "")))
    javac_11 = bool(re.search(r"\bjavac 11(?:\.|$)", checks["javac"].get("version", "")))
    try:
        info = run([executable, "info", "-p", "Lang"], timeout=30)
        cli = {"ok": True, "info_lang": info.stdout.strip()}
        try:
            env = run([executable, "env"], timeout=30)
            cli["environment"] = (env.stdout + env.stderr).strip()
        except CommandError as exc:
            cli["environment_error"] = str(exc)
    except CommandError as exc:
        cli = {"ok": False, "reason": str(exc)}
    return {"tools": checks, "perl_modules": modules, "java_11": java_11,
            "javac_11": javac_11, "defects4j": cli,
            "ready_for_smoke": cli["ok"] and "environment" in cli and java_11 and javac_11}


class Defects4J:
    def __init__(self, executable: str, timeout: float, logs: Path):
        resolved = shutil.which(executable)
        if not resolved:
            raise CommandError(f"Defects4J não encontrado: {executable}. Execute doctor.")
        self.executable = str(Path(resolved).resolve())
        self.timeout = timeout
        self.logs = logs
        self.counter = 0
        self.env = {**os.environ, "TZ": "America/Los_Angeles", "D4J_DEBUG": "0"}

    def _run(self, argv, label, *, cwd=None):
        self.counter += 1
        log = self.logs / f"{self.counter:06d}-{label}.log"
        return run(argv, cwd=cwd, timeout=self.timeout, env=self.env, log=log)

    def command(self, action, *args, cwd=None):
        return self._run([self.executable, action, *args], action, cwd=cwd)

    def checkout(self, project, version, dest):
        self.command("checkout", "-p", project, "-v", version, "-w", str(dest))

    def export(self, key, work):
        return self.command("export", "-p", key, cwd=work).stdout.strip()

    def exports_path(self, key, work):
        value = self.export(key, work)
        path = (work / value).resolve()
        if not value or not path.is_relative_to(work.resolve()) or not path.is_dir():
            raise CommandError(f"{key} não aponta para um diretório válido: {value!r}")
        return path

    def inspect_java(self, items, inputs, cwd, *, encoding="UTF-8"):
        if not items:
            return []
        inputs.write_text("\n".join(map(str, items)) + "\n", encoding="utf-8")
        jvm = ["java", "-Duser.timezone=America/Los_Angeles", "-Dfile.encoding=UTF-8"]
        result = self._run([*jvm, str(HELPER), "methods", str(inputs), encoding],
                           "methods", cwd=cwd)
        return lines(result.stdout)

    def discover(self, work):
        self.command("test", cwd=work)
        raw = self._test_events(work)
        tests = [parse_test_display(row) for row in raw]
        counts = Counter(tests)
        runnable = [test for test in tests if test and counts[test] == 1]
        skipped = [row for row, test in zip(raw, tests) if not test or counts[test] != 1]
        return runnable, skipped

    def test(self, work, test):
        self._validate_test(test)
        result = self.command("test", "-t", test, cwd=work)
        self._single_execution(work, result, test)
        failures = tuple(self._failures(work))
        count = re.search(r"^Failing tests: (\d+)\s*$", result.stdout, re.M)
        if count is None or int(count[1]) != len(failures):
            raise CommandError(f"Resultados discordantes para {test}. Consulte {result.log}")
        if any(failure != test for failure in failures):
            raise CommandError(f"Falha de classe ou seleção para {test}. Consulte {result.log}")
        return Outcome(test, result.seconds, failures)

    def coverage(self, work, test, instrument):
        self._validate_test(test)
        xml = work / "coverage.xml"
        xml.unlink(missing_ok=True)
        result = self.command("coverage", "-t", test, "-i", str(instrument), cwd=work)
        self._single_execution(work, result, test)
        if self._failures(work):
            raise CommandError(f"Teste falhou durante a cobertura de fixed: {test}. {result.log}")
        if not xml.is_file():
            raise CommandError(f"Cobertura ausente para {test}. Consulte {result.log}")
        try:
            report = read_cobertura(xml)
        except (OSError, ValueError, KeyError, SyntaxError) as exc:
            raise CommandError(f"Cobertura inválida para {test}. {result.log}: {exc}") from exc
        if not report.executable:
            raise CommandError(f"Instrumentação sem linhas executáveis. Consulte {result.log}")
        return report

    @staticmethod
    def _validate_test(test):
        if not TEST_ID.fullmatch(test):
            raise ValueError(f"Esperado Classe::metodo: {test!r}")

    @staticmethod
    def _single_execution(work, result, test):
        if [parse_test_display(row) for row in Defects4J._test_events(work)] != [test]:
            raise CommandError(f"Execução não confirmou exatamente um teste para {test}. {result.log}")

    @staticmethod
    def _test_events(work):
        path = work / "all_tests"
        return lines(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else []

    @staticmethod
    def _failures(work):
        path = work / "failing_tests"
        if not path.is_file():
            return []
        return [row[4:].strip() for row in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if row.startswith("--- ")]


def parse_test_display(row):
    match = JUNIT_DISPLAY.fullmatch(row)
    if match and match[1] not in {"initializationError", "warning"}:
        return f"{match[2]}::{match[1]}"
    return None
