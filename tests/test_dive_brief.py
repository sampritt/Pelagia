import tempfile
import unittest
import hashlib
import io
import os
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import dive_brief


SAMPLE = Path(__file__).resolve().parents[1] / "data/dive_briefs/the_dive_brief_2026-09-04.md"


class DiveBriefTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.app, _, _ = self.make_app(self.root)
        self.app.config.update(DIVE_BRIEF_DIR=str(self.root / "briefs"))
        self.api_key = "pdb_test_only_upload_key_0123456789"
        self.app.config["DIVE_BRIEF_API_KEY_SHA256"] = hashlib.sha256(self.api_key.encode()).hexdigest()
        self.headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "text/markdown"}
        self.client = self.app.test_client()
        self.signup(self.client)
        self.clock = patch("pelagia.dive_brief.effective_date", return_value=date(2026, 10, 22))
        self.edition_clock = self.clock.start()
        self.addCleanup(self.clock.stop)

    def write_edition(self, edition, body="## OCEAN SCIENCE\n\n### A healthy ocean\n\nThe story."):
        folder = Path(self.app.config["DIVE_BRIEF_DIR"])
        folder.mkdir(exist_ok=True)
        path = folder / f"the_dive_brief_{edition.isoformat()}.md"
        path.write_text(f"# The Dive Brief\n\n**{edition.strftime('%A, %B %d, %Y')}**\n\n**Today's ocean headlines.**\n\n---\n\n{body}")
        return path

    def payload(self, edition=date(2026, 10, 22), body="The new story."):
        return (f"# The Dive Brief\n\n**{edition.strftime('%A, %B %d, %Y')}**\n\n"
                f"**Today's ocean headlines.**\n\n---\n\n## OCEAN SCIENCE\n\n### The ocean\n\n{body}").encode()

    def test_card_requires_exact_edition_on_disk_and_renders_the_sample_format(self):
        self.edition_clock.return_value = date(2026, 9, 4)
        self.assertNotIn(b'class="brief-card"', self.client.get("/home").data)
        path = self.write_edition(date(2026, 9, 4))
        path.write_bytes(SAMPLE.read_bytes())
        html = self.client.get("/home").get_data(as_text=True)
        self.assertLess(html.index('class="brief-card"'), html.index('class="empty-state"'))
        self.assertIn("Friday, September 4, 2026", html)
        card = html.split('<article class="brief-card"', 1)[1].split("</article>", 1)[0]
        self.assertIn("Florida scientists breed 61,000 coral larvae", card)
        self.assertIn('href="/brief/2026-09-04"', card)
        self.assertNotIn("Scientists working in the Florida Keys", card)
        page = self.client.get("/brief/2026-09-04")
        self.assertEqual(page.status_code, 200)
        reader = page.get_data(as_text=True)
        self.assertEqual(reader.count('<section class="brief-story">'), 6)
        self.assertIn("<em>Po</em>", reader)
        self.assertIn('target="_blank" rel="noopener noreferrer"', reader)
        self.assertIn('class="brief-source-link"', reader)

    def test_today_is_selected_and_updates_from_disk_without_restart(self):
        path = self.write_edition(date(2026, 10, 22))
        self.write_edition(date(2026, 10, 23), "Tomorrow's unpublished edition.")
        with self.app.app_context():
            brief = dive_brief.load_brief()
            self.assertEqual(brief.effective_date, date(2026, 10, 22))
            self.assertIn("The story.", brief.body_html)
            path.write_text(path.read_text().replace("The story.", "The revised story, now updated."))
            self.assertIn("The revised story", dive_brief.load_brief().body_html)
        self.assertEqual(self.client.get("/brief/2026-10-23").status_code, 404)

    def test_no_edition_keeps_feed_working_and_deep_links_are_validated(self):
        self.write_edition(date(2026, 10, 21), "Yesterday's stale story.")
        # Retired sample configuration cannot re-enable a fallback.
        self.app.config["DIVE_BRIEF_SAMPLE_PATH"] = str(SAMPLE)
        html = self.client.get("/home").data
        self.assertNotIn(b'class="brief-card"', html)
        self.assertIn(b"No dives yet", html)
        for edition in ("2026-09-04", "bad-date", "2026-02-30", "20261021", ".."):
            self.assertEqual(self.client.get(f"/brief/{edition}").status_code, 404)
        self.assertEqual(self.app.test_client().get("/brief/2026-09-04").status_code, 302)

    def test_markdown_escapes_html_and_blocks_executable_link_protocols(self):
        self.write_edition(date(2026, 10, 21), '''## SCIENCE

### Keep the <script>alert(1)</script> ocean safe

<script>alert('unsafe')</script>

[unsafe](javascript:alert%281%29)

**Bold**, *italic*, and `code`.

> Protect the reef.

- One
- Two

| Place | Status |
| --- | --- |
| Reef | Healthy |
''')
        html = self.client.get("/brief/2026-10-21").get_data(as_text=True)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn('href="javascript:', html)
        for element in ("&lt;script&gt;", "<strong>Bold</strong>", "<em>italic</em>", "<code>code</code>", "<blockquote>", "<ul>", "<table>"):
            self.assertIn(element, html)

    def test_invalid_or_unreadable_editions_do_not_break_feed(self):
        path = self.write_edition(date(2026, 10, 22))
        for content in ("# Missing metadata", path.read_text().replace("October 22", "October 20"), "\xff"):
            path.write_bytes(content.encode("latin-1"))
            with self.app.app_context():
                self.assertIsNone(dive_brief.load_brief())
            self.assertEqual(self.client.get("/brief/2026-10-22").status_code, 404)
            self.assertNotIn(b'class="brief-card"', self.client.get("/home").data)

    def test_editorial_date_uses_configured_timezone_across_utc_midnight(self):
        self.clock.stop()
        with self.app.app_context(), patch("pelagia.dive_brief.datetime") as clock:
            clock.now.side_effect = lambda zone: datetime(2026, 10, 23, 2, 30, tzinfo=timezone.utc).astimezone(zone)
            self.app.config["DIVE_BRIEF_TIMEZONE"] = "America/New_York"
            self.assertEqual(dive_brief.effective_date(), date(2026, 10, 22))
            self.app.config["DIVE_BRIEF_TIMEZONE"] = "Pacific/Auckland"
            self.assertEqual(dive_brief.effective_date(), date(2026, 10, 23))

    def test_authenticated_upload_persists_today_with_server_controlled_filename(self):
        guest = self.app.test_client()
        payload = self.payload()
        response = guest.post("/api/dive-brief?filename=../../overwrite.md&date=2000-01-01", data=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json, {"date": "2026-10-22", "filename": "the_dive_brief_2026-10-22.md", "url": "/brief/2026-10-22"})
        self.assertEqual(response.headers["Location"], "/brief/2026-10-22")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        path = Path(self.app.config["DIVE_BRIEF_DIR"]) / response.json["filename"]
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertIn(b'class="brief-card"', self.client.get("/home").data)
        self.assertIn(b"The new story.", self.client.get(response.headers["Location"]).data)
        self.assertEqual(guest.get(response.headers["Location"]).status_code, 302)
        self.assertNotIn(self.api_key.encode(), self.client.get("/home").data)

    def test_api_key_is_required_even_when_logged_in_and_query_keys_are_rejected(self):
        for header in (None, "Bearer wrong", "Basic " + self.api_key, "Bearer", "Bearer a b", "Bearer café"):
            headers = {"Content-Type": "text/markdown"}
            if header is not None:
                headers["Authorization"] = header
            with self.subTest(header=header):
                response = self.client.post("/api/dive-brief?api_key=" + self.api_key, data=self.payload(), headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Bearer", response.headers["WWW-Authenticate"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertFalse(Path(self.app.config["DIVE_BRIEF_DIR"]).exists())

    def test_missing_or_invalid_server_authentication_fails_closed(self):
        for digest in ("", "not-a-hash"):
            self.app.config["DIVE_BRIEF_API_KEY_SHA256"] = digest
            self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(), headers=self.headers).status_code, 503)
        self.assertFalse(Path(self.app.config["DIVE_BRIEF_DIR"]).exists())

    def test_invalid_upload_never_replaces_existing_edition(self):
        path = self.write_edition(date(2026, 10, 22))
        original = path.read_bytes()
        for payload in (b"", b"\xff", b"# Bad format", self.payload(date(2026, 10, 21)), self.payload(body="\x00"),
                        self.payload().split(b"## OCEAN")[0] + b"---"):
            with self.subTest(payload=payload):
                response = self.client.post("/api/dive-brief", data=payload, headers=self.headers)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json["expected_date"], "2026-10-22")
                self.assertEqual(path.read_bytes(), original)

    def test_wrong_media_type_or_encoding_and_oversized_uploads_are_rejected(self):
        for content_type in ("application/json", "text/html", "text/markdown; charset=latin-1"):
            response = self.client.post("/api/dive-brief", data=self.payload(), headers={**self.headers, "Content-Type": content_type})
            self.assertEqual(response.status_code, 415)
        response = self.client.post("/api/dive-brief", data=b"x" * (dive_brief.MAX_BRIEF_BYTES + 1), headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(Path(self.app.config["DIVE_BRIEF_DIR"]).exists())
        # Streaming bodies without Content-Length are bounded too.
        response = self.client.post("/api/dive-brief", headers=self.headers, environ_overrides={
            "wsgi.input": io.BytesIO(b"x" * (dive_brief.MAX_BRIEF_BYTES + 1)),
            "wsgi.input_terminated": True, "CONTENT_LENGTH": "",
        })
        self.assertEqual(response.status_code, 413)

    def test_atomic_replacement_is_immediately_visible_and_failure_preserves_previous_file(self):
        self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(), headers=self.headers).status_code, 201)
        self.assertIn(b"The new story.", self.client.get("/brief/2026-10-22").data)
        replacement = self.payload(body="Updated and corrected story.")
        self.assertEqual(self.client.post("/api/dive-brief", data=replacement, headers=self.headers).status_code, 201)
        self.assertIn(b"Updated and corrected story.", self.client.get("/brief/2026-10-22").data)
        with patch("pelagia.dive_brief.os.replace", side_effect=OSError("disk unavailable")):
            self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(), headers=self.headers).status_code, 503)
        folder = Path(self.app.config["DIVE_BRIEF_DIR"])
        self.assertEqual(list(folder.iterdir()), [folder / "the_dive_brief_2026-10-22.md"])
        self.assertEqual(next(folder.iterdir()).read_bytes(), replacement)

    def test_key_creation_rotation_and_persistence_across_app_restart(self):
        self.app.config["DIVE_BRIEF_API_KEY_SHA256"] = ""
        runner = self.app.test_cli_runner()
        first = runner.invoke(args=["create-dive-brief-key"])
        self.assertEqual(first.exit_code, 0)
        key = first.output.strip()
        self.assertTrue(key.startswith("pdb_"))
        path = Path(self.app.config["DIVE_BRIEF_API_KEY_FILE"])
        self.assertEqual(path.read_text().strip(), hashlib.sha256(key.encode()).hexdigest())
        self.assertNotIn(key, path.read_text())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertNotEqual(runner.invoke(args=["create-dive-brief-key"]).exit_code, 0)
        headers = {**self.headers, "Authorization": "Bearer " + key}
        self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(), headers=headers).status_code, 201)
        rotated = runner.invoke(args=["create-dive-brief-key", "--rotate"])
        self.assertEqual(rotated.exit_code, 0)
        self.assertNotEqual(rotated.output.strip(), key)
        self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(), headers=headers).status_code, 401)
        restarted, _, _ = self.make_app(self.root)
        restarted.config.update(DIVE_BRIEF_DIR=self.app.config["DIVE_BRIEF_DIR"], DIVE_BRIEF_API_KEY_SHA256="")
        headers["Authorization"] = "Bearer " + rotated.output.strip()
        response = restarted.test_client().post("/api/dive-brief", data=self.payload(body="After restart."), headers=headers)
        self.assertEqual(response.status_code, 201)
        with restarted.app_context():
            self.assertIn("After restart.", dive_brief.load_brief().body_html)

    def test_upload_normalizes_utf8_bom_and_feed_disappears_at_next_editorial_day(self):
        payload = b"\xef\xbb\xbf" + self.payload(body="The ocean’s future.")
        self.assertEqual(self.client.post("/api/dive-brief", data=payload, headers=self.headers).status_code, 201)
        self.assertIn(b'class="brief-card"', self.client.get("/home").data)
        self.edition_clock.return_value = date(2026, 10, 23)
        self.assertNotIn(b'class="brief-card"', self.client.get("/home").data)
        self.assertEqual(self.client.get("/brief/2026-10-22").status_code, 200)
        self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(date(2026, 10, 23)), headers=self.headers).status_code, 201)
        self.assertIn(b'class="brief-card"', self.client.get("/home").data)

    def test_environment_digest_overrides_file_key_and_cannot_be_shadowed_by_cli(self):
        file_key = dive_brief.create_api_key(self.app.config["DIVE_BRIEF_API_KEY_FILE"])
        response = self.client.post("/api/dive-brief", data=self.payload(), headers={
            **self.headers, "Authorization": "Bearer " + file_key,
        })
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/api/dive-brief", data=self.payload(), headers=self.headers).status_code, 201)
        result = self.app.test_cli_runner().invoke(args=["create-dive-brief-key", "--rotate"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("environment digest", result.output)


if __name__ == "__main__":
    unittest.main()
