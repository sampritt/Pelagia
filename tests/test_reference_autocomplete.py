import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pelagia import create_app, sac_rate, sac_rate_display, sac_tank_size, dive_site_recent_conditions
from pelagia import db as database
from pelagia.units import PSI_TO_BAR


def write_csv(path, content):
    path.write_text(content.strip() + "\n")


def image_upload(name, color):
    stream = io.BytesIO()
    Image.new("RGB", (160, 110), color).save(stream, "JPEG")
    stream.seek(0)
    return stream, name


class ReferenceAutocompleteTest(unittest.TestCase):
    def test_pressure_numeric_limits_are_independent_of_sliders_and_saved_in_bar(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            form = client.get("/dive/new").data
            for field in ("starting_pressure_bar", "ending_pressure_bar"):
                self.assertIn(f'name="{field}" type="number" min="0" max="300"'.encode(), form)
            self.assertIn(b'min="0" max="200" step="10" value="200" data-range="startingPressure"', form)
            for unit, start, end, expected_start, expected_end in (
                ("bar", "250", "50", 250, 50),
                ("bar", "300", "250", 300, 250),
                ("bar", "350", "325", 300, 300),
                ("psi", "3000", "600", 3000 * PSI_TO_BAR, 600 * PSI_TO_BAR),
                ("psi", "4000", "3500", 4000 * PSI_TO_BAR, 3500 * PSI_TO_BAR),
                ("psi", "4351", "3500", 4351 * PSI_TO_BAR, 3500 * PSI_TO_BAR),
                ("psi", "5000", "4500", 300, 300),
            ):
                with self.subTest(unit=unit, start=start, end=end):
                    payload = {"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50", "pressure_unit": unit,
                               "starting_pressure_bar": start, "ending_pressure_bar": end}
                    payload["date"] = (date(2026, 1, 1) + timedelta(days=len(client.get("/api/dives/mine").get_json()))).isoformat()
                    self.assertEqual(client.post("/dive/new", data=payload).status_code, 302)
                    dive = max(client.get("/api/dives/mine").get_json(), key=lambda item: item["id"])
                    self.assertAlmostEqual(dive["starting_pressure_bar"], expected_start, places=8)
                    self.assertAlmostEqual(dive["ending_pressure_bar"], expected_end, places=8)
                    self.assertAlmostEqual(dive["sac_rate_l_min"], (expected_start - expected_end) / 50 / 3 * 12)
                    # Reopen and resave in metric without discarding pressures
                    # above the 200 bar slider maximum.
                    self.assertEqual(client.get(f"/dive/{dive['id']}/edit").status_code, 200)
                    self.assertEqual(client.post(f"/dive/{dive['id']}/edit", data={**payload, "pressure_unit": "bar",
                                     "starting_pressure_bar": str(dive["starting_pressure_bar"]),
                                     "ending_pressure_bar": str(dive["ending_pressure_bar"])}).status_code, 302)
                    resaved = client.get(f"/api/dives/{dive['id']}").get_json()
                    self.assertEqual(resaved["starting_pressure_bar"], dive["starting_pressure_bar"])
                    self.assertEqual(resaved["ending_pressure_bar"], dive["ending_pressure_bar"])

    def test_imperial_form_measurements_are_saved_in_metric_and_used_for_sac(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            form = client.get("/dive/new").data
            for group, metric, alternate in (("length", "m", "ft"), ("weight", "kg", "lb"),
                                             ("pressure", "bar", "psi"), ("temperature", "c", "f")):
                self.assertIn(f'name="{group}_unit" value="{metric}" data-unit-toggle="{group}" checked'.encode(), form)
                self.assertIn(f'name="{group}_unit" value="{alternate}" data-unit-toggle="{group}"'.encode(), form)
            payload = {"site_name": "Alert Rock", "depth_m": "100", "average_depth_m": "35", "duration_min": "50",
                       "weight_kg": "16", "starting_pressure_bar": "2850", "ending_pressure_bar": "600",
                       "air_temp_c": "75", "water_temp_c": "65", "visibility_m": "150", "tank_size_l": "15",
                       "length_unit": "ft", "weight_unit": "lb", "pressure_unit": "psi", "temperature_unit": "f"}
            self.assertEqual(client.post("/dive/new", data=payload).status_code, 302)
            dive = client.get("/api/dives/mine").get_json()[0]
            expected = {"depth_m": 30.48, "average_depth_m": 10.668, "weight_kg": 7.25747792,
                        "starting_pressure_bar": 2850 * PSI_TO_BAR, "ending_pressure_bar": 600 * PSI_TO_BAR,
                        "air_temp_c": (75 - 32) * 5 / 9, "water_temp_c": (65 - 32) * 5 / 9, "visibility_m": 45.72}
            for field, value in expected.items():
                self.assertAlmostEqual(dive[field], value, places=8)
            expected_sac = (dive["starting_pressure_bar"] - dive["ending_pressure_bar"]) / 50 / (10.668 / 10 + 1) * 15
            self.assertAlmostEqual(dive["sac_rate_l_min"], expected_sac)
            dive_id = dive["id"]
            edit_url = f"/dive/{dive_id}/edit"
            edit = client.get(edit_url).data
            self.assertIn(b'value="30" data-number="depth"', edit)
            self.assertIn(b'value="11" data-number="averageDepth"', edit)
            self.assertIn(b'value="15" data-tank-size checked', edit)
            # Editing starts from stored metric, so re-saving defaults to metric.
            metric_payload = {"site_name": "Alert Rock", "duration_min": "50", "tank_size_l": "15",
                              **{field: str(dive[field]) for field in expected}}
            self.assertEqual(client.post(edit_url, data=metric_payload).status_code, 302)
            saved = client.get(f"/api/dives/{dive_id}").get_json()
            for field in expected:
                self.assertEqual(saved[field], dive[field])
            self.assertEqual(saved["sac_rate_l_min"], dive["sac_rate_l_min"])
            # Optional values can still be cleared with imperial units selected.
            client.post(edit_url, data={**payload, "average_depth_m": "", "weight_kg": "", "air_temp_c": "", "visibility_m": ""})
            cleared = client.get(f"/api/dives/{dive_id}").get_json()
            for field in ("average_depth_m", "weight_kg", "air_temp_c", "visibility_m"):
                self.assertIsNone(cleared[field])
            self.assertAlmostEqual(cleared["sac_rate_l_min"], (2850 - 600) * PSI_TO_BAR / 50 / (30.48 / 10 + 1) * 15)
            with sqlite3.connect(db_path) as conn:
                column_types = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(dives)")}
                for field in expected:
                    self.assertEqual(column_types[field], "REAL")
                self.assertNotIn("length_unit", column_types)

    def test_units_convert_before_clamping_and_groups_can_use_different_units(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            payload = {"site_name": "Alert Rock", "depth_m": "100", "average_depth_m": "60", "duration_min": "50",
                       "weight_kg": "8.5", "starting_pressure_bar": "195", "ending_pressure_bar": "47",
                       "air_temp_c": "25", "water_temp_c": "20", "length_unit": "ft"}
            client.post("/dive/new", data=payload)
            dive = client.get("/api/dives/mine").get_json()[0]
            self.assertEqual(dive["depth_m"], 30.48)
            self.assertEqual(dive["average_depth_m"], 18.288)
            self.assertEqual(dive["weight_kg"], 8.5)
            self.assertEqual(dive["starting_pressure_bar"], 195)
            self.assertEqual(dive["air_temp_c"], 25)
            client.post(f"/dive/{dive['id']}/edit", data={**payload, "depth_m": "500", "average_depth_m": "-10",
                        "weight_kg": "100", "weight_unit": "lb", "starting_pressure_bar": "5000", "pressure_unit": "psi",
                        "air_temp_c": "-100", "water_temp_c": "200", "temperature_unit": "f"})
            saved = client.get(f"/api/dives/{dive['id']}").get_json()
            self.assertEqual((saved["depth_m"], saved["average_depth_m"], saved["weight_kg"], saved["starting_pressure_bar"]), (152.4, 0, 10, 300))
            self.assertEqual((saved["air_temp_c"], saved["water_temp_c"]), (-20, 40))
            # Unknown unit names cannot trigger an arbitrary conversion.
            client.post(f"/dive/{dive['id']}/edit", data={**payload, "depth_m": "15.3", "length_unit": "bad"})
            self.assertEqual(client.get(f"/api/dives/{dive['id']}").get_json()["depth_m"], 15.3)

    def test_integer_metric_columns_migrate_preserving_existing_values_and_relationships(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            def prepare_db(db_path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                for field in ("starting_pressure_bar", "ending_pressure_bar", "visibility_m", "air_temp_c", "water_temp_c"):
                    schema = schema.replace(f"{field} REAL", f"{field} INTEGER")
                with sqlite3.connect(db_path) as conn:
                    conn.executescript(schema)
                    conn.execute("INSERT INTO users (id, username) VALUES (1, 'legacy')")
                    conn.execute("""INSERT INTO dives (id, user_id, date, site_name, depth_m, average_depth_m, duration_min,
                                   starting_pressure_bar, ending_pressure_bar, visibility_m, air_temp_c, water_temp_c, sac_rate_l_min,
                                   dive_types_json, current_types_json)
                                   VALUES (1, 1, '2026-10-13', 'Legacy dive', 20, 10.3, 50, 195, 47, 15, 25, 20, 17.5, '["reef", "wall"]', '["tidal", "drift"]')""")
                    conn.execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'existing.jpg')")
                    conn.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (1, 'Coral')")
            app, db_path, _ = self.make_app(Path(tmp_dir), prepare_db=prepare_db)
            with app.app_context():
                database.init_db()
                database.init_db()
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT starting_pressure_bar, ending_pressure_bar, visibility_m, air_temp_c, water_temp_c, sac_rate_l_min FROM dives").fetchone(), (195, 47, 15, 25, 20, 17.5))
                self.assertEqual(conn.execute("SELECT average_depth_m, dive_types_json, current_types_json FROM dives").fetchone(), (10.3, '["reef", "wall"]', '["tidal", "drift"]'))
                self.assertEqual(conn.execute("SELECT dive_id FROM photos").fetchall(), [(1,)])
                self.assertEqual(conn.execute("SELECT dive_id FROM dive_species").fetchall(), [(1,)])
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_multiple_dive_and_current_types_round_trip_and_display(self):
        class CheckedOptionsParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.selected = {"dive_type": [], "current": []}

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("name") in self.selected and "checked" in attrs:
                    self.selected[attrs["name"]].append(attrs["value"])

        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            payload = {"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50",
                       "dive_type": ["open water", "reef", "wall"], "current": ["tidal", "drift"],
                       "current_strength": "moderate"}
            self.assertEqual(client.post("/dive/new", data=payload).status_code, 302)
            dive = client.get("/api/dives/mine").get_json()[0]
            dive_id = dive["id"]
            self.assertEqual(dive["dive_types"], ["open water", "reef", "wall"])
            self.assertEqual(dive["current_types"], ["tidal", "drift"])
            self.assertEqual(dive["dive_type"], "open water")
            self.assertEqual(dive["current"], "tidal")
            self.assertEqual(dive["current_strength"], "moderate")
            for url in ("/home", "/you", f"/dive/{dive_id}", "/dive-sites/1"):
                self.assertIn(b"Open Water, Reef, Wall", client.get(url).data)
            self.assertIn(b"Tidal, Drift", client.get(f"/dive/{dive_id}").data)
            self.assertIn(b"Open Water, Reef, Wall", app.test_client().get(f"/share/dive/{dive_id}").data)

            def edit_selections():
                parser = CheckedOptionsParser()
                page = client.get(f"/dive/{dive_id}/edit")
                self.assertEqual(page.status_code, 200)
                parser.feed(page.data.decode())
                return parser.selected

            for _ in range(2):
                selected = edit_selections()
                self.assertEqual(selected, {"dive_type": payload["dive_type"], "current": payload["current"]})
                self.assertEqual(client.post(f"/dive/{dive_id}/edit", data={**payload, **selected}).status_code, 302)
            updated = {**payload, "dive_type": ["wall", "deep", "drift", "night"], "current": ["upwelling", "downdraft"]}
            client.post(f"/dive/{dive_id}/edit", data=updated)
            self.assertEqual(edit_selections(), {"dive_type": updated["dive_type"], "current": updated["current"]})
            with app.app_context():
                database.init_db()
                database.init_db()
            self.assertEqual(edit_selections(), {"dive_type": updated["dive_type"], "current": updated["current"]})
            self.assertEqual(client.get(f"/api/dives/{dive_id}").get_json()["current"], "upwelling")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT dive_types_json, current_types_json FROM dives").fetchone()
                self.assertEqual(json.loads(row[0]), updated["dive_type"])
                self.assertEqual(json.loads(row[1]), updated["current"])

    def test_multiple_type_validation_and_none_current(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            payload = {"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50", "current_strength": "strong"}
            for dive_types, currents, expected_dives, expected_currents, strength in (
                (["wall", "reef", "wall", "bad"], ["none", "drift", "tidal", "drift", "bad"], ["reef", "wall"], ["tidal", "drift"], "strong"),
                ([], [], ["open water"], ["none"], "none"),
                (["bad"], ["bad", "vertical"], ["open water"], ["none"], "none"),
                (["wreck"], ["none"], ["wreck"], ["none"], "none"),
            ):
                with self.subTest(dive_types=dive_types, currents=currents):
                    client.post("/dive/new", data={**payload, "dive_type": dive_types, "current": currents})
                    dive = max(client.get("/api/dives/mine").get_json(), key=lambda item: item["id"])
                    self.assertEqual(dive["dive_types"], expected_dives)
                    self.assertEqual(dive["current_types"], expected_currents)
                    self.assertEqual(dive["current_strength"], strength)

    def test_legacy_single_types_and_multi_types_survive_schema_migration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            def prepare_db(db_path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                old_schema = schema.replace("    dive_types_json TEXT,\n", "").replace("    current_types_json TEXT,\n", "")
                with sqlite3.connect(db_path) as conn:
                    conn.executescript(old_schema)
                    conn.execute("INSERT INTO users (id, username) VALUES (1, 'legacy')")
                    conn.execute("""INSERT INTO dives (user_id, date, site_name, dive_type, current, current_strength)
                                    VALUES (1, '2026-10-13', 'Legacy dive', 'wall', 'rip', 'strong')""")
            app, db_path, _ = self.make_app(Path(tmp_dir), prepare_db=prepare_db)
            client = app.test_client()
            self.signup(client)
            dive = client.get("/api/dives/1").get_json()
            self.assertEqual(dive["dive_types"], ["wall"])
            self.assertEqual(dive["current_types"], ["rip"])
            # Only the owner sees the edit form, so verify through a legacy session.
            with client.session_transaction() as session:
                session["user_id"] = 1
            edit = client.get("/dive/1/edit").data
            self.assertIn(b'name="dive_type" value="wall" data-option-label="Wall" checked', edit)
            self.assertIn(b'name="current" value="rip" data-option-label="Rip" checked', edit)
            with sqlite3.connect(db_path) as conn:
                conn.execute("UPDATE dives SET dive_types_json = ?, current_types_json = ?", (json.dumps(["reef", "wall"]), json.dumps(["tidal", "rip"])))
                # Exercise the existing table rebuild while keeping the new arrays.
                conn.execute("ALTER TABLE dives ADD COLUMN weight_lbs REAL")
            with app.app_context():
                database.init_db()
            migrated = client.get("/api/dives/1").get_json()
            self.assertEqual(migrated["dive_types"], ["reef", "wall"])
            self.assertEqual(migrated["current_types"], ["tidal", "rip"])
            self.assertEqual(migrated["current_strength"], "strong")

    def test_site_current_summary_counts_all_selected_current_types(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            for currents in (["tidal", "drift"], ["tidal", "drift"], ["drift"]):
                client.post("/dive/new", data={"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50",
                                               "date": date.today().isoformat(), "current": currents, "current_strength": "strong"})
            with app.app_context():
                self.assertEqual(dive_site_recent_conditions(1)["current"], "drift")

    def test_average_depth_is_optional_and_sac_prefers_it_when_present(self):
        dive = {"starting_pressure_bar": 200, "ending_pressure_bar": 50,
                "duration_min": 50, "depth_m": 20}
        for average_depth, expected in ((None, 1), (10, 1.5), (10.3, 3 / 2.03), (0, 3)):
            with self.subTest(average_depth=average_depth):
                values = {**dive, "average_depth_m": average_depth}
                self.assertAlmostEqual(sac_rate(values), expected)
                self.assertEqual(sac_tank_size({**values, "sac_rate_l_min": expected * 15}), 15)
                self.assertIsNone(sac_rate({**values, "starting_pressure_bar": None}))
                self.assertIsNone(sac_rate({**values, "duration_min": 0}))

    def test_average_depth_round_trip_display_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            form = client.get("/dive/new").data
            self.assertIn(b'<output id="averageDepthOutput">-</output>', form)
            self.assertIn(b'name="average_depth_m" type="number" min="0" step="any" placeholder="-" value=""', form)
            self.assertIn(b'min="0" max="45" step="1" value="0" data-range="averageDepth"', form)
            self.assertLess(form.index(b'name="depth_m"'), form.index(b'name="average_depth_m"'))
            self.assertLess(form.index(b'name="average_depth_m"'), form.index(b'name="duration_min"'))
            payload = {"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50",
                       "starting_pressure_bar": "200", "ending_pressure_bar": "50", "tank_size_l": "15"}
            self.assertEqual(client.post("/dive/new", data=payload).status_code, 302)
            dive = client.get("/api/dives/mine").get_json()[0]
            self.assertIsNone(dive["average_depth_m"])
            self.assertEqual(dive["sac_rate_l_min"], 15)
            dive_id = dive["id"]
            edit_url = f"/dive/{dive_id}/edit"
            self.assertNotIn(b"<small>Average depth</small>", client.get("/home").data)
            for value, display in (("10.3", "10"), ("15.0", "15"), ("0", "0")):
                with self.subTest(average_depth=value):
                    self.assertEqual(client.post(edit_url, data={**payload, "average_depth_m": value}).status_code, 302)
                    dive = client.get(f"/api/dives/{dive_id}").get_json()
                    self.assertIsInstance(dive["average_depth_m"], float)
                    self.assertEqual(dive["average_depth_m"], float(value))
                    self.assertEqual(dive["depth_m"], 20)
                    expected = 150 / 50 / (float(value) / 10 + 1) * 15
                    self.assertAlmostEqual(dive["sac_rate_l_min"], expected)
                    edit = client.get(edit_url).data
                    self.assertIn(f'value="{display}" data-number="averageDepth"'.encode(), edit)
                    self.assertIn(b'value="15" data-tank-size checked', edit)
                    for url in ("/home", "/you", f"/dive/{dive_id}", "/dive-sites/1"):
                        page = client.get(url)
                        self.assertEqual(page.status_code, 200)
                        self.assertNotIn(b"<small>Average depth</small>", page.data)
                        if url == f"/dive/{dive_id}":
                            self.assertIn(b"<dt>Average depth</dt>", page.data)
                            self.assertIn(f"<dd>{display} m</dd>".encode(), page.data)
                        else:
                            self.assertNotIn(b"Average depth", page.data)
                        self.assertNotIn(b"15.0", page.data)
                    public = app.test_client().get(f"/share/dive/{dive_id}").data
                    self.assertIn(f"{display} m average depth".encode(), public)
                    self.assertNotIn(b"<small>Average depth</small>", public)
                    # Preserve both average depth and the inferred 15 L tank choice.
                    without_tank = {**payload, "average_depth_m": value}
                    without_tank.pop("tank_size_l")
                    client.post(edit_url, data=without_tank)
                    self.assertAlmostEqual(client.get(f"/api/dives/{dive_id}").get_json()["sac_rate_l_min"], expected)
            self.assertEqual(client.post(edit_url, data={**payload, "average_depth_m": ""}).status_code, 302)
            dive = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertIsNone(dive["average_depth_m"])
            self.assertEqual(dive["sac_rate_l_min"], 15)
            self.assertIn(b'<output id="averageDepthOutput">-</output>', client.get(edit_url).data)
            self.assertNotIn(b"<small>Average depth</small>", client.get("/home").data)
            self.assertNotIn(b"<dt>Average depth</dt>", client.get(f"/dive/{dive_id}").data)
            # Creating a new dive with average depth uses the same calculation.
            client.post("/dive/new", data={**payload, "average_depth_m": "10.3"})
            created = max(client.get("/api/dives/mine").get_json(), key=lambda item: item["id"])
            self.assertEqual(created["average_depth_m"], 10.3)
            self.assertAlmostEqual(created["sac_rate_l_min"], 150 / 50 / 2.03 * 15)
            with sqlite3.connect(db_path) as conn:
                column = next(row for row in conn.execute("PRAGMA table_info(dives)") if row[1] == "average_depth_m")
                self.assertEqual((column[2], column[3]), ("REAL", 0))

    def test_existing_dives_gain_null_average_depth_without_changing_saved_sac(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            def prepare_db(db_path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                with sqlite3.connect(db_path) as conn:
                    conn.executescript(schema.replace("    average_depth_m REAL,\n", ""))
                    conn.execute("INSERT INTO users (id, username) VALUES (1, 'legacy')")
                    conn.execute("""INSERT INTO dives (user_id, date, site_name, depth_m, duration_min, sac_rate_l_min)
                                    VALUES (1, '2026-07-22', 'Legacy dive', 20, 50, 17.5)""")
            app, db_path, _ = self.make_app(Path(tmp_dir), prepare_db=prepare_db)
            with app.app_context():
                database.init_db()
                database.init_db()
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT depth_m, average_depth_m, sac_rate_l_min FROM dives").fetchone(),
                                 (20.0, None, 17.5))
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_edit_species_preload_and_save_preserve_selected_tags(self):
        class SpeciesInputParser(HTMLParser):
            value = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("id") == "speciesJson":
                    self.value = attrs.get("value")

        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            special_name = 'Diver\'s "fish" & ray'
            with app.app_context():
                db = database.get_db()
                db.execute("INSERT INTO species (country_or_area, common_name) VALUES ('Alaska', ?)", (special_name,))
                db.commit()
            selected = ["Coral", "Reef Fish", special_name]
            payload = {"site_name": "Alert Rock", "depth_m": "15.3", "duration_min": "40",
                       "species_json": json.dumps(selected)}
            client.post("/dive/new", data=payload)
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]
            edit_url = f"/dive/{dive_id}/edit"

            def loaded_species():
                parser = SpeciesInputParser()
                page = client.get(edit_url)
                self.assertEqual(page.status_code, 200)
                parser.feed(page.data.decode())
                return json.loads(parser.value)

            self.assertEqual(loaded_species(), sorted(selected))
            # Submit the actual value that a browser reads from the edit form.
            response = client.post(edit_url, data={**payload, "notes": "Updated notes",
                                                  "species_json": json.dumps(loaded_species())})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.get(f"/api/dives/{dive_id}").get_json()["species"], sorted(selected))
            self.assertEqual(loaded_species(), sorted(selected))

            # Removing a tag and adding another saves exactly the new selection.
            updated = [special_name, "Reef Fish", "Turtle"]
            client.post(edit_url, data={**payload, "species_json": json.dumps(updated)})
            self.assertEqual(loaded_species(), sorted(updated))
            self.assertEqual(client.get(f"/api/dives/{dive_id}").get_json()["species"], sorted(updated))
            client.post(edit_url, data={**payload, "species_json": "[]"})
            self.assertEqual(loaded_species(), [])
            self.assertEqual(client.get(f"/api/dives/{dive_id}").get_json()["species"], [])

    def test_slider_steps_are_independent_of_numeric_input_steps(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            form = client.get("/dive/new").data
            self.assertIn(b'min="0" max="45" step="1" value="12" data-range="depth"', form)
            self.assertIn(b'name="depth_m" type="number" min="0" step="any"', form)
            self.assertIn(b'min="0" max="120" step="1" value="80" data-range="duration"', form)
            self.assertIn(b'min="0" max="10" step="0.5" value="0" data-range="weight"', form)
            for name in ("starting_pressure_bar", "ending_pressure_bar"):
                self.assertIn(f'name="{name}" type="number" min="0" max="300" step="1"'.encode(), form)

    def test_decimal_depth_and_integer_pressure_round_trip_and_display(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            payload = {"site_name": "Alert Rock", "depth_m": "15.0", "duration_min": "40",
                       "starting_pressure_bar": "195", "ending_pressure_bar": "47"}
            client.post("/dive/new", data=payload)
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]
            guest = app.test_client()
            for raw, display in (("15.0", "15"), ("15.3", "15"), ("15.3456789", "15")):
                with self.subTest(depth=raw):
                    self.assertEqual(client.post(f"/dive/{dive_id}/edit", data={**payload, "depth_m": raw}).status_code, 302)
                    dive = client.get(f"/api/dives/{dive_id}").get_json()
                    self.assertIsInstance(dive["depth_m"], float)
                    self.assertEqual(dive["depth_m"], float(raw))
                    self.assertEqual(dive["starting_pressure_bar"], 195)
                    self.assertEqual(dive["ending_pressure_bar"], 47)
                    self.assertAlmostEqual(dive["sac_rate_l_min"], (195 - 47) / 40 / (float(raw) / 10 + 1) * 12)
                    edit = client.get(f"/dive/{dive_id}/edit").data
                    self.assertIn(f'<output id="depthOutput">{display} m</output>'.encode(), edit)
                    self.assertIn(f'value="{display}" data-number="depth"'.encode(), edit)
                    for url in (f"/dive/{dive_id}", "/home", "/you"):
                        page = client.get(url).data
                        self.assertIn(display.encode(), page)
                        self.assertNotIn(b"15.0", page)
                    preview = guest.get(f"/share/dive/{dive_id}").data
                    self.assertIn(f"{display} m deep".encode(), preview)
                    self.assertIn(f"{display} m, 40 min".encode(), preview)
                    self.assertNotIn(b"15.0", preview)
            with sqlite3.connect(db_path) as conn:
                depth, storage_type = conn.execute("SELECT depth_m, typeof(depth_m) FROM dives").fetchone()
                self.assertEqual((depth, storage_type), (15.3456789, "real"))

    def test_integer_depth_schema_migration_preserves_dives_and_relationships(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            def prepare_db(db_path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                with sqlite3.connect(db_path) as conn:
                    conn.executescript(schema.replace("depth_m REAL NOT NULL", "depth_m INTEGER NOT NULL"))
                    conn.execute("INSERT INTO users (id, username) VALUES (1, 'legacy')")
                    conn.execute("INSERT INTO dive_sites (id, master_site_id, name) VALUES (1, 'DS1', 'Alert Rock')")
                    for depth in (15, 15.3):
                        conn.execute("""INSERT INTO dives (user_id, dive_site_id, date, site_name, depth_m, average_depth_m, duration_min)
                                        VALUES (1, 1, '2026-07-22', 'Alert Rock', ?, ?, 40)""", (depth, depth - 5))
                    conn.execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'existing.jpg')")
                    conn.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (1, 'Coral')")
                    conn.execute("INSERT INTO likes (dive_id, user_id) VALUES (1, 1)")
                    conn.execute("INSERT INTO comments (dive_id, user_id, body) VALUES (1, 1, 'Existing comment')")
                    database._ensure_dive_site_counts(conn)
            app, db_path, _ = self.make_app(Path(tmp_dir), prepare_db=prepare_db)
            with app.app_context():
                database.init_db()
                database.init_db()
            with sqlite3.connect(db_path) as conn:
                columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(dives)")}
                self.assertEqual(columns["depth_m"], "REAL")
                self.assertEqual(conn.execute("SELECT id, depth_m, typeof(depth_m) FROM dives ORDER BY id").fetchall(),
                                 [(1, 15.0, "real"), (2, 15.3, "real")])
                self.assertEqual(conn.execute("SELECT average_depth_m FROM dives ORDER BY id").fetchall(), [(10.0,), (10.3,)])
                for table in ("photos", "dive_species", "likes", "comments"):
                    self.assertEqual(conn.execute(f"SELECT dive_id FROM {table}").fetchall(), [(1,)])
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(conn.execute("SELECT logged_dive_count FROM dive_sites WHERE id = 1").fetchone()[0], 2)
                conn.execute("UPDATE dives SET is_deleted = 1 WHERE id = 1")
                self.assertEqual(conn.execute("SELECT logged_dive_count FROM dive_sites WHERE id = 1").fetchone()[0], 1)

    def test_sac_rate_calculation_and_display(self):
        dive = {
            "starting_pressure_bar": 200,
            "ending_pressure_bar": 50,
            "duration_min": 50,
            "depth_m": 20,
        }
        self.assertEqual(sac_rate(dive), 1.0)
        self.assertEqual(sac_rate({**dive, "duration_min": 40}), 1.25)
        self.assertEqual(sac_rate_display({**dive, "sac_rate_l_min": 12}), "12 L/min")
        self.assertEqual(sac_rate_display({**dive, "sac_rate_l_min": 18.75}), "19 L/min")
        self.assertEqual(sac_rate_display({**dive, "sac_rate_l_min": 0}), "0 L/min")
        self.assertEqual(sac_tank_size({**dive, "sac_rate_l_min": 15}), 15)
        self.assertEqual(sac_tank_size({**dive, "sac_rate_l_min": 12}), 12)
        self.assertEqual(sac_tank_size({**dive, "sac_rate_l_min": None}), 12)
        for overrides in ({"starting_pressure_bar": None}, {"ending_pressure_bar": None}, {"duration_min": 0}):
            self.assertIsNone(sac_rate({**dive, **overrides}))
            self.assertEqual(sac_rate_display({**dive, **overrides, "sac_rate_l_min": None}), "-")

    def test_sac_is_saved_with_the_dive_and_detail_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            payload = {
                "date": "2026-07-22",
                "site_name": "Alert Rock",
                "depth_m": "20",
                "duration_min": "40",
                "starting_pressure_bar": "200",
                "ending_pressure_bar": "50",
                "tank_size_l": "15",
                "sac_rate_l_min": "999",  # Never trust a client-supplied calculated rate.
            }
            response = client.post("/dive/new", data=payload)
            self.assertEqual(response.status_code, 302)
            dive = client.get("/api/dives/mine").get_json()[0]
            self.assertEqual(dive["sac_rate"], 18.75)
            self.assertEqual(dive["sac_rate_l_min"], 18.75)
            self.assertNotIn("tank_size_preview", dive)
            self.assertNotIn("tank_size_l", dive)
            detail_url = f'/dive/{dive["id"]}'
            edit_url = f'{detail_url}/edit'
            detail = client.get(detail_url).data
            self.assertIn(b"19 L/min", detail)
            self.assertNotIn(b"data-tank-size", detail)
            self.assertNotIn(b"data-pressure-sac", detail)
            edit = client.get(edit_url).data
            self.assertIn(b"19 L/min", edit)
            self.assertIn(b'value="15" data-tank-size checked', edit)
            self.assertIn(b'data-is-edit="true"', edit)
            self.assertIn(b'value="40" data-number="duration"', edit)
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(dives)")}
                self.assertEqual(conn.execute("SELECT sac_rate_l_min FROM dives WHERE id = ?", (dive["id"],)).fetchone()[0], 18.75)
            self.assertFalse(any("tank" in column for column in columns))

            # Re-saving without changing inputs preserves the saved rate.
            client.post(edit_url, data=payload)
            self.assertEqual(client.get(f'/api/dives/{dive["id"]}').get_json()["sac_rate_l_min"], 18.75)
            payload["duration_min"] = "50"
            client.post(edit_url, data=payload)
            self.assertEqual(client.get(f'/api/dives/{dive["id"]}').get_json()["sac_rate_l_min"], 15)
            # Older callers without a tank-size field retain the inferred choice.
            payload.pop("tank_size_l")
            client.post(edit_url, data=payload)
            self.assertEqual(client.get(f'/api/dives/{dive["id"]}').get_json()["sac_rate_l_min"], 15)
            payload["tank_size_l"] = "12"
            client.post(edit_url, data=payload)
            self.assertEqual(client.get(f'/api/dives/{dive["id"]}').get_json()["sac_rate_l_min"], 12)

            # A logged view must use the saved value, not recalculate from pressure.
            with sqlite3.connect(db_path) as conn:
                conn.execute("UPDATE dives SET sac_rate_l_min = 17.5 WHERE id = ?", (dive["id"],))
            self.assertIn(b"18 L/min", client.get(detail_url).data)
            with app.app_context():
                database.init_db()
                database.init_db()
                saved = database.get_db().execute("SELECT sac_rate_l_min FROM dives WHERE id = ?", (dive["id"],)).fetchone()[0]
            self.assertEqual(saved, 17.5)

            payload["ending_pressure_bar"] = ""
            client.post(edit_url, data=payload)
            self.assertIsNone(client.get(f'/api/dives/{dive["id"]}').get_json()["sac_rate_l_min"])
            self.assertIn(b"<dt>SAC rate</dt>\n                        <dd>-</dd>", client.get(detail_url).data)

    def test_sac_default_validation_and_zero_consumption(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            base = {"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50",
                    "starting_pressure_bar": "200", "ending_pressure_bar": "50"}
            for overrides, expected in (({}, 12), ({"tank_size_l": "999"}, 12),
                                        ({"tank_size_l": "15"}, 15), ({"tank_size_preview": "15"}, 15),
                                        ({"ending_pressure_bar": "200"}, 0), ({"duration_min": "0"}, None)):
                with self.subTest(overrides=overrides):
                    dive_date = (date(2026, 1, 1) + timedelta(days=len(client.get("/api/dives/mine").get_json()))).isoformat()
                    self.assertEqual(client.post("/dive/new", data={**base, **overrides, "date": dive_date}).status_code, 302)
                    dives = client.get("/api/dives/mine").get_json()
                    logged = max(dives, key=lambda dive: dive["id"])
                    self.assertEqual(logged["sac_rate_l_min"], expected)

    def test_existing_metric_dives_migrate_without_inventing_a_sac_value(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            def prepare_db(db_path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                with sqlite3.connect(db_path) as conn:
                    conn.executescript(schema.replace("    sac_rate_l_min REAL,\n", ""))
                    conn.execute("INSERT INTO users (id, username) VALUES (1, 'legacy')")
                    conn.execute("""INSERT INTO dives (user_id, date, site_name, depth_m, duration_min,
                                   starting_pressure_bar, ending_pressure_bar) VALUES (1, '2026-07-22', 'Legacy dive', 20, 50, 200, 50)""")
            app, db_path, _ = self.make_app(Path(tmp_dir), prepare_db=prepare_db)
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT starting_pressure_bar, ending_pressure_bar, sac_rate_l_min FROM dives").fetchone()
                self.assertEqual(row, (200, 50, None))
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            client = app.test_client()
            self.signup(client)
            detail = client.get("/dive/1").data
            self.assertIn(b"<dt>SAC rate</dt>\n                        <dd>-</dd>", detail)
            self.assertNotIn(b"data-tank-size", detail)

    def make_app(self, tmp_path, prepare_db=None):
        sites_csv = tmp_path / "sites.csv"
        species_csv = tmp_path / "species.csv"
        centers_csv = tmp_path / "centers.csv"
        db_path = tmp_path / "pelagia.sqlite3"

        write_csv(
            sites_csv,
            """
master_site_id,dive_site_name,country_or_area,country_code,latitude,longitude,max_depth_m
DS1,Alert Rock,Alaska,US,54.1,-132.9,25
DS2,Kelp Garden,Alaska,US,55.2,-133.1,18
DS3,Blue Wall,Bonaire,BQ,12.1,-68.2,30
""",
        )
        write_csv(
            species_csv,
            """
dive_site_name,species_name
Alert Rock,Coral
Alert Rock,Reef Fish
Kelp Garden,Harbor Seal
Blue Wall,Turtle
""",
        )
        write_csv(
            centers_csv,
            """
name,physical_address,location,website
Shark Bay Dive Center,1 Ocean Road,Galapagos Ecuador,https://example.test
Kelp House,2 Harbor Way,Alaska,https://kelp.example.test
""",
        )

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "secret_key": "test-secret",
                    "data_sources": {
                        "dive_sites_csv": str(sites_csv),
                        "species_csv": str(species_csv),
                        "dive_centers_csv": str(centers_csv),
                    },
                }
            )
        )
        if prepare_db is not None:
            prepare_db(db_path)
        with patch.dict(
            os.environ,
            {
                "PELAGIA_CONFIG": str(config_path),
                "PELAGIA_DATABASE_PATH": str(db_path),
                "PELAGIA_UPLOAD_FOLDER": str(tmp_path / "uploads"),
            },
        ):
            app = create_app({"TESTING": True})
        return app, db_path, config_path

    def signup(self, client, username="tester"):
        with client.application.app_context():
            conn = database.get_db()
            conn.execute("INSERT OR IGNORE INTO users (username, google_subject) VALUES (?, ?)", (username, "test-" + username))
            conn.commit()
            user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()[0]
        with client.session_transaction() as session:
            session["user_id"] = user_id

    def test_reference_autocomplete_endpoints_return_imported_data(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            centers = client.get("/api/dive-centers?q=shark").get_json()
            species = client.get("/api/species?q=reef").get_json()
            site_suggestions = client.get("/api/species-suggestions?site_id=1").get_json()
            country_suggestions = client.get("/api/species-suggestions?country=Alaska").get_json()

            self.assertEqual(centers[0]["name"], "Shark Bay Dive Center")
            self.assertEqual(species[0]["common_name"], "Reef Fish")
            self.assertEqual(site_suggestions[:2], ["Coral", "Reef Fish"])
            self.assertIn("Harbor Seal", country_suggestions)

    def test_dive_site_autocomplete_prioritizes_logged_dive_count(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            with sqlite3.connect(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO dive_sites (id, master_site_id, name, country_or_area, country_code)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        (10, "DS10", "Gordon Rocks", "Galapagos", "EC"),
                        (11, "DS11", "Gordon Rocks Dive Site", "Galapagos", "EC"),
                    ),
                )

            for _index in range(2):
                client.post(
                    "/dive/new",
                    data={
                        "date": "2026-07-22",
                        "site_name": "Gordon Rocks Dive Site",
                        "dive_site_id": "11",
                        "country_or_area": "Galapagos",
                        "depth_m": "12",
                        "duration_min": "45",
                        "dive_type": "reef",
                        "current": "none",
                        "current_strength": "none",
                        "species_json": json.dumps([]),
                    },
                )

            form_results = client.get("/api/sites?q=gordon").get_json()
            self.assertEqual([result["id"] for result in form_results[:2]], [11, 10])
            self.assertEqual([result["logged_dive_count"] for result in form_results[:2]], [2, 0])

            feed_results = client.get("/api/search?q=gordon").get_json()
            site_results = [result for result in feed_results if result["type"] == "site"]
            self.assertEqual([result["label"] for result in site_results[:2]], ["Gordon Rocks Dive Site", "Gordon Rocks"])
            self.assertEqual([result["logged_dive_count"] for result in site_results[:2]], [2, 0])

    def test_user_search_buddy_tags_and_public_profiles(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            client.post("/logout")
            self.signup(client, "buddy")
            client.post("/logout")
            self.signup(client, "tester")

            users = client.get("/api/users?q=bud").get_json()
            self.assertEqual(users[0]["username"], "buddy")
            self.assertEqual(users[0]["url"], "/users/2")
            self.assertEqual(client.get("/api/users?q=test").get_json(), [])

            search_user = client.get("/api/search?q=bud").get_json()
            self.assertEqual(search_user[0]["type"], "user")
            self.assertEqual(search_user[0]["url"], "/users/2")

            center_profile = client.get("/dive-centers/2")
            self.assertEqual(center_profile.status_code, 200)
            self.assertNotIn(b"data-center-map", center_profile.data)
            search_site = client.get("/api/search?q=alert").get_json()
            self.assertEqual(search_site[0]["type"], "site")
            self.assertEqual(search_site[0]["url"], "/dive-sites/1")
            search_center = client.get("/api/search?q=house").get_json()
            self.assertEqual(search_center[0]["type"], "center")
            self.assertEqual(search_center[0]["url"], "/dive-centers/2")

            new_response = client.get("/dive/new")
            self.assertIn(b"Tag a Buddy", new_response.data)
            self.assertIn(b"data-buddy-input", new_response.data)
            self.assertNotIn(b"Buddy username", new_response.data)

            dive_data = {
                "date": "2026-07-22",
                "site_name": "Alert Rock",
                "dive_site_id": "1",
                "dive_center_name": "",
                "dive_center_id": "",
                "country_or_area": "Alaska",
                "latitude": "54.1",
                "longitude": "-132.9",
                "depth_m": "12",
                "duration_min": "70",
                "weight_kg": "",
                "exposure": "",
                "visibility_m": "",
                "air_temp_c": "",
                "water_temp_c": "",
                "dive_type": "shore dive",
                "current": "none",
                "current_strength": "none",
                "species_json": json.dumps([]),
            }

            invalid_response = client.post(
                "/dive/new",
                data={
                    **dive_data,
                    "buddy_username": "missingbuddy",
                    "buddy_user_id": "",
                },
            )
            self.assertEqual(invalid_response.status_code, 302)
            self.assertEqual(client.get("/api/dives/mine").get_json(), [])

            self_response = client.post(
                "/dive/new",
                data={
                    **dive_data,
                    "buddy_username": "tester",
                    "buddy_user_id": "1",
                },
            )
            self.assertEqual(self_response.status_code, 302)
            self.assertEqual(client.get("/api/dives/mine").get_json(), [])

            client.post(
                "/dive/new",
                data={
                    **dive_data,
                    "buddy_username": "buddy",
                    "buddy_user_id": "2",
                },
            )
            logged = client.get("/api/dives/mine").get_json()[0]
            self.assertEqual(logged["buddy_user_id"], 2)
            self.assertEqual(logged["buddy_username"], "buddy")

            home_response = client.get("/home")
            self.assertIn(b'data-global-search', home_response.data)
            self.assertIn(b'href="/users/1"', home_response.data)
            self.assertIn(b'href="/users/2"', home_response.data)
            self.assertIn(b'<span>with</span>', home_response.data)
            author_start = home_response.data.index(b'class="dive-author-line"')
            author_end = home_response.data.index(b"</strong>", author_start)
            author_line = home_response.data[author_start:author_end]
            self.assertLess(author_line.index(b"tester"), author_line.index(b"<span>with</span>"))
            self.assertLess(author_line.index(b"<span>with</span>"), author_line.index(b"buddy"))
            self.assertIn(b'<a class="mini-avatar" href="/users/1"', home_response.data)

            detail_response = client.get(f"/dive/{logged['id']}")
            self.assertIn(b'href="/users/1"', detail_response.data)
            self.assertIn(b'href="/users/2"', detail_response.data)

            public_profile = client.get("/users/2")
            self.assertEqual(public_profile.status_code, 200)
            self.assertIn(b"buddy", public_profile.data)
            self.assertNotIn(b'type="file" name="profile_photo"', public_profile.data)
            self.assertIn(b'class="profile-avatar static-avatar"', public_profile.data)

            owner_profile = client.get("/users/1")
            self.assertEqual(owner_profile.status_code, 200)
            self.assertIn(b'type="file" name="profile_photo"', owner_profile.data)

            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT buddy_user_id FROM dives").fetchone()
            self.assertEqual(row[0], 2)

    def test_reference_import_repairs_stale_partial_database(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, config_path = self.make_app(Path(tmp_dir))

            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE _import_dive_centers (id INTEGER)")
                conn.execute("DELETE FROM dive_centers")
                conn.execute("DELETE FROM site_species")
                conn.commit()

            with patch.dict(
                os.environ,
                {
                    "PELAGIA_CONFIG": str(config_path),
                    "PELAGIA_DATABASE_PATH": str(db_path),
                    "PELAGIA_UPLOAD_FOLDER": str(Path(tmp_dir) / "uploads"),
                },
            ):
                app = create_app({"TESTING": True})
            client = app.test_client()
            self.signup(client)

            centers = client.get("/api/dive-centers?q=shark").get_json()
            suggestions = client.get("/api/species-suggestions?site_id=1").get_json()
            self.assertEqual(centers[0]["name"], "Shark Bay Dive Center")
            self.assertEqual(suggestions[:2], ["Coral", "Reef Fish"])
            with sqlite3.connect(db_path) as conn:
                staging_tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '_import_%'"
                ).fetchall()
            self.assertEqual(staging_tables, [])

    def test_existing_imperial_database_migrates_values_and_schema(self):
        def prepare_legacy_db(db_path):
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        profile_photo TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute("INSERT INTO users (id, username) VALUES (1, 'legacy')")
                conn.execute(
                    """
                    CREATE TABLE dives (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        dive_site_id INTEGER,
                        dive_center_id INTEGER,
                        dive_center_name TEXT,
                        date TEXT NOT NULL,
                        site_name TEXT NOT NULL,
                        country_or_area TEXT,
                        latitude REAL,
                        longitude REAL,
                        depth_ft INTEGER NOT NULL DEFAULT 0,
                        duration_min INTEGER NOT NULL DEFAULT 0,
                        sac_rate_l_min REAL,
                        weight_lbs INTEGER,
                        exposure TEXT,
                        visibility_ft INTEGER,
                        air_temp_degrees INTEGER,
                        water_temp_degrees INTEGER,
                        gas_mix TEXT NOT NULL DEFAULT 'Air',
                        dive_type TEXT NOT NULL DEFAULT 'open water',
                        current TEXT NOT NULL DEFAULT 'none',
                        current_strength TEXT NOT NULL DEFAULT 'none',
                        notes TEXT,
                        is_deleted INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO dives (
                        user_id, date, site_name, depth_ft, duration_min, weight_lbs,
                        visibility_ft, air_temp_degrees, water_temp_degrees, sac_rate_l_min
                    )
                    VALUES (1, '2026-07-01', 'Legacy Reef', 62, 45, 10, 66, 86, 77, 17.5)
                    """
                )
                conn.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            _app, db_path, _config_path = self.make_app(Path(tmp_dir), prepare_db=prepare_legacy_db)
            with sqlite3.connect(db_path) as conn:
                column_rows = conn.execute("PRAGMA table_info(dives)").fetchall()
                columns = {row[1] for row in column_rows}
                column_types = {row[1]: row[2] for row in column_rows}
                indexes = {row[1] for row in conn.execute("PRAGMA index_list(dives)").fetchall()}
                migrated = conn.execute(
                    "SELECT depth_m, weight_kg, visibility_m, air_temp_c, water_temp_c, sac_rate_l_min FROM dives"
                ).fetchone()
                foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertIn("buddy_user_id", columns)
            self.assertIn("idx_dives_buddy_user", indexes)
            self.assertNotIn("depth_ft", columns)
            self.assertEqual(column_types["weight_kg"], "REAL")
            self.assertEqual(migrated, (19, 5, 20, 30, 25, 17.5))
            self.assertEqual(foreign_key_errors, [])

    def test_gas_compositions_save_edit_and_survive_initialization(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _ = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            base = {"site_name": "Alert Rock", "depth_m": "20", "duration_min": "50"}
            for oxygen, helium, label in ((21, 0, "Air"), (32, 0, "EANx 32%"), (21, 35, "Trimix 21/35"), (0, 100, "Trimix 0/100"), (100, 0, "EANx 100%")):
                with self.subTest(label=label):
                    self.assertEqual(client.post("/dive/new", data={**base, "oxygen_pct": str(oxygen), "helium_pct": str(helium), "nitrogen_pct": "999"}).status_code, 302)
                    dive = max(client.get("/api/dives/mine").get_json(), key=lambda item: item["id"])
                    self.assertEqual((dive["oxygen_pct"], dive["helium_pct"], dive["nitrogen_pct"]), (oxygen, helium, 100 - oxygen - helium))
                    self.assertEqual(dive["gas_mix_label"], label)
                    self.assertIn(f"<dd>{label}</dd>".encode(), client.get(f"/dive/{dive['id']}").data)
                    edit = client.get(f"/dive/{dive['id']}/edit").data
                    self.assertIn(f'value="{oxygen}" data-gas-number="oxygen"'.encode(), edit)
                    with app.app_context():
                        database.init_db()
                    self.assertEqual(client.get(f"/api/dives/{dive['id']}").get_json()["gas_mix_label"], label)
            self.assertEqual(client.post(f"/dive/{dive['id']}/edit", data={**base, "oxygen_pct": "18", "helium_pct": "45"}).status_code, 302)
            self.assertEqual(client.get(f"/api/dives/{dive['id']}").get_json()["gas_mix_label"], "Trimix 18/45")
            client.post(f"/dive/{dive['id']}/edit", data={**base, "oxygen_pct": "90", "helium_pct": "50"})
            saved = client.get(f"/api/dives/{dive['id']}").get_json()
            self.assertEqual((saved["oxygen_pct"], saved["helium_pct"], saved["nitrogen_pct"]), (90, 10, 0))
            client.post(f"/dive/{dive['id']}/edit", data={**base, "oxygen_pct": "18", "helium_pct": "0"})
            saved = client.get(f"/api/dives/{dive['id']}").get_json()
            self.assertEqual((saved["oxygen_pct"], saved["helium_pct"], saved["nitrogen_pct"]), (18, 3, 79))
            self.assertEqual(saved["gas_mix_label"], "Trimix 18/3")
            # Existing dropdown values migrate once without changing later compositions.
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE dives SET gas_mix = '32%', oxygen_pct = NULL, helium_pct = NULL WHERE id = ?", (dive["id"],))
            with app.app_context():
                database.init_db()
            self.assertEqual(client.get(f"/api/dives/{dive['id']}").get_json()["gas_mix_label"], "EANx 32%")

    def test_optional_dive_metadata_defaults_to_unset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            new_response = client.get("/dive/new")
            self.assertIn(b'<output id="weightOutput">-</output>', new_response.data)
            self.assertIn(b'<output id="startingPressureOutput" hidden>-</output>', new_response.data)
            self.assertIn(b'<output id="endingPressureOutput" hidden>-</output>', new_response.data)
            self.assertIn(b'<output id="sacRateOutput" aria-live="polite" data-sac-output>-</output>', new_response.data)
            self.assertIn(b'<output id="visibilityOutput">-</output>', new_response.data)
            self.assertIn(b'<output id="airTempOutput">-</output>', new_response.data)
            self.assertIn(b'<output id="waterTempOutput">-</output>', new_response.data)
            self.assertIn(b'value="0" data-range="visibility"', new_response.data)
            self.assertIn(b'value="20" data-range="airTemp"', new_response.data)
            self.assertIn(b'value="20" data-range="waterTemp"', new_response.data)
            self.assertIn(b'min="0" max="200" step="10" value="200" data-range="startingPressure"', new_response.data)
            self.assertIn(b'min="0" max="200" step="10" value="0" data-range="endingPressure"', new_response.data)
            self.assertIn("Max depth (m)".encode(), new_response.data)
            self.assertIn("Weight (kg)".encode(), new_response.data)
            self.assertIn("Air temperature (°C)".encode(), new_response.data)
            self.assertIn(b'name="depth_m" type="number" min="0" step="any"', new_response.data)
            self.assertIn(b'name="visibility_m" type="number" min="0" step="any"', new_response.data)
            self.assertIn(b'name="air_temp_c" type="number" min="-20" max="40"', new_response.data)
            self.assertIn(b'data-exposure-label aria-live="polite">-</output>', new_response.data)
            self.assertNotRegex(new_response.get_data(as_text=True), r'name="exposure"[^>]*\bchecked\b')
            self.assertIn(b'value="21" data-gas-number="oxygen"', new_response.data)
            self.assertIn(b'value="0" data-gas-number="helium"', new_response.data)
            self.assertIn(b'value="79" data-gas-number="nitrogen" readonly', new_response.data)

            client.post(
                "/dive/new",
                data={
                    "date": "2026-07-22",
                    "site_name": "Alert Rock",
                    "dive_site_id": "1",
                    "country_or_area": "Alaska",
                    "latitude": "54.1",
                    "longitude": "-132.9",
                    "depth_m": "12",
                    "duration_min": "70",
                    "weight_kg": "",
                    "starting_pressure_bar": "",
                    "ending_pressure_bar": "",
                    "exposure": "",
                    "visibility_m": "",
                    "air_temp_c": "",
                    "water_temp_c": "",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "species_json": json.dumps([]),
                },
            )
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]
            logged = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertIsNone(logged["weight_kg"])
            self.assertIsNone(logged["starting_pressure_bar"])
            self.assertIsNone(logged["ending_pressure_bar"])
            self.assertIsNone(logged["exposure"])
            self.assertEqual(logged["gas_mix"], "Air")
            self.assertIsNone(logged["visibility_m"])
            self.assertIsNone(logged["air_temp_c"])
            self.assertIsNone(logged["water_temp_c"])

            detail_response = client.get(f"/dive/{dive_id}")
            self.assertGreaterEqual(detail_response.data.count(b"<dd>-</dd>"), 5)

            with sqlite3.connect(db_path) as conn:
                columns = {
                    row[1]: row
                    for row in conn.execute("PRAGMA table_info(dives)").fetchall()
                }
            for column in (
                "weight_kg",
                "starting_pressure_bar",
                "ending_pressure_bar",
                "exposure",
                "visibility_m",
                "air_temp_c",
                "water_temp_c",
            ):
                self.assertEqual(columns[column][3], 0)

    def test_metric_dive_values_use_metric_ranges(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            client.post(
                "/dive/new",
                data={
                    "date": "2026-07-22",
                    "site_name": "Alert Rock",
                    "dive_site_id": "1",
                    "depth_m": "100",
                    "duration_min": "70",
                    "weight_kg": "20",
                    "starting_pressure_bar": "250",
                    "ending_pressure_bar": "60",
                    "visibility_m": "100",
                    "air_temp_c": "-5",
                    "water_temp_c": "45",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "species_json": json.dumps([]),
                },
            )

            logged = client.get("/api/dives/mine").get_json()[0]
            self.assertEqual(logged["depth_m"], 100)
            self.assertEqual(logged["weight_kg"], 10)
            self.assertEqual(logged["starting_pressure_bar"], 250)
            self.assertEqual(logged["ending_pressure_bar"], 60)
            self.assertEqual(logged["visibility_m"], 100)
            self.assertEqual(logged["air_temp_c"], -5)
            self.assertEqual(logged["water_temp_c"], 40)

            detail_response = client.get(f"/dive/{logged['id']}")
            self.assertIn(b"100<em>m</em>", detail_response.data)
            self.assertIn(b"100 m", detail_response.data)
            self.assertIn(b"10 kg", detail_response.data)
            self.assertIn(b"250 bar", detail_response.data)
            self.assertIn(b"60 bar", detail_response.data)
            self.assertIn("-5°C".encode(), detail_response.data)
            self.assertIn("40°C".encode(), detail_response.data)

    def test_weight_accepts_half_kilos_and_hides_zero_decimal(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            new_response = client.get("/dive/new")
            self.assertIn(b'min="0" max="10" step="0.5" value="0" data-range="weight"', new_response.data)
            self.assertIn(b'name="weight_kg" type="number" min="0" max="10" step="any"', new_response.data)

            base_data = {
                "date": "2026-07-22",
                "site_name": "Alert Rock",
                "dive_site_id": "1",
                "depth_m": "12",
                "duration_min": "70",
                "dive_type": "shore dive",
                "current": "none",
                "current_strength": "none",
                "species_json": json.dumps([]),
            }
            client.post("/dive/new", data={**base_data, "weight_kg": "8.5"})
            client.post("/dive/new", data={**base_data, "weight_kg": "8.0"})

            dives = client.get("/api/dives/mine").get_json()
            weights = {dive["weight_kg"] for dive in dives}
            self.assertEqual(weights, {8.0, 8.5})

            half_dive = next(dive for dive in dives if dive["weight_kg"] == 8.5)
            whole_dive = next(dive for dive in dives if dive["weight_kg"] == 8.0)
            self.assertIn(b"8.5 kg", client.get(f"/dive/{half_dive['id']}").data)
            whole_detail = client.get(f"/dive/{whole_dive['id']}").data
            self.assertIn(b"8 kg", whole_detail)
            self.assertNotIn(b"8.0 kg", whole_detail)

            with sqlite3.connect(db_path) as conn:
                weight_type = next(
                    row[2] for row in conn.execute("PRAGMA table_info(dives)") if row[1] == "weight_kg"
                )
            self.assertEqual(weight_type, "REAL")

    def test_typed_reference_names_resolve_to_linked_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            client.post(
                "/dive/new",
                data={
                    "date": "2026-07-22",
                    "site_name": "alert rock",
                    "dive_site_id": "",
                    "dive_center_name": "shark bay dive center",
                    "dive_center_id": "",
                    "country_or_area": "",
                    "latitude": "",
                    "longitude": "",
                    "depth_m": "12",
                    "duration_min": "70",
                    "weight_kg": "",
                    "exposure": "",
                    "visibility_m": "",
                    "air_temp_c": "",
                    "water_temp_c": "",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "species_json": json.dumps([]),
                },
            )

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT dive_site_id, dive_center_id, site_name, dive_center_name,
                        country_or_area, latitude, longitude
                    FROM dives
                    """
                ).fetchone()
            self.assertEqual(row[0], 1)
            self.assertEqual(row[1], 1)
            self.assertEqual(row[2], "Alert Rock")
            self.assertEqual(row[3], "Shark Bay Dive Center")
            self.assertEqual(row[4], "Alaska")
            self.assertEqual(row[5], 54.1)
            self.assertEqual(row[6], -132.9)

    def test_dive_site_profile_uses_median_daily_conditions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            today = date.today().isoformat()

            for visibility, strength, water, air, species in (
                ("10", "light", "22", "25", ["Coral", "Reef Fish"]),
                ("20", "very strong", "26", "29", ["Coral"]),
            ):
                client.post(
                    "/dive/new",
                    data={
                        "date": today,
                        "site_name": "Alert Rock",
                        "dive_site_id": "1",
                        "country_or_area": "Alaska",
                        "latitude": "54.1",
                        "longitude": "-132.9",
                        "depth_m": "12",
                        "duration_min": "70",
                        "weight_kg": "",
                        "exposure": "",
                        "visibility_m": visibility,
                        "air_temp_c": air,
                        "water_temp_c": water,
                        "dive_type": "shore dive",
                        "current": "tidal",
                        "current_strength": strength,
                        "species_json": json.dumps(species),
                    },
                )

            home_response = client.get("/home")
            self.assertIn(b'href="/dive-sites/1"', home_response.data)

            profile_response = client.get("/dive-sites/1")
            self.assertEqual(profile_response.status_code, 200)
            self.assertIn(b"Alert Rock", profile_response.data)
            self.assertIn(b"54.10000", profile_response.data)
            self.assertIn(b"-132.90000", profile_response.data)
            self.assertNotIn(b"RECENT CONDITIONS", profile_response.data)
            self.assertIn(b"VISIBILITY", profile_response.data)
            self.assertIn(b"CURRENT", profile_response.data)
            self.assertIn(b"Water temperature", profile_response.data)
            self.assertIn(b"Tide level", profile_response.data)
            self.assertIn(b"<h2>Current velocity</h2>", profile_response.data)
            self.assertNotIn(b"<h2>Current Strength</h2>", profile_response.data)
            self.assertNotIn(b"<small>Latitude</small>", profile_response.data)
            self.assertNotIn(b"<small>Longitude</small>", profile_response.data)
            self.assertIn(b"15 m", profile_response.data)
            self.assertIn(b'data-marine-value="strength"', profile_response.data)
            self.assertNotIn("24°C".encode(), profile_response.data)
            self.assertNotIn("27°C".encode(), profile_response.data)
            self.assertNotIn(b"Trailing 2 weeks, feet by day", profile_response.data)
            self.assertNotIn(b"Trailing 2 weeks by day", profile_response.data)
            self.assertIn(b"SIGHTINGS", profile_response.data)
            self.assertIn(b"Coral", profile_response.data)
            self.assertIn(b"<strong>2</strong>", profile_response.data)
            self.assertIn(b"Reef Fish", profile_response.data)
            self.assertNotIn(b"<strong>1</strong>", profile_response.data)

    def test_dive_site_forecasts_replace_historical_charts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, _db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            observation_day = date.today() - timedelta(days=20)
            empty_day = date.today()

            for day, visibility, current, strength in (
                (observation_day, "12", "tidal", "moderate"),
                (empty_day, "", "none", "none"),
            ):
                client.post(
                    "/dive/new",
                    data={
                        "date": day.isoformat(),
                        "site_name": "Alert Rock",
                        "dive_site_id": "1",
                        "country_or_area": "Alaska",
                        "latitude": "54.1",
                        "longitude": "-132.9",
                        "depth_m": "12",
                        "duration_min": "70",
                        "visibility_m": visibility,
                        "dive_type": "shore dive",
                        "current": current,
                        "current_strength": strength,
                        "species_json": json.dumps([]),
                    },
                )

            profile_response = client.get("/dive-sites/1")
            self.assertEqual(profile_response.status_code, 200)
            self.assertNotIn(f"{observation_day.strftime('%b')} {observation_day.day}: 12 m".encode(), profile_response.data)
            self.assertIn(b'data-marine-chart="current"', profile_response.data)
            self.assertNotIn(empty_day.strftime("%b %-d").encode(), profile_response.data)

            like_response = client.post("/api/dive-sites/1/like").get_json()
            self.assertEqual(like_response, {"liked": True, "count": 1})
            comment_response = client.post("/api/dive-sites/1/comments", data={"body": "Great site"}).get_json()
            self.assertEqual(comment_response["comments"][0]["body"], "Great site")

    def test_owned_dive_can_be_edited_and_soft_deleted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            new_response = client.get("/dive/new")
            self.assertIn(b'name="dive_type" value="open water" data-option-label="Open Water" checked', new_response.data)
            self.assertIn(b'name="dive_type" value="shore dive" data-option-label="Shore Dive" ', new_response.data)
            self.assertIn(b'name="dive_type" value="drift" data-option-label="Drift" ', new_response.data)
            self.assertLess(new_response.data.index(b'name="dive_type" value="deep"'), new_response.data.index(b'name="dive_type" value="drift"'))
            self.assertLess(new_response.data.index(b'name="dive_type" value="drift"'), new_response.data.index(b'name="dive_type" value="night"'))
            self.assertIn(b'name="current" value="none" data-option-label="-" checked', new_response.data)
            self.assertIn(b"Current type", new_response.data)
            for current in ("slack", "tidal", "rip", "upwelling", "downdraft"):
                self.assertIn(f'name="current" value="{current}" data-option-label="{current.title()}" '.encode(), new_response.data)
            self.assertNotIn(b'name="current" value="vertical"', new_response.data)
            self.assertIn(b"Current strength", new_response.data)
            self.assertIn(b"current-strength-control is-disabled", new_response.data)
            self.assertIn(b"data-current-type-select", new_response.data)
            self.assertIn(b"data-current-strength-range disabled", new_response.data)
            self.assertIn(b'<input name="current_strength" type="hidden" value="none"', new_response.data)
            self.assertIn(b"Very Strong", new_response.data)

            create_response = client.post(
                "/dive/new",
                data={
                    "date": "2026-07-22",
                    "site_name": "Alert Rock",
                    "dive_site_id": "1",
                    "dive_center_name": "Kelp House",
                    "dive_center_id": "2",
                    "country_or_area": "Alaska",
                    "latitude": "54.1",
                    "longitude": "-132.9",
                    "depth_m": "12",
                    "duration_min": "70",
                    "weight_kg": "4",
                    "exposure": "5mm",
                    "gas_mix": "32%",
                    "visibility_m": "17",
                    "air_temp_c": "28",
                    "water_temp_c": "23",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "moderate",
                    "notes": "Clear water.",
                    "species_json": json.dumps(["Coral", "Reef Fish"]),
                },
            )
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]
            self.assertEqual(create_response.status_code, 302)
            self.assertEqual(create_response.location, f"/dive/{dive_id}")
            logged = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertEqual(logged["visibility_m"], 17)
            self.assertEqual(logged["air_temp_c"], 28)
            self.assertEqual(logged["water_temp_c"], 23)
            self.assertEqual(logged["gas_mix"], "32%")
            self.assertEqual(logged["dive_type"], "shore dive")
            self.assertEqual(logged["current"], "none")
            self.assertEqual(logged["current_strength"], "none")

            detail_response = client.get(f"/dive/{dive_id}")
            self.assertEqual(detail_response.status_code, 200)
            self.assertIn(b"Alert Rock", detail_response.data)
            self.assertIn(b"tester", detail_response.data)
            self.assertIn(b"Shore Dive", detail_response.data)
            self.assertIn(b"detail-headline-stats", detail_response.data)
            self.assertIn(b"detail-lower-grid", detail_response.data)
            self.assertLess(detail_response.data.index(b"<dt>Exposure</dt>"), detail_response.data.index(b"<dt>Gas mix</dt>"))
            self.assertIn(b"<dd>EANx 32%</dd>", detail_response.data)
            self.assertIn(b"Alaska", detail_response.data)
            self.assertIn(b'<p class="dive-center-line">', detail_response.data)
            self.assertIn(b"<span>with</span>", detail_response.data)
            self.assertIn(b'<a href="/dive-centers/2">Kelp House</a>', detail_response.data)
            self.assertIn(b"Kelp House", detail_response.data)
            self.assertNotIn(b"metadata-divider", detail_response.data)
            self.assertNotIn(b"dive-center-chip", detail_response.data)
            self.assertNotIn(b"- with", detail_response.data)
            self.assertIn(b"<h2>Conditions</h2>", detail_response.data)

            home_response = client.get("/home")
            self.assertIn(b"Shore Dive", home_response.data)
            self.assertIn(b"Nitrox", home_response.data)

            edit_response = client.get(f"/dive/{dive_id}/edit")
            self.assertEqual(edit_response.status_code, 200)
            self.assertIn(b"Edit dive", edit_response.data)
            self.assertIn(b"Save changes", edit_response.data)
            self.assertIn(b"Delete dive", edit_response.data)
            self.assertIn(b"Alert Rock", edit_response.data)

            client.post("/logout")
            self.signup(client, "viewer")
            foreign_dive = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertFalse(foreign_dive["is_owner"])
            self.assertEqual(client.get(f"/dive/{dive_id}/edit").status_code, 404)
            client.post("/logout")
            self.signup(client, "tester")

            update_response = client.post(
                f"/dive/{dive_id}/edit",
                data={
                    "next": "/you",
                    "date": "2026-07-23",
                    "site_name": "Blue Wall",
                    "dive_site_id": "3",
                    "dive_center_name": "",
                    "dive_center_id": "",
                    "country_or_area": "Bonaire",
                    "latitude": "12.1",
                    "longitude": "-68.2",
                    "depth_m": "19",
                    "duration_min": "55",
                    "weight_kg": "6",
                    "exposure": "3mm",
                    "gas_mix": "Other",
                    "visibility_m": "26",
                    "air_temp_c": "31",
                    "water_temp_c": "27",
                    "dive_type": "wreck",
                    "current": "rip",
                    "current_strength": "very strong",
                    "notes": "Updated notes.",
                    "species_json": json.dumps(["Turtle"]),
                },
            )
            self.assertEqual(update_response.status_code, 302)
            self.assertTrue(update_response.headers["Location"].endswith("/dive/%s" % dive_id))
            updated = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertTrue(updated["is_owner"])
            self.assertEqual(updated["site_name"], "Blue Wall")
            self.assertEqual(updated["depth_m"], 19)
            self.assertEqual(updated["visibility_m"], 26)
            self.assertEqual(updated["air_temp_c"], 31)
            self.assertEqual(updated["water_temp_c"], 27)
            self.assertEqual(updated["gas_mix"], "Other")
            self.assertEqual(updated["dive_type"], "wreck")
            self.assertEqual(updated["current"], "rip")
            self.assertEqual(updated["current_strength"], "very strong")
            self.assertEqual(updated["species"], ["Turtle"])
            updated_detail = client.get(f"/dive/{dive_id}")
            self.assertIn(b"Blue Wall", updated_detail.data)
            self.assertIn(b"Wreck", updated_detail.data)
            self.assertIn(b"19<em>m</em>", updated_detail.data)
            self.assertIn(b"55<em>min</em>", updated_detail.data)
            self.assertIn(b"Very Strong", updated_detail.data)
            updated_home = client.get("/home")
            self.assertIn(b"Wreck", updated_home.data)
            self.assertNotIn(b"Nitrox", updated_home.data)

            delete_response = client.post(f"/dive/{dive_id}/delete", data={"next": "/home?open=%s" % dive_id})
            self.assertEqual(delete_response.status_code, 302)
            self.assertTrue(delete_response.headers["Location"].endswith("/home"))
            self.assertEqual(client.get(f"/api/dives/{dive_id}").status_code, 404)
            self.assertEqual(client.get("/api/dives/mine").get_json(), [])
            self.assertNotIn(b"Blue Wall", client.get("/home").data)

            with sqlite3.connect(db_path) as conn:
                is_deleted = conn.execute("SELECT is_deleted FROM dives WHERE id = ?", (dive_id,)).fetchone()[0]
            self.assertEqual(is_deleted, 1)

    def test_multiple_dive_photos_render_and_individual_photos_can_be_removed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            client.post(
                "/dive/new",
                data={
                    "date": "2026-07-22",
                    "site_name": "Alert Rock",
                    "dive_site_id": "1",
                    "dive_center_name": "",
                    "dive_center_id": "",
                    "country_or_area": "Alaska",
                    "latitude": "54.1",
                    "longitude": "-132.9",
                    "depth_m": "12",
                    "duration_min": "70",
                    "weight_kg": "",
                    "exposure": "",
                    "visibility_m": "",
                    "air_temp_c": "",
                    "water_temp_c": "",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "notes": "Photos from the dive.",
                    "species_json": json.dumps([]),
                    "photos": [
                        image_upload("reef-one.jpg", "navy"),
                        image_upload("reef-two.jpg", "teal"),
                        image_upload("reef-three.jpg", "orange"),
                    ],
                },
                content_type="multipart/form-data",
            )
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]

            detail_response = client.get(f"/dive/{dive_id}")
            self.assertEqual(detail_response.status_code, 200)
            self.assertIn(b"detail-photo-carousel", detail_response.data)
            self.assertEqual(detail_response.data.count(b"class=\"detail-photo-slide\""), 3)
            self.assertNotIn(b"detail-photo-grid", detail_response.data)

            home_response = client.get("/home")
            self.assertEqual(home_response.status_code, 200)
            self.assertIn(b'data-dive-slides', home_response.data)
            self.assertEqual(home_response.data.count(b'data-gallery-dot'), 3)
            self.assertEqual(home_response.data.count(b"uploads/dives/"), 3)

            profile_response = client.get("/you")
            self.assertEqual(profile_response.status_code, 200)
            profile_html = profile_response.data
            self.assertLess(profile_html.index(b"<small>Dives</small>"), profile_html.index(b"<small>Max depth</small>"))
            self.assertNotIn(b"<small>SAC rate</small>", profile_html)
            self.assertIn(b"<small>Max depth</small><span>12 <em>m</em></span>", profile_html)
            self.assertIn(b'History</h2>', profile_html)
            self.assertIn(b'data-history-view="sac_rate_l_min"', profile_html)
            self.assertNotIn(b"View map", profile_html)
            self.assertNotIn(b"profile-map", profile_html)
            self.assertNotIn(b"<small>countries</small>", profile_html)
            self.assertNotIn(b"<small>locations</small>", profile_html)
            self.assertEqual(client.get("/map").status_code, 404)
            self.assertIn(b'data-dive-slides', profile_response.data)
            self.assertEqual(profile_response.data.count(b"uploads/dives/"), 3)

            edit_response = client.get(f"/dive/{dive_id}/edit")
            self.assertEqual(edit_response.status_code, 200)
            self.assertEqual(edit_response.data.count(b"data-remove-photo-id="), 3)
            self.assertIn(b"photo-remove-button", edit_response.data)

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute("SELECT id, filename FROM photos WHERE dive_id = ? ORDER BY id", (dive_id,)).fetchall()
            self.assertEqual(len(rows), 3)
            removed_id, removed_filename = rows[1]
            removed_file = Path(app.config["UPLOAD_FOLDER"], removed_filename.removeprefix("uploads/"))
            self.assertTrue(removed_file.exists())

            update_response = client.post(
                f"/dive/{dive_id}/edit",
                data={
                    "date": "2026-07-23",
                    "site_name": "Alert Rock",
                    "dive_site_id": "1",
                    "dive_center_name": "",
                    "dive_center_id": "",
                    "country_or_area": "Alaska",
                    "latitude": "54.1",
                    "longitude": "-132.9",
                    "depth_m": "13",
                    "duration_min": "68",
                    "weight_kg": "",
                    "exposure": "",
                    "visibility_m": "",
                    "air_temp_c": "",
                    "water_temp_c": "",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "notes": "Kept the best photos.",
                    "species_json": json.dumps([]),
                    "remove_photo_ids": str(removed_id),
                },
            )
            self.assertEqual(update_response.status_code, 302)

            with sqlite3.connect(db_path) as conn:
                remaining = conn.execute("SELECT id FROM photos WHERE dive_id = ? ORDER BY id", (dive_id,)).fetchall()
            self.assertEqual([row[0] for row in remaining], [rows[0][0], rows[2][0]])
            self.assertFalse(removed_file.exists())
            self.assertEqual(len(client.get(f"/api/dives/{dive_id}").get_json()["photos"]), 2)


if __name__ == "__main__":
    unittest.main()
