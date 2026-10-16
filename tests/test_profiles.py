import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_reference_autocomplete as fixtures
from pelagia import db as database, get_profile_sac_history


def _seed_dives(db, user_id, observations):
    db.executemany(
        """INSERT INTO dives (user_id, date, site_name, depth_m, duration_min, sac_rate_l_min, is_deleted)
           VALUES (?, ?, ?, ?, 40, ?, ?)""",
        [(user_id, day, f"History dive {index}", index + 10, rate, deleted)
         for index, (day, rate, deleted) in enumerate(observations)],
    )
    db.commit()


class ProfileTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def test_starting_dive_count_updates_headline_and_metrics_and_is_owner_editable(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _, _ = self.make_app(Path(directory))
            owner = app.test_client()
            self.signup(owner)
            with app.app_context():
                _seed_dives(database.get_db(), 1, [
                    ("2026-01-01", 10, 0), ("2026-01-02", 20, 0), ("2026-01-03", 30, 1),
                ])
            self.assertEqual(owner.post("/you", data={"starting_dive_count": "40"}).status_code, 302)
            owner.post("/you", data={"bio": "Still diving"})
            for path in ("/you", "/users/1"):
                html = owner.get(path).data
                self.assertIn(b'<span class="diver-dive-count"><strong>42</strong> dives</span>', html)
                self.assertIn(b'<small>Dives</small><span>42</span><p>Total lifetime dives</p>', html)
                self.assertNotIn(b'<small>SAC rate</small>', html)
                self.assertIn(b'profile-sac-chart', html)
                self.assertIn(b'value="40" aria-describedby="startingDiveCountHelp"', html)
                self.assertEqual(html.count(b'<article class="dive-card"'), 2)
            for invalid in ("-1", "1.5", "1e2", "", "diver", "9223372036854775808"):
                with self.subTest(invalid=invalid):
                    self.assertEqual(owner.post("/you", data={"starting_dive_count": invalid}).status_code, 400)
            viewer = app.test_client()
            self.signup(viewer, "viewer")
            public = viewer.get("/users/1").data
            self.assertIn(b'<strong>42</strong> dives', public)
            self.assertIn(b'<small>Dives</small><span>42</span>', public)
            self.assertNotIn(b'name="starting_dive_count"', public)
            self.assertEqual(viewer.post("/users/1", data={"starting_dive_count": "99"}).status_code, 405)
            viewer.post("/you", data={"starting_dive_count": "1", "user_id": "1"})
            self.assertIn(b'<strong>1</strong> dive</span>', viewer.get("/you").data)
            self.assertIn(b'<strong>42</strong> dives', owner.get("/you").data)
            owner.post("/you", data={"starting_dive_count": "0"})
            self.assertIn(b'<strong>2</strong> dives', owner.get("/you").data)
            self.assertIn(b'<small>Dives</small><span>2</span>', owner.get("/you").data)

    def test_profile_sac_handles_even_medians_zero_and_legacy_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _, _ = self.make_app(Path(directory))
            self.signup(app.test_client())
            with app.app_context():
                _seed_dives(database.get_db(), 1, [
                    ("2026-01-01", 0, 0), ("2026-01-01", 20, 0),
                    ("2026-01-02", None, 0), ("2026-01-02", -1, 0),
                ])
                history = get_profile_sac_history(1)
                self.assertEqual(history["median"], 10)
                self.assertEqual(history["count"], 2)
                self.assertEqual(len(history["points"]), 1)
                self.assertEqual(history["points"][0]["value"], 10)
                self.assertEqual(history["points"][0]["x"], 48)
                _seed_dives(database.get_db(), 1, [("legacy unknown date", 30, 0)])
                history = get_profile_sac_history(1)
                self.assertEqual(history["median"], 20)
                self.assertEqual(len(history["points"]), 1)

    def test_history_metrics_share_dates_and_use_integer_ticks(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _, _ = self.make_app(Path(directory))
            client = app.test_client()
            self.signup(client)
            with app.app_context():
                _seed_dives(database.get_db(), 1, [
                    ("2026-01-01", None, 0), ("2026-01-02", 6.5, 0),
                    ("2026-01-05", 9, 0), ("2026-01-09", 100, 1),
                ])
                histories = [get_profile_sac_history(1, metric) for metric in
                             ("sac_rate_l_min", "depth_m", "duration_min")]
                for history in histories:
                    self.assertEqual(history["date_labels"], histories[0]["date_labels"])
                    self.assertTrue(all(tick["value"].isdigit() for tick in history["ticks"]))
                self.assertEqual(histories[0]["points"][0]["x"], histories[1]["points"][1]["x"])
                self.assertEqual([p["value"] for p in histories[2]["points"]], [40, 40, 40])
            html = client.get("/you").data
            for metric in (b"sac_rate_l_min", b"depth_m", b"duration_min"):
                self.assertIn(b'data-history-option="' + metric + b'"', html)
                self.assertIn(b'data-history-view="' + metric + b'"', html)
            self.assertIn(b'Max depth (m)', html)
            self.assertIn(b'Duration (min)', html)

    def test_profile_fields_migrate_for_existing_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            def prepare_db(path):
                schema = (Path(__file__).resolve().parents[1] / "pelagia/schema.sql").read_text()
                schema = schema.replace("    bio TEXT,\n", "").replace(
                    "    certification_id INTEGER REFERENCES certifications(id) ON DELETE SET NULL,\n", "").replace(
                    "    starting_dive_count INTEGER NOT NULL DEFAULT 0 CHECK (starting_dive_count >= 0),\n", "")
                with sqlite3.connect(path) as db:
                    db.executescript(schema)
                    db.execute("INSERT INTO users (username) VALUES ('existing')")
            app, _, _ = self.make_app(Path(directory), prepare_db=prepare_db)
            client = app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = 1
            self.assertEqual(client.get("/you").status_code, 200)
            self.assertIn(b'name="starting_dive_count"', client.get("/you").data)
            client.post("/you", data={"bio": "My existing account", "certification_id": 1, "starting_dive_count": 25})
            self.assertIn(b"My existing account", client.get("/you").data)
            self.assertIn(b"Open Water Diver", client.get("/you").data)
            with app.app_context():
                database.init_db()
                self.assertEqual(database.get_db().execute("SELECT starting_dive_count FROM users").fetchone()[0], 25)

    def test_profile_history(self):
        with tempfile.TemporaryDirectory() as directory:
            app, db_path, _ = self.make_app(Path(directory))
            client = app.test_client()
            self.signup(client)
            self.signup(app.test_client(), "other-diver")
            with app.app_context():
                db = database.get_db()
                _seed_dives(db, 1, [
                    ("2026-01-01", 10, 0), ("2026-01-01", 20, 0), ("2026-01-01", 24, 0),
                    ("2026-01-02", 40, 0), ("2026-01-05", 100, 0),
                    ("2026-01-05", None, 0), ("2026-01-05", 999, 1),
                ])
                _seed_dives(db, 2, [("2026-01-01", 900, 0)])
                history = get_profile_sac_history(1)
            # Overall median is computed over individual dives, not over daily medians.
            self.assertEqual(history["median"], 24)
            self.assertEqual(history["count"], 5)
            self.assertEqual([p["value"] for p in history["points"]], [20, 40, 100])
            self.assertEqual([p["date"] for p in history["points"]], ["2026-01-01", "2026-01-02", "2026-01-05"])
            x = [p["x"] for p in history["points"]]
            self.assertAlmostEqual((x[2] - x[1]) / (x[1] - x[0]), 3)
            html = client.get('/you').data
            self.assertIn(b'History</h2>', html)
            self.assertNotIn(b'<small>SAC rate</small>', html)
            self.assertIn(b'Jan 01, 2026: 20 L/min', html)
            self.assertNotIn(b'999 L/min', html)
            # Missing rates and soft-deleted dives leave a clear, honest empty state.
            with sqlite3.connect(db_path) as db:
                db.execute('UPDATE dives SET sac_rate_l_min = NULL WHERE user_id = 1')
            self.assertIn(b'Your air consumption, over time', client.get('/you').data)
            with app.app_context():
                self.assertIsNone(get_profile_sac_history(1)['median'])

    def test_profile_persistence_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            app, db_path, config = self.make_app(Path(directory))
            client = app.test_client()
            self.signup(client)
            certs = client.get('/api/certifications').get_json()
            self.assertEqual(len(certs), 9)
            self.assertEqual([c['name'] for c in client.get('/api/certifications?q=instructor').get_json()],
                             ['Assistant Instructor', 'Instructor'])
            self.assertEqual(client.get('/api/certifications?q=imaginary').get_json(), [])
            cert = certs[2]
            self.assertEqual(client.post('/you', data={'bio': 'Reefs & wrecks <script>', 'certification_id': cert['id']}).status_code, 302)
            self.assertEqual(client.post('/you', data={'certification_id': 'invented'}).status_code, 400)
            self.assertEqual(client.post('/you', data={'bio': 'x' * 501}).status_code, 400)
            html = client.get('/you').data
            self.assertIn(b'Reefs &amp; wrecks &lt;script&gt;', html)
            self.assertIn(b'Rescue Diver', html)
            self.assertIn(b'aria-label="Remove Rescue Diver"', html)
            # Startup migration is repeatable and retains selected references and bio.
            with app.app_context():
                database.init_db()
                database.init_db()
            self.assertIn(b'Rescue Diver', client.get('/you').data)
            viewer = app.test_client()
            self.signup(viewer, 'visitor')
            public = viewer.get('/users/1').data
            self.assertIn(b'Rescue Diver', public)
            self.assertIn(b'Reefs &amp; wrecks', public)
            self.assertNotIn(b'data-bio-edit', public)
            self.assertNotIn(b'data-certification-picker', public)
            self.assertNotIn(b'aria-label="Remove Rescue Diver"', public)
            self.assertEqual(viewer.post('/users/1', data={'bio': 'Changed'}).status_code, 405)
            viewer.post('/you', data={'bio': 'Only mine', 'user_id': 1})
            self.assertIn(b'Reefs &amp; wrecks', client.get('/you').data)
            client.post('/you', data={'certification_id': ''})
            self.assertNotIn(b'aria-label="Remove Rescue Diver"', client.get('/you').data)
            self.assertIn(b'Reefs &amp; wrecks', client.get('/you').data)
            client.post('/you', data={'bio': ''})
            self.assertNotIn(b'Reefs &amp; wrecks', client.get('/you').data)
            self.assertEqual(app.test_client().get('/api/certifications').status_code, 302)

    def test_profile_all_dives_and_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _, _ = self.make_app(Path(directory))
            client = app.test_client()
            self.signup(client)
            with app.app_context():
                _seed_dives(database.get_db(), 1, [("2026-01-01", None, 0)] * 85 + [("2026-01-01", 100, 1)])
            for path in ('/you', '/users/1'):
                html = client.get(path).data
                self.assertEqual(html.count(b'<article class="dive-card"'), 85)
                self.assertIn(b'History dive 0', html)
                self.assertIn(b'History dive 84', html)
                self.assertNotIn(b'History dive 85', html)
                self.assertNotIn(b'profile-hero', html)
            site = client.get('/dive-sites/1').data
            self.assertEqual(site.count(b'data-static-map data-map-lat="54.1"'), 1)
            self.assertLess(site.index(b'site-map-banner'), site.index(b'<h1>Alert Rock'))
            self.assertNotIn(b'profile-hero', site)
            self.assertNotIn(b'profile-hero', client.get('/dive-centers/1').data)
            with app.app_context():
                database.get_db().execute('UPDATE dive_sites SET latitude = NULL, longitude = NULL WHERE id = 1')
                database.get_db().commit()
            site = client.get('/dive-sites/1').data
            self.assertIn(b'Coordinates pending', site)
            self.assertNotIn(b'data-static-map', site)
