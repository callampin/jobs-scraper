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
BASE = "https://www.laborum.cl"


def config(page_size=100):
    return {
        "base_url": BASE,
        "site_id": "BMCL",
        "search_path": "/api/avisos/searchNormalizado",
        "detail_path": "/api/candidates/fichaAvisoNormalizada/{job_id}",
        "page_size": page_size,
    }


def search_item(
    job_id=100,
    *,
    title="Backend Python",
    date="13-11-2026 15:29:42",
    location="Las Condes, Región Metropolitana",
    modality="Híbrido",
    country_id=1007,
):
    return {
        "id": job_id,
        "titulo": title,
        "empresa": "Example SpA",
        "localizacion": location,
        "fechaPublicacion": date[:10],
        "fechaHoraPublicacion": date,
        "modalidadTrabajo": modality,
        "idPais": country_id,
        "detalle": "Descripción de respaldo",
    }


def search_payload(items, *, total=None, number=0, size=100):
    return {
        "number": number,
        "size": size,
        "total": len(items) if total is None else total,
        "totalSearched": len(items) if total is None else total,
        "content": items,
        "filters": [],
        "filtersApplied": [],
    }


def detail_payload(
    job_id=100,
    *,
    title="Backend Python",
    date="13-11-2026 15:29:42",
    state="activo",
    modality="Híbrido",
    city="Las Condes",
    province="Región Metropolitana",
    salary=True,
    benefits=True,
    description=None,
    company="Example SpA",
    confidential=False,
):
    if description is None:
        description = (
            "<p>Desarrollar <strong>APIs REST</strong> y servicios backend.</p>"
            "<ul><li>Mantener Python y PostgreSQL.</li><li>Documentar soluciones.</li></ul>"
        )
    return {
        "aviso": {
            "id": job_id,
            "titulo": title,
            "estado": state,
            "fechaPublicacion": date[:10],
            "fechaHoraPublicacion": date,
            "descripcion": description,
            "confidencial": confidential,
            "empresa": {
                "denominacion": company,
                "ciudad": city,
                "provincia": province,
            },
            "localizacion": {
                "paisId": 1007,
                "paisIdSemantico": "chile",
                "paisDetalle": "Chile",
                "localidadDetalle": city,
                "provinciaDetalle": province,
                "detalle": f"{city}, {province}, Chile",
            },
            "area": {
                "nombre": "Tecnología, Sistemas y Telecomunicaciones",
                "idSemantico": "tecnologia",
            },
            "subArea": {"nombre": "Programación", "idSemantico": "programacion"},
            "requisitos": {
                "detalleSalario": {
                    "salarioMinimo": 1200000 if salary else None,
                    "salarioMaximo": 2000000 if salary else None,
                    "frecuenciaPago": {"nombre": "por Mes"},
                    "tipo": "BRUTO",
                },
                "conocimientos": [
                    {"nombre": "Python"},
                    {"nombre": "PostgreSQL"},
                ],
            },
            "beneficiosNormalizados": (
                [
                    {
                        "nombre": "Trabajo remoto",
                        "descripcion": "Dos días desde casa",
                    }
                ]
                if benefits
                else []
            ),
            "modalidadTrabajo": {"nombre": modality, "idSemantico": modality.casefold()},
            "seoFriendlyUrl": f"/empleos/backend-python-{job_id}.html",
        },
        "avisosSugeridos": [],
    }


