import json
import unittest

from pelagia.depth_profile import depth_profile_chart


class ProfileChartTest(unittest.TestCase):
    def chart(self, points):
        data = {'version': 1, 'source': 'garmin', 'started_at': '2026-10-10T00:00:00+00:00',
                'bottom_time_seconds': 60, 'recording_duration_seconds': 60, 'depth_profile': points}
        class Database:
            def execute(self, *args):
                return self
            def fetchone(self):
                return {'data_json': json.dumps(data)}
        return depth_profile_chart(Database(), 1)

    def test_elapsed_time_and_inverted_depth_geometry(self):
        chart = self.chart([{'elapsed_seconds': t, 'depth_m': d} for t, d in [(0, 0), (15, 20), (60, 0)]])
        self.assertEqual(chart['line'], 'M 44.00,28.00 L 223.00,250.00 L 760.00,28.00')
        self.assertTrue(chart['fill'].endswith('L 760.00,28 L 44.00,28 Z'))

    def test_dense_profile_retains_brief_extremes_and_bounds_svg(self):
        points = [{'elapsed_seconds': i / 2000, 'depth_m': 40 if i == 23457 else 10} for i in range(100000)]
        chart = self.chart(points)
        self.assertEqual(chart['max_depth_m'], 40)
        self.assertIn(',250.00', chart['line'])
        self.assertLessEqual(chart['line'].count(' L '), 1201)
        self.assertEqual(len(points), 100000)

    def test_surface_only_profile_is_finite(self):
        chart = self.chart([{'elapsed_seconds': t, 'depth_m': 0} for t in (0, 60)])
        self.assertNotIn('nan', chart['line'])
        self.assertEqual(chart['max_depth_m'], 0)


class FeedGalleryTest(unittest.TestCase):
    def render_gallery(self, *, chart=True, coords=True, photos=2, feed=True, public=False):
        from pathlib import Path
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'pelagia/templates'),
                          autoescape=select_autoescape(['html']))
        env.globals.update(display_metric=lambda value, unit, **kwargs: f'{value} m',
                           display_unit=lambda unit: 'm', uploaded_file_url=lambda name: f'/uploads/{name}')
        dive = {'id': 1, 'site_name': 'Reef', 'latitude': 12, 'longitude': 34,
                'photos': [{'filename': f'{i}.jpg'} for i in range(photos)]}
        profile = {'max_depth_m': 30, 'duration_minutes': 40, 'fill': '', 'line': ''} if chart else None
        return env.get_template('_dive_gallery.html').render(
            dive=dive, depth_chart=profile, public_preview=public, feed_gallery=feed, detail_gallery=not feed, has_coords=coords)

    def test_feed_orders_available_slides_without_indicators(self):
        html = self.render_gallery()
        self.assertLess(html.index('Dive location map'), html.index('Dive depth profile'))
        self.assertLess(html.index('Dive depth profile'), html.index('/uploads/0.jpg'))
        self.assertLess(html.index('/uploads/0.jpg'), html.index('/uploads/1.jpg'))
        self.assertNotIn('data-gallery-dot', html)

    def test_feed_omits_missing_visuals(self):
        html = self.render_gallery(chart=False, coords=False, photos=1)
        self.assertNotIn('Dive depth profile', html)
        self.assertNotIn('Dive location map', html)
        self.assertIn('/uploads/0.jpg', html)
        self.assertNotIn('data-dive-gallery', self.render_gallery(chart=False, coords=False, photos=0))

    def test_detail_gallery_starts_with_map_and_public_preview_hides_depth(self):
        detail = self.render_gallery(feed=False)
        self.assertLess(detail.index('Dive location map'), detail.index('Dive depth profile'))
        self.assertIn('data-gallery-dot', detail)
        public = self.render_gallery(feed=False, public=True)
        self.assertIn('Dive location map', public)
        self.assertIn('/uploads/0.jpg', public)
        self.assertNotIn('Dive depth profile', public)
        self.assertNotIn('data-gallery-dot', self.render_gallery(feed=False, chart=False, photos=0))
