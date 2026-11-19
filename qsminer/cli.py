import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

from .adapters.defects4j import TEST_ID, check_environment, lines
from .adapters.process import run
from .benchmark import Case, Settings, rank, run_case
from .change_analyzer import analyze
from .dataset import read_profile
from .reporting import write_json, write_metrics

DEFAULT_SEEDS = "17,23,47,83,101"


def emit(data, path=None):
    if path is None:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, data)


def seeds(value):
    try:
        parsed = tuple(map(int, value.split(",")))
        if len(set(parsed)) != len(parsed):
            raise ValueError
        return parsed
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Forneça sementes inteiras distintas separadas por vírgula") from exc


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Forneça um inteiro positivo")
    return number


def duration(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Forneça um tempo limite positivo e finito")
    return number


def build_parser():
    parser = argparse.ArgumentParser(prog="qsminer", description="Priorização de testes de regressão")
    actions = parser.add_subparsers(dest="action", required=True)

    doctor = actions.add_parser("doctor", help="Verificar pré-requisitos e executar defects4j info")
    doctor.add_argument("--defects4j", default="defects4j")
    doctor.add_argument("--out", type=Path)

    catalog = actions.add_parser("catalog", help="Consultar projetos ou IDs da instalação ativa")
    catalog.add_argument("--defects4j", default="defects4j")
    catalog.add_argument("--project")
    catalog.add_argument("--deprecated", action="store_true")
    catalog.add_argument("--out", type=Path)

    diff = actions.add_parser("diff", help="Comparar duas árvores de código-fonte")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)
    diff.add_argument("--suffix", default=".java")
    diff.add_argument("--out", type=Path, required=True)

    offline = actions.add_parser("rank", help="Priorizar um perfil sem acesso ao oráculo")
    offline.add_argument("profile", type=Path)
    offline.add_argument("--out", type=Path)
    offline.add_argument("--seeds", type=seeds, default=DEFAULT_SEEDS)

    single = actions.add_parser("run", help="Executar todas as estratégias para um defeito")
    single.add_argument("--project", required=True)
    single.add_argument("--bug", required=True, type=positive)
    single.add_argument("--manifest", type=Path, help="Lista pré-registrada de Classe::metodo")
    batch = actions.add_parser("batch", help="Executar casos de um CSV project,bug")
    batch.add_argument("cases", type=Path)
    for action in (single, batch):
        action.add_argument("--out", type=Path, required=True, help="Diretório novo para os resultados")
        action.add_argument("--defects4j", default="defects4j")
        action.add_argument("--seeds", type=seeds, default=DEFAULT_SEEDS)
        action.add_argument("--schedule-seed", type=int, default=137)
        action.add_argument("--repeats", type=positive, default=3)
        action.add_argument("--timeout", type=duration, default=900, help="Limite em segundos por comando")
        action.add_argument("--encoding", default="UTF-8", help="Codificação dos fontes para javac")
    return parser


def read_cases(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["project", "bug"]:
            raise ValueError("Cabeçalho esperado: project,bug")
        cases = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Linha inválida no CSV: {reader.line_num}")
            cases.append(Case(row["project"].strip(), int(row["bug"])))
    if not cases or len(cases) != len(set(cases)):
        raise ValueError("O lote deve conter casos únicos")
    return cases


def experiment_settings(args):
    manifest = None
    if getattr(args, "manifest", None):
        manifest = tuple(lines(args.manifest.read_text(encoding="utf-8-sig")))
        if not manifest or len(set(manifest)) != len(manifest) or any(
                not TEST_ID.fullmatch(test) for test in manifest):
            raise ValueError("Manifesto precisa de testes únicos em formato Classe::metodo")
    return Settings(args.seeds, args.repeats, args.schedule_seed, args.timeout,
                    args.encoding, manifest)


def dispatch(args):
    if args.action == "doctor":
        result = check_environment(args.defects4j)
        emit(result, args.out)
        return 0 if result["ready_for_smoke"] else 1
    if args.action == "catalog":
        if args.project:
            Case(args.project, 1)
            argv = ["bids", "-p", args.project] + (["-D"] if args.deprecated else [])
        elif args.deprecated:
            raise ValueError("--deprecated requer --project")
        else:
            argv = ["pids"]
        values = run([args.defects4j, *argv], timeout=30).stdout.split()
        pattern = r"[0-9]+" if args.project else r"[A-Za-z][A-Za-z0-9]*"
        if any(not re.fullmatch(pattern, item) for item in values):
            raise ValueError("Formato inesperado do catálogo Defects4J")
        emit(values, args.out)
        return 0
    if args.action == "rank":
        emit(rank(read_profile(args.profile), args.seeds), args.out)
        return 0
    if args.action == "diff":
        emit(analyze(args.old, args.new, args.suffix), args.out)
        return 0

    settings = experiment_settings(args)
    target = args.out.resolve()
    if args.action == "run":
        status = run_case(Case(args.project, args.bug), settings, target, args.defects4j)
        emit({"status": status["status"], "phase": status["phase"],
              "output": str(target), "error": status.get("error")})
        return 1 if status["status"] != "completed" else 0

    cases = read_cases(args.cases)
    target.mkdir(parents=True, exist_ok=False)
    summaries = []
    metrics = []
    for case in cases:
        name = f"{case.project}-{case.bug}"
        status = run_case(case, settings, target / name, args.defects4j)
        summaries.append({"project": case.project, "bug": case.bug, "directory": name,
                          "status": status["status"], "phase": status["phase"],
                          "error": status.get("error")})
        write_json(target / "batch_status.json", summaries)
        csv_path = target / name / "metrics.csv"
        if csv_path.is_file():
            with csv_path.open(newline="", encoding="utf-8") as stream:
                metrics.extend(csv.DictReader(stream))
        print(f"{name} {status['status']}", file=sys.stderr, flush=True)
    if metrics:
        write_metrics(target / "metrics.csv", metrics)
    return 1 if any(row["status"] != "completed" for row in summaries) else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"qsminer: {exc}", file=sys.stderr)
        return 2
