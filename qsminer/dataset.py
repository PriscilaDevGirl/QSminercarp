import json
from pathlib import Path

from .core import Element, RankingInput, TestProfile


def encode_profile(data: RankingInput) -> dict:
    return {
        "schema_version": 1,
        "changed": [[element.path, element.line] for element in sorted(data.changed)],
        "tests": [{
            "test": profile.test,
            "seconds": profile.seconds,
            "covered": [[item.path, item.line] for item in sorted(profile.covered)],
        } for profile in data.tests],
    }


def read_profile(path: Path) -> RankingInput:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "changed", "tests"}:
        raise ValueError("Campos esperados: schema_version, changed, tests")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("schema_version esperada: 1")

    def elements(rows):
        if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
            for row in rows
        ):
            raise ValueError("Cada elemento deve ser [caminho, linha]")
        return frozenset(Element(*row) for row in rows)

    profiles = []
    if not isinstance(doc["tests"], list):
        raise ValueError("tests deve ser uma lista")
    for row in doc["tests"]:
        if not isinstance(row, dict) or set(row) != {"test", "seconds", "covered"}:
            raise ValueError("Campos de teste esperados: test, seconds, covered")
        profiles.append(TestProfile(row["test"], row["seconds"], elements(row["covered"])))
    return RankingInput(tuple(profiles), elements(doc["changed"]))
