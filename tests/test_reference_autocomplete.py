import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pelagia import create_app


def write_csv(path, content):
    path.write_text(content.strip() + "\n")


def image_upload(name, color):
    stream = io.BytesIO()
    Image.new("RGB", (160, 110), color).save(stream, "JPEG")
    stream.seek(0)
    return stream, name


class ReferenceAutocompleteTest(unittest.TestCase):
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
                    "database_path": str(db_path),
                    "upload_folder": str(tmp_path / "uploads"),
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
        with patch.dict(os.environ, {"PELAGIA_CONFIG": str(config_path)}):
            app = create_app({"TESTING": True})
        return app, db_path, config_path

    def signup(self, client, username="tester"):
        client.post("/signup", data={"username": username, "password": "password"})

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

    def test_user_search_buddy_tags_and_public_profiles(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)
            client.post("/logout")
            self.signup(client, "buddy")
            client.post(
                "/cert/new",
                data={
                    "agency": "PADI",
                    "level": "Rescue Diver",
                    "cert_no": "BUD123",
                    "cert_date": "2026-07-20",
                },
            )
            client.post("/logout")
            client.post("/login", data={"username": "tester", "password": "password"})

            users = client.get("/api/users?q=bud").get_json()
            self.assertEqual(users[0]["username"], "buddy")
            self.assertEqual(users[0]["url"], "/users/2")

            search_user = client.get("/api/search?q=bud").get_json()
            self.assertEqual(search_user[0]["type"], "user")
            self.assertEqual(search_user[0]["url"], "/users/2")
            search_site = client.get("/api/search?q=alert").get_json()
            self.assertEqual(search_site[0]["type"], "site")
            self.assertEqual(search_site[0]["url"], "/dive-sites/1")
            search_center = client.get("/api/search?q=house").get_json()
            self.assertEqual(search_center[0]["type"], "center")
            self.assertEqual(search_center[0]["url"], "/dive-centers/2")

            new_response = client.get("/dive/new")
            self.assertIn(b"Tag a Buddy", new_response.data)
            self.assertIn(b"data-buddy-input", new_response.data)

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
                    "depth_ft": "40",
                    "duration_min": "70",
                    "weight_lbs": "",
                    "exposure": "",
                    "visibility_ft": "",
                    "air_temp_degrees": "",
                    "water_temp_degrees": "",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "buddy_username": "buddy",
                    "buddy_user_id": "2",
                    "species_json": json.dumps([]),
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
            self.assertLess(home_response.data.index(b"tester"), home_response.data.index(b"<span>with</span>"))
            self.assertLess(home_response.data.index(b"<span>with</span>"), home_response.data.index(b"buddy"))
            self.assertIn(b'<a class="mini-avatar" href="/users/1"', home_response.data)

            detail_response = client.get(f"/dive/{logged['id']}")
            self.assertIn(b'href="/users/1"', detail_response.data)
            self.assertIn(b'href="/users/2"', detail_response.data)

            public_profile = client.get("/users/2")
            self.assertEqual(public_profile.status_code, 200)
            self.assertIn(b"buddy", public_profile.data)
            self.assertIn(b"Rescue Diver", public_profile.data)
            self.assertNotIn(b"profile-cert-button", public_profile.data)
            self.assertNotIn(b'href="/cert"', public_profile.data)
            self.assertNotIn(b'type="file" name="profile_photo"', public_profile.data)
            self.assertIn(b'class="profile-avatar static-avatar"', public_profile.data)

            owner_profile = client.get("/users/1")
            self.assertEqual(owner_profile.status_code, 200)
            self.assertIn(b"profile-cert-button", owner_profile.data)
            self.assertIn(b'href="/cert/new"', owner_profile.data)

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

            with patch.dict(os.environ, {"PELAGIA_CONFIG": str(config_path)}):
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

    def test_existing_database_without_buddy_column_migrates(self):
        def prepare_legacy_db(db_path):
            with sqlite3.connect(db_path) as conn:
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
                conn.commit()

        with tempfile.TemporaryDirectory() as tmp_dir:
            _app, db_path, _config_path = self.make_app(Path(tmp_dir), prepare_db=prepare_legacy_db)
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(dives)").fetchall()}
                indexes = {row[1] for row in conn.execute("PRAGMA index_list(dives)").fetchall()}
            self.assertIn("buddy_user_id", columns)
            self.assertIn("idx_dives_buddy_user", indexes)

    def test_optional_dive_metadata_defaults_to_unset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            new_response = client.get("/dive/new")
            self.assertIn(b'<output id="weightOutput">-</output>', new_response.data)
            self.assertIn(b'<output id="visibilityOutput">-</output>', new_response.data)
            self.assertIn(b'<output id="airTempOutput">-</output>', new_response.data)
            self.assertIn(b'<output id="waterTempOutput">-</output>', new_response.data)
            self.assertIn(b'value="0" data-range="visibility"', new_response.data)
            self.assertIn(b'value="0" data-range="airTemp"', new_response.data)
            self.assertIn(b'value="0" data-range="waterTemp"', new_response.data)
            self.assertIn(b'value="" disabled selected', new_response.data)
            self.assertIn(b'<option value="Air" selected>Air</option>', new_response.data)

            client.post(
                "/dive/new",
                data={
                    "date": "2026-07-22",
                    "site_name": "Alert Rock",
                    "dive_site_id": "1",
                    "country_or_area": "Alaska",
                    "latitude": "54.1",
                    "longitude": "-132.9",
                    "depth_ft": "40",
                    "duration_min": "70",
                    "weight_lbs": "",
                    "exposure": "",
                    "visibility_ft": "",
                    "air_temp_degrees": "",
                    "water_temp_degrees": "",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "none",
                    "species_json": json.dumps([]),
                },
            )
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]
            logged = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertIsNone(logged["weight_lbs"])
            self.assertIsNone(logged["exposure"])
            self.assertEqual(logged["gas_mix"], "Air")
            self.assertIsNone(logged["visibility_ft"])
            self.assertIsNone(logged["air_temp_degrees"])
            self.assertIsNone(logged["water_temp_degrees"])

            detail_response = client.get(f"/dive/{dive_id}")
            self.assertGreaterEqual(detail_response.data.count(b"<dd>-</dd>"), 5)

            with sqlite3.connect(db_path) as conn:
                columns = {
                    row[1]: row
                    for row in conn.execute("PRAGMA table_info(dives)").fetchall()
                }
            for column in ("weight_lbs", "exposure", "visibility_ft", "air_temp_degrees", "water_temp_degrees"):
                self.assertEqual(columns[column][3], 0)

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
                    "depth_ft": "40",
                    "duration_min": "70",
                    "weight_lbs": "",
                    "exposure": "",
                    "visibility_ft": "",
                    "air_temp_degrees": "",
                    "water_temp_degrees": "",
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
                ("20", "light", "74", "80", ["Coral", "Reef Fish"]),
                ("80", "very strong", "78", "84", ["Coral"]),
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
                        "depth_ft": "40",
                        "duration_min": "70",
                        "weight_lbs": "",
                        "exposure": "",
                        "visibility_ft": visibility,
                        "air_temp_degrees": air,
                        "water_temp_degrees": water,
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
            self.assertIn(b"RECENT CONDITIONS", profile_response.data)
            self.assertIn(b"VISIBILITY", profile_response.data)
            self.assertIn(b"CURRENT", profile_response.data)
            self.assertIn(b"WATER TEMP", profile_response.data)
            self.assertIn(b"AIR TEMP", profile_response.data)
            self.assertNotIn(b"<small>Latitude</small>", profile_response.data)
            self.assertNotIn(b"<small>Longitude</small>", profile_response.data)
            self.assertIn(b"50 ft", profile_response.data)
            self.assertIn(b"Strong", profile_response.data)
            self.assertIn(b"76 degrees", profile_response.data)
            self.assertIn(b"82 degrees", profile_response.data)
            self.assertNotIn(b"Trailing 2 weeks, feet by day", profile_response.data)
            self.assertNotIn(b"Trailing 2 weeks by day", profile_response.data)
            self.assertIn(b"SIGHTINGS", profile_response.data)
            self.assertIn(b"Coral", profile_response.data)
            self.assertIn(b"<strong>2</strong>", profile_response.data)
            self.assertIn(b"Reef Fish", profile_response.data)
            self.assertNotIn(b"<strong>1</strong>", profile_response.data)

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
            self.assertIn(b'<option value="open water" selected>Open Water</option>', new_response.data)
            self.assertIn(b'<option value="shore dive" >Shore Dive</option>', new_response.data)
            self.assertIn(b'<option value="none" selected>-</option>', new_response.data)
            self.assertIn(b"Current type", new_response.data)
            self.assertIn(b'<option value="slack" >Slack</option>', new_response.data)
            self.assertIn(b'<option value="tidal" >Tidal</option>', new_response.data)
            self.assertIn(b'<option value="rip" >Rip</option>', new_response.data)
            self.assertIn(b'<option value="vertical" >Vertical</option>', new_response.data)
            self.assertIn(b"Current strength", new_response.data)
            self.assertIn(b"current-strength-control is-disabled", new_response.data)
            self.assertIn(b"data-current-type-select", new_response.data)
            self.assertIn(b"data-current-strength-range disabled", new_response.data)
            self.assertIn(b'<input name="current_strength" type="hidden" value="none"', new_response.data)
            self.assertIn(b"Very Strong", new_response.data)

            client.post(
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
                    "depth_ft": "40",
                    "duration_min": "70",
                    "weight_lbs": "4",
                    "exposure": "5mm",
                    "gas_mix": "32%",
                    "visibility_ft": "55",
                    "air_temp_degrees": "83",
                    "water_temp_degrees": "74",
                    "dive_type": "shore dive",
                    "current": "none",
                    "current_strength": "moderate",
                    "notes": "Clear water.",
                    "species_json": json.dumps(["Coral", "Reef Fish"]),
                },
            )
            dive_id = client.get("/api/dives/mine").get_json()[0]["id"]
            logged = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertEqual(logged["visibility_ft"], 55)
            self.assertEqual(logged["air_temp_degrees"], 83)
            self.assertEqual(logged["water_temp_degrees"], 74)
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
            self.assertIn(b"<dd>32%</dd>", detail_response.data)
            self.assertIn(b"Alaska", detail_response.data)
            self.assertIn(b'<p class="dive-center-line">', detail_response.data)
            self.assertIn(b"<span>with</span>", detail_response.data)
            self.assertIn(b'<a href="/dive-centers/2">Kelp House</a>', detail_response.data)
            self.assertIn(b"Kelp House", detail_response.data)
            self.assertNotIn(b"metadata-divider", detail_response.data)
            self.assertNotIn(b"dive-center-chip", detail_response.data)
            self.assertNotIn(b"- with", detail_response.data)
            self.assertNotIn(b"<h2>Conditions</h2>", detail_response.data)

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
            client.post("/signup", data={"username": "viewer", "password": "password"})
            foreign_dive = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertFalse(foreign_dive["is_owner"])
            self.assertEqual(client.get(f"/dive/{dive_id}/edit").status_code, 404)
            client.post("/logout")
            client.post("/login", data={"username": "tester", "password": "password"})

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
                    "depth_ft": "62",
                    "duration_min": "55",
                    "weight_lbs": "6",
                    "exposure": "3mm",
                    "gas_mix": "Other",
                    "visibility_ft": "85",
                    "air_temp_degrees": "88",
                    "water_temp_degrees": "81",
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
            self.assertEqual(updated["depth_ft"], 62)
            self.assertEqual(updated["visibility_ft"], 85)
            self.assertEqual(updated["air_temp_degrees"], 88)
            self.assertEqual(updated["water_temp_degrees"], 81)
            self.assertEqual(updated["gas_mix"], "Other")
            self.assertEqual(updated["dive_type"], "wreck")
            self.assertEqual(updated["current"], "rip")
            self.assertEqual(updated["current_strength"], "very strong")
            self.assertEqual(updated["species"], ["Turtle"])
            updated_detail = client.get(f"/dive/{dive_id}")
            self.assertIn(b"Blue Wall", updated_detail.data)
            self.assertIn(b"Wreck", updated_detail.data)
            self.assertIn(b"62<em>ft</em>", updated_detail.data)
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

    def test_profile_cert_can_be_added_displayed_edited_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            profile_response = client.get("/you")
            self.assertEqual(profile_response.status_code, 200)
            self.assertIn(b'href="/cert/new"', profile_response.data)
            self.assertNotIn(b"Rescue Diver", profile_response.data)

            form_response = client.get("/cert/new")
            self.assertEqual(form_response.status_code, 200)
            self.assertIn(b"Add a cert", form_response.data)
            self.assertIn(b'<option value="PADI" selected>PADI</option>', form_response.data)
            self.assertIn(b'<option value="" disabled selected>Select level</option>', form_response.data)
            self.assertIn(b'<option value="Rescue Diver" >Rescue Diver</option>', form_response.data)
            self.assertNotIn(b"datalist", form_response.data)
            self.assertIn(b'pattern="[A-Za-z0-9]+"', form_response.data)

            invalid_response = client.post(
                "/cert/new",
                data={
                    "agency": "PADI",
                    "level": "Rescue Diver",
                    "cert_no": "AB-123",
                    "cert_date": "2026-07-20",
                },
            )
            self.assertEqual(invalid_response.status_code, 302)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM user_certs").fetchone()[0], 0)

            create_response = client.post(
                "/cert/new",
                data={
                    "agency": "PADI",
                    "level": "Rescue Diver",
                    "cert_no": "AB123",
                    "cert_date": "2026-07-20",
                },
            )
            self.assertEqual(create_response.status_code, 302)
            self.assertTrue(create_response.headers["Location"].endswith("/you"))

            profile_response = client.get("/you")
            self.assertIn(b"Rescue Diver", profile_response.data)
            self.assertIn(b'<span aria-hidden="true">|</span>', profile_response.data)
            self.assertIn(b'href="/cert"', profile_response.data)

            detail_response = client.get("/cert")
            self.assertEqual(detail_response.status_code, 200)
            self.assertIn(b"PADI certification", detail_response.data)
            self.assertIn(b"<dt>Cert No.</dt>", detail_response.data)
            self.assertIn(b"<dd>AB123</dd>", detail_response.data)
            self.assertIn(b"Delete cert", detail_response.data)
            self.assertIn(b"Edit cert", detail_response.data)

            edit_response = client.post(
                "/cert/edit",
                data={
                    "agency": "PADI",
                    "level": "Divemaster",
                    "cert_no": "DM789",
                    "cert_date": "2026-07-21",
                },
            )
            self.assertEqual(edit_response.status_code, 302)
            updated_detail = client.get("/cert")
            self.assertIn(b"Divemaster", updated_detail.data)
            self.assertIn(b"DM789", updated_detail.data)

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT agency, level, cert_no, cert_date FROM user_certs"
                ).fetchone()
            self.assertEqual(row, ("PADI", "Divemaster", "DM789", "2026-07-21"))

            delete_response = client.post("/cert/delete")
            self.assertEqual(delete_response.status_code, 302)
            self.assertTrue(delete_response.headers["Location"].endswith("/you"))
            self.assertIn(b'href="/cert/new"', client.get("/you").data)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM user_certs").fetchone()[0], 0)

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
                    "depth_ft": "40",
                    "duration_min": "70",
                    "weight_lbs": "",
                    "exposure": "",
                    "visibility_ft": "",
                    "air_temp_degrees": "",
                    "water_temp_degrees": "",
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
            self.assertIn(b'class="photo-strip" aria-label="Dive photos"', home_response.data)
            self.assertEqual(home_response.data.count(b"uploads/dives/"), 3)

            profile_response = client.get("/you")
            self.assertEqual(profile_response.status_code, 200)
            profile_html = profile_response.data
            self.assertLess(profile_html.index(b"<small>dives</small>"), profile_html.index(b"<small>max depth</small>"))
            self.assertLess(profile_html.index(b"<small>max depth</small>"), profile_html.index(b"<small>longest dive</small>"))
            self.assertLess(profile_html.index(b"<small>longest dive</small>"), profile_html.index(b"<small>total minutes</small>"))
            self.assertLess(profile_html.index(b"profile-map"), profile_html.index(b"profile-map-stats"))
            self.assertLess(profile_html.index(b"<small>countries</small>"), profile_html.index(b"<small>locations</small>"))
            self.assertIn(b"<span>40 ft</span><small>max depth</small>", profile_html)
            self.assertIn(b"<span>70 min</span><small>longest dive</small>", profile_html)
            self.assertIn(b"<span>70</span><small>total minutes</small>", profile_html)
            self.assertIn(b"profile-map-stats", profile_html)
            self.assertIn(b'class="photo-strip" aria-label="Dive photos"', profile_response.data)
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
                    "depth_ft": "42",
                    "duration_min": "68",
                    "weight_lbs": "",
                    "exposure": "",
                    "visibility_ft": "",
                    "air_temp_degrees": "",
                    "water_temp_degrees": "",
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
