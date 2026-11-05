import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pelagia.center_registry import refresh_centers
import test_reference_autocomplete as fixtures


class CenterRegistryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.csv = self.root / "centers.csv"
        self.db = sqlite3.connect(self.root / "db.sqlite")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript((Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text())
        self.db.execute("INSERT INTO users(id, username) VALUES(1, 'diver')")
        self.db.execute("INSERT INTO dive_centers(id, name, physical_address, location, website) VALUES(5, 'Existing Dive', 'Beach', 'PH', '')")
        self.db.execute("INSERT INTO dive_centers(id, name) VALUES(10, 'Old Dive Bar')")
        for center_id in (5, 10):
            self.db.execute("INSERT INTO dives(user_id, date, site_name, dive_center_id) VALUES(1, '2026-11-04', 'Reef', ?)", (center_id,))
            self.db.execute("INSERT INTO dive_center_likes VALUES(?, 1, CURRENT_TIMESTAMP)", (center_id,))
            self.db.execute("INSERT INTO dive_center_comments(dive_center_id, user_id, body) VALUES(?, 1, 'Comment')", (center_id,))
            self.db.execute("INSERT INTO dive_center_reviews(dive_center_id,user_id,rating,body) VALUES(?,1,5,'Good guides.')", (center_id,))
            self.db.execute("INSERT INTO dive_center_descriptions(dive_center_id,description,model) VALUES(?,'Boat diving.','test')", (center_id,))
        self.db.commit()

    def write(self, rows):
        with self.csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["name", "physical_address", "location", "website", "latitude", "longitude", "padi_id", "overture_id"])
            writer.writeheader()
            writer.writerows(rows)

    def test_replaces_registry_preserves_matching_links_and_handles_removed_shops(self):
        self.write([
            {"name": "New Scuba", "overture_id": "new", "latitude": 11, "longitude": 124},
            {"name": "Existing Dive", "physical_address": "Beach", "location": "PH", "padi_id": "123"},
        ])
        result = refresh_centers(self.db, self.csv)
        self.assertEqual(result, {"changed": True, "rows": 2, "removed": 1})
        self.assertEqual(self.db.execute("SELECT name FROM dive_centers WHERE id=5").fetchone()[0], "Existing Dive")
        self.assertEqual(self.db.execute("SELECT dive_center_id, dive_center_name FROM dives ORDER BY id").fetchall(), [(5, None), (None, "Old Dive Bar")])
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dive_center_likes").fetchall(), [(5,)])
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dive_center_comments").fetchall(), [(5,)])
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dive_center_reviews").fetchall(), [(5,)])
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dive_center_descriptions").fetchall(), [(5,)])
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertFalse(refresh_centers(self.db, self.csv)["changed"])
        self.write([
            {"name": "Renamed Dive", "padi_id": "123"},
            {"name": "New Scuba", "overture_id": "new", "latitude": 12, "longitude": 125},
        ])
        refresh_centers(self.db, self.csv)
        self.assertEqual(self.db.execute("SELECT name FROM dive_centers WHERE id=5").fetchone()[0], "Renamed Dive")
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dives WHERE id=1").fetchone()[0], 5)

    def test_invalid_csv_leaves_catalog_unchanged(self):
        self.write([{"name": "Invalid", "latitude": "nan"}])
        with self.assertRaises(ValueError):
            refresh_centers(self.db, self.csv)
        self.assertEqual(self.db.execute("SELECT id FROM dive_centers ORDER BY id").fetchall(), [(5,), (10,)])

    def test_startup_updates_search_with_populated_database(self):
        from pelagia import create_app
        app, db_path, config_path = fixtures.ReferenceAutocompleteTest().make_app(self.root)
        client = app.test_client()
        fixtures.ReferenceAutocompleteTest().signup(client)
        source = app.config["PELAGIA_LOCAL_CONFIG"]["data_sources"]["dive_centers_csv"]
        csv_path = config_path.parent / source
        with csv_path.open("a") as handle:
            handle.write("Evolution Dive Resort,Beach,Malapascua,https://evolution.com.ph\n")
        with patch.dict("os.environ", {"PELAGIA_CONFIG": str(config_path)}):
            restarted = create_app({"TESTING": True, "DATABASE": str(db_path), "UPLOAD_FOLDER": str(self.root / "uploads")})
        refreshed_client = restarted.test_client()
        with refreshed_client.session_transaction() as session:
            session["user_id"] = 1
        self.assertTrue(refreshed_client.get("/api/dive-centers?q=Evolution").get_json())
        self.assertTrue(any(item.get("type") == "center" for item in refreshed_client.get("/api/search?q=Evolution").get_json()))
