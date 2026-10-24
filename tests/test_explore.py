import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pelagia import create_app, db as database
from pelagia.explore import PAGE_SIZE


class ExploreTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            self.app = create_app({
                "TESTING": True, "SECRET_KEY": "explore-tests",
                "DATABASE": str(Path(temporary.name) / "test.sqlite3"),
                "UPLOAD_FOLDER": str(Path(temporary.name) / "uploads"),
            })
        self.enterContext(self.app.app_context())
        self.db = database.get_db()
        self.db.executemany("INSERT INTO users (username) VALUES (?)", [("diver",), ("buddy",)])
        self.db.executemany(
            "INSERT INTO dive_sites (name, country_or_area, latitude, longitude) VALUES (?, ?, ?, ?)",
            [("Maple Reef", "Canada", 48.4, -123.3), ("Northern Wall", "Canada", None, None),
             ("Manta Point", "Komodo National Park", -8.5, 119.5), ("Rock <&> Reef", "Côte d’Ivoire", 0, 0)],
        )
        self.db.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    def add_dive(self, site_id, *, user_id=1, deleted=0, created="2026-10-24 12:00:00", day="2026-10-24"):
        cursor = self.db.execute(
            """INSERT INTO dives (user_id, dive_site_id, site_name, country_or_area, date, created_at, is_deleted)
               VALUES (?, ?, 'Logged site', 'Old location', ?, ?, ?)""",
            (user_id, site_id, day, created, deleted),
        )
        self.db.commit()
        return cursor.lastrowid

    def test_requires_login_and_adds_explore_in_both_navigation_bars(self):
        anonymous = self.app.test_client()
        for path in ("/explore", "/api/explore", "/api/explore/locations?q=Canada"):
            self.assertEqual(anonymous.get(path).status_code, 302)
        html = self.client.get("/explore").get_data(as_text=True)
        for nav in re.findall(r'<nav class="(?:desktop-nav|mobile-nav)".*?</nav>', html, re.S):
            links = re.findall(r'href="([^"]+)"', nav)
            self.assertEqual(links, ["/home", "/explore", "/dive/new", "/you"])
        self.assertIn("Where will you dive next?", html)
        self.assertNotIn('role="tablist"', html)
        self.assertNotIn("Coming soon", html)

    def test_location_search_is_distinct_case_insensitive_and_literal(self):
        self.db.execute("INSERT INTO dive_sites (name, country_or_area) VALUES ('Duplicate', 'canada')")
        self.db.execute("INSERT INTO dive_sites (name, country_or_area) VALUES ('Unknown', '')")
        self.db.commit()
        for query, expected in (("can", ["Canada"]), ("KOMODO", ["Komodo National Park"]),
                                ("côte", ["Côte d’Ivoire"]), ("Maple", []), ("%", []), ("_", []), ("", [])):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/explore/locations", query_string={"q": query}).get_json(), expected)

    def save_location(self, location, client=None):
        return (client or self.client).post("/api/explore/location", json={"location": location},
                                            headers={"X-Requested-With": "fetch"})

    def test_initial_default_is_empty_even_with_logged_dives(self):
        self.add_dive(1)
        html = self.client.get("/explore").get_data(as_text=True)
        self.assertIn('data-location=""', html)
        self.assertIn("Where will you dive next?", html)
        self.assertNotIn("Maple Reef", html)
        self.assertNotIn("Your Location", html)
        self.assertNotIn("geolocation", html)
        self.assertEqual(self.client.post("/api/explore/nearby").status_code, 404)

    def test_selected_location_becomes_default_across_navigation_and_sessions(self):
        response = self.save_location("komodo national park")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"location": "Komodo National Park"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.client.get("/home")
        html = self.client.get("/explore").get_data(as_text=True)
        self.assertIn('data-location="Komodo National Park"', html)
        self.assertIn("Manta Point", html)
        self.assertIn('data-explore-input hidden disabled', html)
        fresh_client = self.app.test_client()
        with fresh_client.session_transaction() as session:
            session["user_id"] = 1
        self.assertIn('data-location="Komodo National Park"', fresh_client.get("/explore").get_data(as_text=True))
        self.assertEqual(self.save_location("Canada").status_code, 200)
        self.assertIn("Maple Reef", self.client.get("/explore").get_data(as_text=True))
        self.assertEqual(self.save_location("").status_code, 200)
        self.assertIn('data-location=""', self.client.get("/explore").get_data(as_text=True))

    def test_default_is_per_account_and_only_explicit_selection_changes_it(self):
        self.save_location("Canada")
        buddy = self.app.test_client()
        with buddy.session_transaction() as session:
            session["user_id"] = 2
        self.assertIn('data-location=""', buddy.get("/explore").get_data(as_text=True))
        self.save_location("Komodo National Park", buddy)
        self.assertIn('data-location="Canada"', self.client.get("/explore").get_data(as_text=True))
        self.client.get("/explore?location=Komodo+National+Park")
        self.assertIn('data-location="Canada"', self.client.get("/explore").get_data(as_text=True))

    def test_saved_location_requires_auth_and_valid_catalog_selection(self):
        self.assertEqual(self.save_location("Canada", self.app.test_client()).status_code, 302)
        self.assertEqual(self.client.post("/api/explore/location", json={"location": "Canada"}).status_code, 403)
        for invalid in ("Unknown region", "<script>", 1, None, ["Canada"]):
            self.assertEqual(self.save_location(invalid).status_code, 400)
        self.save_location("Canada")
        database.init_db()
        database.init_db()
        self.assertEqual(self.db.execute("SELECT explore_location FROM users WHERE id = 1").fetchone()[0], "Canada")

    def test_existing_accounts_migrate_to_an_empty_default_without_changing_dives(self):
        dive_id = self.add_dive(1)
        self.db.execute("ALTER TABLE users DROP COLUMN explore_location")
        self.db.commit()
        database.init_db()
        self.assertIsNone(self.db.execute("SELECT explore_location FROM users WHERE id = 1").fetchone()[0])
        self.assertEqual(self.db.execute("SELECT dive_site_id FROM dives WHERE id = ?", (dive_id,)).fetchone()[0], 1)
        self.assertIn('data-location=""', self.client.get("/explore").get_data(as_text=True))

    def test_logged_counts_and_observed_species_exclude_deleted_dives_and_catalog_suggestions(self):
        first = self.add_dive(1)
        second = self.add_dive(1, user_id=2)
        third = self.add_dive(1)
        deleted = self.add_dive(1, deleted=1)
        self.db.executemany("INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
                            [(first, "Turtle"), (first, "Turtle"), (second, "Turtle"),
                             (third, "Ray <&> Shark"), (deleted, "Deleted species")])
        self.db.execute("INSERT INTO site_species (dive_site_name, common_name) VALUES ('Maple Reef', 'Catalog only')")
        self.db.commit()
        for response in (self.client.get("/api/explore?location=Canada"),):
            html = response.get_json()["html"]
            self.assertIn("3 logged dives", html)
            self.assertNotIn("0 logged dives", html)
            self.assertIn("Turtle <strong>2</strong>", html)
            self.assertIn("Ray &lt;&amp;&gt; Shark", html)
            self.assertNotIn("Deleted species", html)
            self.assertNotIn("Catalog only", html)
            self.assertLess(html.index('class="mini-map'), html.index('aria-label="Observed marine species"'))
        self.db.execute("UPDATE dives SET is_deleted = 1 WHERE id IN (?, ?)", (second, third))
        self.db.commit()
        self.assertIn("1 logged dive</span>", self.client.get("/api/explore?location=Canada").get_json()["html"])

    def test_feed_links_maps_missing_coordinates_and_escaping(self):
        data = self.client.get("/api/explore?location=canada").get_json()
        self.assertEqual(data["total"], 2)
        self.assertIn('href="/dive-sites/1"', data["html"])
        self.assertIn('data-map-lat="48.4"', data["html"])
        self.assertIn("Coordinates pending", data["html"])
        self.assertNotIn("Manta Point", data["html"])
        self.assertIsNone(data["next_page"])
        response = self.client.get("/api/explore", query_string={"location": "Côte d’Ivoire"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("Rock &lt;&amp;&gt; Reef", response.get_json()["html"])
        self.assertIn('data-map-lat="0.0"', response.get_json()["html"])
        unknown = self.client.get("/api/explore?location=%27%20OR%201=1").get_json()
        self.assertEqual(unknown["total"], 0)
        self.assertNotIn('class="explore-card ', unknown["html"])

    def test_feed_is_paginated_without_duplicates(self):
        self.db.executemany("INSERT INTO dive_sites (name, country_or_area) VALUES (?, 'Canada')",
                            [(f"Site {index:02}",) for index in range(PAGE_SIZE + 3)])
        self.db.commit()
        first = self.client.get("/api/explore?location=Canada").get_json()
        second = self.client.get("/api/explore?location=Canada&page=2").get_json()
        ids = lambda data: re.findall(r'href="/dive-sites/(\d+)"', data["html"])
        self.assertEqual(len(ids(first)), PAGE_SIZE)
        self.assertEqual(first["next_page"], 2)
        self.assertIsNone(second["next_page"])
        self.assertFalse(set(ids(first)) & set(ids(second)))
        self.assertEqual(len(ids(first)) + len(ids(second)), first["total"])
        for page in ("0", "-1", "bad", "10001"):
            self.assertEqual(self.client.get(f"/api/explore?location=Canada&page={page}").status_code, 400)


if __name__ == "__main__":
    unittest.main()
