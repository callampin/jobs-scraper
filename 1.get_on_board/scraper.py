#!/usr/bin/env python3
"""Conector de ofertas públicas de Get on Board."""

import argparse
import json
import logging
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

CONNECTOR_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONNECTOR_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.dates import UTC, as_utc, cutoff_date, from_unix_timestamp, isoformat_z
from common.http import PoliteHttpClient
from common.jobs import JobDeduplicator
from common.output import dated_output_path, write_jobs_json
from common.text import html_to_text

SOURCE = "get_on_board"
COUNTRY_CODE = "CL"
EXPAND = ("company", "tags", "location_cities", "location_regions")
MODALITY_MAP = {
    "no_remote": "presencial",
    "hybrid": "híbrido",
    "fully_remote": "remoto",
    "remote_local": "remoto",
}
DESCRIPTION_SECTIONS = (
    ("projects", None),
    ("functions", "functions_headline"),
    ("description", "description_headline"),
    ("desirable", "desirable_headline"),
    ("benefits", "benefits_headline"),
)
LOGGER = logging.getLogger(SOURCE)


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _unique_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_string(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(cleaned)
    return unique


def _association_data(attributes: dict, relationship: str) -> list[dict]:
    container = attributes.get(relationship)
    if not isinstance(container, dict):
        return []
    data = container.get("data", [])
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _association_names(attributes: dict, relationship: str) -> list[str]:
    names = []
    for item in _association_data(attributes, relationship):
        nested = item.get("attributes")
        if isinstance(nested, dict):
            name = _clean_string(nested.get("name"))
            if name:
                names.append(name)
    return _unique_strings(names)


def _countries(attributes: dict) -> list[str]:
    raw_countries = attributes.get("countries")
    if isinstance(raw_countries, str):
        raw_countries = [raw_countries]
    if not isinstance(raw_countries, list):
        return []
    return _unique_strings(
        [country for country in raw_countries if isinstance(country, str)]
    )


def _normalized_place(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(character for character in decomposed if not unicodedata.combining(character)).split()
    )


def location_matches(attributes: dict, requested_location: str) -> bool:
    """Chile ya se filtra en la API; otra ubicación se filtra por sus datos."""
    requested = _normalized_place(requested_location)
    if requested == "chile":
        return True

    candidates = (
        _association_names(attributes, "location_cities")
        + _association_names(attributes, "location_regions")
        + _countries(attributes)
    )
    for candidate in candidates:
        normalized = _normalized_place(candidate)
        if requested in normalized or normalized in requested:
            return True
    return False


def _location(attributes: dict) -> str | None:
    remote_modality = attributes.get("remote_modality")
    if attributes.get("remote") is True or remote_modality in {
        "fully_remote",
        "remote_local",
    }:
        return "Remoto"

    places = _association_names(attributes, "location_cities")
    if not places:
        places = _association_names(attributes, "location_regions")
    if not places:
        places = _countries(attributes)
    return ", ".join(places) if places else None


def _salary_number(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _salary(attributes: dict) -> str | None:
    """Get on Board publica estos importes como sueldo bruto USD mensual."""
    minimum = _salary_number(attributes.get("min_salary"))
    maximum = _salary_number(attributes.get("max_salary"))
    if minimum and maximum:
        if minimum == maximum:
            return f"USD {minimum} brutos/mes"
        return f"USD {minimum} - {maximum} brutos/mes"
    if minimum:
        return f"Desde USD {minimum} brutos/mes"
    if maximum:
        return f"Hasta USD {maximum} brutos/mes"
    return None


def _description(attributes: dict) -> str | None:
    sections = []
    for body_field, headline_field in DESCRIPTION_SECTIONS:
        body = html_to_text(attributes.get(body_field))
        if not body:
            continue
        headline = (
            _clean_string(attributes.get(headline_field)) if headline_field else None
        )
        sections.append(f"{headline}\n{body}" if headline else body)
    return "\n\n".join(sections) or None


def _company(attributes: dict) -> str | None:
    for item in _association_data(attributes, "company"):
        nested = item.get("attributes")
        if isinstance(nested, dict):
            name = _clean_string(nested.get("name"))
            if name:
                return name
    return None


def _tags(attributes: dict) -> list[str]:
    category = _clean_string(attributes.get("category_name"))
    return _unique_strings(
        ([category] if category else []) + _association_names(attributes, "tags")
    )


def normalize_job(
    item: dict,
    *,
    published_at: datetime | None,
    scraped_at: str,
) -> dict:
    """Convierte un recurso JSON:API al esquema común, sin rellenar datos."""
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        raise ValueError("La oferta no contiene attributes válido")

    raw_id = item.get("id")
    job_id = str(raw_id).strip() if raw_id is not None else None
    links = item.get("links")
    public_url = links.get("public_url") if isinstance(links, dict) else None
    remote_modality = _clean_string(attributes.get("remote_modality"))

    job = {
        "source": SOURCE,
        "job_id": job_id or None,
        "title": _clean_string(attributes.get("title")),
        "company": _company(attributes),
        "location": _location(attributes),
        "modality": MODALITY_MAP.get(remote_modality),
        "salary": _salary(attributes),
        "published_at": isoformat_z(published_at) if published_at else None,
        "url": _clean_string(public_url),
        "description": _description(attributes),
        "tags": _tags(attributes),
        "scraped_at": scraped_at,
    }
    if not job["job_id"] and not job["url"]:
        raise ValueError("La oferta no tiene job_id ni URL para deduplicarla")
    return job


def _reported_total_pages(payload: dict) -> int | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict) or "total_pages" not in meta:
        return None
    total_pages = meta["total_pages"]
    if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 0:
        raise RuntimeError(f"meta.total_pages inválido: {total_pages!r}")
    return total_pages


def _page_signature(data: list[dict]) -> tuple[str, ...]:
    signature = []
    for item in data:
        links = item.get("links") if isinstance(item, dict) else None
        url = links.get("public_url") if isinstance(links, dict) else None
        signature.append(str(item.get("id") or url or ""))
    return tuple(signature)


def collect_jobs(
    client: PoliteHttpClient,
    *,
    query: str,
    location: str,
    days: int,
    max_results: int | None,
    config: dict,
    now: datetime | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Recorre la búsqueda completa y devuelve ofertas únicas dentro del rango."""
    if not query.strip():
        raise ValueError("La palabra clave no puede estar vacía")
    if not location.strip():
        raise ValueError("La ubicación no puede estar vacía")
    if max_results is not None and max_results < 1:
        raise ValueError("max_results debe ser mayor o igual que 1")

    per_page = config["per_page"]
    if (
        isinstance(per_page, bool)
        or not isinstance(per_page, int)
        or not 1 <= per_page <= 120
    ):
        raise ValueError("per_page debe ser un entero entre 1 y 120")

    now = as_utc(now or datetime.now(UTC))
    cutoff = cutoff_date(now, days)
    scraped_at = isoformat_z(now)
    deduplicator = JobDeduplicator()
    jobs: list[dict] = []
    stats = {
        "received": 0,
        "saved": 0,
        "discarded_date": 0,
        "missing_date": 0,
        "discarded_location": 0,
        "duplicates": 0,
        "invalid": 0,
        "pages": 0,
    }

    page = 1
    total_pages: int | None = None
    seen_pages: set[tuple[str, ...]] = set()

    while True:
        suffix = f"/{total_pages}" if total_pages is not None else ""
        LOGGER.info("Procesando página %d%s", page, suffix)
        params: list[tuple[str, object]] = [
            ("query", query.strip()),
            ("country_code", COUNTRY_CODE),
            ("page", page),
            ("per_page", per_page),
        ]
        params.extend(("expand[]", relationship) for relationship in EXPAND)
        payload = client.get_json(config["api_url"], params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError("La API devolvió un objeto sin una lista data")

        data = payload["data"]
        if any(not isinstance(item, dict) for item in data):
            raise RuntimeError("La API devolvió elementos no objetos en data")
        if total_pages is None:
            total_pages = _reported_total_pages(payload)
        if not data:
            LOGGER.info("Página %d vacía; paginación terminada", page)
            break

        signature = _page_signature(data)
        if signature in seen_pages:
            raise RuntimeError(
                f"La API repitió la página {page}; se detiene para evitar un ciclo"
            )
        seen_pages.add(signature)
        stats["pages"] += 1
        stats["received"] += len(data)

        reached_max = False
        for item in data:
            attributes = item.get("attributes")
            if not isinstance(attributes, dict):
                stats["invalid"] += 1
                continue

            published_at = from_unix_timestamp(attributes.get("published_at"))
            if published_at is None:
                stats["missing_date"] += 1
                continue
            if published_at < cutoff or published_at > now:
                stats["discarded_date"] += 1
                continue
            if not location_matches(attributes, location):
                stats["discarded_location"] += 1
                continue

            try:
                job = normalize_job(
                    item,
                    published_at=published_at,
                    scraped_at=scraped_at,
                )
            except (TypeError, ValueError) as exc:
                stats["invalid"] += 1
                LOGGER.warning("Oferta descartada por datos inválidos: %s", exc)
                continue

            if not deduplicator.add(job):
                stats["duplicates"] += 1
                continue
            jobs.append(job)
            if max_results is not None and len(jobs) >= max_results:
                reached_max = True
                break

        stats["saved"] = len(jobs)
        LOGGER.info(
            "Página %d: %d recibidas, %d acumuladas válidas",
            page,
            len(data),
            len(jobs),
        )

        if reached_max:
            LOGGER.info("Se alcanzó max-results=%d", max_results)
            break
        if total_pages is not None and page >= total_pages:
            break
        if total_pages is None and len(data) < per_page:
            break
        page += 1

    stats["saved"] = len(jobs)
    return jobs, stats


def load_config() -> dict:
    path = CONNECTOR_DIR / "config.json"
    with path.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("config.json debe contener un objeto JSON")
    return config


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("debe ser mayor o igual que 1")
    return parsed


def _minimum_delay(value: str) -> float:
    parsed = float(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("debe ser al menos 1 segundo")
    return parsed


def build_parser(config: dict) -> argparse.ArgumentParser:
    configured_output = Path(config.get("output_dir", "results"))
    if not configured_output.is_absolute():
        configured_output = CONNECTOR_DIR / configured_output

    parser = argparse.ArgumentParser(
        description="Busca ofertas de software en Get on Board disponibles para Chile."
    )
    parser.add_argument("--query", required=True, help="Cargo, tecnología o búsqueda libre")
    parser.add_argument(
        "--location",
        default=config.get("location", "Chile"),
        help="Chile (incluye remotos) o una ciudad/región para filtrar localmente",
    )
    parser.add_argument(
        "--days",
        type=_positive_int,
        default=config.get("days", 30),
        help="Antigüedad máxima en días (por defecto: 30)",
    )
    parser.add_argument(
        "--max-results",
        type=_positive_int,
        default=None,
        help="Máximo opcional de ofertas útiles a guardar",
    )
    parser.add_argument(
        "--delay",
        type=_minimum_delay,
        default=config.get("delay_seconds", 1.5),
        help="Espera mínima entre peticiones, en segundos",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=configured_output,
        help="Carpeta de salida del JSON fechado",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        LOGGER.error("No se pudo leer la configuración: %s", exc)
        return 1

    parser = build_parser(config)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)

    try:
        client = PoliteHttpClient(
            user_agent=config["user_agent"],
            delay_seconds=args.delay,
            timeout_seconds=config["timeout_seconds"],
            max_retries=config["max_retries"],
            backoff_seconds=config["backoff_seconds"],
        )
        LOGGER.info(
            "Búsqueda=%r, ubicación=%r, días=%d, máximo=%s",
            args.query,
            args.location,
            args.days,
            args.max_results,
        )
        jobs, stats = collect_jobs(
            client,
            query=args.query,
            location=args.location,
            days=args.days,
            max_results=args.max_results,
            config=config,
            now=now,
        )
        output_path = dated_output_path(args.output_dir, SOURCE, now)
        write_jobs_json(jobs, output_path)
    except (KeyError, OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        LOGGER.error("La extracción falló: %s", exc)
        return 1

    LOGGER.info(
        (
            "Resumen: páginas=%(pages)d, recibidas=%(received)d, "
            "guardadas=%(saved)d, fuera_de_fecha=%(discarded_date)d, "
            "sin_fecha=%(missing_date)d, fuera_de_ubicacion=%(discarded_location)d, "
            "duplicadas=%(duplicates)d, inválidas=%(invalid)d"
        ),
        stats,
    )
    LOGGER.info("Archivo guardado: %s", output_path)
    # La ruta queda sola en stdout para que otro agente pueda capturarla fácilmente.
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
