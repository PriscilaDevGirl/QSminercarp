from collections.abc import Iterable
from math import isfinite
from statistics import median


def execution_cost(samples: Iterable[float]) -> float:
    """Estime o custo com tempos positivos coletados na versão fixed."""
    values = tuple(samples)
    if not values or any(not isfinite(value) or value <= 0 for value in values):
        raise ValueError("Amostras de duração ausentes ou inválidas")
    return median(values)
