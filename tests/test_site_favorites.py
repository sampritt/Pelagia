import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database


class DiveSiteFavoritesTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = self.make_app(Path(self.directory.name))
        self.client = self.app.test_client()
        self.signup(self.client)

    def test_empty_state_follow_toggle_and_home_site_reports(self):
        empty_home = self.client.get("/home").get_data(as_text=True)
        self.assertIn('aria-labelledby="siteReportsTitle"', empty_home)
        self.assertIn('<h2 id="siteReportsTitle" class="site-reports-heading">Site reports</h2>', empty_home)
        self.assertNotIn('site-reports-meta', empty_home)
        self.assertIn("Check the forecast", empty_home)
        self.assertIn("Follow dive sites to get daily reports in your feed.", empty_home)
        self.assertIn('href="/explore">Explore dive sites</a>', empty_home)
        self.assertNotIn("data-site-reports-track", empty_home)
        self.assertLess(empty_home.index("Check the forecast"), empty_home.index("No dives yet"))

        profile = self.client.get("/dive-sites/1").get_data(as_text=True)
        self.assertIn('data-site-favorite data-site-id="1"', profile)
        self.assertIn('aria-pressed="false"', profile)
        self.assertIn("Follow", profile)
        self.assertNotIn("data-site-like", profile)

        self.assertEqual(
            self.client.post("/api/dive-sites/1/favorite").get_json(),
            {"favorited": True},
        )
        followed_profile = self.client.get("/dive-sites/1").get_data(as_text=True)
        self.assertIn("site-favorite-button following", followed_profile)
        self.assertIn('aria-pressed="true"', followed_profile)
        self.assertIn("Following", followed_profile)

        home = self.client.get("/home").get_data(as_text=True)
        reports = home.split('<section class="site-reports"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Alert Rock", reports)
        self.assertIn('class="site-reports-track"', reports)
        self.assertIn('class="site-report-card"', reports)
        self.assertIn('aria-labelledby="followedSiteTitle1"', reports)
        self.assertIn('data-followed-site-report', reports)
        self.assertIn('data-report-url="/api/dive-sites/1/report"', reports)
        self.assertIn('data-description-url="/api/dive-sites/1/description"', reports)
        self.assertIn('data-conditions-url="/api/dive-sites/1/conditions"', reports)
        self.assertIn('data-followed-report-text', reports)
        self.assertNotIn('data-followed-report-toggle', reports)
        self.assertNotIn('site-report-view', reports)
        self.assertNotIn('Read more', reports)
        self.assertNotIn('data-site-reports-navigation', reports)
        self.assertIn('aria-label="Followed dive sites" tabindex="0"', reports)
        self.assertNotIn("species-row", reports)
        self.assertNotIn("Explore dive site", reports)
        self.assertNotIn("logged dive", reports)
        self.assertIn("Site reports", reports)
        self.assertNotIn("<time", reports)
        self.assertNotIn("site-reports-explore", reports)
        self.assertNotIn('href="/explore"', reports)
        self.assertNotIn("site followed", reports)
        self.assertIn('class="site-report-card" href="/dive-sites/1#daily-report"', reports)
        self.assertEqual(reports.count('href="/dive-sites/1#daily-report"'), 1)
        self.assertIn('js/feed-site-reports.js', home)

        self.assertEqual(
            self.client.post("/api/dive-sites/1/favorite").get_json(),
            {"favorited": False},
        )
        empty_home = self.client.get("/home").get_data(as_text=True)
        self.assertIn("Check the forecast", empty_home)
        self.assertIn("Follow dive sites to get daily reports in your feed.", empty_home)

    def test_daily_feature_requires_seven_sightings_and_ocean_and_is_not_duplicated(self):
        with self.app.app_context():
            db = database.get_db()
            for site_id, count, feature in ((1, 7, "OCEAN"), (2, 7, "LAKE"), (3, 6, "OCEAN")):
                db.execute("INSERT INTO dives (user_id, dive_site_id, date, site_name) VALUES (1, ?, '2026-01-01', 'Test')", (site_id,))
                dive_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.executemany("INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
                               [(dive_id, f"Species {i}") for i in range(count)])
                db.execute("""INSERT INTO dive_site_water_classifications
                    (dive_site_id, latitude, longitude, feature)
                    SELECT id, latitude, longitude, ? FROM dive_sites WHERE id = ?""", (feature, site_id))
            db.commit()

        home = self.client.get("/home").get_data(as_text=True)
        reports = home.split('<section class="site-reports"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Featured", reports)
        self.assertIn("Alert Rock", reports)
        self.assertNotIn("Kelp Garden", reports)
        self.assertNotIn("Blue Wall", reports)
        self.assertEqual(reports.count('data-followed-site-report'), 1)
        self.client.post("/api/dive-sites/1/favorite")
        followed = self.client.get("/home").get_data(as_text=True)
        reports = followed.split('<section class="site-reports"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(reports.count('data-followed-site-report'), 1)
        self.assertEqual(reports.count("Featured"), 1)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute("SELECT count(*) FROM daily_featured_sites").fetchone()[0], 1)

    def test_feature_classifies_an_uncached_candidate(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO dives (user_id, dive_site_id, date, site_name) VALUES (1, 1, '2026-01-01', 'Test')")
            dive_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.executemany("INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
                           [(dive_id, f"Species {i}") for i in range(7)])
            db.commit()
        with patch("pelagia.water_type.classify_site", return_value={"feature": "OCEAN"}) as classify:
            self.assertIn("Featured", self.client.get("/home").get_data(as_text=True))
            self.assertIn("Featured", self.client.get("/home").get_data(as_text=True))
            self.assertEqual(classify.call_count, 1)

    def test_ten_site_limit_does_not_block_unfollow(self):
        with self.app.app_context():
            db = database.get_db()
            db.executemany(
                "INSERT INTO dive_sites (id, master_site_id, name, country_or_area) VALUES (?, ?, ?, 'Test Sea')",
                [(site_id, f"EXTRA-{site_id}", f"Site {site_id}") for site_id in range(4, 12)],
            )
            db.commit()

        for site_id in range(1, 11):
            response = self.client.post(f"/api/dive-sites/{site_id}/favorite")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"favorited": True})

        over_limit = self.client.post("/api/dive-sites/11/favorite")
        self.assertEqual(over_limit.status_code, 409)
        self.assertEqual(over_limit.get_json(), {"error": "You can follow up to 10 dive sites."})

        self.assertEqual(
            self.client.post("/api/dive-sites/1/favorite").get_json(),
            {"favorited": False},
        )
        self.assertEqual(
            self.client.post("/api/dive-sites/11/favorite").get_json(),
            {"favorited": True},
        )
        home = self.client.get("/home").get_data(as_text=True)
        reports = home.split('<section class="site-reports"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("<time", reports)
        self.assertNotIn("10/10 followed", home)
        self.assertNotIn('href="/dive-sites/1"', home.split('<section class="site-reports"', 1)[1].split("</section>", 1)[0])

    def test_legacy_site_likes_migrate_once_and_are_retired(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute(
                """
                CREATE TABLE dive_site_likes (
                    dive_site_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(dive_site_id, user_id)
                )
                """
            )
            db.execute("INSERT INTO dive_site_likes (dive_site_id, user_id) VALUES (2, 1)")
            db.commit()
            database.init_db()
            database.init_db()
            self.assertEqual(
                db.execute("SELECT dive_site_id, user_id FROM dive_site_favorites").fetchall()[0][:],
                (2, 1),
            )
            self.assertIsNone(
                db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'dive_site_likes'").fetchone()
            )


if __name__ == "__main__":
    unittest.main()
