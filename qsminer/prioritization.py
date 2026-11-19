from .baselines import greedy
from .core import RankingInput


def carp(data: RankingInput) -> list[str]:
    """Priorize pelo número de linhas alteradas inéditas por segundo estimado."""
    return greedy(data, scope=data.changed, cost_aware=True)
