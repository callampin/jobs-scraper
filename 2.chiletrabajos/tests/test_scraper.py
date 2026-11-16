import html
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
BASE = "https://www.chiletrabajos.cl"


def listing_card(title, job_id, date, *, company="Example SpA", city="Santiago"):
    url = f"{BASE}/trabajo/oferta-{job_id}"
    return f"""
    <div class="job-item">
      <h2 class="title"><a href="{url}">{html.escape(title)}</a></h2>
      <h3 class="meta">{html.escape(company)}, <a href="{BASE}/ciudad/santiago.html">{html.escape(city)}</a></h3>
      <h3 class="meta"><a href="{url}"><i class="far fa-calendar"></i>{date}</a></h3>
      <p class="description">Resumen de la oferta… <a class="ver-mas-btn" href="{url}">Ver más</a></p>
      <a class="guardar" data-id="{job_id}" href="{url}">Guardar</a>
    </div>
    """


def listing_html(cards, *, total=1, next_url=None, include_ad_duplicate=True):
    ad = '<div class="container" id="buscador"><p>Publicidad</p></div>' if include_ad_duplicate else ""
    next_link = (
        f'<a class="page-link" rel="next" href="{html.escape(next_url)}">&gt;</a>'
        if next_url
        else ""
    )
    return f"""
    <html><body>
      {ad}
      <form><select name="13">
        <option value="">--</option>
        <option value="1022">Santiago</option>
        <option value="1014">Valparaíso</option>
      </select></form>
      <div class="col-md-8" id="buscador">
        <div class="title-lines"><h2>{total} Trabajos     de python</h2></div>
        {"".join(cards)}
        <ul class="pagination"><li>{next_link}</li></ul>
      </div>
      <aside>
        <div class="job-item"><h2 class="title"><a href="{BASE}/trabajo/relacionada-999">Relacionada</a></h2></div>
      </aside>
    </body></html>
    """


def detail_html(
    *,
    job_id="100",
    title="Backend Python",
    company="Example SpA",
    date="2026-11-13 11:35:55",
    city="Santiago",
    category="Informática / Telecomunicaciones",
    salary=None,
    description="<p>Desarrollar APIs en Python.<br>Mantener servicios.</p>",
    benefits=None,
    remote=False,
):
    salary_row = f"<tr><th>Salario</th><td>{html.escape(salary)}</td></tr>" if salary else ""
    benefit_html = ""
    if benefits:
        benefit_html = '<div class="beneficios-wrapper">' + "".join(
            f'<div class="beneficios-info"><div class="beneficio-title">{html.escape(name)}</div>'
            f'<div class="beneficio-desc">{html.escape(desc)}</div></div>'
            for name, desc in benefits
        ) + "</div>"
    return f"""
    <html><body>
      <div id="detalle-oferta">
        <div class="datos">
          <table>
            <tr><th>ID</th><td>{job_id}</td></tr>
            <tr><th>Buscado</th><td>{html.escape(company)}</td></tr>
            <tr><th>Fecha</th><td>{date}</td></tr>
            <tr><th>Ubicación</th><td>{html.escape(city)}</td><td>CL</td></tr>
            <tr><th>Categoría</th><td>{html.escape(category)}</td></tr>
            {salary_row}
          </table>
        </div>
        <h1>{html.escape(title)}</h1>
        <div class="job-item detalle">
          <div class="p-x-3">{description}</div>
          {benefit_html}
          <div class="botones-desc mt-3">
            <span class="btn"><i class="fas fa-briefcase"></i>{html.escape(category)}</span>
            <span class="btn"><i class="fas fa-location-arrow"></i>{html.escape(city)}</span>
            <span class="btn"><i class="fa fa-tag"></i>Python</span>
            <span class="btn"><i class="fa fa-tag"></i>APIs</span>
          </div>
        </div>
      </div>
    </body></html>
    """


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.status_code = 200
        self.headers = {"Content-Type": "text/html; charset=UTF-8"}

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"URL no configurada: {url}")
        return FakeResponse(self.routes[url], url)


def config():
    return {"base_url": BASE}


