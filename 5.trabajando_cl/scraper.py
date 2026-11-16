#!/usr/bin/env python3
"""Conector de ofertas públicas de Trabajando.com Chile."""

import argparse
import json
import logging
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

CONNECTOR_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONNECTOR_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.dates import UTC, as_utc, cutoff_date, isoformat_z
from common.http import PoliteHttpClient
from common.jobs import JobDeduplicator
from common.output import dated_output_path, write_jobs_json
from common.text import html_to_text

SOURCE = "trabajando_cl"
ALLOWED_HOSTS = {"trabajando.cl", "www.trabajando.cl"}
CHILE_TZ = ZoneInfo("America/Santiago")
LOGGER = logging.getLogger(SOURCE)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join(
        "".join(
            character for character in decomposed if not unicodedata.combining(character)
        ).split()
    )


def clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace("\xa0", " ").split())
    return cleaned or None


def unique_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        key = normalize_text(cleaned)
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def ensure_allowed_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_HOSTS:
        raise RuntimeError(f"URL fuera de Trabajando: {url}")
    return url


def parse_publication_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    for date_format in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, date_format)
            return parsed.replace(tzinfo=CHILE_TZ)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHILE_TZ)
    return parsed


def detect_modality(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("nombre") or value.get("descripcion")
    normalized = normalize_text(value)
    if normalized == "teletrabajo":
        return "remoto"
    if "teletrabajo" in normalized and "presencial" in normalized:
        return "híbrido"
    if normalized in {"presencial", "trabajo presencial", "jornada presencial"}:
        return "presencial"
    return None


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def format_salary(detail: dict) -> str | None:
    if detail.get("mostrarSueldo") is not True:
        return None
    amount = _number(detail.get("sueldo"))
    if amount is None or amount <= 0:
        return None
    text = f"$ {amount:,}".replace(",", ".")
    currency = clean_text(detail.get("nombreMoneda"))
    return f"{text} ({currency})" if currency else text


def _tag_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            label = (
                clean_text(item.get("nombre"))
                or clean_text(item.get("descripcion"))
                or clean_text(item.get("detalle"))
            )
            if label:
                result.append(label)
    return unique_strings(result)


def extract_tags(detail: dict) -> list[str]:
    return unique_strings(
        [detail.get("nombreArea")]
        + _tag_values(detail.get("categorias"))
        + _tag_values(detail.get("habilidades"))
    )


def extract_location(detail: dict) -> tuple[str | None, list[str]]:
    location = detail.get("ubicacion")
    if not isinstance(location, dict):
        return None, []
    parts = unique_strings(
        [
            location.get("nombreComuna"),
            location.get("nombreRegion"),
        ]
    )
    if not parts:
        parts = unique_strings([location.get("nombrePais")])
    candidates = unique_strings(
        [
            location.get("nombreComuna"),
            location.get("nombreRegion"),
            location.get("nombrePais"),
        ]
    )
    return (", ".join(parts) if parts else None), candidates


def search_page(
    client: PoliteHttpClient,
    *,
    config: dict,
    query: str,
    page: int,
) -> dict:
    payload = client.get_json(
        f"{config['base_url']}{config['search_path']}",
        params={
            "palabraClave": "",
            "cargo": query,
            "pagina": page,
            "orden": "RANKING",
            "tipoOrden": "DESC",
        },
        headers={
            "Accept": "application/json",
            "Referer": f"{config['base_url']}/trabajo-empleo/chile",
        },
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("ofertas"), list):
        raise RuntimeError("La API de búsqueda de Trabajando devolvió un formato inesperado")
    for field in ("cantidadRegistros", "cantidadPaginas", "paginaActual", "registrosPorPagina"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"Campo de paginación inválido: {field}={value!r}")
    return payload


def normalize_job(
    detail: dict,
    listing: dict,
    *,
    scraped_at: str,
    published_at: datetime | None,
    config: dict,
) -> dict:
    slug = clean_text(detail.get("slug"))
    if not slug:
        raise RuntimeError("El detalle de Trabajando no incluyó slug")
    url = ensure_allowed_url(
        urljoin(f"{config['base_url']}/trabajo/", slug)
    )

    if detail.get("ofertaConfidencial") is True:
        company = "Empresa Confidencial"
    else:
        company = clean_text(detail.get("nombreEmpresaFantasia")) or clean_text(
            listing.get("nombreEmpresa")
        )

    description = html_to_text(detail.get("descripcionOferta"))
    if not description:
        description = html_to_text(listing.get("descripcionOferta"))

    location, _ = extract_location(detail)
    modality = detect_modality(detail.get("nombreJornada"))
    if modality == "remoto":
        location = "Remoto"

    job_id = detail.get("idOferta") or listing.get("idOferta")
    return {
        "source": SOURCE,
        "job_id": str(job_id) if job_id is not None else None,
        "title": clean_text(detail.get("nombreCargo")) or clean_text(listing.get("nombreCargo")),
        "company": company,
        "location": location,
        "modality": modality,
        "salary": format_salary(detail),
        "published_at": isoformat_z(published_at) if published_at else None,
        "url": url,
        "description": description or None,
        "tags": extract_tags(detail),
        "scraped_at": scraped_at,
    }


def _matches_location(listing: dict, location: str) -> bool:
    requested = normalize_text(location)
    value = normalize_text(listing.get("ubicacion"))
    return bool(value) and (requested in value or value in requested)


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
    if not isinstance(query, str) or not query.strip():
        raise ValueError("La palabra clave no puede estar vacía")
    if not isinstance(location, str) or not location.strip():
        raise ValueError("La ubicación no puede estar vacía")
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("days debe ser un entero mayor o igual que 1")
    if max_results is not None and max_results < 1:
        raise ValueError("max_results debe ser mayor o igual que 1")

    now = as_utc(now or datetime.now(UTC))
    cutoff = cutoff_date(now, days)
    cutoff_day = cutoff.astimezone(CHILE_TZ).date()
    scraped_at = isoformat_z(now)
    default_chile = normalize_text(location) == "chile"

    stats = {
        "received": 0,
        "saved": 0,
        "discarded_date": 0,
        "discarded_location": 0,
        "discarded_inactive": 0,
        "duplicates": 0,
        "invalid": 0,
        "pages": 0,
        "details_fetched": 0,
    }
    candidates: list[dict] = []
    seen_candidates: set[str] = set()
    page = 1
    total_pages = None
    total_records = None

    while True:
        suffix = f"/{total_pages}" if total_pages is not None else ""
        LOGGER.info("Procesando página %d%s", page, suffix)
        payload = search_page(
            client,
            config=config,
            query=query.strip(),
            page=page,
        )
        if total_pages is None:
            total_pages = payload["cantidadPaginas"]
            total_records = payload["cantidadRegistros"]
        listings = payload["ofertas"]
        stats["pages"] += 1
        stats["received"] += len(listings)
        LOGGER.info(
            "Página %d: %d ofertas, total declarado %d",
            page,
            len(listings),
            total_records,
        )

        if page <= total_pages and not listings:
            raise RuntimeError(
                f"Trabajando devolvió la página {page} vacía antes de completar {total_pages}"
            )

        for listing in listings:
            if not isinstance(listing, dict) or listing.get("idOferta") is None:
                stats["invalid"] += 1
                continue
            if not default_chile and not _matches_location(listing, location):
                stats["discarded_location"] += 1
                continue
            published = parse_publication_datetime(listing.get("fechaPublicacion"))
            if published is not None and published.date() < cutoff_day:
                stats["discarded_date"] += 1
                continue
            key = str(listing["idOferta"])
            if key in seen_candidates:
                stats["duplicates"] += 1
                continue
            seen_candidates.add(key)
            candidates.append(listing)

        if page >= total_pages:
            break
        page += 1

    candidates.sort(
        key=lambda listing: (
            parse_publication_datetime(listing.get("fechaPublicacion"))
            or datetime.min.replace(tzinfo=CHILE_TZ),
            clean_text(listing.get("nombreCargo")) or "",
        ),
        reverse=True,
    )
    LOGGER.info("Listado completo: %d candidatas", len(candidates))

    jobs: list[dict] = []
    deduplicator = JobDeduplicator()
    for listing in candidates:
        if max_results is not None and len(jobs) >= max_results:
            break
        job_id = str(listing["idOferta"])
        detail_url = f"{config['base_url']}{config['detail_path'].format(job_id=job_id)}"
        LOGGER.info("Obteniendo detalle: %s", detail_url)
        detail = client.get_json(
            detail_url,
            headers={
                "Accept": "application/json",
                "Referer": f"{config['base_url']}/",
            },
        )
        stats["details_fetched"] += 1
        if not isinstance(detail, dict):
            raise RuntimeError("La API de detalle de Trabajando devolvió un formato inesperado")

        if normalize_text(detail.get("estadoOferta")) not in {"publicada", "publicado"}:
            stats["discarded_inactive"] += 1
            continue

        published = (
            parse_publication_datetime(listing.get("fechaPublicacion"))
            or parse_publication_datetime(detail.get("fechaPublicacionFormatoIngles"))
        )
        if published is None or published < cutoff or published > now:
            stats["discarded_date"] += 1
            continue

        try:
            job = normalize_job(
                detail,
                listing,
                scraped_at=scraped_at,
                published_at=published,
                config=config,
            )
        except (TypeError, ValueError) as exc:
            stats["invalid"] += 1
            LOGGER.warning("Oferta inválida %s: %s", job_id, exc)
            continue

        if not deduplicator.add(job):
            stats["duplicates"] += 1
            continue
        jobs.append(job)
        stats["saved"] = len(jobs)

    stats["saved"] = len(jobs)
    return jobs, stats


def load_config() -> dict:
    with (CONNECTOR_DIR / "config.json").open(encoding="utf-8") as config_file:
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
        description="Busca ofertas de software en Trabajando.com Chile."
    )
    parser.add_argument("--query", required=True, help="Cargo, tecnología o búsqueda libre")
    parser.add_argument(
        "--location",
        default=config.get("location", "Chile"),
        help="Chile o una ciudad/región para filtrar localmente",
    )
    parser.add_argument(
        "--days",
        type=_positive_int,
        default=config.get("days", 30),
        help="Antigüedad máxima en días (por defecto: 30)",
    )
    parser.add_argument("--max-results", type=_positive_int, default=None)
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

    args = build_parser(config).parse_args(argv)
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
            "guardadas=%(saved)d, detalles=%(details_fetched)d, "
            "fuera_de_fecha=%(discarded_date)d, "
            "fuera_de_ubicacion=%(discarded_location)d, "
            "inactivas=%(discarded_inactive)d, "
            "duplicadas=%(duplicates)d, inválidas=%(invalid)d"
        ),
        stats,
    )
    LOGGER.info("Archivo guardado: %s", output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
