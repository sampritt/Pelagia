import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from flask import Flask
from PIL import Image, ImageDraw

from pelagia.static_maps import CACHE_SECONDS, render_static_map


class StaticMapsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Flask(__name__)
        self.cache = Path(self.tmp.name) / "tiles"
        self.app.config.update(DATABASE=str(Path(self.tmp.name) / "test.sqlite3"),
                               MAP_TILE_CACHE_DIR=str(self.cache), PUBLIC_BASE_URL="https://pelagia.example")
        self.enterContext(self.app.app_context())
        stream = io.BytesIO()
        Image.new("RGB", (256, 256), "#aad3df").save(stream, "PNG")
        self.tile = stream.getvalue()

    def response(self, status=200, content=None):
        response = Mock(status_code=status, content=self.tile if content is None else content,
                        headers={"Cache-Control": "max-age=1209600", "ETag": '"tile-version"'})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_visible_viewport_is_cached_and_provider_headers_are_identified(self):
        with patch("pelagia.static_maps.requests.get", side_effect=lambda *a, **k: self.response()) as fetch:
            first = render_static_map(7.134, 134.22)
            self.assertEqual(first.size, (580, 630))
            self.assertLessEqual(fetch.call_count, 16)
            urls = [call.args[0] for call in fetch.call_args_list]
            self.assertEqual(len(urls), len(set(urls)))
            for call in fetch.call_args_list:
                self.assertTrue(call.args[0].startswith("https://tile.openstreetmap.org/10/"))
                self.assertIn("Pelagia", call.kwargs["headers"]["User-Agent"])
                self.assertEqual(call.kwargs["headers"]["Referer"], "https://pelagia.example/")
            fetch.reset_mock()
            # Persisted cache survives a subsequent render with no HTTP requests.
            self.assertEqual(render_static_map(7.134, 134.22).tobytes(), first.tobytes())
            fetch.assert_not_called()
        for metadata_file in self.cache.glob("*.json"):
            self.assertGreater(json.loads(metadata_file.read_text())["expires"], metadata_file.stat().st_mtime + CACHE_SECONDS)

    def test_expired_tiles_revalidate_and_stale_tiles_survive_provider_outage(self):
        with patch("pelagia.static_maps.requests.get", side_effect=lambda *a, **k: self.response()):
            first = render_static_map(7.134, 134.22)

        def expire_cache():
            for path in self.cache.glob("*.json"):
                metadata = json.loads(path.read_text())
                metadata["expires"] = 0
                path.write_text(json.dumps(metadata))

        expire_cache()
        with patch("pelagia.static_maps.requests.get", side_effect=lambda *a, **k: self.response(304)) as fetch:
            self.assertEqual(render_static_map(7.134, 134.22).tobytes(), first.tobytes())
            self.assertGreater(fetch.call_count, 0)
            for call in fetch.call_args_list:
                self.assertEqual(call.kwargs["headers"]["If-None-Match"], '"tile-version"')
        expire_cache()
        with patch("pelagia.static_maps.requests.get", side_effect=requests.Timeout("offline")):
            self.assertEqual(render_static_map(7.134, 134.22).tobytes(), first.tobytes())

    def test_zero_coordinates_and_dateline_wrap_without_invalid_tile_indices(self):
        for lat, lng in ((0, 0), (0, 180), (0, -180), (85, 0), (-85, 0)):
            with self.subTest(latitude=lat, longitude=lng):
                with patch("pelagia.static_maps.requests.get", side_effect=lambda *a, **k: self.response()) as fetch:
                    image = render_static_map(lat, lng)
                    self.assertEqual(image.size, (580, 630))
                    for call in fetch.call_args_list:
                        zoom, x, y = call.args[0].removesuffix(".png").split("/")[-3:]
                        self.assertEqual(int(zoom), 10)
                        self.assertTrue(0 <= int(x) < 1024)
                        self.assertTrue(0 <= int(y) < 1024)

    def test_invalid_coordinates_or_unreadable_tiles_return_no_map(self):
        with patch("pelagia.static_maps.requests.get") as fetch:
            for lat, lng in ((None, 0), (0, None), ("bad", 0), (float("nan"), 0), (0, float("inf")), (86, 0), (0, 181)):
                self.assertIsNone(render_static_map(lat, lng))
            fetch.assert_not_called()
        with patch("pelagia.static_maps.requests.get", side_effect=lambda *a, **k: self.response(content=b"not an image")):
            self.assertIsNone(render_static_map(7.134, 134.22))

    def test_offset_pin_preserves_the_sites_geographic_position(self):
        tile = Image.new("RGB", (256, 256), "#aad3df")
        draw = ImageDraw.Draw(tile)
        for x in range(0, 256, 16):
            draw.line((x, 0, x, 255), fill=(x, 80, 100), width=3)
        stream = io.BytesIO()
        tile.save(stream, "PNG")
        with patch("pelagia.static_maps.requests.get", side_effect=lambda *a, **k: self.response(content=stream.getvalue())):
            centered = render_static_map(7.134, 134.22)
            offset = render_static_map(7.134, 134.22, size=(1200, 630), pin_position=(930, 235))
        self.assertEqual(offset.getpixel((930, 235)), (6, 42, 70))
        self.assertEqual(centered.crop((320, 280, 400, 350)).tobytes(),
                         offset.crop((960, 200, 1040, 270)).tobytes())


if __name__ == "__main__":
    unittest.main()
