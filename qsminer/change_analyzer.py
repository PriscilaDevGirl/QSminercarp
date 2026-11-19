from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .core import Element


@dataclass(frozen=True)
class Region:
    kind: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(frozen=True)
class FileChange:
    path: str
    old_exists: bool
    new_exists: bool
    regions: tuple[Region, ...]


def analyze(old_root: Path, new_root: Path, suffix: str = ".java") -> tuple[FileChange, ...]:
    """Compare caminhos relativos à raiz de fontes de cada revisão."""
    for root in (old_root, new_root):
        if not root.is_dir():
            raise ValueError(f"Raiz de fontes inexistente: {root}")

    def files(root):
        return {p.relative_to(root).as_posix(): p for p in root.rglob("*" + suffix)
                if p.is_file()}

    old, new = files(old_root), files(new_root)
    changes = []
    for path in sorted(old.keys() | new.keys()):
        before = old[path].read_bytes().splitlines() if path in old else []
        after = new[path].read_bytes().splitlines() if path in new else []
        if before == after and (path in old) == (path in new):
            continue
        matcher = SequenceMatcher(None, before, after, autojunk=False)
        regions = tuple(Region(tag, i + 1, j - i, k + 1, end - k)
                        for tag, i, j, k, end in matcher.get_opcodes() if tag != "equal")
        changes.append(FileChange(path, path in old, path in new, regions))
    return tuple(changes)


def fixed_lines(changes: tuple[FileChange, ...]) -> frozenset[Element]:
    return frozenset(
        Element(change.path, line)
        for change in changes
        for region in change.regions
        for line in range(region.new_start, region.new_start + region.new_count)
    )
