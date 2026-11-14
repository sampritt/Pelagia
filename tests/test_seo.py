import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

import test_reference_autocomplete as fixtures
from pelagia import db as database, seo


class PublicSeoTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = fixtures.ReferenceAutocompleteTest().make_app(Path(self.directory.name))
        self.app.config["PUBLIC_BASE_URL"] = "https://pelagia.example"
        with (Path(__file__).resolve().parents[1] / "data/global_dive_sites_master.csv").open(encoding="utf-8") as source:
            self.catalog = {row["master_site_id"]: row for row in csv.DictReader(source)}
        with self.app.app_context():
            db = database.get_db()
            # Deliberately avoid assuming catalog IDs equal database primary keys.
            for site_id, master_id in enumerate(seo.selected_sites(), 50000):
                row = self.catalog[master_id]
                db.execute("INSERT INTO dive_sites (id, master_site_id, name, country_or_area, latitude, longitude) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (site_id, master_id, row["dive_site_name"],
                           row["country_or_area"], row["latitude"], row["longitude"]))
            db.commit()
        self.client = self.app.test_client()

    def test_selection_is_exactly_100_real_distinct_global_sites(self):
        selected = list(seo.selected_sites().values())
        self.assertEqual(len(selected), 100)
        self.assertEqual(len({row["master_site_id"] for row in selected}), 100)
        self.assertGreaterEqual(len({row["country"] for row in selected}), 30)
        self.assertEqual(len(Counter(row["region"] for row in selected)), 7)
        for row in selected:
            record = self.catalog[row["master_site_id"]]
            self.assertTrue(-90 <= float(record["latitude"]) <= 90)
            self.assertTrue(-180 <= float(record["longitude"]) <= 180)
            self.assertTrue(row["description"].strip())

    def test_sitemap_and_directory_match_indexable_pages_without_paid_generation(self):
        sitemap = ElementTree.fromstring(self.client.get("/sitemap.xml").data)
        urls = [node.text for node in sitemap.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        site_urls = [url for url in urls if "/explore/dive-sites/" in url]
        self.assertEqual(len(site_urls), 100)
        self.assertEqual(len(urls), len(set(urls)))
        directory = self.client.get("/dive-sites").get_data(as_text=True)
        with patch("pelagia.site_descriptions.generate_description", side_effect=AssertionError("Paid request")):
            for url in site_urls:
                path = url.removeprefix("https://pelagia.example")
                self.assertIn(f'href="{path}"', directory)
                response = self.client.get(path)
                html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Robots-Tag"], "index, follow")
                self.assertIn('name="robots" content="index, follow"', html)
                self.assertIn(f'rel="canonical" href="{url}"', html)
                self.assertIn('class="site-description"', html)
                self.assertNotIn("data-description-url", html)
                self.assertIn('href="/dive-sites"', html)
        homepage = self.client.get("/").get_data(as_text=True)
        footer = homepage.split('<footer class="marketing-footer">', 1)[1].split('</footer>', 1)[0]
        self.assertIn('<a href="/dive-sites">Dive Sites</a>', footer)
        self.assertEqual(homepage.count('href="/dive-sites"'), 1)
        self.assertIn('https://pelagia.example/dive-sites', urls)
        self.assertNotIn("/share/", " ".join(urls))

    def test_unselected_and_share_pages_stay_noindexed(self):
        for path in ("/explore/dive-sites/1", "/share/dive-site/50000", "/share/dive/999999"):
            response = self.client.get(path)
            if response.status_code == 200:
                self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
                self.assertIn('content="noindex, nofollow"', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/explore/dive-sites/999999').status_code, 404)

    def test_centers_require_a_cached_description_location_and_coordinates(self):
        self.assertEqual(self.client.get('/explore/dive-centers/1').headers['X-Robots-Tag'], 'noindex, nofollow')
        with self.app.app_context():
            db = database.get_db()
            db.execute("UPDATE dive_centers SET latitude=0, longitude=0 WHERE id=1")
            db.execute("INSERT INTO dive_center_descriptions (dive_center_id, description, model) VALUES (1, 'A local dive center offering guided boat dives.', 'test')")
            db.commit()
        response = self.client.get('/explore/dive-centers/1')
        self.assertEqual(response.headers['X-Robots-Tag'], 'index, follow')
        self.assertIn(b'https://pelagia.example/explore/dive-centers/1', self.client.get('/sitemap.xml').data)
        self.assertEqual(self.client.get('/share/dive-center/1').headers['X-Robots-Tag'], 'noindex, nofollow')
        with self.app.app_context():
            database.get_db().execute("UPDATE dive_center_descriptions SET description=NULL")
            database.get_db().commit()
        self.assertNotIn(b'/explore/dive-centers/1', self.client.get('/sitemap.xml').data)

    def test_cached_description_is_preferred_and_private_logs_are_excluded(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (id, username) VALUES (1, 'PRIVATE_DIVER')")
            db.execute("INSERT INTO dives (user_id, dive_site_id, date, site_name, notes) "
                       "VALUES (1, 50000, '2026-11-01', 'PRIVATE_TITLE', 'PRIVATE_NOTES')")
            db.execute("INSERT INTO dive_site_descriptions (dive_site_id, description, model) "
                       "VALUES (50000, 'A cached description of this wreck.', 'test')")
            db.commit()
        html = self.client.get('/explore/dive-sites/50000').get_data(as_text=True)
        self.assertIn('A cached description of this wreck.', html)
        for private in ('PRIVATE_DIVER', 'PRIVATE_TITLE', 'PRIVATE_NOTES'):
            self.assertNotIn(private, html)
