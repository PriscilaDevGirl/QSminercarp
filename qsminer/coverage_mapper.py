import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .core import Element


@dataclass(frozen=True)
class Coverage:
    executable: frozenset[Element]
    covered: frozenset[Element]
    branch_lines: frozenset[Element]


def read_cobertura(xml: Path) -> Coverage:
    root = ET.parse(xml).getroot()
    if root.tag != "coverage":
        raise ValueError(f"XML Cobertura inválido: {xml}")
    executable, covered, branches = set(), set(), set()
    for cls in root.findall("./packages/package/classes/class"):
        path = cls.attrib["filename"].replace("\\", "/")
        for row in cls.findall("./lines/line"):
            element = Element(path, int(row.attrib["number"]))
            hits = int(row.attrib["hits"])
            if hits < 0:
                raise ValueError(f"Número de hits inválido: {element}")
            executable.add(element)
            if hits:
                covered.add(element)
            if row.get("branch") == "true":
                branches.add(element)
    return Coverage(frozenset(executable), frozenset(covered), frozenset(branches))
