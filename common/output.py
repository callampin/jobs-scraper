"""Escritura consistente de los archivos JSON de ofertas."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from common.dates import isoformat_z, parse_iso_datetime
from common.jobs import validate_jobs


def dated_output_path(output_dir: Path, source: str, now: datetime) -> Path:
    timestamp = isoformat_z(now).replace(":", "").replace("-", "")
    # Formato compacto y ordenable: 20261115T123000Z.json
    filename = f"{source}_{timestamp}.json"
    return output_dir / filename


def sort_jobs(jobs: list[dict]) -> list[dict]:
    """Ordena por publicación descendente, dejando fechas ausentes al final."""
    minimum = datetime.min.replace(tzinfo=timezone.utc)

    def publication_date(job: dict) -> datetime:
        value = job.get("published_at")
        return parse_iso_datetime(value) if value else minimum

    return sorted(jobs, key=publication_date, reverse=True)


def write_jobs_json(jobs: list[dict], output_path: Path) -> Path:
    """Valida y reemplaza el JSON de forma atómica, sin dejarlo truncado."""
    validate_jobs(jobs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(sort_jobs(jobs), ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, output_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    return output_path
