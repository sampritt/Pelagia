import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from pelagia import create_app, db as database
from pelagia.explore import PAGE_SIZE, GeocodingError, cartesian_distance_km, geocode_place


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

    def add_dive(self, site_id, *, user_id=1, deleted=0, created="2026-10-24 12:00:00",
                 day="2026-10-24", country="Canada"):
        cursor = self.db.execute(
            """INSERT INTO dives (user_id, dive_site_id, site_name, country_or_area, date, created_at, is_deleted)
               VALUES (?, ?, 'Logged site', ?, ?, ?, ?)""",
            (user_id, site_id, country, day, created, deleted),
        )
        self.db.commit()
        return cursor.lastrowid

    def add_obis_species(self, site_id, common_name, record_id):
        species_id = self.db.execute(
            "INSERT INTO species (country_or_area, common_name) VALUES (?, ?)",
            (record_id, common_name),
        ).lastrowid
        self.db.execute(
            """INSERT INTO obis_occurrences
               (obis_id, queried_taxon_id, decimal_latitude, decimal_longitude,
                coordinate_uncertainty_m, raw_json) VALUES (?, 1, 48.4, -123.3, 10, '{}')""",
            (record_id,),
        )
        self.db.execute(
            """INSERT INTO dive_site_obis_occurrences
               (dive_site_id, species_id, obis_id, distance_meters) VALUES (?, ?, ?, 10)""",
            (site_id, species_id, record_id),
        )
        self.db.commit()

    def test_requires_login_and_adds_explore_in_both_navigation_bars(self):
        anonymous = self.app.test_client()
        for path in ("/explore", "/api/explore", "/api/explore/locations?q=Canada",
                     "/api/explore/nearby?query=x&radius=1&unit=mi"):
            self.assertEqual(anonymous.get(path).status_code, 302)
        html = self.client.get("/explore").get_data(as_text=True)
        for nav in re.findall(r'<nav class="(?:desktop-nav|mobile-nav)".*?</nav>', html, re.S):
            links = re.findall(r'href="([^"]+)"', nav)
            self.assertEqual(links, ["/home", "/explore", "/dive/new", "/you"])
        self.assertIn("Where will you dive next?", html)
        self.assertNotIn('role="tablist"', html)
        self.assertNotIn("Coming soon", html)
        self.assertIn("Advanced search", html)
        self.assertIn("Search within", html)
        self.assertIn("City, island, or landmark", html)
        self.assertNotIn("Place search by", html)
        self.assertIn('type="range" min="1" max="100"', html)

    def nearby_search(self, query="Victoria", radius=50, unit="mi"):
        return self.client.post(
            "/api/explore/nearby",
            json={"query": query, "radius": radius, "unit": unit},
            headers={"X-Requested-With": "fetch"},
        )

    def test_nominatim_request_and_result_validation(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{
            "display_name": "Victoria, British Columbia, Canada",
            "lat": "48.4283", "lon": "-123.3649",
        }]
        with patch("pelagia.explore.requests.get", return_value=response) as get:
            result = geocode_place("Victoria")
        self.assertEqual(result, {
            "display_name": "Victoria, British Columbia, Canada",
            "latitude": 48.4283, "longitude": -123.3649,
        })
        self.assertEqual(get.call_args.args[0], "https://nominatim.openstreetmap.org/search")
        self.assertEqual(get.call_args.kwargs["params"], {
            "q": "Victoria", "format": "jsonv2", "limit": 1,
        })
        self.assertIn("Pelagia/1.0", get.call_args.kwargs["headers"]["User-Agent"])
        self.assertEqual(get.call_args.kwargs["timeout"], 10)

        response.json.return_value = []
        with patch("pelagia.explore.requests.get", return_value=response):
            self.assertIsNone(geocode_place("Nowhere"))
        with patch("pelagia.explore.requests.get", side_effect=requests.Timeout):
            with self.assertRaises(GeocodingError):
                geocode_place("Victoria")

    def test_advanced_search_geocodes_then_filters_by_cartesian_radius(self):
        self.db.executemany(
            "INSERT INTO dive_sites (name, country_or_area, latitude, longitude) VALUES (?, ?, ?, ?)",
            [("Nearby Wall", "Canada", 48.5, -123.3),
             ("Outside Wall", "Canada", 49.2, -123.3)],
        )
        self.db.commit()
        place = {
            "display_name": "Victoria, Capital Regional District, British Columbia, Canada",
            "latitude": 48.4, "longitude": -123.3,
        }
        with patch("pelagia.explore.geocode_place", return_value=place) as geocode:
            response = self.nearby_search("Victoria", 10, "mi")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        data = response.get_json()
        self.assertEqual(data["place"], place)
        self.assertEqual(data["query"], "Victoria")
        self.assertEqual(data["total"], 2)
        self.assertLess(data["html"].index("Maple Reef"), data["html"].index("Nearby Wall"))
        self.assertNotIn("Outside Wall", data["html"])
        self.assertNotIn("Northern Wall", data["html"])
        geocode.assert_called_once_with("Victoria")
        self.assertAlmostEqual(cartesian_distance_km(0, 179.9, 0, -179.9), 22.24, places=1)

        self.client.get("/home")
        restored = self.client.get("/explore").get_data(as_text=True)
        self.assertIn("Victoria, Capital Regional District, British Columbia, Canada", restored)
        self.assertIn("2 dive sites within 10 miles", restored)
        self.assertIn("Maple Reef", restored)
        self.assertIn('"radius": 10', restored)
        fresh_client = self.app.test_client()
        with fresh_client.session_transaction() as fresh_session:
            fresh_session["user_id"] = 1
        self.assertIn(
            "Victoria, Capital Regional District, British Columbia, Canada",
            fresh_client.get("/explore").get_data(as_text=True),
        )

    def test_advanced_search_no_result_errors_and_validation(self):
        self.assertEqual(self.client.post("/api/explore/nearby", json={}).status_code, 403)
        with patch("pelagia.explore.geocode_place", return_value=None):
            missing = self.nearby_search("Gaunacaste")
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.get_json(), {"error": "no_results", "query": "Gaunacaste"})
        with patch("pelagia.explore.geocode_place", side_effect=GeocodingError("offline")):
            unavailable = self.nearby_search()
        self.assertEqual(unavailable.status_code, 502)
        self.assertEqual(unavailable.get_json()["error"], "geocoding_unavailable")
        for payload in (
            {"query": "", "radius": 10, "unit": "mi"},
            {"query": "Victoria", "radius": 0, "unit": "mi"},
            {"query": "Victoria", "radius": 10.5, "unit": "mi"},
            {"query": "Victoria", "radius": 101, "unit": "mi"},
            {"query": "Victoria", "radius": 161, "unit": "km"},
            {"query": "Victoria", "radius": 10, "unit": "league"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/explore/nearby", json=payload,
                    headers={"X-Requested-With": "fetch"},
                )
                self.assertEqual(response.status_code, 400)

    def test_advanced_search_pagination_reuses_coordinates_without_geocoding(self):
        self.db.executemany(
            "INSERT INTO dive_sites (name, country_or_area, latitude, longitude) VALUES (?, 'Canada', ?, ?)",
            [(f"Nearby {index:02}", 48.4 + index / 10000, -123.3)
             for index in range(PAGE_SIZE + 3)],
        )
        self.db.commit()
        response = self.client.get("/api/explore/nearby", query_string={
            "query": "Victoria", "display_name": "Victoria, British Columbia, Canada",
            "latitude": 48.4, "longitude": -123.3, "radius": 10, "unit": "km",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["next_page"], 2)
        page_two = self.client.get("/api/explore/nearby", query_string={
            "query": "Victoria", "display_name": "Victoria, British Columbia, Canada",
            "latitude": 48.4, "longitude": -123.3, "radius": 10, "unit": "km", "page": 2,
        }).get_json()
        self.assertIsNone(page_two["next_page"])
        self.assertEqual(response.get_json()["total"], PAGE_SIZE + 4)

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

    def test_initial_default_uses_most_recently_logged_dive_region(self):
        self.add_dive(1)
        html = self.client.get("/explore").get_data(as_text=True)
        self.assertIn('data-location="Canada"', html)
        self.assertIn("Maple Reef", html)
        self.assertNotIn("Where will you dive next?", html)
        self.assertNotIn("Your Location", html)
        self.assertNotIn("geolocation", html)
        self.assertEqual(self.client.post("/api/explore/nearby").status_code, 403)

    def test_initial_default_uses_log_time_and_ignores_deleted_or_other_users_dives(self):
        self.add_dive(3, created="2026-10-24 13:00:00", day="2026-10-25",
                      country="Komodo National Park")
        self.add_dive(1, created="2026-10-24 14:00:00", day="2026-10-23")
        self.add_dive(3, created="2026-10-24 15:00:00", deleted=1,
                      country="Komodo National Park")
        self.add_dive(3, created="2026-10-24 16:00:00", user_id=2,
                      country="Komodo National Park")
        html = self.client.get("/explore").get_data(as_text=True)
        self.assertIn('data-location="Canada"', html)
        self.assertIn("Maple Reef", html)
        self.assertNotIn("Manta Point", html)

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
        self.assertIsNone(self.db.execute(
            "SELECT explore_nearby_json FROM users WHERE id = 1"
        ).fetchone()[0])
        self.assertIn("Maple Reef", self.client.get("/explore").get_data(as_text=True))
        self.assertEqual(self.save_location("").status_code, 200)
        self.assertIn('data-location=""', self.client.get("/explore").get_data(as_text=True))
        self.assertEqual(self.db.execute("SELECT explore_location FROM users WHERE id = 1").fetchone()[0], "")

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
        self.assertIn("explore_nearby_json", {
            row["name"] for row in self.db.execute("PRAGMA table_info(users)")
        })

    def test_existing_accounts_migrate_to_latest_dive_default_without_changing_dives(self):
        dive_id = self.add_dive(1)
        self.db.execute("ALTER TABLE users DROP COLUMN explore_location")
        self.db.commit()
        database.init_db()
        self.assertIsNone(self.db.execute("SELECT explore_location FROM users WHERE id = 1").fetchone()[0])
        self.assertEqual(self.db.execute("SELECT dive_site_id FROM dives WHERE id = ?", (dive_id,)).fetchone()[0], 1)
        self.assertIn('data-location="Canada"', self.client.get("/explore").get_data(as_text=True))

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

    def test_feed_combines_logged_and_obis_species_without_duplicate_tags_or_dive_counts(self):
        for _ in range(2):
            dive_id = self.add_dive(1)
            self.db.execute(
                "INSERT INTO dive_species (dive_id, common_name) VALUES (?, 'Turtle')",
                (dive_id,),
            )
        self.add_obis_species(1, " turtle ", "overlap")
        self.add_obis_species(1, "Octopus <&>", "octopus-1")
        self.add_obis_species(1, " Octopus <&> ", "octopus-2")
        self.add_obis_species(2, "Seal", "seal")
        for html in (
            self.client.get("/explore?location=Canada").get_data(as_text=True),
            self.client.get("/api/explore?location=Canada").get_json()["html"],
            self.client.get("/api/explore/nearby", query_string={
                "query": "Victoria", "display_name": "Victoria", "latitude": 48.4,
                "longitude": -123.3, "radius": 10, "unit": "km",
            }).get_json()["html"],
        ):
            self.assertEqual(html.count("Turtle <strong>2</strong>"), 1)
            self.assertNotIn(">turtle", html)
            self.assertEqual(html.count("Octopus &lt;&amp;&gt;"), 1)
            self.assertIn("2 logged dives", html)
        html = self.client.get("/api/explore?location=Canada").get_json()["html"]
        self.assertIn("Seal</span>", html)

    def test_feed_ranks_by_dives_then_combined_species_before_pagination(self):
        # Put the species-rich site on the second page under alphabetical sorting.
        self.db.executemany(
            """INSERT INTO dive_sites (name, country_or_area, latitude, longitude)
               VALUES (?, 'Canada', 48.4, -123.3)""",
            [(f"A Reef {index:02}",) for index in range(PAGE_SIZE)],
        )
        rich_site = self.db.execute(
            """INSERT INTO dive_sites (name, country_or_area, latitude, longitude)
               VALUES ('Z Rich Reef', 'Canada', 48.45, -123.3)"""
        ).lastrowid
        self.add_dive(1)
        rich_dive = self.add_dive(rich_site)
        self.db.execute(
            "INSERT INTO dive_species (dive_id, common_name) VALUES (?, 'Turtle')",
            (rich_dive,),
        )
        self.add_obis_species(rich_site, "Turtle", "overlap")
        self.add_obis_species(rich_site, "Octopus", "octopus")
        self.add_obis_species(rich_site, " Octopus ", "duplicate")
        # More dives take precedence over the richer site's species count.
        self.add_dive(2)
        self.add_dive(2)
        deleted_dive = self.add_dive(1, deleted=1)
        self.db.executemany(
            "INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
            [(deleted_dive, name) for name in ("Deleted A", "Deleted B", "Deleted C")],
        )
        self.db.execute("UPDATE dive_sites SET latitude = 48.4, longitude = -123.3 WHERE id = 2")
        self.db.commit()
        nearby = {"query": "Victoria", "display_name": "Victoria", "latitude": 48.4,
                  "longitude": -123.3, "radius": 10, "unit": "km"}
        for endpoint, query in (("/api/explore", {"location": "Canada"}),
                                ("/api/explore/nearby", nearby)):
            first = self.client.get(endpoint, query_string=query).get_json()
            second = self.client.get(endpoint, query_string=dict(query, page=2)).get_json()
            ids = lambda data: re.findall(r'href="/dive-sites/(\d+)"', data["html"])
            self.assertEqual(ids(first)[:3], ["2", str(rich_site), "1"])
            self.assertEqual(len(ids(first)), PAGE_SIZE)
            self.assertFalse(set(ids(first)) & set(ids(second)))
            self.assertEqual(len(ids(first)) + len(ids(second)), first["total"])

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
