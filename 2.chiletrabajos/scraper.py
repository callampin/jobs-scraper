#!/usr/bin/env python3
"""Conector de ofertas públicas de Chiletrabajos."""

import argparse
import json
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

CONNECTOR_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONNECTOR_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.dates import UTC, as_utc, cutoff_date, isoformat_z
from common.http import PoliteHttpClient
from common.jobs import JobDeduplicator
from common.output import dated_output_path, write_jobs_json
from common.text import html_to_text

SOURCE = "chiletrabajos"
SEARCH_PATH = "/encuentra-un-empleo"
ALLOWED_HOSTS = {"chiletrabajos.cl", "www.chiletrabajos.cl"}
CHILE_TZ = ZoneInfo("America/Santiago")
MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
SPANISH_DATE_RE = re.compile(
    r"(\d{1,2})\s+de\s+([a-záéíóúüñ]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
JOB_ID_RE = re.compile(r"-(\d+)(?:/)?$")
TOTAL_RE = re.compile(r"([\d.]+)\s+Trabajos?", re.IGNORECASE)
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


def unique_strings(values: list[str]) -> list[str]:
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
        raise RuntimeError(f"URL fuera de Chiletrabajos: {url}")
    return url


def parse_spanish_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    match = SPANISH_DATE_RE.search(" ".join(value.split()))
    if not match:
        return None
    day, month_name, year = match.groups()
    month = MONTHS.get(normalize_text(month_name))
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=CHILE_TZ)
    except ValueError:
        return None


def parse_detail_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", value)
    if not match:
        return None
    try:
        naive = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=CHILE_TZ)


def _listing_item(item: Any, base_url: str) -> dict | None:
    title_link = item.select_one("h2.title a[href]")
    if title_link is None:
        return None
    url = ensure_allowed_url(urljoin(base_url, title_link["href"]))
    metas = item.select("h3.meta")
    if not metas:
        return None

    company = clean_text(metas[0].get_text(" ", strip=True))
    city_link = metas[0].find("a", href=True)
    location = None
    if city_link is not None:
        location = clean_text(city_link.get_text(" ", strip=True))
        full_meta = company or ""
        if location and full_meta.casefold().endswith(location.casefold()):
            company = clean_text(full_meta[: -len(location)].rstrip(" ,"))
        else:
            company = None

    published = parse_spanish_date(metas[1].get_text(" ", strip=True)) if len(metas) > 1 else None
    job_id_match = JOB_ID_RE.search(urlparse(url).path)
    job_id = job_id_match.group(1) if job_id_match else None
    if not job_id:
        save_link = item.select_one("[data-id]")
        job_id = clean_text(save_link.get("data-id")) if save_link else None

    excerpt = item.select_one("p.description")
    if excerpt is not None:
        for extra in excerpt.select(".ver-mas-btn"):
            extra.decompose()

    return {
        "job_id": job_id,
        "title": clean_text(title_link.get_text(" ", strip=True)),
        "company": company,
        "location": location,
        "published_at": published,
        "url": url,
        "excerpt": clean_text(excerpt.get_text(" ", strip=True)) if excerpt else None,
    }


def _city_options(soup: BeautifulSoup) -> dict[str, str]:
    select = soup.select_one('form select[name="13"]')
    if select is None:
        return {}
    cities: dict[str, str] = {}
    for option in select.find_all("option"):
        label = normalize_text(option.get_text(" ", strip=True))
        value = clean_text(option.get("value"))
        if label and value:
            cities.setdefault(label, value)
    return cities


def _results_container(soup: BeautifulSoup) -> Any:
    # El portal repite id="buscador" en un bloque publicitario.
    for container in soup.select("#buscador"):
        if container.select_one(".title-lines") or container.select(".job-item"):
            return container
    return None


