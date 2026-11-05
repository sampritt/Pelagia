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
            writer = csv.DictWriter(handle, fieldnames=["name", "physical_address", "location", "website", "latitude", "longitude", "padi_id", "overture_id", "merged_reference_keys"])
            writer.writeheader()
            writer.writerows(rows)

    def test_replaces_registry_preserves_matching_links_and_handles_removed_shops(self):
        self.write([
            {"name": "New Scuba", "physical_address": "Harbor", "website": "https://new.test", "overture_id": "new", "latitude": 11, "longitude": 124},
            {"name": "Existing Dive", "physical_address": "Beach", "website": "https://existing.test", "location": "PH", "padi_id": "123"},
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
            {"name": "Renamed Dive", "physical_address": "Beach", "website": "https://existing.test", "padi_id": "123"},
            {"name": "New Scuba", "physical_address": "Harbor", "website": "https://new.test", "overture_id": "new", "latitude": 12, "longitude": 125},
        ])
        refresh_centers(self.db, self.csv)
        self.assertEqual(self.db.execute("SELECT name FROM dive_centers WHERE id=5").fetchone()[0], "Renamed Dive")
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dives WHERE id=1").fetchone()[0], 5)

    def test_invalid_csv_leaves_catalog_unchanged(self):
        self.write([{"name": "Invalid", "physical_address": "Harbor", "website": "https://invalid.test", "latitude": "nan"}])
        with self.assertRaises(ValueError):
            refresh_centers(self.db, self.csv)
        self.assertEqual(self.db.execute("SELECT id FROM dive_centers ORDER BY id").fetchall(), [(5,), (10,)])

    def test_requires_both_contact_fields_and_preserves_email(self):
        self.write([
            {"name": "North Seymour Dive Spot", "location": "EC"},
            {"name": "No address", "website": "https://example.test"},
            {"name": "No website", "physical_address": "Beach"},
            {"name": "Email center", "physical_address": "Beach", "website": "mailto:diver@example.test"},
        ])
        self.assertEqual(refresh_centers(self.db, self.csv)["rows"], 1)
        self.assertEqual(self.db.execute("SELECT name FROM dive_centers").fetchall(), [("Email center",)])

    def test_merge_preserves_community_data_and_latest_review(self):
        import json
        from pelagia.center_registry import _legacy_reference
        old = dict(zip(("name", "physical_address", "location"), ("Old Dive Bar", "", "")))
        self.db.execute("UPDATE dive_center_reviews SET updated_at='2026-11-01 00:00:00' WHERE dive_center_id=5")
        self.db.execute("UPDATE dive_center_reviews SET body='Newer review', updated_at='2026-11-05 00:00:00' WHERE dive_center_id=10")
        self.db.commit()
        self.write([{"name": "Existing Dive", "physical_address": "Beach", "location": "PH",
                     "website": "https://existing.test", "padi_id": "123",
                     "merged_reference_keys": json.dumps([_legacy_reference(old)])}])
        result = refresh_centers(self.db, self.csv)
        self.assertEqual(result["removed"], 1)
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dives").fetchall(), [(5,), (5,)])
        self.assertEqual(self.db.execute("SELECT dive_center_name FROM dives WHERE id=2").fetchone()[0], "Old Dive Bar")
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dive_center_likes").fetchall(), [(5,)])
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dive_center_comments").fetchall(), [(5,), (5,)])
        self.assertEqual(self.db.execute("SELECT dive_center_id,body FROM dive_center_reviews").fetchall(), [(5, "Newer review")])
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertFalse(refresh_centers(self.db, self.csv)["changed"])

    def test_merge_keeps_alias_id_if_canonical_was_not_previously_imported(self):
        import json
        self.db.execute("ALTER TABLE dive_centers ADD COLUMN reference_key TEXT")
        self.db.execute("UPDATE dive_centers SET reference_key='overture:old' WHERE id=5")
        self.db.commit()
        self.write([{"name": "Canonical Dive", "physical_address": "Beach", "website": "https://example.test",
                     "padi_id": "123", "merged_reference_keys": json.dumps(["overture:old"])}])
        refresh_centers(self.db, self.csv)
        self.assertEqual(self.db.execute("SELECT id,reference_key FROM dive_centers").fetchall(), [(5, "padi:123")])
        self.assertEqual(self.db.execute("SELECT dive_center_id FROM dives WHERE id=1").fetchone()[0], 5)

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
