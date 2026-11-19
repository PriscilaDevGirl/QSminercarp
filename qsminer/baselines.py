from collections import defaultdict
from collections.abc import Iterable
from heapq import heapify, heappop, heappush
from random import Random

from .core import RankingInput


def greedy(data: RankingInput, *, scope, cost_aware: bool) -> list[str]:
    """Ganhos marginais sobre a união de elementos ainda não cobertos."""
    coverage = {profile.test: profile.covered & scope for profile in data.tests}
    costs = {profile.test: profile.seconds if cost_aware else 1 for profile in data.tests}
    gains = {test: len(elements) for test, elements in coverage.items()}
    covering_tests = defaultdict(list)
    for test, elements in coverage.items():
        for element in elements:
            covering_tests[element].append(test)

    def entry(test):
        gain, cost = gains[test], costs[test]
        return (-gain / cost, -gain, cost, test)

    heap = [entry(test) for test in gains]
    heapify(heap)
    order = []
    while heap:
        _, negative_gain, _, winner = heappop(heap)
        if gains.get(winner) != -negative_gain:
            continue
        order.append(winner)
        del gains[winner]
        affected = set()
        for element in coverage[winner]:
            for test in covering_tests.pop(element, ()):
                if test in gains:
                    gains[test] -= 1
                    affected.add(test)
        for test in affected:
            heappush(heap, entry(test))
    return order


def rankings(data: RankingInput, seeds: Iterable[int]) -> dict[str, list[str]]:
    original = [profile.test for profile in data.tests]
    global_scope = frozenset().union(*(profile.covered for profile in data.tests))
    orders = {
        "original": original,
        "fastest": [p.test for p in sorted(data.tests, key=lambda p: (p.seconds, p.test))],
        "total": [p.test for p in sorted(data.tests, key=lambda p: (-len(p.covered), p.test))],
        "additional": greedy(data, scope=global_scope, cost_aware=False),
        "change_additional": greedy(data, scope=data.changed, cost_aware=False),
    }
    for seed in seeds:
        order = sorted(original)
        Random(seed).shuffle(order)
        orders[f"random:{seed}"] = order
    return orders
