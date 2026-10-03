import secrets
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey
from requests.exceptions import Timeout
from werkzeug.security import generate_password_hash

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

    def start(self, link=False):
        if link:
            self.client.get("/you")
            with self.client.session_transaction() as session:
                csrf = session["google_csrf"]
            response = self.client.post("/auth/google/link", data={"csrf_token": csrf})
        else:
            response = self.client.get("/auth/google/login")
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

    def password_signup(self, username="existing"):
        self.client.post("/signup", data={"username": username, "password": "password"})
        with self.client.session_transaction() as session:
            return session["user_id"]

    def test_optional_feature_and_password_login(self):
        app = self.make_app(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
        client = app.test_client()
        self.assertNotIn(b"Continue with Google", client.get("/").data)
        for route in ("login", "callback", "signup"):
            self.assertEqual(client.get(f"/auth/google/{route}").status_code, 404)
        self.assertEqual(client.post("/auth/google/link").status_code, 404)
        client.post("/signup", data={"username": "old-login", "password": "password"})
        client.post("/logout")
        client.post("/login", data={"username": "old-login", "password": "password"})
        with client.session_transaction() as session:
            self.assertTrue(session.get("user_id"))
        self.assertIn(b"Continue with Google", self.client.get("/").data)

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
        with self.client.session_transaction() as session:
            user_id = session["user_id"]
            self.assertEqual(dict(session), {"user_id": user_id})
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT username, password_hash, google_subject FROM users").fetchone(), ("new-diver", "", "google-123"))
        self.assertIn(b"Google sign-in linked", self.client.get("/you").data)
        self.client.post("/logout")
        for password in ("", "password"):
            self.client.post("/login", data={"username": "new-diver", "password": password})
            with self.client.session_transaction() as session:
                self.assertNotIn("user_id", session)
        self.assertEqual(self.callback(self.start(), email="new-address@example.com").location, "/home")
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user_id)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*), google_email FROM users").fetchone(), (1, "new-address@example.com"))

    def test_link_existing_account_preserves_password_and_dives(self):
        user_id = self.password_signup()
        self.client.post("/dive/new", data={"site_name": "Test reef", "depth_m": "15", "duration_min": "40"})
        self.assertEqual(self.callback(self.start(link=True)).location, "/you")
        with sqlite3.connect(self.db_path) as conn:
            self.assertTrue(conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()[0])
            self.assertEqual(conn.execute("SELECT user_id FROM dives").fetchone()[0], user_id)
        self.client.post("/logout")
        self.assertEqual(self.callback(self.start()).location, "/home")
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user_id)
        self.client.post("/logout")
        self.client.post("/login", data={"username": "existing", "password": "password"})
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user_id)
        self.assertEqual(len(self.client.get("/api/dives/mine").get_json()), 1)

    def test_link_conflicts_do_not_merge_or_switch_accounts(self):
        first = self.password_signup("first")
        self.callback(self.start(link=True))
        # Cannot replace a linked identity.
        self.callback(self.start(link=True), subject="different-google")
        self.client.post("/logout")
        second = self.password_signup("second")
        self.callback(self.start(link=True))
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], second)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT id, google_subject FROM users ORDER BY id").fetchall()
            self.assertEqual(rows, [(first, "google-123"), (second, None)])

    def test_username_collision_and_csrf(self):
        self.password_signup("Taken")
        self.assertEqual(self.client.post("/auth/google/link").status_code, 400)
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

    def test_link_cannot_continue_in_another_users_session(self):
        self.password_signup("first")
        params = self.start(link=True)
        with self.client.session_transaction() as session:
            session["user_id"] = 999
        self.assertEqual(self.callback(params).location, "/")
        with sqlite3.connect(self.db_path) as conn:
            self.assertIsNone(conn.execute("SELECT google_subject FROM users").fetchone()[0])

    def test_concurrent_onboarding_uses_one_identity_and_does_not_expose_email(self):
        self.callback(self.start())
        with sqlite3.connect(self.db_path) as conn:
            user_id = conn.execute("INSERT INTO users (username, password_hash, google_subject, google_email) VALUES ('other-tab', '', 'google-123', 'diver@example.com')").lastrowid
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
            conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("legacy", generate_password_hash("password")))
        app = self.make_app(DATABASE=str(legacy))
        with app.app_context():
            database.init_db()
            database.init_db()
            db = database.get_db()
            self.assertEqual(tuple(db.execute("SELECT id, username, google_subject FROM users").fetchone()), (1, "legacy", None))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            db.execute("UPDATE users SET google_subject = 'unique-id' WHERE id = 1")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO users (username, password_hash, google_subject) VALUES ('other', '', 'unique-id')")
        client = app.test_client()
        client.post("/login", data={"username": "legacy", "password": "password"})
        with client.session_transaction() as session:
            self.assertEqual(session["user_id"], 1)


if __name__ == "__main__":
    unittest.main()
