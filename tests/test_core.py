import json
import random
import tempfile
import unittest
from pathlib import Path

from qsminer.baselines import greedy
from qsminer.benchmark import rank
from qsminer.change_analyzer import analyze, fixed_lines
from qsminer.core import Element, RankingInput, TestProfile
from qsminer.dataset import read_profile
from qsminer.evaluation import Outcome, evaluate


ROOT = Path(__file__).resolve().parents[1]


class RankingTests(unittest.TestCase):
    def test_synthetic_profile_carp_and_baselines(self):
        data = read_profile(ROOT / "datasets" / "synthetic_profile.json")
        orders = rank(data, (17, 23))
        short = lambda order: [name.split("::")[1] for name in order]
        self.assertEqual(short(orders["carp"]), ["quick", "edge", "unrelated", "expensive"])
        self.assertEqual(orders["original"][0], "example.PriceTest::expensive")
        self.assertEqual(orders["total"][0], orders["original"][0])
        self.assertEqual(orders["fastest"][0], "example.PriceTest::unrelated")
        self.assertEqual(orders, rank(data, (17, 23)))
        for order in orders.values():
            self.assertCountEqual(order, [p.test for p in data.tests])

    def test_heap_matches_naive_marginal_gain(self):
        rng = random.Random(233)
        elements = [Element("a", line) for line in range(1, 14)]
        for _ in range(40):
            profiles = tuple(TestProfile(str(i), rng.randint(1, 7),
                                         frozenset(rng.sample(elements, rng.randint(0, 13))))
                             for i in range(15))
            scope = frozenset(rng.sample(elements, rng.randint(0, 13)))
            for cost_aware in (False, True):
                available, expected, uncovered = list(profiles), [], set(scope)
                while available:
                    def key(profile):
                        gain = len(profile.covered & uncovered)
                        cost = profile.seconds if cost_aware else 1
                        return (-gain / cost, -gain, cost, profile.test)

                    winner = min(available, key=key)
                    uncovered.difference_update(winner.covered)
                    expected.append(winner.test)
                    available.remove(winner)
                self.assertEqual(greedy(RankingInput(profiles, scope), scope=scope,
                                        cost_aware=cost_aware), expected)

    def test_offline_schema_rejects_oracle(self):
        source = json.loads((ROOT / "datasets" / "synthetic_profile.json").read_text())
        source["tests"][0]["trigger"] = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_profile(path)

    def test_deleted_lines_are_not_in_fixed_coordinate_system(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "b", Path(folder) / "f"
            old.mkdir()
            new.mkdir()
            (old / "Diff.java").write_bytes(b"a\nb\nc\nd\n")
            (new / "Diff.java").write_bytes(b"a\r\nc\r\nD\r\n")
            (old / "Deleted.java").write_bytes(b"removed\n")
            (new / "Added.java").write_bytes(b"added\n")
            changes = analyze(old, new)
            self.assertEqual([change.path for change in changes], ["Added.java", "Deleted.java", "Diff.java"])
            self.assertEqual([(r.kind, r.old_start, r.new_count) for r in changes[2].regions],
                             [("delete", 2, 0), ("replace", 4, 1)])
            self.assertEqual(fixed_lines(changes), {Element("Diff.java", 3), Element("Added.java", 1)})


class EvaluationTests(unittest.TestCase):
    def test_single_defect_metrics_with_observed_failures(self):
        order = ["non-oracle", "trigger", "other"]
        outcomes = [Outcome("non-oracle", 1, ("non-oracle",)), Outcome("trigger", 2, ("trigger",)),
                    Outcome("other", 5)]
        result = evaluate(order, outcomes, {"trigger"})
        self.assertEqual(result["first_rank"], 2)
        self.assertEqual(result["time_to_first_seconds"], 3)
        self.assertEqual(result["apfd"], 0.5)
        self.assertEqual(result["apfdc"], 0.75)

    def test_trigger_without_observed_failure_does_not_detect(self):
        result = evaluate(["trigger"], [Outcome("trigger", 1)], {"trigger"})
        self.assertFalse(result["detected"])
        self.assertIsNone(result["apfd"])
        self.assertIsNone(result["apfdc"])
