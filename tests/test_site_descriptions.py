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
        self.app.config["FORCE_DIVE_SITE_DESCRIPTION_REGENERATION"] = False
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
            self.assertEqual(data["fragments"], [{"text": "A rocky reef reaches 25 m and is accessed by boat."}])
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
            self.assertIn("Coordinates are provided only to identify", body["instructions"])
            self.assertIn("geographic setting, accessibility and shore/boat", body["instructions"])
            self.assertIn("do not force every category", body["instructions"])
            self.assertIn("URLs, links, source names, citations", body["instructions"])
            self.assertEqual(post.call_args.kwargs["timeout"], (3, 20))
            self.assertFalse(post.call_args.kwargs["allow_redirects"])
            html = self.client.get("/dive-sites/1").data
            self.assertIn(b"rocky reef", html)
            self.assertNotIn(b'href="https://operator.example/alert-rock"', html)
            self.assertNotIn(b'Alert Rock &amp; diving', html)
            self.assertNotIn(b"data-site-description", html)
            self.assertLess(html.index(b"Alaska</p>"), html.index(b"rocky reef"))
            self.assertNotIn(b"test-server-secret", html)
            self.assertEqual(self.post().get_json(), data)
            self.assertEqual(post.call_count, 1)
        result.close.assert_called_once()
        with self.connect() as db:
            row = db.execute("SELECT * FROM dive_site_descriptions").fetchone()
            self.assertEqual(row["model"], descriptions.MODEL)
            self.assertEqual(json.loads(row["citations_json"]), [{
                "url": "https://operator.example/alert-rock", "title": "Alert Rock & diving",
            }])
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

    def test_temporary_force_regeneration_overwrites_cached_description(self):
        with patch.object(descriptions.requests, "post", return_value=upstream()):
            self.assertEqual(self.post().status_code, 200)

        self.app.config["FORCE_DIVE_SITE_DESCRIPTION_REGENERATION"] = True
        page = self.client.get("/dive-sites/1")
        self.assertIn(b'data-site-description data-description-url=', page.data)
        self.assertNotIn(b"A rocky reef reaches", page.data)

        replacement = response_payload("A wall dive reaches 30 m and has moderate current. [source]")
        with patch.object(descriptions.requests, "post", return_value=upstream(replacement)) as post:
            response = self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["description"],
                             "A wall dive reaches 30 m and has moderate current.")
            post.assert_called_once()
        with self.connect() as db:
            self.assertEqual(
                db.execute("SELECT description FROM dive_site_descriptions WHERE dive_site_id = 1").fetchone()[0],
                "A wall dive reaches 30 m and has moderate current.",
            )

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

    def test_public_preview_generates_once_and_reuses_cache_even_with_force_enabled(self):
        guest = self.app.test_client()
        endpoint = "/api/explore/dive-sites/1/description"
        for path in ("/explore/dive-sites/1", "/share/dive-site/1"):
            self.assertIn(endpoint.encode(), guest.get(path).data)
        with patch.object(descriptions.requests, "post", return_value=upstream()) as post:
            response = guest.post(endpoint, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertIn("rocky reef", response.json["description"])
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(post.call_args.kwargs["json"]["model"], descriptions.MODEL)
            self.app.config["FORCE_DIVE_SITE_DESCRIPTION_REGENERATION"] = True
            self.assertEqual(guest.post(endpoint, headers=self.headers).json, response.json)
            for path in ("/explore/dive-sites/1", "/share/dive-site/1"):
                html = guest.get(path).data
                self.assertIn(b"rocky reef", html)
                self.assertNotIn(b"data-description-url", html)
                self.assertIn(b"Create your free account", html)
            post.assert_called_once()

    def test_public_description_validates_requests_and_reuses_pending_and_failure_states(self):
        guest = self.app.test_client()
        endpoint = "/api/explore/dive-sites/1/description"
        with patch.object(descriptions.requests, "post") as post:
            self.assertEqual(guest.post(endpoint).status_code, 403)
            self.assertEqual(guest.get(endpoint).status_code, 405)
            self.assertEqual(guest.post("/api/explore/dive-sites/999/description", headers=self.headers).status_code, 404)
            with self.app.app_context():
                descriptions.claim_generation(database.get_db(), 1)
            self.assertEqual(guest.post(endpoint, headers=self.headers).status_code, 202)
            post.assert_not_called()
        with self.app.app_context():
            database.get_db().execute("DELETE FROM dive_site_description_attempts")
            database.get_db().commit()
        with patch.object(descriptions.requests, "post", side_effect=requests.Timeout()) as post:
            self.assertEqual(guest.post(endpoint, headers=self.headers).status_code, 503)
            self.assertEqual(guest.post(endpoint, headers=self.headers).status_code, 503)
            post.assert_called_once()

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

    def test_unusable_output_cannot_become_a_permanent_result(self):
        for payload in ({"status": "completed", "output": []}, response_payload("  "),
                        {"status": "incomplete", "output": []}):
            with self.subTest(payload=payload), self.assertRaises(descriptions.GenerationError):
                descriptions.parse_response(payload)

    def test_citation_errors_do_not_discard_description(self):
        base = response_payload()
        for patch_data in ({"url": "javascript:alert(1)"}, {"url": "https://user:pass@example.com"},
                           {"url": "https://example.com\ninvalid"}, {"start_index": -1}, {"end_index": 100000}):
            bad = copy.deepcopy(base)
            bad["output"][1]["content"][0]["annotations"][0].update(patch_data)
            with self.subTest(patch_data=patch_data):
                description, citations = descriptions.parse_response(bad)
                self.assertIn("A rocky reef", description)
                self.assertEqual(citations, [])

    def test_text_is_accepted_without_web_action_or_format_limits(self):
        text = " ".join(["reef"] * 71) + ". A wall. A wreck.\nMore details."
        payload = response_payload(text)
        payload["output"].pop(0)
        self.assertEqual(descriptions.parse_response(payload), (text, []))

    def test_multiple_output_parts_keep_citation_offsets(self):
        payload = response_payload("  First detail.")
        second = response_payload("Second detail. [source]")["output"][1]["content"][0]
        payload["output"][1]["content"].append(second)
        description, citations = descriptions.parse_response(payload)
        self.assertEqual(description, "First detail.\nSecond detail.")
        self.assertEqual(citations[0]["url"], "https://operator.example/alert-rock")

    def test_summary_without_citations_is_valid(self):
        description, citations = descriptions.parse_response(response_payload("A reef reaches 25 m by boat."))
        self.assertEqual(description, "A reef reaches 25 m by boat.")
        self.assertEqual(citations, [])

    def test_completed_page_open_is_valid_web_research(self):
        payload = response_payload("Boat trips and equipment rental are available.")
        payload["output"][0]["action"] = {"type": "open_page", "url": "https://example.com/"}
        self.assertEqual(descriptions.parse_response(payload),
                         ("Boat trips and equipment rental are available.", []))
        payload["output"][0]["status"] = "in_progress"
        self.assertEqual(descriptions.parse_response(payload),
                         ("Boat trips and equipment rental are available.", []))

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
