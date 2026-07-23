import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pelagia import create_app


def write_csv(path, content):
    path.write_text(content.strip() + "\n")


class ReferenceAutocompleteTest(unittest.TestCase):
    def make_app(self, tmp_path):
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
        with patch.dict(os.environ, {"PELAGIA_CONFIG": str(config_path)}):
            app = create_app({"TESTING": True})
        return app, db_path, config_path

    def signup(self, client):
        client.post("/signup", data={"username": "tester", "password": "password"})

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

    def test_owned_dive_can_be_edited_and_soft_deleted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app, db_path, _config_path = self.make_app(Path(tmp_dir))
            client = app.test_client()
            self.signup(client)

            new_response = client.get("/dive/new")
            self.assertIn(b'<option value="open water" selected>Open Water</option>', new_response.data)
            self.assertIn(b'<option value="shore dive" >Shore Dive</option>', new_response.data)
            self.assertIn(b'<option value="none" selected>None</option>', new_response.data)
            self.assertIn(b"Current type", new_response.data)
            self.assertIn(b"Current strength", new_response.data)
            self.assertIn(b'<input name="current_strength" type="hidden" value="none"', new_response.data)
            self.assertIn(b"Very Strong", new_response.data)
            self.assertNotIn(b"Slack", new_response.data)

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
                    "visibility_ft": "55",
                    "air_temp_degrees": "83",
                    "water_temp_degrees": "74",
                    "dive_type": "shore dive",
                    "current": "drift",
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
            self.assertEqual(logged["dive_type"], "shore dive")
            self.assertEqual(logged["current"], "drift")
            self.assertEqual(logged["current_strength"], "moderate")

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
                    "visibility_ft": "85",
                    "air_temp_degrees": "88",
                    "water_temp_degrees": "81",
                    "dive_type": "wreck",
                    "current": "surge",
                    "current_strength": "very strong",
                    "notes": "Updated notes.",
                    "species_json": json.dumps(["Turtle"]),
                },
            )
            self.assertEqual(update_response.status_code, 302)
            self.assertTrue(update_response.headers["Location"].endswith("/you?open=%s" % dive_id))
            updated = client.get(f"/api/dives/{dive_id}").get_json()
            self.assertTrue(updated["is_owner"])
            self.assertEqual(updated["site_name"], "Blue Wall")
            self.assertEqual(updated["depth_ft"], 62)
            self.assertEqual(updated["visibility_ft"], 85)
            self.assertEqual(updated["air_temp_degrees"], 88)
            self.assertEqual(updated["water_temp_degrees"], 81)
            self.assertEqual(updated["dive_type"], "wreck")
            self.assertEqual(updated["current"], "surge")
            self.assertEqual(updated["current_strength"], "very strong")
            self.assertEqual(updated["species"], ["Turtle"])

            delete_response = client.post(f"/dive/{dive_id}/delete", data={"next": "/home?open=%s" % dive_id})
            self.assertEqual(delete_response.status_code, 302)
            self.assertTrue(delete_response.headers["Location"].endswith("/home"))
            self.assertEqual(client.get(f"/api/dives/{dive_id}").status_code, 404)
            self.assertEqual(client.get("/api/dives/mine").get_json(), [])
            self.assertNotIn(b"Blue Wall", client.get("/home").data)

            with sqlite3.connect(db_path) as conn:
                is_deleted = conn.execute("SELECT is_deleted FROM dives WHERE id = ?", (dive_id,)).fetchone()[0]
            self.assertEqual(is_deleted, 1)


if __name__ == "__main__":
    unittest.main()
