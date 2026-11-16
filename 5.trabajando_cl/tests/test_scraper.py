import sys
import unittest
from datetime import datetime
from pathlib import Path

CONNECTOR_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CONNECTOR_DIR.parent
for directory in (PROJECT_ROOT, CONNECTOR_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import scraper
from common.dates import UTC, isoformat_z
from common.jobs import JOB_FIELDS, validate_job

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
BASE = "https://www.trabajando.cl"


def config():
    return {
        "base_url": BASE,
        "search_path": "/api/searchjob",
        "detail_path": "/api/ofertas/{job_id}",
    }


def search_item(
    job_id=6147899,
    *,
    title="Backend Python",
    date="2026-11-10 11:56",
    location="Santiago, Metropolitana de Santiago",
    workday="Jornada Completa",
):
    return {
        "idOferta": job_id,
        "nombreCargo": title,
        "nombreEmpresa": "Example SpA",
        "descripcionOferta": "Resumen de la oferta…",
        "publicadoHace": "Hace 5 días",
        "ubicacion": location,
        "ofertaDestacada": False,
        "geolocalizacion": "",
        "nombreJornada": workday,
        "ofertaInclusiva": False,
        "ofertaExclusiva": False,
        "fechaPublicacion": date,
    }


def search_payload(items, *, total=None, pages=1, page=1, size=15):
    return {
        "estado": "CARGANDO",
        "ofertas": items,
        "cantidadRegistros": len(items) if total is None else total,
        "cantidadPaginas": pages,
        "paginaActual": page,
        "registrosPorPagina": size,
        "facetas": {},
    }


def detail_payload(
    job_id=6147899,
    *,
    title="Backend Python",
    description="<p>Descripción completa de la oferta.</p><ul><li>Python</li></ul>",
    company="Example SpA",
    confidential=False,
    state="PUBLICADA",
    modality="Teletrabajo",
    salary=True,
    area="Tecnologías de Información",
    categories=None,
    skills=None,
    city="Santiago",
    region="Metropolitana de Santiago",
):
    return {
        "idOferta": job_id,
        "slug": f"{job_id}-backend-python",
        "ofertaConfidencial": confidential,
        "nombreCargo": title,
        "descripcionOferta": description,
        "cantidadVacantes": 1,
        "nombreEmpresaFantasia": company,
        "categorias": categories or ["Desarrollo de Software"],
        "nombreArea": area,
        "tiempoContrato": None,
        "nombreJornada": modality,
        "mostrarSueldo": salary,
        "nombreMoneda": "Pesos Chilenos",
        "sueldo": 2200000 if salary else 0,
        "nombreOperadorExperiencia": "Sin experiencia",
        "aniosExperiencia": 3,
        "nombreNivelAcademico": "Universitaria",
        "fechaPublicacion": "10/11/2026",
        "fechaExpiracion": "17/11/2026",
        "fechaPublicacionFormatoIngles": "2026-11-10",
        "fechaExpiracionFormatoIngles": "2026-11-17",
        "habilidades": skills or [{"nombre": "Python"}, {"nombre": "SQL"}],
        "ubicacion": {
            "nombrePais": "Chile",
            "nombreRegion": region,
            "nombreComuna": city,
            "direccion": None,
        },
        "estadoOferta": state,
        "esBuscable": True,
    }


class FakeClient:
    def __init__(self, search_pages, details):
        self.search_pages = search_pages
        self.details = details
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/api/searchjob"):
            page = kwargs["params"]["pagina"]
            return self.search_pages[page]
        if url not in self.details:
            raise AssertionError(f"Detalle no configurado: {url}")
        return self.details[url]


def detail_url(job_id):
    return f"{BASE}/api/ofertas/{job_id}"


class NormalizationTests(unittest.TestCase):
    def test_parses_publication_dates_in_chile(self):
        parsed = scraper.parse_publication_datetime("2026-11-10 11:56")
        self.assertEqual(parsed.isoformat(), "2026-11-10T11:56:00-03:00")
        self.assertEqual(
            scraper.parse_publication_datetime("2026-11-10").date().isoformat(),
            "2026-11-10",
        )
        self.assertIsNone(scraper.parse_publication_datetime("hace 3 días"))

    def test_normalizes_remote_detail_and_structured_fields(self):
        listing = search_item()
        job = scraper.normalize_job(
            detail_payload(),
            listing,
            scraped_at=isoformat_z(NOW),
            published_at=scraper.parse_publication_datetime(listing["fechaPublicacion"]),
            config=config(),
        )

        self.assertEqual(tuple(job.keys()), JOB_FIELDS)
        validate_job(job)
        self.assertEqual(job["source"], "trabajando_cl")
        self.assertEqual(job["job_id"], "6147899")
        self.assertEqual(job["title"], "Backend Python")
        self.assertEqual(job["company"], "Example SpA")
        self.assertEqual(job["location"], "Remoto")
        self.assertEqual(job["modality"], "remoto")
        self.assertEqual(job["salary"], "$ 2.200.000 (Pesos Chilenos)")
        self.assertEqual(job["published_at"], "2026-11-10T14:56:00Z")
        self.assertEqual(
            job["url"],
            f"{BASE}/trabajo/6147899-backend-python",
        )
        self.assertIn("Descripción completa de la oferta.", job["description"])
        self.assertIn("- Python", job["description"])
        self.assertEqual(
            job["tags"],
            ["Tecnologías de Información", "Desarrollo de Software", "Python", "SQL"],
        )

    def test_hybrid_confidential_and_hidden_salary(self):
        job = scraper.normalize_job(
            detail_payload(
                modality="Mixta (Teletrabajo + Presencial)",
                confidential=True,
                company="",
                salary=False,
            ),
            search_item(workday="Mixta (Teletrabajo + Presencial)"),
            scraped_at=isoformat_z(NOW),
            published_at=scraper.parse_publication_datetime("2026-11-10 11:56"),
            config=config(),
        )
        self.assertEqual(job["modality"], "híbrido")
        self.assertEqual(job["location"], "Santiago, Metropolitana de Santiago")
        self.assertEqual(job["company"], "Empresa Confidencial")
        self.assertIsNone(job["salary"])

    def test_onsite_jornada_does_not_invent_modality(self):
        job = scraper.normalize_job(
            detail_payload(modality="Jornada Completa"),
            search_item(),
            scraped_at=isoformat_z(NOW),
            published_at=scraper.parse_publication_datetime("2026-11-10 11:56"),
            config=config(),
        )
        self.assertIsNone(job["modality"])


class CollectionTests(unittest.TestCase):
    def run_collection(self, client, **overrides):
        values = {
            "query": "python",
            "location": "Chile",
            "days": 30,
            "max_results": None,
            "config": config(),
            "now": NOW,
        }
        values.update(overrides)
        return scraper.collect_jobs(client, **values)

    def test_full_pagination_date_filter_and_inactive(self):
        page_one = search_payload(
            [
                search_item(100, date="2026-11-10 10:00"),
                search_item(101, date="2026-09-01 10:00"),
            ],
            total=3,
            pages=2,
            page=1,
            size=2,
        )
        page_two = search_payload(
            [search_item(102, date="2026-11-12 10:00")],
            total=3,
            pages=2,
            page=2,
            size=2,
        )
        client = FakeClient(
            {1: page_one, 2: page_two},
            {
                detail_url(100): detail_payload(100),
                detail_url(102): detail_payload(102, state="FINALIZADA"),
            },
        )
        jobs, stats = self.run_collection(client)

        self.assertEqual([job["job_id"] for job in jobs], ["100"])
        self.assertEqual(stats["pages"], 2)
        self.assertEqual(stats["received"], 3)
        self.assertEqual(stats["discarded_date"], 1)
        self.assertEqual(stats["discarded_inactive"], 1)
        self.assertEqual(stats["details_fetched"], 2)
        search_call = client.calls[0]
        self.assertEqual(search_call[1]["params"]["cargo"], "python")
        self.assertEqual(search_call[1]["params"]["orden"], "RANKING")

    def test_exact_detail_date_is_rechecked(self):
        client = FakeClient(
            {1: search_payload([search_item(100)], total=1)},
            {
                detail_url(100): detail_payload(100),
            },
        )
        jobs, stats = self.run_collection(
            client,
            now=datetime(2026, 12, 30, 12, tzinfo=UTC),
        )
        self.assertEqual(jobs, [])
        self.assertEqual(stats["discarded_date"], 1)

    def test_location_filter_and_deduplication(self):
        item = search_item(100)
        client = FakeClient(
            {
                1: search_payload(
                    [
                        item,
                        item,
                        search_item(101, location="Valparaíso, Valparaíso"),
                    ],
                    total=3,
                )
            },
            {detail_url(100): detail_payload(100)},
        )
        jobs, stats = self.run_collection(client, location="Santiago")
        self.assertEqual([job["job_id"] for job in jobs], ["100"])
        self.assertEqual(stats["duplicates"], 1)
        self.assertGreaterEqual(stats["discarded_location"], 1)

    def test_max_results_uses_newest_listing_first(self):
        client = FakeClient(
            {
                1: search_payload(
                    [
                        search_item(100, date="2026-11-10 10:00"),
                        search_item(101, date="2026-11-12 10:00"),
                    ],
                    total=2,
                )
            },
            {detail_url(101): detail_payload(101)},
        )
        jobs, _ = self.run_collection(client, max_results=1)
        self.assertEqual([job["job_id"] for job in jobs], ["101"])
        detail_calls = [url for url, _ in client.calls if "/api/ofertas/" in url]
        self.assertEqual(detail_calls, [detail_url(101)])


if __name__ == "__main__":
    unittest.main()
