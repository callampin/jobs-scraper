#!/usr/bin/env python3
"""Conector de ofertas públicas de Laborum Chile."""

import argparse
import json
import logging
import re
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

SOURCE = "laborum"
ALLOWED_HOSTS = {"laborum.cl", "www.laborum.cl"}
CHILE_TZ = ZoneInfo("America/Santiago")
MODALITY_MAP = {
    "presencial": "presencial",
    "hibrido": "híbrido",
    "remoto": "remoto",
}
DATE_FILTERS = (
    (3, "publicacion-menor-a-3-dias"),
    (4, "publicacion-menor-a-4-dias"),
    (5, "publicacion-menor-a-5-dias"),
    (6, "publicacion-menor-a-6-dias"),
    (7, "publicacion-menor-a-1-semana"),
    (15, "publicacion-menor-a-15-dias"),
    (31, "publicacion-menor-a-1-mes"),
)
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
        raise RuntimeError(f"URL fuera de Laborum: {url}")
    return url


def parse_laborum_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    for date_format in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
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


def date_filter_for_days(days: int) -> str | None:
    for maximum_days, semantic_value in DATE_FILTERS:
        if days <= maximum_days:
            return semantic_value
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


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_salary(requirements: object) -> str | None:
    if not isinstance(requirements, dict):
        return None
    detail = requirements.get("detalleSalario")
    if not isinstance(detail, dict):
        detail = requirements.get("salario")
    if not isinstance(detail, dict):
        return None

    minimum = _number(detail.get("salarioMinimo"))
    maximum = _number(detail.get("salarioMaximo"))
    if minimum is None and maximum is None:
        return None

    if minimum is not None and maximum is not None:
        amount = (
            f"$ {_thousands(minimum)}"
            if minimum == maximum
            else f"$ {_thousands(minimum)} - $ {_thousands(maximum)}"
        )
    elif minimum is not None:
        amount = f"Desde $ {_thousands(minimum)}"
    else:
        amount = f"Hasta $ {_thousands(maximum)}"

    context: list[str] = []
    salary_type = clean_text(detail.get("tipo"))
    if salary_type:
        context.append(salary_type)
    frequency = detail.get("frecuenciaPago")
    if isinstance(frequency, dict):
        frequency_name = clean_text(frequency.get("nombre"))
        if frequency_name:
            context.append(frequency_name)
    return f"{amount} ({', '.join(context)})" if context else amount


def detect_modality(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("nombre") or value.get("idSemantico")
    return MODALITY_MAP.get(normalize_text(value))


def _benefit_text(value: object) -> str | None:
    if isinstance(value, str):
        return clean_text(value)
    if not isinstance(value, dict):
        return None
    parts = []
    for key in ("nombre", "titulo", "descripcion", "detalle", "texto"):
        part = clean_text(value.get(key))
        if part and part not in parts:
            parts.append(part)
    return ": ".join(parts) if parts else None


def format_benefits(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    benefits = [_benefit_text(item) for item in value]
    return unique_strings(benefits)


def _knowledge_values(value: object) -> list[str]:
    if isinstance(value, str):
        return unique_strings(re.split(r"[,;\n]+", value))
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                name = (
                    clean_text(item.get("nombre"))
                    or clean_text(item.get("descripcion"))
                    or clean_text(item.get("detalle"))
                )
                if name:
                    result.append(name)
        return unique_strings(result)
    if isinstance(value, dict):
        return unique_strings(
            [
                item
                for key, item in value.items()
                if key in {"nombre", "descripcion", "conocimiento", "habilidad"}
            ]
        )
    return []


def extract_tags(notice: dict) -> list[str]:
    values: list[str] = []
    area = notice.get("area")
    if isinstance(area, dict):
        values.append(area.get("nombre"))
    subarea = notice.get("subArea")
    if isinstance(subarea, dict):
        values.append(subarea.get("nombre"))
    requirements = notice.get("requisitos")
    if isinstance(requirements, dict):
        values.extend(_knowledge_values(requirements.get("conocimientos")))
    return unique_strings(values)


def extract_location(notice: dict) -> tuple[str | None, list[str]]:
    location = notice.get("localizacion")
    if not isinstance(location, dict):
        return None, []
    candidates = unique_strings(
        [
            location.get("localidadDetalle"),
            location.get("provinciaDetalle"),
            location.get("paisDetalle"),
            location.get("detalle"),
        ]
    )
    parts = unique_strings(
        [location.get("localidadDetalle"), location.get("provinciaDetalle")]
    )
    if not parts:
        parts = unique_strings([location.get("paisDetalle")])
    return (", ".join(parts) if parts else None), candidates


def normalize_notice(
    payload: dict,
    listing: dict,
    *,
    scraped_at: str,
    published_at: datetime | None,
    config: dict,
) -> dict:
    notice = payload.get("aviso")
    if not isinstance(notice, dict):
        raise RuntimeError("La API de detalle no devolvió el objeto aviso")

    url_path = clean_text(notice.get("seoFriendlyUrl"))
    if not url_path:
        raise RuntimeError("El detalle de Laborum no incluyó seoFriendlyUrl")
    url = ensure_allowed_url(urljoin(config["base_url"], url_path))

    company_data = notice.get("empresa")
    company = (
        clean_text(company_data.get("denominacion"))
        if isinstance(company_data, dict)
        else None
    )
    if notice.get("confidencial") is True and not company:
        company = "Confidencial"

    location, _ = extract_location(notice)
    modality = detect_modality(notice.get("modalidadTrabajo"))
    if modality == "remoto":
        location = "Remoto"

    description = html_to_text(notice.get("descripcion"))
    if not description:
        description = html_to_text(listing.get("detalle"))
    benefits = format_benefits(notice.get("beneficiosNormalizados"))
    if benefits:
        benefit_block = "Beneficios\n" + "\n".join(f"- {item}" for item in benefits)
        description = f"{description}\n\n{benefit_block}" if description else benefit_block

    job_id = notice.get("id") or listing.get("id")
    return {
        "source": SOURCE,
        "job_id": str(job_id) if job_id is not None else None,
        "title": clean_text(notice.get("titulo")) or clean_text(listing.get("titulo")),
        "company": company,
        "location": location,
        "modality": modality,
        "salary": format_salary(notice.get("requisitos")),
        "published_at": isoformat_z(published_at) if published_at else None,
        "url": url,
        "description": description or None,
        "tags": extract_tags(notice),
        "scraped_at": scraped_at,
    }


def _search_headers(config: dict) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-site-id": config["site_id"],
        "Origin": config["base_url"],
        "Referer": f"{config['base_url']}/",
    }


def _detail_headers(config: dict) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "x-site-id": config["site_id"],
        "Referer": f"{config['base_url']}/",
    }


