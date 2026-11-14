import io
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

import test_reference_autocomplete as fixtures
from pelagia import branding
from pelagia import db as database


class Metadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.images = []
        self.icons = []
        self.cards = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('property') == 'og:image':
            self.images.append(attrs['content'])
        if tag == 'meta' and attrs.get('name') == 'twitter:card':
            self.cards.append(attrs['content'])
        if tag == 'link' and attrs.get('rel') == 'icon':
            self.icons.append(attrs['href'])


class BrandingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = fixtures.ReferenceAutocompleteTest().make_app(Path(self.directory.name))
        self.app.config['PUBLIC_BASE_URL'] = 'https://pelagia.example'
        self.client = self.app.test_client()
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (id, username) VALUES (1, 'diver')")
            db.execute("INSERT INTO dives (id, user_id, site_name, date) VALUES (1, 1, 'A reef', '2026-11-14')")
            db.commit()

    def test_public_pages_have_one_explicit_fin_preview_and_high_resolution_favicon(self):
        for path in ('/', '/login', '/signup', '/terms', '/privacy', '/dive-sites',
                     '/explore/dive-sites/1', '/share/dive-site/1',
                     '/explore/dive-centers/1', '/share/dive-center/1'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                metadata = Metadata(response.get_data(as_text=True))
                self.assertEqual(metadata.images, ['https://pelagia.example/brand/pelagia-fin-preview.png'])
                self.assertEqual(metadata.cards, ['summary_large_image'])
                self.assertEqual(metadata.icons, ['/brand/fin-icon-512.png'])

    def test_dive_preview_retains_its_own_image_and_requests_a_fresh_brand_version(self):
        metadata = Metadata(self.client.get('/share/dive/1').get_data(as_text=True))
        self.assertEqual(metadata.images, ['https://pelagia.example/share/dive/1/preview.jpg?brand=fin-v1'])
        self.assertEqual(metadata.cards, ['summary_large_image'])

    def test_fresh_icon_urls_serve_the_supplied_fin_artwork_and_work_offline(self):
        worker = self.client.get('/service-worker.js').get_data(as_text=True)
        for filename, source in branding.ASSETS.items():
            with self.subTest(filename=filename):
                response = self.client.get('/brand/' + filename)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, (Path(self.app.static_folder) / 'img' / source).read_bytes())
                self.assertIn('/brand/' + filename, worker)
                self.assertIn('max-age=0', response.headers['Cache-Control'])
                response.close()
        self.assertEqual(self.client.get('/brand/not-an-icon.png').status_code, 404)

    def test_root_favicon_has_small_and_large_frames(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/vnd.microsoft.icon')
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.format, 'ICO')
            self.assertTrue({(16, 16), (48, 48), (256, 256)}.issubset(image.ico.sizes()))

    def test_social_preview_is_rendered_and_revalidates(self):
        response = self.client.get('/brand/pelagia-fin-preview.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/png')
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))
            self.assertGreater(max(image.getextrema()[0]), 240)
        cached = self.client.get('/brand/pelagia-fin-preview.png', headers={'If-None-Match': response.headers['ETag']})
        self.assertEqual(cached.status_code, 304)
