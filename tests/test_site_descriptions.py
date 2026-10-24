import copy
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import test_reference_autocomplete as fixtures
from pelagia import db as database, site_descriptions as descriptions
from pelagia.importer import import_reference_data


def response_payload(text="A rocky reef reaches 25 m and is accessed by boat. [source]"):
    start = text.find("[source]")
    citations = [] if start == -1 else [{
        "type": "url_citation", "start_index": start, "end_index": start + 8,
        "url": "https://operator.example/alert-rock", "title": "Alert Rock & diving",
    }]
    return {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed", "action": {"type": "search"}},
        {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": citations}]},
    ]}


def upstream(payload=None):
    result = Mock()
    result.json.return_value = payload if payload is not None else response_payload()
    return result


class SiteDescriptionTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, self.db_path, self.config_path = self.make_app(Path(self.directory.name))
        self.app.config["OPENAI_API_KEY"] = "test-server-secret"
        self.client = self.app.test_client()
        self.signup(self.client)
        self.headers = {"X-Requested-With": "fetch"}
        self.url = "/api/dive-sites/1/description"

    def post(self, site_id=1):
        return self.client.post(f"/api/dive-sites/{site_id}/description", headers=self.headers)

    def connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def test_initially_empty_and_upgrade_is_idempotent(self):
        with self.app.app_context():
            db = database.get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_descriptions").fetchone()[0], 0)
            db.execute("DROP TABLE dive_site_descriptions")
            db.execute("DROP TABLE dive_site_description_attempts")
            db.commit()
            database.init_db()
            database.init_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_descriptions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_sites").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT username FROM users").fetchone()[0], "tester")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO dive_site_descriptions (dive_site_id, model) VALUES (999, 'test')")

    def test_cold_request_saves_then_warm_page_and_api_do_not_generate(self):
        cold = self.client.get("/dive-sites/1").data
        self.assertIn(b'data-site-description data-description-url=', cold)
        result = upstream()

        def call(*args, **kwargs):
            # A different connection can take the SQLite write lock during HTTP work.
            with self.connect() as other:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            return result

        with patch.object(descriptions.requests, "post", side_effect=call) as post:
            response = self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            data = response.get_json()
            self.assertEqual(data["status"], "complete")
            self.assertIn("rocky reef", data["description"])
            self.assertEqual(data["fragments"][1]["text"], "[1]")
            body = post.call_args.kwargs["json"]
            self.assertEqual(body["model"], "gpt-5.6-luna")
            self.assertEqual(body["tools"], [{"type": "web_search", "search_context_size": "low"}])
            self.assertEqual(body["tool_choice"], "required")
            self.assertEqual(body["max_tool_calls"], 1)
            self.assertEqual(body["reasoning"], {"effort": "low"})
            self.assertEqual(body["max_output_tokens"], 1000)
            self.assertFalse(body["store"])
            for value in ("Alert Rock", "Alaska", '"US"', "54.1", "-132.9"):
                self.assertIn(value, body["input"])
            self.assertIn("BOTH its name AND geographic location", body["instructions"])
            self.assertEqual(post.call_args.kwargs["timeout"], (3, 20))
            self.assertFalse(post.call_args.kwargs["allow_redirects"])
            html = self.client.get("/dive-sites/1").data
            self.assertIn(b"rocky reef", html)
            self.assertIn(b'href="https://operator.example/alert-rock"', html)
            self.assertIn(b'Alert Rock &amp; diving', html)
            self.assertNotIn(b"data-site-description", html)
            self.assertLess(html.index(b"Alaska</p>"), html.index(b"rocky reef"))
            self.assertNotIn(b"test-server-secret", html)
            self.assertEqual(self.post().get_json(), data)
            self.assertEqual(post.call_count, 1)
        result.close.assert_called_once()
        with self.connect() as db:
            row = db.execute("SELECT * FROM dive_site_descriptions").fetchone()
            self.assertEqual(row["model"], descriptions.MODEL)
            self.assertTrue(row["created_at"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_description_attempts").fetchone()[0], 0)

    def test_completed_no_match_is_permanent_null_and_renders_nothing(self):
        with patch.object(descriptions.requests, "post", return_value=upstream(response_payload(descriptions.NO_DESCRIPTION))) as post:
            result = self.post()
            self.assertEqual(result.status_code, 200)
            self.assertIsNone(result.get_json()["description"])
            self.assertEqual(result.get_json()["fragments"], [])
            self.assertEqual(self.post().status_code, 200)
            self.assertEqual(post.call_count, 1)
        html = self.client.get("/dive-sites/1").data
        self.assertNotIn(b"site-description", html)
        self.assertNotIn(b"Description unavailable", html)
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT description FROM dive_site_descriptions").fetchone()[0])
        # Reference refreshes preserve IDs and both positive/negative cached results.
        import_reference_data(self.db_path, self.app.config["PELAGIA_LOCAL_CONFIG"], self.config_path)
        with patch.object(descriptions.requests, "post") as post:
            self.assertIsNone(self.post().get_json()["description"])
            post.assert_not_called()

    def test_temporary_failures_have_cooldown_then_can_succeed(self):
        now = time.time()
        with patch.object(descriptions.time, "time", return_value=now), patch.object(
            descriptions.requests, "post", side_effect=requests.Timeout("secret must not be logged")
        ) as post:
            with self.assertLogs(self.app.logger, level="WARNING") as logs:
                self.assertEqual(self.post().status_code, 503)
            self.assertNotIn("secret must not be logged", " ".join(logs.output))
            self.assertEqual(self.post().status_code, 503)
            self.assertEqual(post.call_count, 1)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_descriptions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT retry_after FROM dive_site_description_attempts").fetchone()[0], now + 300)
        with patch.object(descriptions.time, "time", return_value=now + 301), patch.object(
            descriptions.requests, "post", return_value=upstream()
        ) as post:
            self.assertEqual(self.post().status_code, 200)
            post.assert_called_once()

    def test_missing_credentials_never_call_openai_or_store_null(self):
        self.app.config["OPENAI_API_KEY"] = ""
        with patch.object(descriptions.requests, "post") as post:
            self.assertEqual(self.post().status_code, 503)
            self.assertEqual(self.post().status_code, 503)
            post.assert_not_called()
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_descriptions").fetchone()[0], 0)

    def test_upstream_auth_rate_limit_bad_json_and_incomplete_output_are_retryable(self):
        for failure in (requests.HTTPError("401"), requests.HTTPError("429"), ValueError("bad JSON"),
                        {"status": "incomplete", "output": []}, {"status": "completed", "output": None}):
            with self.subTest(failure=str(failure)), self.connect() as db:
                db.execute("DELETE FROM dive_site_description_attempts")
                db.commit()
                result = upstream(failure if isinstance(failure, dict) else None)
                if isinstance(failure, requests.HTTPError):
                    result.raise_for_status.side_effect = failure
                elif isinstance(failure, Exception):
                    result.json.side_effect = failure
                with patch.object(descriptions.requests, "post", return_value=result) as post:
                    self.assertEqual(self.post().status_code, 503)
                    self.assertEqual(post.call_count, 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_descriptions").fetchone()[0], 0)
                result.close.assert_called_once()

    def test_authenticated_same_origin_requests_and_unknown_sites(self):
        with patch.object(descriptions.requests, "post") as post:
            guest = self.app.test_client().post(self.url, headers=self.headers)
            self.assertEqual(guest.status_code, 302)
            self.assertEqual(guest.headers["Cache-Control"], "no-store")
            self.assertEqual(self.client.post(self.url).status_code, 403)
            self.assertEqual(self.post(999).status_code, 404)
            self.assertEqual(self.post(999).headers["Cache-Control"], "no-store")
            self.assertEqual(self.client.get(self.url).status_code, 405)
            post.assert_not_called()

    def test_multiple_connections_claim_only_one_generation_and_api_returns_pending(self):
        barrier = threading.Barrier(2)

        def claim():
            with self.connect() as db:
                barrier.wait()
                return descriptions.claim_generation(db, 1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sorted(result[0] for result in results), ["claimed", "pending"])
        with patch.object(descriptions.requests, "post") as post:
            response = self.post()
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.headers["Retry-After"], "2")
            post.assert_not_called()

    def test_expired_claims_can_be_reclaimed_and_stale_workers_cannot_write(self):
        with self.connect() as db:
            with patch.object(descriptions.time, "time", return_value=1000):
                _, old_token = descriptions.claim_generation(db, 1)
            with patch.object(descriptions.time, "time", return_value=1061):
                _, new_token = descriptions.claim_generation(db, 1)
                self.assertNotEqual(old_token, new_token)
                self.assertFalse(descriptions.save_result(db, 1, old_token, None, []))
                descriptions.record_failure(db, 1, old_token)
                self.assertEqual(db.execute("SELECT token FROM dive_site_description_attempts").fetchone()[0], new_token)
                self.assertTrue(descriptions.save_result(db, 1, new_token, None, []))
                self.assertEqual(descriptions.claim_generation(db, 1), ("complete", None))
            with patch.object(descriptions.time, "time", return_value=2000):
                _, token = descriptions.claim_generation(db, 2)
            with patch.object(descriptions.time, "time", return_value=2061):
                self.assertFalse(descriptions.save_result(db, 2, token, None, []))
                self.assertIsNone(descriptions.read_cache(2, db))

    def test_same_names_in_different_locations_have_separate_cache_entries(self):
        with self.connect() as db:
            db.execute("INSERT INTO dive_sites (id, name, country_or_area, country_code) VALUES (4, 'Alert Rock', 'Mexico', 'MX')")
        with patch.object(descriptions.requests, "post", return_value=upstream()) as post:
            self.assertEqual(self.post().status_code, 200)
            self.assertEqual(self.post(4).status_code, 200)
            self.assertIn("Alaska", post.call_args_list[0].kwargs["json"]["input"])
            self.assertIn("Mexico", post.call_args_list[1].kwargs["json"]["input"])
            self.assertIn('"latitude": null', post.call_args_list[1].kwargs["json"]["input"])
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dive_site_descriptions").fetchone()[0], 2)

    def test_unverified_or_malformed_output_cannot_become_permanent_results(self):
        base = response_payload()
        cases = []
        no_search = response_payload(descriptions.NO_DESCRIPTION)
        no_search["output"].pop(0)
        cases.append(no_search)
        for patch_data in ({"url": "javascript:alert(1)"}, {"url": "https://user:pass@example.com"},
                           {"url": "https://example.com\ninvalid"}, {"start_index": -1}, {"end_index": 100000}):
            bad = copy.deepcopy(base)
            bad["output"][1]["content"][0]["annotations"][0].update(patch_data)
            cases.append(bad)
        cases.extend([response_payload("No citation."), response_payload(" ".join(["reef"] * 71) + " [source]"),
                      response_payload("A reef. A wall. A wreck. [source]"),
                      response_payload("A reef.\nA wall. [source]"), {"status": "completed", "output": []}])
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(descriptions.GenerationError):
                descriptions.parse_response(payload)

    def test_generated_text_and_titles_are_escaped_in_server_rendering(self):
        payload = response_payload('A reef with <script>alert("x")</script> & rocks. [source]')
        payload["output"][1]["content"][0]["annotations"][0]["title"] = '"><img src=x onerror=alert(1)>'
        with patch.object(descriptions.requests, "post", return_value=upstream(payload)):
            self.assertEqual(self.post().status_code, 200)
        html = self.client.get("/dive-sites/1").data
        self.assertIn(b"&lt;script&gt;", html)
        self.assertNotIn(b'<script>alert("x")', html)
        self.assertNotIn(b'<img src=x onerror=', html)


if __name__ == "__main__":
    unittest.main()
