import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from pelagia import create_app, db


class PWATest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            self.app = create_app({
                "TESTING": True, "SECRET_KEY": "pwa-tests",
                "DATABASE": str(Path(tmp.name) / "test.sqlite3"),
                "UPLOAD_FOLDER": str(Path(tmp.name) / "uploads"),
                "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
            })
        self.client = self.app.test_client()

    def get(self, path):
        response = self.client.get(path)
        self.addCleanup(response.close)
        return response

    def test_public_manifest_and_icons_are_installable(self):
        response = self.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/manifest+json")
        manifest = json.loads(response.data)
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["id"], "/")
        self.assertEqual({icon["sizes"] for icon in manifest["icons"]}, {"192x192", "512x512"})
        for icon in manifest["icons"]:
            response = self.get(icon["src"])
            self.assertEqual(response.status_code, 200)
            image = Image.open(io.BytesIO(response.data))
            self.assertEqual(image.size, tuple(map(int, icon["sizes"].split("x"))))
            self.assertEqual(image.mode, "RGB")
            if icon["purpose"] == "maskable":
                # The white mark must fit Android's central safe circle.
                for y in range(image.height):
                    for x in range(image.width):
                        if min(image.getpixel((x, y))) > 240:
                            self.assertLess((x - 256)**2 + (y - 256)**2, (512 * .4)**2)
        touch = Image.open(io.BytesIO(self.get("/static/img/apple-touch-icon.png").data))
        self.assertEqual(touch.size, (180, 180))

    def test_root_worker_has_correct_scope_mime_and_revalidates(self):
        response = self.get("/service-worker.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/javascript")
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", response.headers["Cache-Control"])
        self.assertNotIn(b"__PELAGIA_", response.data)
        self.assertIn(self.app.jinja_env.globals["pwa_asset_version"].encode(), response.data)

    def test_precache_resources_exist_and_match_page_asset_versions(self):
        source = self.get("/service-worker.js").get_data(as_text=True)
        paths = json.loads(re.search(r"const PRECACHE = (\[.*?\]);", source).group(1))
        self.assertIn("/offline.html", paths)
        self.assertIn("/manifest.webmanifest", paths)
        for path in paths:
            response = self.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn("/api/", path)
            self.assertNotIn("/uploads/", path)
        for page in ("/", "/offline.html"):
            html = self.get(page).get_data(as_text=True)
            for asset in re.findall(r'(?:src|href)="(/static/[^\"]+\?v=[^\"]+)"', html):
                self.assertIn(asset, paths)
            self.assertIn('rel="manifest" href="/manifest.webmanifest"', html)
            self.assertIn("viewport-fit=cover", html)

    def test_offline_page_is_identical_across_accounts(self):
        anonymous = self.get("/offline.html").data
        with self.app.app_context():
            database = db.get_db()
            database.execute("INSERT INTO users (username, password_hash, google_email) VALUES ('PRIVATE-USERNAME', '', 'PRIVATE-EMAIL')")
            database.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        authenticated = self.get("/offline.html").data
        self.assertEqual(anonymous, authenticated)
        self.assertNotIn(b"PRIVATE", authenticated)
        self.assertIn(b"data-pwa-retry", authenticated)

    def test_install_guidance_is_available_on_login_and_own_profile(self):
        self.assertIn(b"data-pwa-install hidden", self.get("/").data)
        with self.app.app_context():
            database = db.get_db()
            database.execute("INSERT INTO users (username, password_hash) VALUES ('diver', '')")
            database.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        profile = self.get("/you").data
        self.assertIn(b"data-pwa-install hidden", profile)
        self.assertIn(b"data-pwa-back", profile)
        self.assertIn(b"data-pwa-update", profile)


if __name__ == "__main__":
    unittest.main()
