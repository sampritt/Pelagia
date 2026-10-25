import re
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import ImageDraw

import test_reference_autocomplete as fixtures
from pelagia import db as database


METRIC = {"pressure_unit": "bar", "length_unit": "m", "temperature_unit": "c", "weight_unit": "kg"}
IMPERIAL = {"pressure_unit": "psi", "length_unit": "ft", "temperature_unit": "f", "weight_unit": "lb"}


class UnitPreferencesTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, self.db_path, _ = self.make_app(Path(self.directory.name))
        self.client = self.app.test_client()
        self.signup(self.client)

    def assert_selected(self, html, units):
        for field, unit in units.items():
            self.assertRegex(html, rf'name="{field}" value="{unit}" data-unit-toggle="[^"]+" checked')

    def seed_dive(self):
        response = self.client.post("/dive/new", data={
            "date": date.today().isoformat(), "dive_site_id": "1", "dive_center_id": "1",
            "site_name": "Alert Rock", "depth_m": "15.3", "average_depth_m": "10.668",
            "duration_min": "50", "weight_kg": "7.25747792", "starting_pressure_bar": "195.3",
            "ending_pressure_bar": "47.2", "visibility_m": "15.3", "air_temp_c": "23.7",
            "water_temp_c": "-2.4",
        })
        self.assertEqual(response.status_code, 302)
        return self.client.get("/api/dives/mine").get_json()[0]

    def test_defaults_persistence_partial_updates_and_account_isolation(self):
        self.assert_selected(self.client.get("/you/settings").get_data(as_text=True), METRIC)
        self.assert_selected(self.client.get("/dive/new").get_data(as_text=True), METRIC)
        self.assertEqual(self.client.post("/you/settings", data=IMPERIAL).status_code, 302)
        self.client.post("/you", data={"bio": "Diver", "starting_dive_count": "12"})
        self.assert_selected(self.client.get("/you/settings").get_data(as_text=True), IMPERIAL)
        other = self.app.test_client()
        self.signup(other, "other")
        self.assert_selected(other.get("/you/settings").get_data(as_text=True), METRIC)
        self.assertNotIn('id="profileUnitsTitle"', other.get("/users/1").get_data(as_text=True))
        self.client.post("/you/settings", data={"temperature_unit": "c", "user_id": "2"})
        mixed = {**IMPERIAL, "temperature_unit": "c"}
        self.assert_selected(self.client.get("/you/settings").get_data(as_text=True), mixed)
        self.assert_selected(other.get("/you/settings").get_data(as_text=True), METRIC)
        self.client.post("/logout")
        self.signup(self.client)
        self.assert_selected(self.client.get("/dive/new").get_data(as_text=True), mixed)

    def test_invalid_preferences_are_rejected_without_partial_updates(self):
        for field in METRIC:
            for invalid in ("", "unknown", "FT", "0"):
                with self.subTest(field=field, invalid=invalid):
                    self.assertEqual(self.client.post("/you/settings", data={**IMPERIAL, field: invalid}).status_code, 400)
                    self.assert_selected(self.client.get("/you/settings").get_data(as_text=True), METRIC)
        self.assertEqual(self.app.test_client().post("/you/settings", data=IMPERIAL).status_code, 302)
        self.assert_selected(self.client.get("/you/settings").get_data(as_text=True), METRIC)

    def test_display_conversions_cover_feeds_details_profiles_sites_and_charts(self):
        original = self.seed_dive()
        self.client.post("/you/settings", data=IMPERIAL)
        for path in ("/home", "/you", "/users/1", "/dive-sites/1", "/dive-centers/1"):
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                self.assertIn('50 <em>ft</em>', html)
                self.assertNotIn('15 <em>m</em>', html)
        detail = self.client.get("/dive/1").get_data(as_text=True)
        for expected in ("50<em>ft</em>", "35 ft", "16 lb", "2833 psi", "685 psi", "50 ft", "75°F", "28°F"):
            self.assertIn(expected, detail)
        self.assertNotRegex(detail, r"\d+\.\d+\s*(?:ft|psi|°F)")
        profile = self.client.get("/you").get_data(as_text=True)
        self.assertIn(": 50 ft", profile)
        site = self.client.get("/dive-sites/1").get_data(as_text=True)
        for expected in ("50 ft", 'data-temperature-unit="f"', 'data-length-unit="ft"', "Current velocity", "Tide level"):
            self.assertIn(expected, site)
        viewer = self.app.test_client()
        self.signup(viewer, "metric-viewer")
        self.assertIn('15 <em>m</em>', viewer.get("/users/1").get_data(as_text=True))
        self.assertEqual(original, self.client.get("/api/dives/1").get_json())
        self.client.post("/you/settings", data={"length_unit": "m", "weight_unit": "kg"})
        mixed = self.client.get("/dive/1").get_data(as_text=True)
        for expected in ("15<em>m</em>", "11 m", "7.5 kg", "2833 psi", "75°F"):
            self.assertIn(expected, mixed)

    def test_form_preferences_are_defaults_and_do_not_override_submitted_units(self):
        self.seed_dive()
        self.client.post("/you/settings", data=IMPERIAL)
        for path in ("/dive/new", "/dive/1/edit"):
            self.assert_selected(self.client.get(path).get_data(as_text=True), IMPERIAL)
        self.client.post("/dive/1/edit", data={"site_name": "Alert Rock", "depth_m": "20", "weight_kg": "8.5",
                                              "duration_min": "40", **METRIC})
        dive = self.client.get("/api/dives/1").get_json()
        self.assertEqual(dive["depth_m"], 20)
        self.assertEqual(dive["weight_kg"], 8.5)
        self.assert_selected(self.client.get("/dive/new").get_data(as_text=True), IMPERIAL)
        self.assertIn('<dd>-</dd>', self.client.get("/dive/1").get_data(as_text=True))

    def test_water_type_defaults_to_none_and_is_saved(self):
        form = self.client.get("/dive/new").get_data(as_text=True)
        self.assertNotIn('name="water_type" value="none"', form)
        self.assertIn('data-water-type-label aria-live="polite">-</output>', form)
        self.assertIn('name="water_type" value="fresh"', form)
        self.assertIn('name="water_type" value="salt"', form)
        response = self.client.post("/dive/new", data={
            "date": date.today().isoformat(), "site_name": "Freshwater Point", "depth_m": "10",
            "duration_min": "45", "water_type": "fresh",
        })
        self.assertEqual(response.status_code, 302)
        dive = self.client.get("/api/dives/mine").get_json()[0]
        self.assertEqual(dive["water_type"], "fresh")
        self.assertIn("Fresh", self.client.get(f"/dive/{dive['id']}").get_data(as_text=True))
        for value, expected in (("salt", "salt"), ("none", "none"), ("invalid", "none")):
            self.client.post(f"/dive/{dive['id']}/edit", data={
                "site_name": "Freshwater Point", "depth_m": "10", "duration_min": "45", "water_type": value,
            })
            self.assertEqual(self.client.get(f"/api/dives/{dive['id']}").get_json()["water_type"], expected)

    def test_full_cylinder_pressure_labels_preserve_exact_measurements(self):
        from pelagia.units import PSI_TO_BAR

        self.assertAlmostEqual(PSI_TO_BAR, 0.06894757293168361)
        for unit, entered, expected in (("psi", "3000", 3000 * PSI_TO_BAR), ("bar", "200", 200)):
            response = self.client.post("/dive/new", data={
                "site_name": "Alert Rock", "date": "2026-10-01", "depth_m": "15", "duration_min": "45",
                "starting_pressure_bar": entered, "pressure_unit": unit,
            })
            self.assertEqual(response.status_code, 302)
            dive = max(self.client.get("/api/dives/mine").get_json(), key=lambda item: item["id"])
            self.assertAlmostEqual(dive["starting_pressure_bar"], expected, places=8)
            for preference, label in (("bar", "200 bar"), ("psi", "3000 psi")):
                self.client.post("/you/settings", data={"pressure_unit": preference})
                self.assertIn(label, self.client.get(f"/dive/{dive['id']}").get_data(as_text=True))

    def test_share_images_use_viewer_units_and_guests_keep_metric_defaults(self):
        self.seed_dive()
        self.client.post("/you/settings", data=IMPERIAL)
        drawn = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original_text(draw, xy, text, *args, **kwargs)

        with patch("pelagia.sharing.render_static_map", return_value=None), patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            response = self.client.get("/share/dive/1/preview.jpg")
            self.assertEqual(response.status_code, 200)
            for text in ("50", "35", "ft"):
                self.assertIn(text, drawn)
            self.assertIn("Cookie", response.headers.get("Vary", ""))
            drawn.clear()
            guest = self.app.test_client()
            self.assertEqual(guest.get("/share/dive/1/preview.jpg").status_code, 200)
            for text in ("15", "11", "m"):
                self.assertIn(text, drawn)
            self.assertNotIn("ft", drawn)
            self.assertIn("15<em>m</em>", guest.get("/share/dive/1").get_data(as_text=True))

    def test_existing_accounts_migrate_to_metric_without_changing_dives(self):
        with tempfile.TemporaryDirectory() as directory:
            def prepare(path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                schema = re.sub(r"^    (?:pressure|length|temperature|weight)_unit .*\n", "", schema, flags=re.MULTILINE)
                with sqlite3.connect(path) as db:
                    db.executescript(schema)
                    db.execute("INSERT INTO users (username) VALUES ('legacy')")
                    db.execute("INSERT INTO dives (user_id, date, site_name, depth_m, weight_kg) VALUES (1, '2026-01-01', 'Legacy', 15.3, 7.25747792)")
            app, _, _ = self.make_app(Path(directory), prepare_db=prepare)
            client = app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = 1
            self.assert_selected(client.get("/you/settings").get_data(as_text=True), METRIC)
            client.post("/you/settings", data=IMPERIAL)
            with app.app_context():
                database.init_db()
                database.init_db()
                dive = database.get_db().execute("SELECT depth_m, weight_kg FROM dives").fetchone()
                self.assertEqual(tuple(dive), (15.3, 7.25747792))
            self.assert_selected(client.get("/you/settings").get_data(as_text=True), IMPERIAL)