def search_page(
    client: PoliteHttpClient,
    *,
    config: dict,
    query: str,
    days: int,
    page: int,
) -> dict:
    filters = []
    date_filter = date_filter_for_days(days)
    if date_filter:
        filters.append({"id": "dias_fecha_publicacion", "value": date_filter})

    payload = client.post_json(
        f"{config['base_url']}{config['search_path']}",
        params={"pageSize": config["page_size"], "page": page},
        headers=_search_headers(config),
        json={
            "filtros": filters,
            "busquedaExtendida": False,
            "query": query,
            "tipoDetalle": "full",
            "withHome": False,
        },
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise RuntimeError("La API de búsqueda de Laborum devolvió un formato inesperado")
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError(f"Total de resultados inválido: {total!r}")
    return payload


def _belongs_to_chile(listing: dict) -> bool:
    country_id = listing.get("idPais")
    if country_id is not None:
        return country_id == 1007
    return True


def _matches_location(listing: dict, location: str) -> bool:
    requested = normalize_text(location)
    values = [
        listing.get("localizacion"),
        (listing.get("empresa") or {}).get("ciudad") if isinstance(listing.get("empresa"), dict) else None,
    ]
    return any(requested in normalize_text(value) or normalize_text(value) in requested for value in values if value)


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

    page_size = config.get("page_size", 100)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValueError("page_size debe ser un entero entre 1 y 100")

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
    page = 0
    total = None

    while True:
        suffix = f"/{total}" if total is not None else ""
        LOGGER.info("Procesando página %d%s", page + 1, suffix)
        payload = search_page(
            client,
            config=config,
            query=query.strip(),
            days=days,
            page=page,
        )
        if total is None:
            total = payload["total"]
        content = payload["content"]
        stats["pages"] += 1
        stats["received"] += len(content)
        LOGGER.info(
            "Página %d: %d ofertas, total declarado %d",
            page + 1,
            len(content),
            total,
        )

        if not content:
            if page * page_size < total:
                raise RuntimeError(
                    "Laborum devolvió una página vacía antes de completar la paginación"
                )
            break

        for listing in content:
            if not isinstance(listing, dict) or listing.get("id") is None:
                stats["invalid"] += 1
                continue
            if not _belongs_to_chile(listing):
                stats["discarded_location"] += 1
                continue
            if not default_chile and not _matches_location(listing, location):
                stats["discarded_location"] += 1
                continue
            published = parse_laborum_datetime(
                listing.get("fechaHoraPublicacion") or listing.get("fechaPublicacion")
            )
            if published is not None and published.date() < cutoff_day:
                stats["discarded_date"] += 1
                continue
            key = str(listing["id"])
            if key in seen_candidates:
                stats["duplicates"] += 1
                continue
            seen_candidates.add(key)
            candidates.append(listing)

        page += 1
        if page * page_size >= total:
            break

    candidates.sort(
        key=lambda listing: (
            parse_laborum_datetime(
                listing.get("fechaHoraPublicacion") or listing.get("fechaPublicacion")
            )
            or datetime.min.replace(tzinfo=CHILE_TZ),
            clean_text(listing.get("titulo")) or "",
        ),
        reverse=True,
    )
    LOGGER.info("Listado completo: %d candidatas", len(candidates))

    jobs: list[dict] = []
    deduplicator = JobDeduplicator()
    for listing in candidates:
        if max_results is not None and len(jobs) >= max_results:
            break
        job_id = str(listing["id"])
        detail_url = (
            f"{config['base_url']}{config['detail_path'].format(job_id=job_id)}"
        )
        LOGGER.info("Obteniendo detalle: %s", detail_url)
        payload = client.get_json(detail_url, headers=_detail_headers(config))
        stats["details_fetched"] += 1
        if not isinstance(payload, dict):
            raise RuntimeError("La API de detalle de Laborum devolvió un formato inesperado")
        notice = payload.get("aviso")
        if not isinstance(notice, dict):
            raise RuntimeError("La API de detalle de Laborum no devolvió aviso")
        if normalize_text(notice.get("estado")) != "activo":
            stats["discarded_inactive"] += 1
            continue

        published = parse_laborum_datetime(
            notice.get("fechaHoraPublicacion") or notice.get("fechaPublicacion")
        ) or parse_laborum_datetime(
            listing.get("fechaHoraPublicacion") or listing.get("fechaPublicacion")
        )
        if published is None or published < cutoff or published > now:
            stats["discarded_date"] += 1
            continue

        try:
            job = normalize_notice(
                payload,
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
        description="Busca ofertas de software en Laborum Chile."
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
        default=config.get("delay_seconds", 2.0),
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
