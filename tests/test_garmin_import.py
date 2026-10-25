import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pelagia import create_app
from pelagia import db as database
from pelagia.garmin_fit import MAX_FIT_BYTES
from test_garmin_fit import fit_messages, make_fit


URL = "/api/dive-import/garmin"
HEADERS = {"X-Requested-With": "fetch", "Content-Type": "application/octet-stream"}


class GarminImportTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            self.app = create_app({"TESTING": True, "SECRET_KEY": "fit-tests",
                                   "DATABASE": str(self.root / "test.sqlite3"),
                                   "UPLOAD_FOLDER": str(self.root / "uploads")})
        self.client = self.app.test_client()
        with self.app.app_context():
            db = database.get_db()
            db.executemany("INSERT INTO users (username) VALUES (?)", [("diver",), ("other",)])
            db.executemany("INSERT INTO dive_sites (id, name, country_or_area, latitude, longitude) VALUES (?, ?, ?, ?, ?)", [
                (2544, "Daphne", "Ecuador", -0.39688, -90.35088),
                (3248, "Daphne Minor", "Galápagos Islands", -0.4, -90.37),
                (1, "No coordinates", "Unknown", None, None)])
            db.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    def import_dive(self, messages=None):
        response = self.client.post(URL, data=make_fit(messages), headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def save(self, result, path="/dive/new", **extra):
        return self.client.post(path, data={**result["fields"], "notes": "Keep my notes",
                                           "air_temp_c": "31", "dive_computer_data_json": json.dumps(result["computer_data"]), **extra})

    def stored(self, table="dive_computer_data"):
        with self.app.app_context():
            return [dict(row) for row in database.get_db().execute(f"SELECT * FROM {table}")]

    def test_import_matches_all_sites_and_does_not_save_file_or_dive(self):
        before = sorted(str(path) for path in (self.root / "uploads").rglob("*"))
        with patch("werkzeug.formparser.SpooledTemporaryFile", side_effect=AssertionError("Multipart spool used")):
            result = self.import_dive()
        self.assertEqual(result["fields"]["site_name"], "Daphne")
        self.assertEqual(result["fields"]["dive_site_id"], 2544)
        self.assertEqual(result["fields"]["country_or_area"], "Ecuador")
        self.assertNotEqual(result["fields"]["longitude"], -90.35088)
        self.assertAlmostEqual(result["matched_site"]["distance_m"], 88.24, places=2)
        self.assertEqual(self.stored("dives"), [])
        self.assertEqual(self.stored(), [])
        self.assertEqual(before, sorted(str(path) for path in (self.root / "uploads").rglob("*")))

    def test_api_errors_are_json_and_not_cached(self):
        for headers, data, status in [({}, b"x", 403),
                                      ({"X-Requested-With": "fetch", "Content-Type": "multipart/form-data"}, b"x", 415),
                                      (HEADERS, b"garbage", 422), (HEADERS, b"x" * (MAX_FIT_BYTES + 1), 413),
                                      (HEADERS, b"x" * (25 * 1024 * 1024), 413)]:
            with self.subTest(status=status):
                response = self.client.post(URL, data=data, headers=headers)
                self.assertEqual(response.status_code, status)
                self.assertIsInstance(response.get_json()["error"], str)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.client.session_transaction() as session:
            session.clear()
        response = self.client.post(URL, data=make_fit(), headers=HEADERS)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_oversize_stream_without_content_length_is_bounded(self):
        import io
        response = self.client.open(URL, method="POST", headers=HEADERS, environ_overrides={
            "wsgi.input": io.BytesIO(b"x" * (MAX_FIT_BYTES + 1)), "wsgi.input_terminated": True, "CONTENT_LENGTH": ""})
        self.assertEqual(response.status_code, 413)

    def test_missing_gps_does_not_replace_existing_location_fields(self):
        messages = fit_messages()
        messages[1].pop("end_position_lat")
        result = self.import_dive(messages)
        self.assertIsNone(result["matched_site"])
        self.assertNotIn("site_name", result["fields"])
        self.assertNotIn("latitude", result["fields"])

    def test_empty_catalog_clears_stale_site_but_preserves_recorded_coordinates(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("DELETE FROM dive_sites")
            db.commit()
        result = self.import_dive()
        self.assertEqual(result["fields"]["site_name"], "")
        self.assertEqual(result["fields"]["dive_site_id"], "")
        self.assertIn("latitude", result["fields"])

    def test_save_edit_and_reimport_roundtrip(self):
        result = self.import_dive()
        response = self.save(result)
        self.assertEqual(response.status_code, 302)
        data = json.loads(self.stored()[0]["data_json"])
        self.assertEqual(data, result["computer_data"])
        dive = self.stored("dives")[0]
        self.assertEqual(dive["notes"], "Keep my notes")
        self.assertEqual(dive["air_temp_c"], 31)
        self.assertEqual(dive["depth_m"], 21.038)
        self.assertEqual(dive["oxygen_pct"], 33)
        self.assertEqual(dive["latitude"], result["fields"]["latitude"])
        edit = self.client.get("/dive/1/edit").get_data(as_text=True)
        self.assertIn("Garmin depth profile saved · 4 measurements", edit)
        self.assertNotIn("depth_profile", edit)
        self.assertEqual(self.client.post("/dive/1/edit", data={"site_name": "Manual edit", "date": "2026-10-09"}).status_code, 302)
        self.assertEqual(json.loads(self.stored()[0]["data_json"]), data)
        replacement = copy.deepcopy(result)
        replacement["computer_data"]["depth_profile"][1]["depth_m"] = 18.5
        self.assertEqual(self.save(replacement, "/dive/1/edit").status_code, 302)
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(json.loads(self.stored()[0]["data_json"])["depth_profile"][1]["depth_m"], 18.5)

    def test_chart_follows_map_precedes_photos_and_uses_viewer_units(self):
        self.save(self.import_dive())
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'dives/test.jpg')")
            db.execute("UPDATE users SET length_unit = 'ft' WHERE id = 1")
            db.commit()
        html = self.client.get("/dive/1").get_data(as_text=True)
        self.assertLess(html.index('depth-profile-slide'), html.index('alt="Dive photo'))
        self.assertLess(html.index('mini-map detail-map'), html.index('depth-profile-slide'))
        self.assertLess(html.index('alt="Dive photo'), html.index('detail-headline-stats'))
        self.assertIn('data-gallery-dot', html)
        self.assertIn('>54 min</text>', html)
        self.assertNotIn('54.2 min</text>', html)
        feed = self.client.get('/home').get_data(as_text=True)
        self.assertIn('depth-profile-chart', feed)
        self.assertIn('depthProfileFill-1', feed)
        self.assertLess(feed.index('class="mini-map'), feed.index('depth-profile-slide'))
        self.assertIn('data-gallery-dot', feed)
        self.assertNotIn('data-gallery-controls', html)
        self.assertNotIn('1 / 2', html)
        self.assertIn('>ft</text>', html)
        self.assertIn('Depth over time', html)
        # Public previews and APIs continue to omit the private computer data.
        with self.client.session_transaction() as session:
            session.clear()
        self.assertNotIn('depth-profile-chart', self.client.get('/share/dive/1').get_data(as_text=True))

    def test_missing_and_unusable_profiles_leave_photo_gallery_available(self):
        result = self.import_dive()
        for points in ([], [{"elapsed_seconds": 0, "depth_m": 1}],
                       [{"elapsed_seconds": 0, "depth_m": 1}] * 2):
            result['computer_data']['depth_profile'] = points
            self.save(result)
            dive_id = self.stored('dives')[-1]['id']
            html = self.client.get(f'/dive/{dive_id}').get_data(as_text=True)
            self.assertNotIn('depth-profile-chart', html)
            self.assertNotIn('data-gallery-controls', html)
            self.assertIn('mini-map detail-map', html)

    def test_bad_profile_rolls_back_both_create_and_edit(self):
        result = self.import_dive()
        good = copy.deepcopy(result)
        result["computer_data"]["depth_profile"][1]["depth_m"] = -5
        self.assertEqual(self.save(result).status_code, 400)
        self.assertEqual(self.stored("dives"), [])
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.save(good).status_code, 302)
        self.assertEqual(self.save(result, "/dive/1/edit", notes="Should roll back").status_code, 400)
        self.assertEqual(self.stored("dives")[0]["notes"], "Keep my notes")
        self.assertEqual(json.loads(self.stored()[0]["data_json"]), good["computer_data"])

    def test_numeric_depth_and_duration_can_exceed_old_caps(self):
        result = self.import_dive()
        for units, depth, average in [("m", 83.123, 50.125), ("ft", 83.123 / .3048, 50.125 / .3048)]:
            with self.subTest(units=units):
                response = self.save(result, depth_m=depth, average_depth_m=average, duration_min=183, length_unit=units)
                self.assertEqual(response.status_code, 302)
                dive = self.stored("dives")[-1]
                self.assertAlmostEqual(dive["depth_m"], 83.123)
                self.assertAlmostEqual(dive["average_depth_m"], 50.125)
                self.assertEqual(dive["duration_min"], 183)

    def test_private_profiles_are_not_exposed_and_delete_cascades(self):
        self.save(self.import_dive())
        for path in ("/api/dives/mine", "/api/dives/1", "/share/dive/1", "/home"):
            self.assertNotIn("depth_profile", self.client.get(path).get_data(as_text=True))
        with self.client.session_transaction() as session:
            session["user_id"] = 2
        self.assertEqual(self.client.get("/dive/1/edit").status_code, 404)
        with self.app.app_context():
            db = database.get_db()
            db.execute("DELETE FROM users WHERE id = 1")
            db.commit()
        self.assertEqual(self.stored(), [])

    def test_new_and_edit_markup_offer_accessible_brand_flow(self):
        self.save(self.import_dive())
        for path in ("/dive/new", "/dive/1/edit"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn("Import from dive computer", html)
            self.assertIn('aria-labelledby="computerImportTitle"', html)
            self.assertIn('data-computer-import-garmin', html)
            self.assertEqual(html.count('class="computer-brand" type="button" disabled'), 5)
            for brand in ("Garmin", "Cressi", "Mares", "Suunto", "Scubapro", "Shearwater"):
                self.assertIn(f"<span>{brand}</span>", html)
            self.assertIn('accept=".fit,.FIT"', html)
            self.assertIn('Export Dive as FIT File', html)

    def test_missing_import_conditions_keep_typical_blank_placeholders(self):
        new = self.client.get("/dive/new").get_data(as_text=True)
        self.assertIn('<output id="currentStrengthOutput">-</output>', new)
        self.assertIn('id="currentTypeSummary" data-multi-select-summary>-</span>', new)
        result = self.import_dive()
        for field in ("current", "current_strength", "air_temp_c", "visibility_m", "weight_kg", "exposure", "water_type"):
            self.assertNotIn(field, result["fields"])
        self.assertEqual(self.save(result, air_temp_c="").status_code, 302)
        detail = self.client.get("/dive/1").get_data(as_text=True)
        values = dict(re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", detail))
        for field in ("Current type", "Current strength", "Air temperature", "Visibility", "Water type",
                      "Weight", "Exposure", "Starting pressure", "Ending pressure", "SAC rate"):
            with self.subTest(field=field):
                self.assertEqual(values[field], "-")
        self.assertEqual(values["Water temperature"], "28°C")
        self.assertEqual(values["Gas mix"], "EANx 33%")
        edit = self.client.get("/dive/1/edit").get_data(as_text=True)
        self.assertIn('<output id="currentStrengthOutput">-</output>', edit)
        self.assertIn('id="currentTypeSummary" data-multi-select-summary>-</span>', edit)
        # Storage remains compatible, so existing missing-current dives also use the corrected labels.
        saved = self.stored("dives")[0]
        self.assertEqual((saved["current"], saved["current_strength"]), ("none", "none"))

    def test_actual_currents_and_zero_measurements_remain_visible(self):
        result = self.import_dive()
        self.assertEqual(self.save(result, current=["tidal", "drift"], current_strength="strong",
                                   air_temp_c="0", visibility_m="0", weight_kg="0", water_type="salt").status_code, 302)
        detail = self.client.get("/dive/1").get_data(as_text=True)
        values = dict(re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", detail))
        self.assertEqual(values["Current type"], "Tidal, Drift")
        self.assertEqual(values["Current strength"], "Strong")
        self.assertEqual(values["Air temperature"], "0°C")
        self.assertEqual(values["Visibility"], "0 m")
        self.assertEqual(values["Weight"], "0 kg")
        self.assertEqual(values["Water type"], "Salt")

    def test_primary_navigation_has_equal_labels_and_tracks_nested_pages(self):
        self.save(self.import_dive())
        for path, destination, current in [("/home", "/home", "page"), ("/explore", "/explore", "page"),
                                           ("/dive/new", "/dive/new", "page"), ("/dive/1/edit", "/dive/new", "location"),
                                           ("/dive/1", "/home", "location"), ("/dive-sites/2544", "/explore", "location"),
                                           ("/you", "/you", "page"), ("/you/settings", "/you", "location")]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                navigations = re.findall(r'<nav class="(?:desktop-nav|mobile-nav)".*?</nav>', response.get_data(as_text=True), re.S)
                self.assertEqual(len(navigations), 2)
                for navigation in navigations:
                    self.assertEqual(re.findall(r"<span>(.*?)</span>", navigation), ["Feed", "Explore", "Log dive", "Profile"])
                    self.assertEqual(re.findall(r'<a class="active" href="([^"]+)" aria-current="([^"]+)"', navigation), [(destination, current)])
