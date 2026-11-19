from dataclasses import dataclass
from math import fsum, isfinite


@dataclass(frozen=True)
class Outcome:
    test: str
    seconds: float
    failures: tuple[str, ...] = ()

    def __post_init__(self):
        if not isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("Duração observada inválida")


def evaluate(order: list[str], outcomes: list[Outcome], oracle: set[str]) -> dict:
    """Meça detecção de um único defeito e preserve execuções sem detecção."""
    if not oracle:
        raise ValueError("Oráculo vazio")
    if not order or len(set(order)) != len(order) or order != [row.test for row in outcomes]:
        raise ValueError("Resultados devem acompanhar uma ordem completa sem duplicatas")
    total = fsum(result.seconds for result in outcomes)
    for index, outcome in enumerate(outcomes):
        detected = sorted({outcome.test} & set(outcome.failures) & oracle)
        if detected:
            elapsed = fsum(result.seconds for result in outcomes[:index + 1])
            return {
                "detected": True,
                "first_rank": index + 1,
                "first_test": outcome.test,
                "time_to_first_seconds": elapsed,
                "total_seconds": total,
                "apfd": 1 - (index + 0.5) / len(order),
                "apfdc": min(1.0, fsum([outcome.seconds / 2,
                                        *(row.seconds for row in outcomes[index + 1:])]) / total),
            }
    return dict(detected=False, first_rank=None, first_test=None,
                time_to_first_seconds=None, total_seconds=total, apfd=None, apfdc=None)
