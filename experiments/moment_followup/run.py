"""Execute o estudo exploratório de acompanhamento do QS Miner."""

import argparse
from pathlib import Path
from random import Random
from statistics import median
import subprocess
from tempfile import TemporaryDirectory

from experiments.moment_4417.run import SEEDS, VERSIONS, lcov, outcome, prepare
from qsminer.benchmark import rank
from qsminer.change_analyzer import analyze, fixed_lines
from qsminer.core import RankingInput, TestProfile
from qsminer.dataset import encode_profile
from qsminer.evaluation import evaluate
from qsminer.history_analyzer import execution_cost
from qsminer.reporting import write_json, write_metrics


HARNESS = Path(__file__).resolve().with_name("cases.cjs")
TESTS = tuple(f"t{i:02d}" for i in range(1, 14))
BLOCKS = (137, 271, 509)


def run(buggy, fixed, out):
    out.mkdir(parents=True, exist_ok=False)
    raw_dir = out / "lcov"
    raw_dir.mkdir()
    node = subprocess.check_output(["node", "--version"], text=True).strip()
    with TemporaryDirectory(prefix="qsminer-followup-") as temp:
        roots = {name: Path(temp) / name for name in VERSIONS}
        for name, source in (("buggy", buggy), ("fixed", fixed)):
            prepare(source, roots[name], VERSIONS[name][1])
        changes = analyze(roots["buggy"], roots["fixed"], ".js")
        changed = fixed_lines(changes)
        samples, profiles, executable = {}, [], set()
        for test in TESTS:
            observations = [outcome(roots["fixed"], test, HARNESS) for _ in range(5)]
            if any(item.failures for item in observations):
                raise RuntimeError(f"{test} falhou em fixed")
            samples[test] = [item.seconds for item in observations]
            lines, raw = lcov(roots["fixed"], test, HARNESS)
            (raw_dir / f"{test}.info").write_text(raw, encoding="utf-8")
            executable.update(lines)
            covered = frozenset(element for element, count in lines.items() if count > 0)
            profiles.append(TestProfile(test, execution_cost(samples[test]), covered))

        data = RankingInput(tuple(profiles), changed & executable)
        orders = rank(data, SEEDS)
        write_json(out / "profile.json", encode_profile(data))
        write_json(out / "changes.json", changes)
        write_json(out / "fixed_timings.json", samples)
        write_json(out / "rankings.json", orders)
        write_json(out / "provenance.json", {
            "project": "moment/moment", "node": node, "versions": VERSIONS,
            "test_count": len(TESTS), "changed_lines": len(changed),
            "changed_lines_in_lcov": len(data.changed), "block_seeds": BLOCKS,
        })
        print("Perfil e ordens gravados", flush=True)

        oracle = {"4417": {"t05", "t08", "t09"}, "4698": {"t11", "t12", "t13"}}
        expected = set().union(*oracle.values())
        write_json(out / "oracle.json", {key: sorted(tests) for key, tests in oracle.items()})
        rows = []
        for block in BLOCKS:
            schedule = list(orders)
            Random(block).shuffle(schedule)
            executions = {}
            for strategy in schedule:
                order = orders[strategy]
                observations = [outcome(roots["buggy"], test, HARNESS) for test in order]
                executions[strategy] = observations
                observed = {failure for item in observations for failure in item.failures}
                if observed != expected:
                    write_json(out / f"block-{block}.json", executions)
                    raise RuntimeError(f"Falhas inesperadas no bloco {block}, {strategy}: {sorted(observed)}")
                for issue, triggers in oracle.items():
                    rows.append({"issue": issue, "block": block, "strategy": strategy,
                                 **evaluate(order, observations, triggers)})
            write_json(out / f"block-{block}.json", executions)
            write_metrics(out / "metrics.csv", rows)
            print(f"Bloco {block} concluído", flush=True)

        summaries = []
        for issue in oracle:
            for strategy in orders:
                group = [row for row in rows if row["issue"] == issue and row["strategy"] == strategy]
                ms = [row["time_to_first_seconds"] * 1000 for row in group]
                positions = {row["first_rank"] for row in group}
                if len(positions) != 1:
                    raise RuntimeError(f"Posição instável em {issue}, {strategy}")
                summaries.append({"issue": issue, "strategy": strategy, "first_rank": positions.pop(),
                                  "median_ms": median(ms), "min_ms": min(ms), "max_ms": max(ms),
                                  "apfd": group[0]["apfd"],
                                  "median_apfdc": median(row["apfdc"] for row in group)})
        write_metrics(out / "summary.csv", summaries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("buggy", "fixed", "out"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    args = parser.parse_args()
    run(args.buggy, args.fixed, args.out)


if __name__ == "__main__":
    main()
