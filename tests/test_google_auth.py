import secrets
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey
from requests.exceptions import Timeout

from pelagia import create_app
from pelagia import db as database


class GoogleAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RSAKey.generate_key(2048)
        cls.key.ensure_kid()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "pelagia.sqlite3"
        self.app = self.make_app()
        self.client = self.app.test_client()
        self.google = self.app.extensions["authlib.integrations.flask_client"].google
        # Keep the real Authlib authorization and ID token validation paths;
        # only discovery/JWKS and the token exchange use local provider data.
        self.google.server_metadata.update({
            "issuer": "https://accounts.google.com",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "id_token_signing_alg_values_supported": ["RS256"],
            "jwks": {"keys": [self.key.as_dict(private=False)]},
            "_loaded_at": time.time(),
        })

    def make_app(self, **overrides):
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            return create_app({
                "TESTING": True,
                "SECRET_KEY": "google-auth-test-secret",
                "DATABASE": str(self.db_path),
                "UPLOAD_FOLDER": str(Path(self.tmp.name) / "uploads"),
                "GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "GOOGLE_REDIRECT_URI": "https://pelagia.example/auth/google/callback",
                "SESSION_COOKIE_SECURE": False,
                **overrides,
            })

    def test_public_landing_seo_and_google_only_screens(self):
        from xml.etree import ElementTree
        app = self.make_app(PUBLIC_BASE_URL="https://pelagia.example")
        client = app.test_client()
        landing = client.get("/").get_data(as_text=True)
        self.assertIn('<h1 id="welcomeTitle">Pelagia</h1>', landing)
        self.assertIn('rel="canonical" href="https://pelagia.example/"', landing)
        self.assertIn('<title>Pelagia Dive Log — Scuba Logbook & Dive Buddies</title>', landing)
        self.assertIn('Record your scuba dives, track depth and bottom time', landing)
        self.assertIn('<span data-nosnippet>Log in</span>', landing)
        self.assertIn('<div class="welcome-actions" data-nosnippet>', landing)
        self.assertIn('application/ld+json', landing)
        self.assertNotIn('data-pwa-guide', landing)
        self.assertNotIn('name="username"', landing)
        for path in ("/login", "/signup"):
            page = client.get(path + "?next=/dive/42").get_data(as_text=True)
            self.assertIn('Continue with Google', page)
            self.assertIn('/auth/google/login?next=/dive/42', page)
            self.assertIn('noindex, follow', page)
            self.assertNotIn('type="password"', page)
            self.assertNotIn('name="username"', page)
        root = ElementTree.fromstring(client.get("/sitemap.xml").data)
        locations = [node.text for node in root.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        self.assertEqual(locations, ['https://pelagia.example/', 'https://pelagia.example/terms', 'https://pelagia.example/privacy'])
        robots = client.get('/robots.txt').data
        self.assertIn(b'Sitemap: https://pelagia.example/sitemap.xml', robots)
        self.assertNotIn(b'Disallow: /login', robots)
        self.assertNotIn(b'Disallow: /signup', robots)
        self.assertIn(b'Disallow: /auth/', robots)

    def test_google_redirect_rejects_external_destinations(self):
        for destination in ('https://evil.example', '//evil.example', '/\\evil.example', 'http://localhost//evil.example'):
            client = self.app.test_client()
            response = client.get('/auth/google/login', query_string={'next': destination})
            self.assertEqual(response.status_code, 302)
            with client.session_transaction() as session:
                self.assertEqual(session['google_flow']['next'], '/home')

    def test_shared_dive_destination_survives_google_signup(self):
        response = self.client.get("/auth/google/login?next=/dive/42")
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(self.callback(params).location, "/auth/google/signup")
        response = self.complete_signup("shared-diver")
        self.assertEqual(response.location, "/dive/42")

    def test_shared_dive_destination_survives_existing_google_login(self):
        with self.app.app_context():
            database.get_db().execute("INSERT INTO users (username, google_subject) VALUES ('returning-diver', 'google-123')")
            database.get_db().commit()
        response = self.client.get("/auth/google/login?next=/dive/42")
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(self.callback(params).location, "/dive/42")

    def test_shared_site_destination_survives_google_signup(self):
        response = self.client.get("/auth/google/login?next=/dive-sites/42")
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(self.callback(params).location, "/auth/google/signup")
        self.assertEqual(self.complete_signup("site-diver").location, "/dive-sites/42")

    def test_shared_center_destination_survives_google_signup(self):
        response = self.client.get("/auth/google/login?next=/dive-centers/42")
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(self.callback(params).location, "/auth/google/signup")
        self.assertEqual(self.complete_signup("center-diver").location, "/dive-centers/42")

    def test_shared_center_destination_survives_existing_google_login(self):
        with self.app.app_context():
            database.get_db().execute("INSERT INTO users (username, google_subject) VALUES ('center-diver', 'google-123')")
            database.get_db().commit()
        response = self.client.get("/auth/google/login?next=/dive-centers/42")
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(self.callback(params).location, "/dive-centers/42")

    def start(self):
        response = self.client.get("/auth/google/login")
        self.assertIsNone(self.client.get_cookie("session").expires)
        self.assertEqual(response.status_code, 302)
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(params["redirect_uri"], ["https://pelagia.example/auth/google/callback"])
        self.assertEqual(params["scope"], ["openid email"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertTrue(params["nonce"][0])
        self.assertTrue(params["code_challenge"][0])
        return params

    def callback(self, params, subject="google-123", signing_key=None, **claims):
        encoded = jwt.encode({"alg": "RS256", "kid": self.key.kid}, {
            "iss": "https://accounts.google.com", "sub": subject,
            "aud": "test-client.apps.googleusercontent.com",
            "exp": int(time.time()) + 600, "iat": int(time.time()),
            "nonce": params["nonce"][0], "email": "diver@example.com", "email_verified": True,
            **claims,
        }, signing_key or self.key)
        with patch.object(self.google, "fetch_access_token", return_value={"access_token": "private-access-token", "id_token": encoded}) as exchange:
            response = self.client.get("/auth/google/callback", query_string={"state": params["state"][0], "code": "test-code"})
        if exchange.called:
            self.assertTrue(exchange.call_args.kwargs["code_verifier"])
        return response

    def complete_signup(self, username):
        self.client.get("/auth/google/signup")
        with self.client.session_transaction() as session:
            csrf = session["google_csrf"]
        return self.client.post("/auth/google/signup", data={"username": username, "csrf_token": csrf})

    def seed_account(self, username="existing"):
        with self.app.app_context():
            db = database.get_db()
            user_id = db.execute("INSERT INTO users (username, google_subject) VALUES (?, ?)", (username, "seed-" + username)).lastrowid
            db.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session.permanent = True
        return user_id

    def request_at(self, timestamp, path, method="GET", client=None, **kwargs):
        with patch("time.time", return_value=timestamp), patch("flask.sessions.datetime") as clock:
            clock.now.return_value = datetime.fromtimestamp(timestamp, timezone.utc)
            return (client or self.client).open(path, method=method, **kwargs)

    def test_activity_renews_session_and_inactivity_expires_it(self):
        started_at = 1800000000
        day = 24 * 60 * 60
        with patch("time.time", return_value=started_at):
            self.seed_account("returning-diver")
        for days_since_login in (29, 31):
            with self.subTest(days_since_login=days_since_login):
                response = self.request_at(started_at + days_since_login * day, "/api/dives/mine")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.client.get_cookie("session").expires,
                                 datetime.fromtimestamp(started_at + (days_since_login + 30) * day, timezone.utc))
        response = self.request_at(started_at + 62 * day, "/api/dives/mine")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")

    def test_persistent_session_survives_restart_and_logout_clears_it(self):
        self.seed_account("persistent-diver")
        cookie = self.client.get_cookie("session")
        restarted_client = self.make_app().test_client()
        restarted_client.set_cookie(cookie.key, cookie.value)
        self.assertEqual(restarted_client.get("/api/dives/mine").status_code, 200)
        restarted_client.post("/logout")
        self.assertIsNone(restarted_client.get_cookie("session"))
        self.assertEqual(restarted_client.get("/api/dives/mine").status_code, 302)

    def test_google_only_and_missing_configuration(self):
        app = self.make_app(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
        client = app.test_client()
        self.assertIn(b"temporarily unavailable", client.get("/login").data)
        for path in ("/login", "/signup"):
            self.assertEqual(client.post(path, data={"username": "old-login", "password": "password"}).status_code, 405)
        self.assertEqual(client.post("/auth/google/link").status_code, 404)
        with client.session_transaction() as session:
            self.assertNotIn("user_id", session)
        self.assertIn(b"Continue with Google", self.client.get("/login").data)

    def test_new_account_onboarding_and_repeat_login(self):
        params = self.start()
        response = self.callback(params)
        self.assertEqual(response.location, "/auth/google/signup")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        page = self.client.get(response.location)
        self.assertIn(b"Choose your username", page.data)
        self.assertNotIn(b"diver@example.com", page.data)
        self.assertEqual(self.complete_signup("new-diver").location, "/home")
        self.assertIsNotNone(self.client.get_cookie("session").expires)
        with self.client.session_transaction() as session:
            user_id = session["user_id"]
            self.assertEqual(dict(session), {"user_id": user_id, "_permanent": True})
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT username, google_subject FROM users").fetchone(), ("new-diver", "google-123"))
        self.assertNotIn(b"Google sign-in linked", self.client.get("/you").data)
        self.client.post("/logout")
        for password in ("", "password"):
            self.client.post("/login", data={"username": "new-diver", "password": password})
            with self.client.session_transaction() as session:
                self.assertNotIn("user_id", session)
        self.assertEqual(self.callback(self.start(), email="new-address@example.com").location, "/home")
        self.assertIsNotNone(self.client.get_cookie("session").expires)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user_id)
            self.assertTrue(session.permanent)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*), google_email FROM users").fetchone(), (1, "new-address@example.com"))

    def test_username_collision_and_csrf(self):
        self.seed_account("Taken")
        self.assertEqual(self.client.post("/auth/google/link").status_code, 404)
        self.client.post("/logout")
        self.callback(self.start())
        self.assertEqual(self.client.post("/auth/google/signup", data={"username": "diver"}).status_code, 400)
        for username in ("taken", "ab", "x" * 41):
            self.assertEqual(self.complete_signup(username).status_code, 200)
            with self.client.session_transaction() as session:
                self.assertNotIn("user_id", session)
        self.assertEqual(self.complete_signup("available").location, "/home")

    def test_bad_state_expired_flow_and_logout_reject_callback(self):
        for kind in ("bad-state", "expired", "logout", "missing-provider-state"):
            with self.subTest(kind=kind):
                params = self.start()
                if kind == "bad-state":
                    params["state"] = [secrets.token_urlsafe(32)]
                elif kind == "expired":
                    with self.client.session_transaction() as session:
                        flow = dict(session["google_flow"])
                        flow["started_at"] -= 601
                        session["google_flow"] = flow
                elif kind == "logout":
                    self.client.post("/logout")
                else:
                    with self.client.session_transaction() as session:
                        session.pop("_state_google_" + params["state"][0])
                self.assertEqual(self.callback(params).location, "/")
                with self.client.session_transaction() as session:
                    self.assertNotIn("user_id", session)
                    self.assertNotIn("google_pending", session)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_invalid_tokens_and_unverified_identities_are_rejected(self):
        other_key = RSAKey.generate_key(2048)
        cases = (
            {"nonce": "wrong"}, {"iss": "https://attacker.example"}, {"aud": "wrong-client"},
            {"exp": int(time.time()) - 300}, {"signing_key": other_key},
            {"email_verified": False}, {"email": ""}, {"subject": ""},
        )
        for claims in cases:
            with self.subTest(claims=claims):
                self.assertEqual(self.callback(self.start(), **claims).location, "/")
                with self.client.session_transaction() as session:
                    self.assertNotIn("google_pending", session)
                    self.assertNotIn("user_id", session)

    def test_provider_cancellation_network_failure_and_replay(self):
        params = self.start()
        response = self.client.get("/auth/google/callback", query_string={"state": params["state"][0], "error": "access_denied"})
        self.assertEqual(response.location, "/")
        self.assertEqual(self.callback(params).location, "/")
        with patch.object(self.google, "load_server_metadata", side_effect=Timeout):
            self.assertEqual(self.client.get("/auth/google/login").location, "/")
        params = self.start()
        with patch.object(self.google, "fetch_access_token", side_effect=Timeout):
            response = self.client.get("/auth/google/callback", query_string={"state": params["state"][0], "code": "test-code"})
        self.assertEqual(response.location, "/")
        self.assertEqual(self.callback(self.start()).location, "/auth/google/signup")
        with self.client.session_transaction() as session:
            pending = dict(session["google_pending"])
            pending["started_at"] -= 601
            session["google_pending"] = pending
        self.assertEqual(self.client.get("/auth/google/signup").location, "/")

    def test_unsigned_userinfo_without_id_token_is_rejected(self):
        params = self.start()
        with patch.object(self.google, "fetch_access_token", return_value={
            "access_token": "access-token", "userinfo": {"sub": "fake", "email": "fake@example.com", "email_verified": True}
        }):
            response = self.client.get("/auth/google/callback", query_string={"state": params["state"][0], "code": "test-code"})
        self.assertEqual(response.location, "/")
        with self.client.session_transaction() as session:
            self.assertNotIn("google_pending", session)
            self.assertNotIn("user_id", session)

    def test_callback_cannot_continue_in_another_users_session(self):
        params = self.start()
        with self.client.session_transaction() as session:
            session["user_id"] = 999
        self.assertEqual(self.callback(params).location, "/")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_concurrent_onboarding_uses_one_identity_and_does_not_expose_email(self):
        self.callback(self.start())
        with sqlite3.connect(self.db_path) as conn:
            user_id = conn.execute("INSERT INTO users (username, google_subject, google_email) VALUES ('other-tab', 'google-123', 'diver@example.com')").lastrowid
        self.assertEqual(self.complete_signup("new-name").location, "/home")
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user_id)
        for path in ("/you", f"/users/{user_id}", "/api/users?q=other", "/api/search?q=other"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"diver@example.com", response.data)
            self.assertNotIn(b"google-123", response.data)

    def test_legacy_database_migration_is_repeatable(self):
        legacy = Path(self.tmp.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, profile_photo TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("legacy", "retired-hash"))
            conn.executescript(Path("pelagia/schema.sql").read_text())
            conn.execute("INSERT INTO dives (user_id, date, site_name, depth_m, duration_min) VALUES (1, '2026-10-16', 'Legacy reef', 18, 45)")
        app = self.make_app(DATABASE=str(legacy))
        with app.app_context():
            database.init_db()
            database.init_db()
            db = database.get_db()
            self.assertEqual(tuple(db.execute("SELECT id, username, google_subject FROM users").fetchone()), (1, "legacy", None))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertNotIn("password_hash", {row["name"] for row in db.execute("PRAGMA table_info(users)")})
            self.assertEqual(tuple(db.execute("SELECT user_id, site_name FROM dives").fetchone()), (1, "Legacy reef"))
            db.execute("UPDATE users SET google_subject = 'unique-id' WHERE id = 1")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO users (username, google_subject) VALUES ('other', 'unique-id')")
        client = app.test_client()
        client.post("/login", data={"username": "legacy", "password": "password"})
        with client.session_transaction() as session:
            self.assertNotIn("user_id", session)


if __name__ == "__main__":
    unittest.main()
