import io
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from pelagia import create_app, db


class StartupLinkParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.screens = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "apple-touch-startup-image":
            self.screens.append(attrs)


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

    def test_apple_launch_images_match_device_media_and_manifest_background(self):
        background = json.loads(self.get("/manifest.webmanifest").data)["background_color"]
        expected_color = tuple(bytes.fromhex(background.removeprefix("#")))
        pages = [StartupLinkParser(self.get(page).get_data(as_text=True)).screens
                 for page in ("/", "/login", "/offline.html")]
        self.assertEqual(pages[0], pages[1])
        self.assertEqual(pages[0], pages[2])
        self.assertTrue(pages[0])
        devices = set()
        for screen in pages[0]:
            media = screen["media"]
            width = int(re.search(r"device-width: (\d+)px", media).group(1))
            height = int(re.search(r"device-height: (\d+)px", media).group(1))
            scale = int(re.search(r"device-pixel-ratio: (\d+)", media).group(1))
            orientation = re.search(r"orientation: (\w+)", media).group(1)
            devices.add((width, height, scale, orientation))
            expected_size = (width * scale, height * scale)
            if orientation == "landscape":
                expected_size = expected_size[::-1]
            response = self.get(screen["href"])
            self.assertEqual(response.status_code, 200, screen["href"])
            with Image.open(io.BytesIO(response.data)) as image:
                self.assertEqual(image.size, expected_size)
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), expected_color)
                self.assertEqual(image.getpixel((image.width - 1, image.height - 1)), expected_color)
                # A centered, visible logo is present on the otherwise plain background.
                self.assertNotEqual(image.getpixel((image.width // 2, image.height // 2)), expected_color)
        for device in ((375, 667, 2), (390, 844, 3), (402, 874, 3), (768, 1024, 2), (1032, 1376, 2)):
            for orientation in ("portrait", "landscape"):
                self.assertIn((*device, orientation), devices)
        source = self.get("/service-worker.js").get_data(as_text=True)
        paths = json.loads(re.search(r"const PRECACHE = (\[.*?\]);", source).group(1))
        self.assertFalse(any("/img/startup/" in path for path in paths))

    def test_launch_background_is_available_before_external_styles(self):
        for page in ("/", "/login", "/offline.html"):
            html = self.get(page).get_data(as_text=True)
            self.assertIn('<meta name="color-scheme" content="dark">', html)
            self.assertLess(html.index("html { background: #031e33;"), html.index('rel="stylesheet"'))

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
            database.execute("INSERT INTO users (username, google_email) VALUES ('PRIVATE-USERNAME', 'PRIVATE-EMAIL')")
            database.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        authenticated = self.get("/offline.html").data
        self.assertEqual(anonymous, authenticated)
        self.assertNotIn(b"PRIVATE", authenticated)
        self.assertIn(b"data-pwa-retry", authenticated)

    def test_install_guidance_is_available_on_login_and_own_profile(self):
        landing = self.get("/").data
        self.assertNotIn(b"Download", landing)
        self.assertNotIn(b"data-pwa-guide", landing)
        self.assertNotIn(b"data-pwa-install-dialog", landing)
        self.assertNotIn(b"data-pwa-install-notice", landing)
        self.assertNotIn(b"Add to Home Screen", landing)
        self.assertIn(b"data-pwa-install-dialog", self.get("/login").data)
        with self.app.app_context():
            database = db.get_db()
            database.execute("INSERT INTO users (username) VALUES ('diver')")
            database.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
        profile = self.get("/you").data
        self.assertIn(b"data-pwa-install hidden", profile)
        self.assertIn(b"data-pwa-install-dialog", profile)
        self.assertNotIn(b"data-pwa-back", profile)
        self.assertIn(b"data-pwa-update", profile)


if __name__ == "__main__":
    unittest.main()
