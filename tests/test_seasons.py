import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database, seasons


class SeasonsTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def test_cached_catalog_and_recurring_month_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _, _ = self.make_app(Path(directory))
            with app.app_context(), patch("pathlib.Path.open", side_effect=AssertionError("read after startup")):
                self.assertEqual(len(app.extensions["rainy_seasons"]), 12353)
                for month in range(1, 13):
                    result = seasons.for_site("DS005429", date(2030, month, 1))
                    rainy = 5 <= month <= 11
                    self.assertEqual(result, {
                        "label": "Rainy season" if rainy else "Dry season",
                        "start_month": "May" if rainy else "November",
                        "end_month": "November" if rainy else "May",
                    })
                self.assertEqual(seasons.for_site("DS003250", date(2030, 1, 1))["label"], "Dry season")
                self.assertEqual(seasons.for_site("DS003250", date(2030, 3, 1))["label"], "Rainy season")
                self.assertEqual(seasons.for_site("DS012966", date(2030, 8, 1))["label"], "Dry season")
                self.assertEqual(seasons.for_site("DS012966", date(2030, 12, 1))["label"], "Rainy season")
                self.assertEqual(seasons.for_site("DS004282", date(2030, 2, 1)), {
                    "label": "Rainy season",
                    "start_month": "September",
                    "end_month": "April",
                })
                self.assertEqual(seasons.for_site("DS004282", date(2030, 6, 1)), {
                    "label": "Dry season",
                    "start_month": "April",
                    "end_month": "September",
                })
                self.assertIsNone(seasons.for_site(None))
                self.assertIsNone(seasons.for_site("missing"))

    def test_site_page_renders_bold_season_and_hides_missing_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _, _ = self.make_app(Path(directory))
            client = app.test_client()
            self.signup(client)
            self.assertNotIn(b'class="site-season-advice"', client.get('/dive-sites/1').data)
            with app.app_context():
                db = database.get_db()
                db.execute("UPDATE dive_sites SET master_site_id='DS005429' WHERE id=1")
                db.commit()
            with patch("pelagia.seasons.datetime") as clock:
                clock.now.return_value = datetime(2026, 10, 27)
                self.assertIn(b'<strong>Rainy season</strong> from May to November', client.get('/dive-sites/1').data)
                clock.now.return_value = datetime(2026, 12, 1)
                self.assertIn(b'<strong>Dry season</strong> from November to May', client.get('/dive-sites/1').data)
