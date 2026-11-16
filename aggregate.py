#!/usr/bin/env python3
"""Combina los JSON actuales de los conectores en una única lista jobs.json."""

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from common.jobs import JobDeduplicator, validate_job
from common.output import write_jobs_json

LOGGER = logging.getLogger("aggregate")


def aggregate_files(input_paths: list[Path], output_path: Path) -> tuple[int, int]:
    combined: list[dict] = []
    duplicates = 0
    deduplicators: dict[str, JobDeduplicator] = defaultdict(JobDeduplicator)

    for path in input_paths:
        with path.open(encoding="utf-8") as input_file:
            payload = json.load(input_file)
        if not isinstance(payload, list):
            raise ValueError(f"{path} debe contener una lista JSON")
        LOGGER.info("Leyendo %s: %d ofertas", path, len(payload))

        for item in payload:
            validate_job(item)
            if not deduplicators[item["source"]].add(item):
                duplicates += 1
                continue
            combined.append(item)

    write_jobs_json(combined, output_path)
    return len(combined), duplicates


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Genera jobs.json solo con los archivos de la búsqueda actual."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Rutas exactas de los JSON producidos por los conectores",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("jobs.json"),
        help="Archivo consolidado (por defecto: jobs.json)",
    )
    args = parser.parse_args()

    try:
        total, duplicates = aggregate_files(args.inputs, args.output)
    except (OSError, TypeError, ValueError) as exc:
        LOGGER.error("No se pudo generar el consolidado: %s", exc)
        return 1

    LOGGER.info("Consolidado: %d ofertas, %d duplicadas descartadas", total, duplicates)
    LOGGER.info("Archivo guardado: %s", args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
