from dataclasses import dataclass
from math import isfinite
from pathlib import PurePosixPath


@dataclass(frozen=True, order=True)
class Element:
    path: str
    line: int

    def __post_init__(self):
        path = PurePosixPath(self.path)
        if (path.is_absolute() or ".." in path.parts or not path.parts
                or "\\" in self.path or path.as_posix() != self.path):
            raise ValueError(f"Caminho de cobertura inválido: {self.path!r}")
        if type(self.line) is not int or self.line < 1:
            raise ValueError("A linha deve ser um inteiro positivo")


@dataclass(frozen=True)
class TestProfile:
    test: str
    seconds: float
    covered: frozenset[Element]

    def __post_init__(self):
        if not isinstance(self.test, str) or not self.test.strip():
            raise ValueError("Identificador de teste vazio ou inválido")
        if (isinstance(self.seconds, bool) or not isinstance(self.seconds, (int, float))
                or not isfinite(self.seconds) or self.seconds <= 0):
            raise ValueError(f"Custo inválido para {self.test}")


@dataclass(frozen=True)
class RankingInput:
    tests: tuple[TestProfile, ...]
    changed: frozenset[Element]

    def __post_init__(self):
        names = {profile.test for profile in self.tests}
        if not names or len(names) != len(self.tests):
            raise ValueError("Forneça uma suíte não vazia, sem testes duplicados")