class ListingTests(unittest.TestCase):
    def test_parses_results_without_sidebar_or_ad_duplicate(self):
        first_url = f"{BASE}/trabajo/oferta-100"
        page = scraper.parse_listing_page(
            listing_html(
                [listing_card("Backend Python", "100", "13 de  Noviembre de 2026")],
                total=1,
            ),
            f"{BASE}/encuentra-un-empleo?2=python",
        )
        self.assertEqual(page["total"], 1)
        self.assertEqual(len(page["jobs"]), 1)
        self.assertEqual(page["jobs"][0]["job_id"], "100")
        self.assertEqual(page["jobs"][0]["url"], first_url)
        self.assertEqual(page["jobs"][0]["company"], "Example SpA")
        self.assertEqual(page["jobs"][0]["location"], "Santiago")
        self.assertEqual(page["jobs"][0]["published_at"].date().isoformat(), "2026-11-13")
        self.assertEqual(page["cities"]["santiago"], "1022")

    def test_no_results_does_not_use_sidebar_cards(self):
        page = scraper.parse_listing_page(
            listing_html([], total=0),
            f"{BASE}/encuentra-un-empleo?2=noexiste",
        )
        self.assertEqual(page["total"], 0)
        self.assertEqual(page["jobs"], [])

    def test_relative_dates_parser_is_explicit(self):
        self.assertIsNone(scraper.parse_spanish_date("hace 3 días"))
        self.assertIsNone(scraper.parse_spanish_date("ayer"))
        self.assertEqual(
            scraper.parse_spanish_date("03 de septiembre de 2026").isoformat(),
            "2026-09-03T00:00:00-04:00",
        )


class DetailTests(unittest.TestCase):
    def setUp(self):
        self.listing = {
            "job_id": "100",
            "title": "Backend Python…",
            "company": "Example SpA",
            "location": "Santiago",
            "published_at": datetime(2026, 11, 13, tzinfo=scraper.CHILE_TZ),
            "url": f"{BASE}/trabajo/oferta-100",
            "excerpt": "Resumen",
        }

    def test_extracts_complete_detail_and_structured_benefits(self):
        job = scraper.parse_detail_page(
            detail_html(
                salary="50000",
                benefits=[("Trabajo 100% remoto", "Puedes trabajar desde casa")],
            ),
            self.listing,
            scraped_at=isoformat_z(NOW),
        )
        self.assertEqual(tuple(job.keys()), JOB_FIELDS)
        validate_job(job)
        self.assertEqual(job["title"], "Backend Python")
        self.assertEqual(job["company"], "Example SpA")
        self.assertEqual(job["job_id"], "100")
        self.assertEqual(job["modality"], "remoto")
        self.assertEqual(job["location"], "Remoto")
        self.assertEqual(job["salary"], "50000")
        self.assertEqual(job["published_at"], "2026-11-13T14:35:55Z")
        self.assertIn("Desarrollar APIs en Python.\nMantener servicios.", job["description"])
        self.assertIn("Beneficios", job["description"])
        self.assertIn("Trabajo 100% remoto", job["description"])
        self.assertEqual(job["tags"], ["Informática / Telecomunicaciones", "Python", "APIs"])

    def test_explicit_description_modality_and_empty_salary(self):
        job = scraper.parse_detail_page(
            detail_html(description="<p>Modalidad híbrida en Santiago.</p>"),
            self.listing,
            scraped_at=isoformat_z(NOW),
        )
        self.assertEqual(job["modality"], "híbrido")
        self.assertIsNone(job["salary"])
        self.assertEqual(job["location"], "Santiago")

    def test_conflicting_structured_modalities_are_null(self):
        job = scraper.parse_detail_page(
            detail_html(
                benefits=[
                    ("Trabajo 100% remoto", "Desde casa"),
                    ("Trabajo Híbrido", "Casa y oficina"),
                ]
            ),
            self.listing,
            scraped_at=isoformat_z(NOW),
        )
        self.assertIsNone(job["modality"])


