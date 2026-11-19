import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path


def write_json(path: Path, data) -> None:
    def encode(value):
        if is_dataclass(value):
            return asdict(value)
        raise TypeError(f"Tipo não serializável: {type(value).__name__}")

    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False,
                               default=encode) + "\n", encoding="utf-8")
    temp.replace(path)


def write_metrics(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Não há métricas para exportar")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
