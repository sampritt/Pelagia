import tempfile
import unittest
from pathlib import Path

import test_reference_autocomplete as fixtures
from pelagia import db as database, dive_brief


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
        self.assertIn("Site reports", empty_home)
        with self.app.app_context():
            today = dive_brief.effective_date()
        self.assertIn(f'<time datetime="{today.isoformat()}">{today.day} {today:%b %Y}</time>', empty_home)
        self.assertIn("Follow dive sites to keep their daily reports in your feed.", empty_home)
        self.assertIn('href="/explore">Explore dive sites</a>', empty_home)
        self.assertNotIn("data-site-reports-track", empty_home)
        self.assertLess(empty_home.index("Site reports"), empty_home.index("No dives yet"))

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
        self.assertIn('data-followed-report-toggle', reports)
        self.assertIn('aria-controls="followedReport1"', reports)
        self.assertNotIn('data-site-reports-navigation', reports)
        self.assertIn('aria-label="Followed dive sites" tabindex="0"', reports)
        self.assertNotIn("species-row", reports)
        self.assertNotIn("Explore dive site", reports)
        self.assertNotIn("logged dive", reports)
        self.assertIn('class="site-reports-explore" href="/explore"', reports)
        self.assertLess(reports.index("site-reports-explore"), reports.index("Alert Rock"))
        self.assertNotIn("site followed", reports)
        self.assertIn('class="site-report-view" href="/dive-sites/1"', reports)
        self.assertIn('js/feed-site-reports.js', home)

        self.assertEqual(
            self.client.post("/api/dive-sites/1/favorite").get_json(),
            {"favorited": False},
        )
        self.assertIn("Follow dive sites to keep their daily reports in your feed.", self.client.get("/home").get_data(as_text=True))

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
        with self.app.app_context():
            today = dive_brief.effective_date()
        self.assertIn(f"{today.day} {today:%b %Y}", home)
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
