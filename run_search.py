#!/usr/bin/env python3
"""Ejecuta los conectores disponibles y consolida una búsqueda actual."""

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aggregate import aggregate_files
from common.jobs import validate_jobs

LOGGER = logging.getLogger("run_search")
JOBS_OUTPUT = PROJECT_ROOT / "jobs.json"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    script: Path
    blocked_reason: str | None = None


@dataclass(frozen=True)
class SearchOptions:
    query: str
    days: int
    location: str
    max_results: int | None = None


SOURCE_SPECS = (
    SourceSpec(
        "get_on_board",
        "Get on Board",
        PROJECT_ROOT / "1.get_on_board" / "scraper.py",
    ),
    SourceSpec(
        "chiletrabajos",
        "Chiletrabajos",
        PROJECT_ROOT / "2.chiletrabajos" / "scraper.py",
    ),
    SourceSpec(
        "computrabajo_chile",
        "Computrabajo",
        PROJECT_ROOT / "3.computrabajo_chile" / "scraper.py",
        blocked_reason=(
            "WAF HTTP 403; documentado para retomarlo con Apify o una vía autorizada"
        ),
    ),
    SourceSpec(
        "laborum",
        "Laborum",
        PROJECT_ROOT / "4.laborum" / "scraper.py",
    ),
    SourceSpec(
        "trabajando_cl",
        "Trabajando",
        PROJECT_ROOT / "5.trabajando_cl" / "scraper.py",
    ),
)

Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def build_command(
    source: SourceSpec,
    options: SearchOptions,
    *,
    executable: str = sys.executable,
) -> list[str]:
    command = [
        executable,
        str(source.script),
        "--query",
        options.query,
        "--location",
        options.location,
        "--days",
        str(options.days),
    ]
    if options.max_results is not None:
        command.extend(["--max-results", str(options.max_results)])
    return command


def run_subprocess(
    command: Sequence[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta el conector dejando sus logs visibles en stderr en tiempo real."""
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )
    try:
        stdout, _ = process.communicate()
    except KeyboardInterrupt:
        process.terminate()
        process.wait(timeout=10)
        raise
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=process.returncode,
        stdout=stdout,
        stderr=None,
    )


def parse_output_path(stdout: str) -> Path:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("El conector no imprimió la ruta de su archivo de resultados")
    path = Path(lines[-1])
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"El conector indicó un archivo inexistente: {path}")
    return path


def validate_source_output(path: Path, expected_source: str) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer el resultado {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"El resultado {path} no es una lista JSON")
    validate_jobs(payload)
    wrong_sources = sorted(
        {
            job["source"]
            for job in payload
            if job["source"] != expected_source
        }
    )
    if wrong_sources:
        raise RuntimeError(
            f"El archivo {path} contiene fuentes inesperadas: {wrong_sources}"
        )
    return len(payload)


def execute_search(
    options: SearchOptions,
    *,
    specs: Sequence[SourceSpec] = SOURCE_SPECS,
    runner: Runner = run_subprocess,
    output_path: Path = JOBS_OUTPUT,
    aggregator: Callable[[list[Path], Path], tuple[int, int]] = aggregate_files,
) -> dict:
    """Ejecuta fuentes disponibles y sólo consolida si todas terminan bien."""
    if not options.query.strip():
        raise ValueError("La palabra clave no puede estar vacía")
    if not options.location.strip():
        raise ValueError("La ubicación no puede estar vacía")
    if options.days < 1:
        raise ValueError("days debe ser mayor o igual que 1")
    if options.max_results is not None and options.max_results < 1:
        raise ValueError("max-results debe ser mayor o igual que 1")

    available = [spec for spec in specs if spec.blocked_reason is None]
    if not available:
        raise RuntimeError("No hay conectores disponibles para ejecutar")

    results: list[tuple[SourceSpec, Path, int]] = []
    blocked: list[tuple[SourceSpec, str]] = []

    for spec in specs:
        if spec.blocked_reason is not None:
            LOGGER.warning("%s: OMITIDO. %s", spec.label, spec.blocked_reason)
            blocked.append((spec, spec.blocked_reason))
            continue
        if not spec.script.is_file():
            raise RuntimeError(f"No existe el scraper de {spec.label}: {spec.script}")

        LOGGER.info("=" * 72)
        LOGGER.info("Ejecutando %s", spec.label)
        command = build_command(spec, options)
        completed = runner(command, PROJECT_ROOT)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{spec.label} terminó con código {completed.returncode}; "
                "jobs.json no fue modificado"
            )
        result_path = parse_output_path(completed.stdout or "")
        count = validate_source_output(result_path, spec.key)
        results.append((spec, result_path, count))
        LOGGER.info("%s: %d ofertas -> %s", spec.label, count, result_path)

    paths = [path for _, path, _ in results]
    LOGGER.info("=" * 72)
    LOGGER.info("Todos los conectores disponibles terminaron; consolidando resultado")
    total, duplicates = aggregator(paths, output_path)

    summary = {
        "query": options.query,
        "days": options.days,
        "location": options.location,
        "max_results": options.max_results,
        "sources": {spec.key: count for spec, _, count in results},
        "blocked": {spec.key: reason for spec, reason in blocked},
        "outputs": [str(path) for _, path, _ in results],
        "total": total,
        "duplicates_discarded": duplicates,
        "jobs_json": str(output_path.resolve()),
    }

    LOGGER.info("Búsqueda completada")
    for spec, _, count in results:
        LOGGER.info("  %s: %d", spec.label, count)
    for spec, reason in blocked:
        LOGGER.info("  %s: omitido (%s)", spec.label, reason)
    LOGGER.info("  Total consolidado: %d", total)
    LOGGER.info("  jobs.json: %s", output_path.resolve())
    return summary


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("debe ser mayor o igual que 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ejecuta los conectores disponibles y genera jobs.json."
    )
    parser.add_argument("--query", required=True, help="Cargo, tecnología o búsqueda libre")
    parser.add_argument(
        "--days",
        type=_positive_int,
        default=30,
        help="Antigüedad máxima en días (por defecto: 30)",
    )
    parser.add_argument(
        "--location",
        default="Chile",
        help="Chile o una ciudad/región; por defecto, Chile",
    )
    parser.add_argument(
        "--max-results",
        type=_positive_int,
        default=None,
        help="Máximo opcional por cada portal (no es un máximo total)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    options = SearchOptions(
        query=args.query.strip(),
        days=args.days,
        location=args.location.strip(),
        max_results=args.max_results,
    )

    try:
        summary = execute_search(options)
    except KeyboardInterrupt:
        LOGGER.error("Búsqueda interrumpida; jobs.json no fue reemplazado")
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        LOGGER.error("Búsqueda fallida: %s", exc)
        LOGGER.error("jobs.json conserva la búsqueda anterior")
        return 1

    print(summary["jobs_json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
