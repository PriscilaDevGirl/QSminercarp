import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qsminer.adapters.defects4j import Defects4J
from qsminer.adapters.process import CommandError, Result, run
from qsminer.benchmark import Case, Settings, experiment
from qsminer.coverage_mapper import read_cobertura

TEST_A = "demo.PriceTest::normal"
TEST_B = "demo.PriceTest::trigger"


def display(test):
    cls, _, method = test.partition("::")
    return f"{method}({cls})"


class InterfaceFixture:
    """Simula os arquivos e saídas do CLI. Nenhum projeto do benchmark é baixado."""
    def __init__(self, output, *, confirm_trigger=True, extra_event=False):
        self.output = output
        self.confirm_trigger = confirm_trigger
        self.extra_event = extra_event
        self.buggy_actions = []

    def __call__(self, argv, *, cwd, timeout, env, log):
        if argv[0] == "java":
            return run(argv, cwd=cwd, timeout=timeout, env=env)
        name, *args = argv[1:]
        stdout = ""
        seconds = 1.0
        if name == "checkout":
            dest = Path(args[5])
            (dest / "src" / "demo").mkdir(parents=True)
            (dest / "bin" / "demo").mkdir(parents=True)
            value = "1" if dest.name == "buggy" else "2"
            source = "package demo;\nclass Price {\n int price() {\n  return " + value + ";\n }\n}\n"
            (dest / "src" / "demo" / "Price.java").write_text(source, encoding="utf-8")
            (dest / "bin" / "demo" / "Price.class").touch()
        elif name == "export":
            key = args[1]
            if key == "tests.trigger":
                assert (self.output / "rankings.json").is_file()
                self.buggy_actions.append("oracle")
            stdout = {"dir.src.classes": "src", "dir.bin.classes": "bin", "tests.all": "demo.PriceTest",
                      "tests.trigger": TEST_B, "classes.modified": "demo.Price",
                      "tests.relevant": "demo.PriceTest"}[key]
        elif name == "test":
            if args:
                test = args[1]
                (cwd / "all_tests").write_text(display(test), encoding="utf-8")
                if cwd.name == "buggy":
                    self.buggy_actions.append(test)
                failure = cwd.name == "buggy" and test == TEST_B and self.confirm_trigger
                (cwd / "failing_tests").write_text(f"--- {test}\n" if failure else "", encoding="utf-8")
                stdout = "Failing tests: " + ("1\n" if failure else "0\n")
                seconds = 1.0 if test == TEST_B else 3.0
            else:
                (cwd / "all_tests").write_text("\n".join([display(TEST_A), display(TEST_B),
                    "param[0](demo.PriceTest)"]) + "\n", encoding="utf-8")
                stdout = "Failing tests: 0\n"
        elif name == "coverage":
            test = args[1]
            self.assert_instrument(args)
            events = [display(test), display(TEST_A)] if self.extra_event else [display(test)]
            (cwd / "all_tests").write_text("\n".join(events), encoding="utf-8")
            (cwd / "failing_tests").write_text("", encoding="utf-8")
            hits = 1 if test == TEST_B else 0
            (cwd / "coverage.xml").write_text(
                '<coverage><packages><package><classes><class filename="demo/Price.java"><lines>'
                f'<line number="4" hits="{hits}" branch="true"/><line number="5" hits="1"/>'
                '</lines></class></classes></package></packages></coverage>', encoding="utf-8")
        elif name not in {"compile", "env"}:
            raise AssertionError(f"Comando inesperado: {argv}")
        return Result(stdout, "", seconds, log)

    @staticmethod
    def assert_instrument(args):
        assert args[:1] == ["-t"] and args[2] == "-i"
        assert Path(args[3]).read_bytes() == b"demo.Price\n"


class BenchmarkTests(unittest.TestCase):
    def exercise(self, root, **flags):
        out = Path(root) / "out"
        out.mkdir()
        work = Path(root) / "work"
        work.mkdir()
        fixture = InterfaceFixture(out, **flags)
        with patch("qsminer.adapters.defects4j.run", side_effect=fixture):
            adapter = Defects4J(shutil.which("python"), 60, out)
            settings = Settings((17,), 2, 19, 60, "UTF-8")
            state = experiment(adapter, Case("Lang", 1), settings, work, out,
                               {"warnings": [], "excluded_fixed": {}})
        return out, state, fixture

    def test_orders_are_frozen_before_oracle_and_executed_in_order(self):
        with tempfile.TemporaryDirectory() as temp:
            out, state, fixture = self.exercise(temp)
            self.assertEqual(state["status"], "completed")
            orders = json.loads((out / "rankings.json").read_text())
            self.assertEqual(orders["carp"], [TEST_B, TEST_A])
            self.assertEqual(fixture.buggy_actions,
                             ["oracle"] + [test for name in state["schedule"] for test in orders[name]])
            self.assertIn("param[0](demo.PriceTest)", state["unsupported_test_events"])
            self.assertNotIn("oracle", (out / "profile.json").read_text())
            with (out / "metrics.csv").open(newline="", encoding="utf-8") as stream:
                rows = {row["strategy"]: row for row in csv.DictReader(stream)}
            self.assertEqual(rows["carp"]["first_rank"], "1")
            self.assertEqual(rows["original"]["first_rank"], "2")
            self.assertEqual(rows["carp"]["time_to_first_seconds"], "1.0")
            if shutil.which("java"):
                methods = json.loads((out / "changes.json").read_text())["methods"]["fixed"]
                self.assertEqual(methods[0]["signature"], "demo.Price#price()")

    def test_buggy_passing_trigger_is_reported_as_not_reproduced(self):
        with tempfile.TemporaryDirectory() as temp:
            _, state, _ = self.exercise(temp, confirm_trigger=False)
            self.assertEqual(state["status"], "not_reproduced")

    def test_multiple_test_events_are_a_profile_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(CommandError, "duração e cobertura válidas"):
                self.exercise(temp, extra_event=True)
            state = json.loads((Path(temp) / "out" / "status.json").read_text())
            self.assertEqual(state["phase"], "profile")

    def test_cobertura_merges_source_lines_across_classes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "coverage.xml"
            path.write_text(
                '<coverage><packages><package><classes>'
                '<class filename="C.java"><lines><line number="7" hits="0"/></lines></class>'
                '<class filename="C.java"><lines><line number="7" hits="9" branch="true"/></lines></class>'
                '</classes></package></packages></coverage>', encoding="utf-8")
            result = read_cobertura(path)
            self.assertEqual(result.covered, result.executable)
            self.assertEqual(result.branch_lines, result.covered)
            self.assertEqual(len(result.covered), 1)
