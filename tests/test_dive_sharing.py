import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw
import requests

from pelagia import create_app
from pelagia import db as database
from pelagia.sharing import TRANSPARENT_LAYOUTS, _select_share_stats, fetch_public_dive, render_share_image, render_transparent_share_image
from pelagia.static_maps import render_static_map


class DiveSharingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            self.app = create_app({
                "TESTING": True, "SECRET_KEY": "sharing-tests",
                "DATABASE": str(Path(self.tmp.name) / "test.sqlite3"),
                "UPLOAD_FOLDER": str(Path(self.tmp.name) / "uploads"),
                "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
                "PUBLIC_BASE_URL": "https://pelagia.example",
            })
        self.client = self.app.test_client()
        # Unit tests render deterministic tiles without accessing a live provider.
        tile = io.BytesIO()
        Image.new("RGB", (256, 256), "#aad3df").save(tile, "PNG")

        def tile_response(*args, **kwargs):
            response = Mock(status_code=200, content=tile.getvalue(), headers={"Cache-Control": "max-age=604800"})
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            return response

        self.tile_request = self.enterContext(patch("pelagia.static_maps.requests.get", side_effect=tile_response))
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (username, google_email, profile_photo) VALUES (?, ?, ?)",
                       ("maya", "private@example.com", "profiles/maya.jpg"))
            db.execute("INSERT INTO users (username) VALUES ('private-buddy')")
            db.execute("""INSERT INTO dives (user_id, buddy_user_id, date, site_name, country_or_area,
                       latitude, longitude, depth_m, duration_min, notes, exposure, weight_kg)
                       VALUES (1, 2, '2026-10-01', 'Blue Corner', 'Palau', 7.134, 134.22, 24, 52,
                       'PRIVATE DIVE NOTES', 'dry suit', 7.5)""")
            db.execute("INSERT INTO comments (dive_id, user_id, body) VALUES (1, 2, 'PRIVATE COMMENT')")
            db.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (1, 'PRIVATE SPECIES')")
            db.commit()

    def login_session(self, user_id=1):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

    def test_guest_preview_allowlist_and_metadata(self):
        response = self.client.get("/share/dive/1")
        self.assertEqual(response.status_code, 200)
        for visible in (b"Blue Corner", b"Palau", b"maya", b"profiles/maya.jpg", b"data-map-lat", b"See the whole dive."):
            self.assertIn(visible, response.data)
        for secret in (b"PRIVATE DIVE NOTES", b"PRIVATE COMMENT", b"PRIVATE SPECIES", b"private-buddy", b"private@example.com", b"dry suit", b"7.5"):
            self.assertNotIn(secret, response.data)
        self.assertIn(b'content="maya logged a dive', response.data)
        self.assertIn(b'https://pelagia.example/share/dive/1/preview.jpg', response.data)
        self.assertIn("no-store", response.headers["Cache-Control"])
        with self.app.app_context():
            dive = fetch_public_dive(1)
            self.assertNotIn("notes", dive)
            self.assertNotIn("user_id", dive)

    def test_signed_in_visitor_redirects_to_normal_dive(self):
        self.login_session(2)
        response = self.client.get("/share/dive/1")
        self.assertEqual(response.location, "/dive/1")
        self.assertIn(b"PRIVATE DIVE NOTES", self.client.get(response.location).data)

    def test_owner_has_share_on_detail_feed_and_profile(self):
        self.login_session()
        for url in ("/dive/1", "/home", "/you"):
            self.assertIn(b"data-share-dive", self.client.get(url).data)
        self.login_session(2)
        self.assertNotIn(b"data-share-dive", self.client.get("/dive/1").data)

    def test_full_dive_api_remains_authenticated(self):
        for url in ("/api/dives/1", "/dive/1"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertNotIn(b"PRIVATE DIVE NOTES", response.data)

    def test_auth_pages_preserve_shared_dive_destination(self):
        for path in ("/login", "/signup"):
            response = self.client.get(path + "?next=/dive/1")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b'type="password"', response.data)
        self.assertEqual(self.client.post("/login").status_code, 405)
        self.assertEqual(self.client.post("/signup").status_code, 405)

    def test_preview_image_without_photos_is_public_jpeg(self):
        drawn_text = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            drawn_text.append(text)
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            response = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))
            # The full-bleed map stays visible above the stats, and its pin is
            # offset to the right of the headline instead of hidden beneath it.
            for actual, expected in zip(image.getpixel((1150, 235)), (170, 211, 223)):
                self.assertLessEqual(abs(actual - expected), 3)
            self.assertNotEqual(image.getpixel((930, 235)), image.getpixel((1150, 235)))
            # The old panel boundary is now a continuous, gradual fade.
            for x in range(590, 650):
                before, after = image.getpixel((x, 350)), image.getpixel((x + 1, 350))
                self.assertLess(max(abs(a - b) for a, b in zip(before, after)), 8)
        self.assertNotIn("© OpenStreetMap contributors", drawn_text)
        self.assertGreater(self.tile_request.call_count, 0)
        self.assertEqual(self.client.get("/share/dive/1/preview.jpg?download=1").data, response.data)

    def test_map_failure_or_missing_coordinates_keeps_thumbnail_available(self):
        self.tile_request.side_effect = requests.Timeout("Map unavailable")
        failed = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(failed.status_code, 200)
        self.assertGreater(self.tile_request.call_count, 0)
        self.tile_request.reset_mock()
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET latitude = NULL, longitude = NULL WHERE id = 1")
            database.get_db().commit()
        missing = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(missing.data, failed.data)
        self.tile_request.assert_not_called()

    def test_average_depth_is_only_in_logged_dive_metrics(self):
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET average_depth_m = 15.0 WHERE id = 1")
            database.get_db().commit()
        self.login_session()
        for url in ("/home", "/you"):
            self.assertNotIn(b"Average depth", self.client.get(url).data)
        detail = self.client.get("/dive/1").data
        headline, metrics = detail.split(b"detail-lower-grid", 1)
        self.assertNotIn(b"Average depth", headline)
        self.assertIn(b"<dt>Average depth</dt>", metrics)
        self.assertIn(b"<dd>15 m</dd>", metrics)

    def test_share_thumbnail_includes_average_depth_when_logged(self):
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET average_depth_m = 15.0 WHERE id = 1")
            database.get_db().commit()
        drawn = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            response = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AVG DEPTH", drawn)
        self.assertIn("MAX DEPTH", drawn)
        self.assertIn("15", drawn)
        self.assertNotIn("15.0", drawn)

    def upload_photos(self):
        photos = []
        for name, color in (("primary.jpg", "#17adad"), ("second.jpg", "#ff6633")):
            stream = io.BytesIO()
            Image.new("RGB", (200, 300), color).save(stream, "JPEG")
            stream.seek(0)
            photos.append((stream, name))
        self.login_session()
        response = self.client.post("/dive/1/edit", data={
            "site_name": "Blue Corner", "country_or_area": "Palau",
            "date": "2026-10-01",
            "depth_m": "24", "duration_min": "52", "photos": photos,
            "latitude": "7.134", "longitude": "134.22",
        })
        self.assertEqual(response.status_code, 302)

    def assert_preview_photo_color(self, color):
        # Check a clear part of the full-bleed photo, above the lower scrim.
        guest = self.app.test_client()
        response = guest.get("/share/dive/1/preview.jpg")
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))
            pixel = image.getpixel((1180, 235))
            for actual, expected in zip(pixel, color):
                self.assertLessEqual(abs(actual - expected), 3)
        download = guest.get("/share/dive/1/preview.jpg?download=1")
        self.assertEqual(download.data, response.data)

    def test_uploaded_primary_photo_appears_in_public_and_saved_thumbnail(self):
        self.upload_photos()
        with patch("pelagia.sharing.render_static_map", wraps=render_static_map) as map_renderer:
            self.assert_preview_photo_color((23, 173, 173))
            for call in map_renderer.call_args_list:
                self.assertEqual(call.args, (7.134, 134.22))
                self.assertEqual(call.kwargs, {"size": (314, 252)})
            self.assertGreater(map_renderer.call_count, 0)
        self.assertGreater(self.tile_request.call_count, 0)
        with Image.open(io.BytesIO(self.client.get("/share/dive/1/preview.jpg").data)) as image:
            self.assertNotEqual(image.getpixel((987, 234)), image.getpixel((1080, 234)))
            # The inset leaves the uploaded photo visible outside its bounds.
            self.assertNotEqual(image.getpixel((1080, 234)), image.getpixel((1180, 234)))

    def test_photo_share_omits_inset_when_coordinates_or_tiles_are_unavailable(self):
        self.upload_photos()
        self.tile_request.side_effect = requests.Timeout("Map unavailable")
        failed = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(failed.status_code, 200)
        self.assertGreater(self.tile_request.call_count, 0)
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET latitude = NULL, longitude = NULL WHERE id = 1")
            database.get_db().commit()
        self.tile_request.reset_mock()
        missing = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(failed.data, missing.data)
        self.tile_request.assert_not_called()

    def test_unavailable_primary_photo_uses_next_photo_then_map_fallback(self):
        self.upload_photos()
        with self.app.app_context():
            # Editing also records the default gas, so compare the fallback
            # using the same saved metrics as the photo-bearing dive.
            dive = fetch_public_dive(1)
            dive["photos"] = []
            fallback = render_share_image(dive).getvalue()
            photos = database.get_db().execute("SELECT filename FROM photos ORDER BY id").fetchall()
            paths = [Path(self.app.config["UPLOAD_FOLDER"], photo["filename"].removeprefix("uploads/")) for photo in photos]
        paths[0].unlink()
        self.assert_preview_photo_color((255, 102, 51))
        paths[0].write_bytes(b"unreadable photo")
        self.assert_preview_photo_color((255, 102, 51))
        paths[1].write_bytes(b"unreadable photo")
        self.assertEqual(self.app.test_client().get("/share/dive/1/preview.jpg").data, fallback)

    def test_thumbnail_cannot_load_a_photo_outside_upload_folder(self):
        fallback = self.client.get("/share/dive/1/preview.jpg").data
        Image.new("RGB", (200, 300), "#ff6633").save(Path(self.tmp.name, "outside.jpg"))
        with self.app.app_context():
            database.get_db().execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'uploads/../outside.jpg')")
            database.get_db().commit()
        self.assertEqual(self.client.get("/share/dive/1/preview.jpg").data, fallback)

    def test_save_downloads_a_named_jpeg_attachment(self):
        response = self.client.get("/share/dive/1/preview.jpg?download=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("pelagia-Blue_Corner.jpg", response.headers["Content-Disposition"])
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))

    def test_transparent_image_is_a_public_png_with_only_site_stats_and_brand(self):
        drawn = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            response = self.client.get("/share/dive/1/transparent.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertEqual(drawn, ["Blue Corner", "24", "m", "MAX DEPTH", "52", "min", "DIVE TIME",
                                 "7.5", "kg", "WEIGHT", "dry suit", "EXPOSURE"])
        self.tile_request.assert_not_called()
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("Cookie", response.headers["Vary"])
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 780))
            self.assertEqual(image.mode, "RGBA")
            alpha = image.getchannel("A")
            self.assertEqual(alpha.getextrema(), (0, 255))
            # Empty margins and the gaps between rows are actually transparent.
            for position in ((0, 0), (1199, 629), (600, 250), (600, 390), (600, 300)):
                self.assertEqual(alpha.getpixel(position), 0)
            self.assertIsNotNone(alpha.crop((100, 60, 1100, 235)).getbbox())
            self.assertIsNotNone(alpha.crop((250, 240, 950, 365)).getbbox())
            self.assertIsNotNone(alpha.crop((450, 620, 750, 770)).getbbox())

    def test_transparent_save_downloads_png_attachment_and_respects_depth_units(self):
        self.login_session()
        with self.app.app_context():
            database.get_db().execute("UPDATE users SET length_unit = 'ft' WHERE id = 1")
            database.get_db().commit()
        drawn = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            response = self.client.get("/share/dive/1/transparent.png?download=1")
        self.assertEqual(response.mimetype, "image/png")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("pelagia-Blue_Corner-transparent.png", response.headers["Content-Disposition"])
        self.assertIn("79", drawn)
        self.assertIn("ft", drawn)
        self.assertEqual(response.data, self.client.get("/share/dive/1/transparent.png").data)

    def test_transparent_titles_fit_without_losing_words(self):
        original_text = ImageDraw.ImageDraw.text
        for title in ("Kicker Rock (Leon Dormido)", "Very long dive site name " * 15,
                      "AReallyLongUnbrokenDiveSiteName" * 4):
            with self.subTest(title=title):
                drawn = []

                def record_text(draw, xy, text, *args, **kwargs):
                    if xy[0] == 600:
                        drawn.append((text, draw.textbbox(xy, text, font=kwargs["font"], anchor=kwargs["anchor"])))
                    return original_text(draw, xy, text, *args, **kwargs)

                with self.app.app_context():
                    database.get_db().execute("UPDATE dives SET site_name = ? WHERE id = 1", (title,))
                    database.get_db().commit()
                with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                    response = self.client.get("/share/dive/1/transparent.png")
                self.assertEqual(response.status_code, 200)
                self.assertEqual("".join(text for text, _ in drawn).replace(" ", ""), title.replace(" ", ""))
                for _, (left, top, right, bottom) in drawn:
                    self.assertGreaterEqual(left, 95)
                    self.assertLessEqual(right, 1105)
                    self.assertGreaterEqual(top, 40)
                    self.assertLessEqual(bottom, 210)

    def test_optional_gas_and_sac_appear_in_both_exports_without_private_equipment(self):
        original_text = ImageDraw.ImageDraw.text
        for oxygen, helium, expected in ((21, 0, "Air"), (32, 0, "EANx 32%"), (18, 45, "Trimix 18/45")):
            with self.subTest(gas=expected):
                with self.app.app_context():
                    database.get_db().execute(
                        "UPDATE dives SET oxygen_pct = ?, helium_pct = ?, sac_rate_l_min = 17.6, "
                        "starting_pressure_bar = 200, ending_pressure_bar = 50 WHERE id = 1", (oxygen, helium),
                    )
                    database.get_db().commit()
                    public = fetch_public_dive(1)
                    for field in ("starting_pressure_bar", "ending_pressure_bar", "notes", "buddy_user_id"):
                        self.assertNotIn(field, public)
                for suffix in ("preview.jpg", "transparent.png"):
                    drawn = []

                    def record_text(draw, xy, text, *args, **kwargs):
                        drawn.append(text)
                        return original_text(draw, xy, text, *args, **kwargs)

                    with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                        response = self.client.get(f"/share/dive/1/{suffix}")
                    self.assertEqual(response.status_code, 200)
                    for text in (expected, "GAS MIX", "18", "L/min", "SAC RATE"):
                        self.assertIn(text, drawn)
                    self.assertNotIn("200", drawn)
                    if suffix == "transparent.png":
                        with Image.open(io.BytesIO(response.data)) as image:
                            self.assertEqual(image.getchannel("A").getpixel((0, 0)), 0)
                            self.assertIsNotNone(image.getchannel("A").crop((100, 450, 1100, 590)).getbbox())
                            self.assertIsNotNone(image.getchannel("A").crop((500, 620, 700, 770)).getbbox())

    def test_missing_optional_stats_are_omitted_independently(self):
        original_text = ImageDraw.ImageDraw.text
        with self.app.app_context():
            dive = fetch_public_dive(1)
            for gas, sac, labels in ((None, None, ()), ("EANx 32%", None, ("GAS MIX",)),
                                     (None, 18, ("SAC RATE",)), (None, 0, ("SAC RATE",)),
                                     (None, -5, ()), (None, float("nan"), ())):
                for renderer in (render_share_image, render_transparent_share_image):
                    with self.subTest(gas=gas, sac=sac, renderer=renderer.__name__):
                        drawn = []

                        def record_text(draw, xy, text, *args, **kwargs):
                            drawn.append(text)
                            return original_text(draw, xy, text, *args, **kwargs)

                        dive.update(gas_mix_label=gas, sac_rate_l_min=sac)
                        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                            renderer(dive)
                        self.assertEqual(tuple(label for label in ("GAS MIX", "SAC RATE") if label in drawn), labels)
                        self.assertNotIn("-", drawn)

    def test_transparent_layouts_keep_equal_stat_sizes_and_all_text_in_bounds(self):
        original_text = ImageDraw.ImageDraw.text
        with self.app.app_context():
            dive = fetch_public_dive(1)
            for title in ("Kicker Rock (Leon Dormido)",
                          "Great Blue Hole and Lighthouse Reef National Marine Reserve"):
                for gas, sac in ((None, None), ("Air", None), (None, 18),
                                 ("EANx 32%", 18), ("Trimix 18/45", 18)):
                    dive.update(site_name=title, gas_mix_label=gas, sac_rate_l_min=sac)
                    for layout, dimensions in TRANSPARENT_LAYOUTS.items():
                        with self.subTest(title=title, gas=gas, sac=sac, layout=layout):
                            drawn = []

                            def record_text(draw, xy, text, *args, **kwargs):
                                drawn.append((text, kwargs["font"].size,
                                              draw.textbbox(xy, text, font=kwargs["font"], anchor=kwargs["anchor"])))
                                return original_text(draw, xy, text, *args, **kwargs)

                            with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                                stream = render_transparent_share_image(dive, layout=layout)
                            with Image.open(stream) as image:
                                self.assertEqual(image.size, dimensions)
                                self.assertEqual(image.mode, "RGBA")
                                self.assertEqual(image.getchannel("A").getpixel((0, 0)), 0)
                            values = {"24", "52", "18", gas}
                            self.assertEqual(len({size for text, size, _ in drawn if text in values}), 1)
                            for _, _, (left, top, right, bottom) in drawn:
                                self.assertGreaterEqual(left, 12)
                                self.assertGreaterEqual(top, 12)
                                self.assertLessEqual(right, dimensions[0] - 12)
                                self.assertLessEqual(bottom, dimensions[1] - 12)
                            labels = {text for text, _, _ in drawn}
                            if layout == "map":
                                self.assertNotIn("GAS MIX", labels)
                                self.assertNotIn("SAC RATE", labels)
                            if layout in {"vertical", "horizontal"}:
                                self.assertFalse(any("Kicker" in text or "Dormido" in text or "Lighthouse" in text
                                                     for text, _, _ in drawn))


    def test_each_png_layout_downloads_with_its_own_name_and_map_fallback(self):
        self.login_session()
        with self.app.app_context():
            database.get_db().execute("UPDATE users SET length_unit = 'ft' WHERE id = 1")
            database.get_db().commit()
        for layout, dimensions in TRANSPARENT_LAYOUTS.items():
            with self.subTest(layout=layout):
                response = self.client.get(f"/share/dive/1/transparent.png?download=1&layout={layout}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"transparent-{layout}.png", response.headers["Content-Disposition"])
                with Image.open(io.BytesIO(response.data)) as image:
                    self.assertEqual(image.size, dimensions)
                self.assertEqual(response.data, self.client.get(f"/share/dive/1/transparent.png?layout={layout}").data)
        self.assertEqual(self.client.get("/share/dive/1/transparent.png?layout=unknown").status_code, 400)
        self.tile_request.assert_called()
        self.tile_request.reset_mock()
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET latitude = NULL, longitude = NULL WHERE id = 1")
            database.get_db().commit()
        drawn = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            self.assertEqual(self.client.get("/share/dive/1/transparent.png?layout=map").status_code, 200)
        self.assertIn("Map unavailable", drawn)
        self.assertIn("ft", drawn)
        self.tile_request.assert_not_called()

    def test_stats_use_the_first_four_available_values_in_priority_order(self):
        fields = ("depth_m", "average_depth_m", "duration_min", "gas_mix_label",
                  "sac_rate_l_min", "weight_kg", "exposure")
        values = (24, 15, 52, "EANx 32%", 18, 7.5, "dry suit")
        labels = ("MAX DEPTH", "AVG DEPTH", "DIVE TIME", "GAS MIX", "SAC RATE", "WEIGHT", "EXPOSURE")
        # All combinations cover each fallback and shorter/empty selections.
        for mask in range(1 << len(fields)):
            dive = {field: value if mask & (1 << index) else None
                    for index, (field, value) in enumerate(zip(fields, values))}
            expected = [label for index, label in enumerate(labels) if mask & (1 << index)][:4]
            with self.subTest(mask=mask):
                self.assertEqual([stat[2] for stat in _select_share_stats(dive)], expected)
        zeroes = dict(depth_m=0, average_depth_m=0, duration_min=0, weight_kg=0)
        self.assertEqual([stat[0] for stat in _select_share_stats(zeroes)], ["0"] * 4)

    def test_splash_and_three_stat_pngs_share_selection_and_equal_value_sizes(self):
        labels = {"MAX DEPTH", "AVG DEPTH", "DIVE TIME", "GAS MIX", "SAC RATE", "WEIGHT", "EXPOSURE"}
        original_text = ImageDraw.ImageDraw.text
        with self.app.app_context():
            dive = fetch_public_dive(1)
            cases = (
                (dict(average_depth_m=15, gas_mix_label="EANx 32%", sac_rate_l_min=18),
                 ["MAX DEPTH", "AVG DEPTH", "DIVE TIME", "GAS MIX"]),
                (dict(average_depth_m=15, gas_mix_label=None, sac_rate_l_min=18),
                 ["MAX DEPTH", "AVG DEPTH", "DIVE TIME", "SAC RATE"]),
                (dict(average_depth_m=None, gas_mix_label=None, sac_rate_l_min=None),
                 ["MAX DEPTH", "DIVE TIME", "WEIGHT", "EXPOSURE"]),
            )
            for changes, expected in cases:
                dive.update(changes)
                for layout in ("splash", "vertical", "horizontal", "stacked", "map"):
                    with self.subTest(layout=layout, expected=expected):
                        drawn, values = [], []
                        chosen = _select_share_stats(dive, map_only=layout == "map")
                        chosen_values = {stat[0] for stat in chosen}

                        def record_text(draw, xy, text, *args, **kwargs):
                            drawn.append(text)
                            if text in chosen_values:
                                values.append(kwargs["font"].size)
                            return original_text(draw, xy, text, *args, **kwargs)

                        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                            if layout == "splash":
                                render_share_image(dive)
                            else:
                                render_transparent_share_image(dive, layout=layout)
                        self.assertEqual([text for text in drawn if text in labels],
                                         ["MAX DEPTH", "DIVE TIME"] if layout == "map" else expected)
                        self.assertEqual(len(set(values)), 1)
                        self.assertEqual(len(values), len(chosen))
                        if layout in {"vertical", "horizontal"}:
                            self.assertNotIn(dive["site_name"], drawn)

    def test_weight_fallback_uses_viewer_weight_units_in_all_four_stat_exports(self):
        self.login_session()
        with self.app.app_context():
            database.get_db().execute("UPDATE users SET weight_unit = 'lb' WHERE id = 1")
            database.get_db().commit()
        original_text = ImageDraw.ImageDraw.text
        for suffix in ("preview.jpg", "transparent.png?layout=vertical", "transparent.png?layout=horizontal",
                       "transparent.png?layout=stacked"):
            drawn = []

            def record_text(draw, xy, text, *args, **kwargs):
                drawn.append(text)
                return original_text(draw, xy, text, *args, **kwargs)

            with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                self.assertEqual(self.client.get(f"/share/dive/1/{suffix}").status_code, 200)
            for text in ("16.5", "lb", "WEIGHT", "dry suit", "EXPOSURE"):
                self.assertIn(text, drawn)
            self.assertNotIn("kg", drawn)

    def test_deleted_and_missing_dives_have_no_public_page_or_image(self):
        self.login_session()
        self.client.post("/dive/1/delete")
        for client in (self.client, self.app.test_client()):
            for dive_id in (1, 999):
                for suffix in ("", "/preview.jpg", "/transparent.png"):
                    self.assertEqual(client.get(f"/share/dive/{dive_id}{suffix}").status_code, 404)

    def test_no_coordinates_and_long_escaped_titles(self):
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET latitude = NULL, longitude = NULL, site_name = ?", ("<script>alert(1)</script> " + "Long dive site " * 15,))
            database.get_db().commit()
        response = self.client.get("/share/dive/1")
        self.assertIn(b"Coordinates pending", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)
        self.assertEqual(self.client.get("/share/dive/1/preview.jpg").status_code, 200)

    def test_complete_titles_are_drawn_inside_the_headline_area(self):
        uploads = Path(self.app.config["UPLOAD_FOLDER"])
        Image.new("RGB", (1200, 630), "#17adad").save(uploads / "title-review.jpg")
        with self.app.app_context():
            database.get_db().execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'title-review.jpg')")
            database.get_db().commit()
        original_text = ImageDraw.ImageDraw.text
        for title in (
            "Blue Corner",
            "Kicker Rock (Leon Dormido)",
            "NorthwesternSanctuary Entrance",
            "Great Blue Hole and Lighthouse Reef National Marine Reserve",
            "Very long dive site name " * 15,
            "AReallyLongUnbrokenDiveSiteName" * 4,
        ):
            with self.subTest(title=title):
                drawn = []

                def record_text(draw, xy, text, *args, **kwargs):
                    if xy[0] == 54 and kwargs.get("fill") == "white":
                        drawn.append((text, draw.textbbox(xy, text, font=kwargs["font"], anchor=kwargs["anchor"])))
                    return original_text(draw, xy, text, *args, **kwargs)

                with self.app.app_context():
                    database.get_db().execute("UPDATE dives SET site_name = ? WHERE id = 1", (title,))
                    database.get_db().commit()
                with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                    response = self.client.get("/share/dive/1/preview.jpg")
                self.assertEqual(response.status_code, 200)
                self.assertEqual("".join(text for text, _ in drawn).replace(" ", ""), title.replace(" ", ""))
                for text, (left, top, right, bottom) in drawn:
                    self.assertNotIn("…", text)
                    self.assertGreaterEqual(left, 50)
                    self.assertLessEqual(right, 788)
                    self.assertGreaterEqual(top, 150)
                    self.assertLessEqual(bottom, 324)
                if title == "NorthwesternSanctuary Entrance":
                    self.assertIn("NorthwesternSanctuary", [text for text, _ in drawn])
                if title == "Kicker Rock (Leon Dormido)":
                    self.assertEqual([text for text, _ in drawn], ["Kicker Rock", "(Leon Dormido)"])


if __name__ == "__main__":
    unittest.main()