class FakeClient:
    def __init__(self, search_pages, details):
        self.search_pages = search_pages
        self.details = details
        self.calls = []

    def post_json(self, url, **kwargs):
        page = kwargs["params"]["page"]
        self.calls.append(("POST", url, kwargs))
        return self.search_pages[page]

    def get_json(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url not in self.details:
            raise AssertionError(f"Detalle no configurado: {url}")
        return self.details[url]


def detail_url(job_id):
    return f"{BASE}/api/candidates/fichaAvisoNormalizada/{job_id}"


class NormalizationTests(unittest.TestCase):
    def test_parses_dates_and_selects_safe_server_filter(self):
        parsed = scraper.parse_laborum_datetime("13-11-2026 15:29:42")
        self.assertEqual(parsed.isoformat(), "2026-11-13T15:29:42-03:00")
        self.assertEqual(
            scraper.date_filter_for_days(30),
            "publicacion-menor-a-1-mes",
        )
        self.assertEqual(
            scraper.date_filter_for_days(7),
            "publicacion-menor-a-1-semana",
        )
        self.assertIsNone(scraper.date_filter_for_days(45))
        self.assertIsNone(scraper.parse_laborum_datetime("ayer"))

    def test_formats_structured_salary_without_inventing_currency(self):
        self.assertEqual(
            scraper.format_salary(
                {
                    "detalleSalario": {
                        "salarioMinimo": 1200000,
                        "salarioMaximo": 2000000,
                        "frecuenciaPago": {"nombre": "por Mes"},
                        "tipo": "BRUTO",
                    }
                }
            ),
            "$ 1.200.000 - $ 2.000.000 (BRUTO, por Mes)",
        )
        self.assertEqual(
            scraper.format_salary({"detalleSalario": {"salarioMinimo": 900000}}),
            "Desde $ 900.000",
        )
        self.assertIsNone(scraper.format_salary({"detalleSalario": {}}))

    def test_normalizes_full_detail(self):
        listing = search_item()
        job = scraper.normalize_notice(
            detail_payload(),
            listing,
            scraped_at=isoformat_z(NOW),
            published_at=scraper.parse_laborum_datetime(listing["fechaHoraPublicacion"]),
            config=config(),
        )

        self.assertEqual(tuple(job.keys()), JOB_FIELDS)
        validate_job(job)
        self.assertEqual(job["source"], "laborum")
        self.assertEqual(job["job_id"], "100")
        self.assertEqual(job["title"], "Backend Python")
        self.assertEqual(job["company"], "Example SpA")
        self.assertEqual(job["location"], "Las Condes, Región Metropolitana")
        self.assertEqual(job["modality"], "híbrido")
        self.assertEqual(job["salary"], "$ 1.200.000 - $ 2.000.000 (BRUTO, por Mes)")
        self.assertEqual(job["published_at"], "2026-11-13T18:29:42Z")
        self.assertEqual(job["url"], f"{BASE}/empleos/backend-python-100.html")
        self.assertIn("Desarrollar APIs REST", job["description"])
        self.assertIn("- Mantener Python y PostgreSQL.", job["description"])
        self.assertIn("Beneficios", job["description"])
        self.assertIn("Trabajo remoto: Dos días desde casa", job["description"])
        self.assertEqual(
            job["tags"],
            [
                "Tecnología, Sistemas y Telecomunicaciones",
                "Programación",
                "Python",
                "PostgreSQL",
            ],
        )

    def test_remote_changes_location_and_confidential_company_is_explicit(self):
        payload = detail_payload(modality="Remoto", company="", confidential=True)
        job = scraper.normalize_notice(
            payload,
            search_item(),
            scraped_at=isoformat_z(NOW),
            published_at=scraper.parse_laborum_datetime("13-11-2026 15:29:42"),
            config=config(),
        )
        self.assertEqual(job["modality"], "remoto")
        self.assertEqual(job["location"], "Remoto")
        self.assertEqual(job["company"], "Confidencial")


class CollectionTests(unittest.TestCase):
    def run_collection(self, client, **overrides):
        values = {
            "query": "python",
            "location": "Chile",
            "days": 30,
            "max_results": None,
            "config": config(page_size=2),
            "now": NOW,
        }
        values.update(overrides)
        return scraper.collect_jobs(client, **values)

    def test_paginates_applies_dates_and_skips_inactive(self):
        page_zero = search_payload(
            [
                search_item(100),
                search_item(101, date="01-10-2026 10:00:00"),
            ],
            total=3,
            size=2,
        )
        page_one = search_payload(
            [search_item(102, date="10-11-2026 09:00:00")],
            total=3,
            number=1,
            size=2,
        )
        client = FakeClient(
            {0: page_zero, 1: page_one},
            {
                detail_url(100): detail_payload(100),
                detail_url(102): detail_payload(102, state="offline"),
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
        body = search_call[2]["json"]
        self.assertEqual(
            body["filtros"],
            [{"id": "dias_fecha_publicacion", "value": "publicacion-menor-a-1-mes"}],
        )
        self.assertEqual(search_call[2]["headers"]["x-site-id"], "BMCL")

    def test_detail_exact_date_is_rechecked(self):
        page = search_payload([search_item(100)], total=1)
        client = FakeClient(
            {0: page},
            {detail_url(100): detail_payload(100, date="15-10-2026 10:00:00")},
        )
        jobs, stats = self.run_collection(client)
        self.assertEqual(jobs, [])
        self.assertEqual(stats["discarded_date"], 1)

    def test_filters_non_chile_and_requested_location(self):
        page = search_payload(
            [
                search_item(100, location="Santiago, Región Metropolitana"),
                search_item(101, location="Buenos Aires, Argentina", country_id=1),
                search_item(102, location="Valparaíso, Región de Valparaíso"),
            ],
            total=3,
        )
        client = FakeClient(
            {0: page},
            {detail_url(100): detail_payload(100, city="Santiago")},
        )
        jobs, stats = self.run_collection(
            client,
            location="Santiago",
            config=config(page_size=3),
        )
        self.assertEqual([job["job_id"] for job in jobs], ["100"])
        self.assertGreaterEqual(stats["discarded_location"], 2)

    def test_max_results_limits_details_after_newest_first_sort(self):
        page = search_payload(
            [
                search_item(100, date="11-11-2026 10:00:00"),
                search_item(101, date="12-11-2026 10:00:00"),
            ],
            total=2,
        )
        client = FakeClient(
            {0: page},
            {detail_url(101): detail_payload(101, date="12-11-2026 10:00:00")},
        )
        jobs, _ = self.run_collection(client, max_results=1)
        self.assertEqual([job["job_id"] for job in jobs], ["101"])
        detail_calls = [call[1] for call in client.calls if call[0] == "GET"]
        self.assertEqual(detail_calls, [detail_url(101)])


if __name__ == "__main__":
    unittest.main()