class CollectionTests(unittest.TestCase):
    def run_collection(self, routes, **overrides):
        values = {
            "query": "python",
            "location": "Chile",
            "days": 30,
            "max_results": None,
            "config": config(),
            "now": NOW,
        }
        values.update(overrides)
        return scraper.collect_jobs(FakeClient(routes), **values)

    def test_full_pagination_exact_date_filter_and_details(self):
        search_one = scraper.build_search_url(config(), "python", 30)
        page_two_url = f"{BASE}/encuentra-un-empleo/30?page=2"
        listing_one = listing_html(
            [
                listing_card("Vigente", "100", "13 de Noviembre de 2026"),
                listing_card("Antigua", "101", "01 de Octubre de 2026"),
            ],
            total=3,
            next_url=page_two_url,
        )
        listing_two = listing_html(
            [listing_card("Vigente dos", "102", "10 de Noviembre de 2026")],
            total=3,
        )
        routes = {
            search_one: listing_one,
            page_two_url: listing_two,
            f"{BASE}/trabajo/oferta-100": detail_html(job_id="100", title="Vigente"),
            f"{BASE}/trabajo/oferta-102": detail_html(job_id="102", title="Vigente dos", date="2026-11-10 09:00:00"),
        }
        jobs, stats = self.run_collection(routes)

        self.assertEqual([job["job_id"] for job in jobs], ["100", "102"])
        self.assertEqual(stats["pages"], 2)
        self.assertEqual(stats["received"], 3)
        self.assertEqual(stats["discarded_date"], 1)
        self.assertEqual(stats["details_fetched"], 2)
        self.assertEqual(stats["saved"], 2)
        for job in jobs:
            validate_job(job)

    def test_detail_date_outside_window_is_discarded(self):
        search_url = scraper.build_search_url(config(), "python", 30)
        listing = listing_html(
            [listing_card("Borde de fecha", "100", "16 de Octubre de 2026")],
            total=1,
        )
        detail = detail_html(date="2026-10-15 10:00:00")
        jobs, stats = self.run_collection(
            {search_url: listing, f"{BASE}/trabajo/oferta-100": detail}
        )
        self.assertEqual(jobs, [])
        self.assertEqual(stats["discarded_date"], 1)

    def test_max_results_limits_detail_requests(self):
        search_url = scraper.build_search_url(config(), "python", 30)
        listing = listing_html(
            [
                listing_card("Primera", "100", "13 de Noviembre de 2026"),
                listing_card("Segunda", "101", "12 de Noviembre de 2026"),
            ],
            total=2,
        )
        client = FakeClient(
            {
                search_url: listing,
                f"{BASE}/trabajo/oferta-100": detail_html(job_id="100", date="2026-11-13 11:35:55"),
            }
        )
        jobs, _ = scraper.collect_jobs(
            client,
            query="python",
            location="Chile",
            days=30,
            max_results=1,
            config=config(),
            now=NOW,
        )
        self.assertEqual([job["job_id"] for job in jobs], ["100"])
        detail_calls = [url for url in client.calls if "/trabajo/" in url]
        self.assertEqual(detail_calls, [f"{BASE}/trabajo/oferta-100"])

    def test_known_city_uses_portal_filter(self):
        base_url = scraper.build_search_url(config(), "python", 30)
        city_url = scraper.add_city_filter(base_url, "1022")
        routes = {
            base_url: listing_html(
                [listing_card("Backend", "100", "13 de Noviembre de 2026")],
                total=1,
            ),
            city_url: listing_html(
                [listing_card("Backend", "100", "13 de Noviembre de 2026")],
                total=1,
            ),
            f"{BASE}/trabajo/oferta-100": detail_html(),
        }
        jobs, _ = self.run_collection(routes, location="Santiago")
        self.assertEqual(len(jobs), 1)
        self.assertIn("13=1022", city_url)

    def test_deduplicates_same_listing(self):
        search_url = scraper.build_search_url(config(), "python", 30)
        card = listing_card("Backend", "100", "13 de Noviembre de 2026")
        routes = {
            search_url: listing_html([card, card], total=2),
            f"{BASE}/trabajo/oferta-100": detail_html(),
        }
        jobs, stats = self.run_collection(routes)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(stats["duplicates"], 1)


if __name__ == "__main__":
    unittest.main()