def parse_listing_page(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    container = _results_container(soup)
    if container is None:
        raise RuntimeError("No se encontró el contenedor de resultados de Chiletrabajos")

    heading = container.select_one(".title-lines h2")
    total_match = TOTAL_RE.search(heading.get_text(" ", strip=True)) if heading else None
    if total_match is None:
        raise RuntimeError("No se pudo determinar el total de resultados")
    total = int(total_match.group(1).replace(".", ""))

    jobs: list[dict] = []
    invalid = 0
    if total > 0:
        for item in container.select(".job-item"):
            parsed = _listing_item(item, base_url)
            if parsed is None:
                invalid += 1
            else:
                jobs.append(parsed)
        if not jobs:
            raise RuntimeError(
                "La página declara resultados pero no se encontraron ofertas; "
                "posible cambio de estructura"
            )

    next_link = container.select_one(".pagination a[rel='next'][href]")
    next_url = (
        ensure_allowed_url(urljoin(base_url, next_link["href"]))
        if next_link is not None
        else None
    )
    return {
        "jobs": jobs,
        "total": total,
        "next_url": next_url,
        "cities": _city_options(soup),
        "invalid": invalid,
    }


def _table_fields(soup: BeautifulSoup) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    container = soup.select_one("#detalle-oferta")
    if container is None:
        raise RuntimeError("No se encontró el detalle de la oferta")

    for row in container.select(".datos table tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = normalize_text(cells[0].get_text(" ", strip=True))
        values = [clean_text(cell.get_text(" ", strip=True)) for cell in cells[1:]]
        fields[key] = [value for value in values if value]
    return fields


def detect_modality(title: str, description: str | None, benefit_titles: list[str]) -> str | None:
    detected: set[str] = set()
    for benefit in benefit_titles:
        normalized = normalize_text(benefit)
        if "100% remoto" in normalized or normalized in {"trabajo remoto", "remoto"}:
            detected.add("remoto")
        elif "hibrido" in normalized:
            detected.add("híbrido")
        elif normalized in {"presencial", "trabajo presencial"}:
            detected.add("presencial")

    if len(detected) == 1:
        return next(iter(detected))
    if len(detected) > 1:
        return None

    source_text = normalize_text(" ".join(filter(None, [title, description])))
    patterns = {
        "remoto": (
            r"\b100\s*%\s*remot[oa]\b",
            r"\bmodalidad(?:\s+de\s+trabajo)?\s*[:\-]?\s*remot[oa]\b",
        ),
        "híbrido": (
            r"\bmodalidad(?:\s+de\s+trabajo)?\s*[:\-]?\s*hibrid[oa]\b",
            r"\b100\s*%\s*hibrid[oa]\b",
        ),
        "presencial": (
            r"\bmodalidad(?:\s+de\s+trabajo)?\s*[:\-]?\s*presencial\b",
            r"\b100\s*%\s*presencial\b",
        ),
    }
    for modality, modality_patterns in patterns.items():
        if any(re.search(pattern, source_text) for pattern in modality_patterns):
            detected.add(modality)
    return next(iter(detected)) if len(detected) == 1 else None


def _description_and_benefits(soup: BeautifulSoup) -> tuple[str | None, list[str]]:
    container = soup.select_one("#detalle-oferta .job-item.detalle")
    if container is None:
        return None, []

    paragraphs = [
        html_to_text(paragraph.decode_contents())
        for paragraph in container.select(".p-x-3 p")
    ]
    description = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)

    benefits: list[str] = []
    for block in container.select(".beneficios-wrapper .beneficios-info"):
        title = clean_text(block.select_one(".beneficio-title").get_text(" ", strip=True)) if block.select_one(".beneficio-title") else None
        detail = clean_text(block.select_one(".beneficio-desc").get_text(" ", strip=True)) if block.select_one(".beneficio-desc") else None
        if title and detail:
            benefits.append(f"{title}: {detail}")
        elif title:
            benefits.append(title)

    if benefits:
        description = (
            f"{description}\n\nBeneficios\n" + "\n".join(f"- {benefit}" for benefit in benefits)
            if description
            else "Beneficios\n" + "\n".join(f"- {benefit}" for benefit in benefits)
        )
    return description or None, benefits


def _detail_tags(soup: BeautifulSoup, category: str | None, location: str | None) -> list[str]:
    values = [category] if category else []
    for icon in soup.select("#detalle-oferta .job-item.detalle .botones-desc i.fa-tag"):
        label = icon.find_parent("span")
        if label is not None:
            values.append(label.get_text(" ", strip=True))
    excluded = {normalize_text(value) for value in (category, location) if value}
    return [tag for tag in unique_strings(values) if normalize_text(tag) not in excluded or tag == category]


def parse_detail_page(
    html: str,
    listing: dict,
    *,
    scraped_at: str,
) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    fields = _table_fields(soup)
    container = soup.select_one("#detalle-oferta")
    title_node = container.select_one("h1") if container else None
    title = clean_text(title_node.get_text(" ", strip=True)) if title_node else listing["title"]

    company = next(iter(fields.get("buscado", []) + fields.get("empresa", [])), None)
    company = company or listing["company"]
    location = next(iter(fields.get("ubicacion", [])), None) or listing["location"]
    category = next(iter(fields.get("categoria", [])), None)
    salary = next(iter(fields.get("salario", [])), None)
    table_job_id = next(iter(fields.get("id", [])), None)

    detail_date = parse_detail_datetime(next(iter(fields.get("fecha", [])), None))
    published_at = detail_date or listing["published_at"]

    description, benefits = _description_and_benefits(soup)
    benefit_titles = []
    for benefit in benefits:
        benefit_titles.append(benefit.split(":", 1)[0])
    modality = detect_modality(title or "", description, benefit_titles)

    job = {
        "source": SOURCE,
        "job_id": table_job_id or listing["job_id"],
        "title": title,
        "company": company,
        "location": "Remoto" if modality == "remoto" else location,
        "modality": modality,
        "salary": salary,
        "published_at": isoformat_z(published_at) if published_at else None,
        "url": listing["url"],
        "description": description,
        "tags": _detail_tags(soup, category, location),
        "scraped_at": scraped_at,
    }
    if not job["job_id"] and not job["url"]:
        raise ValueError("La oferta no tiene job_id ni URL")
    return job


def build_search_url(config: dict, query: str, days: int) -> str:
    params = {
        "action": "search",
        "order_by": "",
        "ord": "",
        "within": "25",
        "2": query.strip(),
        "filterSearch": "Buscar",
    }
    # "Hace un mes" acota la búsqueda; el filtro exacto se aplica por oferta.
    if days <= 30:
        params["fecha"] = "6"
    return f"{config['base_url']}{SEARCH_PATH}?{urlencode(params)}"


def add_city_filter(url: str, city_id: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["13"] = [city_id]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def fetch_html(client: PoliteHttpClient, url: str) -> str:
    ensure_allowed_url(url)
    response = client.get(url)
    response.raise_for_status()
    ensure_allowed_url(response.url)
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.casefold():
        raise RuntimeError(f"Se esperaba HTML de {url}, se recibió {content_type!r}")
    return response.text


def _candidate_key(listing: dict) -> tuple[str | None, str]:
    return listing["job_id"], listing["url"]


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
    page_url = build_search_url(config, query, days)
    local_location = None if normalize_text(location) == "chile" else location

    LOGGER.info("Procesando página 1")
    first_html = fetch_html(client, page_url)
    first_page = parse_listing_page(first_html, page_url)

    if local_location:
        city_id = first_page["cities"].get(normalize_text(local_location))
        if city_id:
            page_url = add_city_filter(page_url, city_id)
            LOGGER.info("Aplicando filtro de ciudad del portal para %r", local_location)
            LOGGER.info("Procesando página 1 con filtro de ciudad")
            first_html = fetch_html(client, page_url)
            first_page = parse_listing_page(first_html, page_url)
            local_location = None

    stats = {
        "received": 0,
        "saved": 0,
        "discarded_date": 0,
        "discarded_location": 0,
        "duplicates": 0,
        "invalid": 0,
        "pages": 0,
        "details_fetched": 0,
    }
    candidates: list[dict] = []
    seen_candidates: set[tuple[str | None, str]] = set()
    seen_pages: set[str] = set()
    page_number = 1
    current_page = first_page

    while True:
        if page_url in seen_pages:
            raise RuntimeError(f"El portal repitió la página {page_number}")
        seen_pages.add(page_url)
        stats["pages"] += 1
        stats["received"] += len(current_page["jobs"])
        stats["invalid"] += current_page["invalid"]
        LOGGER.info(
            "Página %d: %d ofertas listadas, total declarado %d",
            page_number,
            len(current_page["jobs"]),
            current_page["total"],
        )

        for listing in current_page["jobs"]:
            published = listing["published_at"]
            if published is None or published.date() < cutoff_day:
                stats["discarded_date"] += 1
                continue
            key = _candidate_key(listing)
            if key in seen_candidates:
                stats["duplicates"] += 1
                continue
            seen_candidates.add(key)
            candidates.append(listing)

        next_url = current_page["next_url"]
        if not next_url:
            break
        page_url = ensure_allowed_url(next_url)
        page_number += 1
        LOGGER.info("Procesando página %d", page_number)
        current_page = parse_listing_page(fetch_html(client, page_url), page_url)

    candidates.sort(
        key=lambda listing: (
            listing["published_at"] or datetime.min.replace(tzinfo=CHILE_TZ),
            listing["title"] or "",
        ),
        reverse=True,
    )
    LOGGER.info(
        "Listado completo: %d candidatas dentro del margen preliminar",
        len(candidates),
    )

    jobs: list[dict] = []
    deduplicator = JobDeduplicator()
    for listing in candidates:
        if max_results is not None and len(jobs) >= max_results:
            break
        LOGGER.info("Obteniendo detalle: %s", listing["url"])
        detail_html = fetch_html(client, listing["url"])
        stats["details_fetched"] += 1
        job = parse_detail_page(detail_html, listing, scraped_at=scraped_at)

        published_value = job["published_at"]
        published = (
            datetime.fromisoformat(published_value.replace("Z", "+00:00"))
            if published_value
            else None
        )
        if published is None or published < cutoff or published > now:
            stats["discarded_date"] += 1
            continue
        if local_location:
            candidate = normalize_text(job["location"])
            requested = normalize_text(local_location)
            if requested not in candidate and candidate not in requested:
                stats["discarded_location"] += 1
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
        description="Busca ofertas de software en Chiletrabajos."
    )
    parser.add_argument("--query", required=True, help="Cargo, tecnología o búsqueda libre")
    parser.add_argument(
        "--location",
        default=config.get("location", "Chile"),
        help="Chile o una ciudad disponible en el filtro del portal",
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
            "duplicadas=%(duplicates)d, inválidas=%(invalid)d"
        ),
        stats,
    )
    LOGGER.info("Archivo guardado: %s", output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
