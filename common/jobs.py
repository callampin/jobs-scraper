"""Esquema de salida y deduplicación por conector."""

from collections.abc import Iterable
from urllib.parse import urldefrag

from common import JOB_FIELDS
from common.dates import parse_iso_datetime

_TEXT_FIELDS = (
    "source",
    "job_id",
    "title",
    "company",
    "location",
    "salary",
    "published_at",
    "url",
    "description",
    "scraped_at",
)
_ALLOWED_MODALITIES = {"presencial", "híbrido", "remoto", None}


def validate_job(job: object) -> None:
    """Valida claves, tipos, modalidad y fechas de una oferta normalizada."""
    if not isinstance(job, dict):
        raise ValueError("Cada oferta debe ser un objeto JSON")

    actual_fields = set(job)
    expected_fields = set(JOB_FIELDS)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        unexpected = sorted(actual_fields - expected_fields)
        raise ValueError(
            f"Esquema inválido; faltan={missing}, sobran={unexpected}"
        )

    for field in _TEXT_FIELDS:
        if job[field] is not None and not isinstance(job[field], str):
            raise ValueError(f"{field} debe ser texto o null")

    if not job["source"]:
        raise ValueError("source no puede estar vacío")
    if not job["scraped_at"]:
        raise ValueError("scraped_at no puede estar vacío")
    if job["modality"] not in _ALLOWED_MODALITIES:
        raise ValueError(f"Modalidad inválida: {job['modality']!r}")

    tags = job["tags"]
    if tags is not None and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
    ):
        raise ValueError("tags debe ser una lista de textos o null")

    for field in ("published_at", "scraped_at"):
        if job[field] is not None:
            try:
                parse_iso_datetime(job[field])
            except ValueError as exc:
                raise ValueError(f"{field} debe ser ISO 8601 con zona horaria") from exc


def validate_jobs(jobs: Iterable[object]) -> None:
    for job in jobs:
        validate_job(job)


def _job_id_key(job: dict) -> str | None:
    value = job.get("job_id")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _url_key(job: dict) -> str | None:
    value = job.get("url")
    if not isinstance(value, str) or not value.strip():
        return None
    url, _ = urldefrag(value.strip())
    if url.endswith("/") and not url.endswith("://"):
        url = url.rstrip("/")
    return url or None


class JobDeduplicator:
    """Conserva la primera aparición por job_id o por URL."""

    def __init__(self) -> None:
        self._job_ids: set[str] = set()
        self._urls: set[str] = set()

    def add(self, job: dict) -> bool:
        job_id = _job_id_key(job)
        url = _url_key(job)
        if (job_id is not None and job_id in self._job_ids) or (
            url is not None and url in self._urls
        ):
            return False

        if job_id is not None:
            self._job_ids.add(job_id)
        if url is not None:
            self._urls.add(url)
        return True


def deduplicate_jobs(jobs: Iterable[dict]) -> list[dict]:
    deduplicator = JobDeduplicator()
    return [job for job in jobs if deduplicator.add(job)]
