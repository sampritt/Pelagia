import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database
from pelagia.feed_report import select_followed_site


def site(site_id, latitude, longitude, followed_at='2026-10-01 12:00:00'):
    return dict(id=site_id, name=f'Site {site_id}', country_or_area='Ocean',
                latitude=latitude, longitude=longitude, followed_at=followed_at)


class FeedReportSelectionTest(unittest.TestCase):
    def select(self, sites, instant):
        return select_followed_site(sites, datetime.fromisoformat(instant))

    def test_switches_at_midnight_using_coordinates_without_forecast_caches(self):
        california = site(1, 36.612, -121.902)
        galapagos = site(2, -.392, -90.287, '2026-11-01 12:00:00')
        sites = [galapagos, california]
        selected, _, next_refresh = self.select(sites, '2026-11-03T07:59:59+00:00')
        self.assertEqual(selected['id'], 2)
        self.assertEqual(next_refresh, datetime.fromisoformat('2026-11-03T08:00:00+00:00').timestamp())
        self.assertEqual(self.select(sites, '2026-11-03T08:00:00+00:00')[0]['id'], 1)

    def test_equal_midnights_use_recent_follow_even_across_the_date_line(self):
        kiribati = site(1, 1.8721, -157.4278, '2026-11-01 12:00:00')
        hawaii = site(2, 21.3069, -157.8583, '2026-11-02 12:00:00')
        selected, local_date, _ = self.select([kiribati, hawaii], '2026-11-03T11:00:00+00:00')
        self.assertEqual(selected['id'], 2)
        self.assertEqual(str(local_date), '2026-11-03')

    def test_dst_uses_the_offset_at_midnight_instead_of_the_current_offset(self):
        new_york = site(1, 40.7128, -74.006, '2026-11-01 06:00:00')
        lima = site(2, -12.0464, -77.0428)
        self.assertEqual(self.select([new_york, lima], '2026-11-01T07:00:00+00:00')[0]['id'], 2)

    def test_fractional_hour_timezones_are_not_rounded_to_longitude_bands(self):
        nepal = site(1, 27.7172, 85.3240, '2026-11-02 12:00:00')
        india = site(2, 19.0760, 72.8777)
        self.assertEqual(self.select([nepal, india], '2026-11-03T18:45:00+00:00')[0]['id'], 2)

    def test_next_midnight_observes_the_short_day_at_spring_forward(self):
        _, _, next_refresh = self.select([site(1, 40.7128, -74.006)], '2026-03-08T05:30:00+00:00')
        self.assertEqual(next_refresh, datetime.fromisoformat('2026-03-09T04:00:00+00:00').timestamp())

    def test_missing_coordinates_fall_back_to_follow_recency(self):
        unknown = site(1, None, None, '2026-11-02 12:00:00')
        invalid = site(2, 1000, float('nan'))
        california = site(3, 36.612, -121.902)
        self.assertEqual(self.select([unknown, invalid], '2026-11-03T09:00:00+00:00')[0]['id'], 1)
        self.assertEqual(self.select([unknown, california], '2026-11-03T09:00:00+00:00')[0]['id'], 3)


class FeedReportPageTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = self.make_app(Path(self.directory.name))
        self.client = self.app.test_client()
        self.signup(self.client)

    def test_featured_fallback_keeps_only_the_featured_badge_and_links_to_reports(self):
        with patch('pelagia.fetch_daily_featured_site', return_value=site(1, 36.612, -121.902)):
            for path in ('/home', '/feed', '/welcome'):
                html = self.client.get(path).get_data(as_text=True)
                self.assertEqual(html.count('class="site-report-card feed-site-report"'), 1)
                self.assertIn('class="site-report-card feed-site-report" href="/reports"', html)
                self.assertNotIn('DAILY REPORT', html)
                self.assertIn('<span class="site-report-featured">FEATURED</span>', html)

    def test_follows_suppress_featured_and_api_returns_only_the_selected_preview(self):
        self.client.post('/api/dive-sites/1/favorite')
        self.client.post('/api/dive-sites/2/favorite')
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_sites SET latitude=36.612, longitude=-121.902 WHERE id=1')
            db.execute('UPDATE dive_sites SET latitude=-.392, longitude=-90.287 WHERE id=2')
            db.commit()
        instant = datetime.fromisoformat('2026-11-03T08:30:00+00:00')
        with patch('pelagia.fetch_daily_featured_site') as featured, \
                patch('pelagia.feed_report.select_followed_site', side_effect=lambda sites: select_followed_site(sites, instant)), \
                patch('pelagia.site_reports.generate') as generate:
            html = self.client.get('/home').get_data(as_text=True)
            self.assertEqual(html.count('class="site-report-card feed-site-report"'), 1)
            self.assertIn('id="followedSiteTitle1"', html)
            self.assertNotIn('data-featured-site-report', html)
            response = self.client.get('/api/feed/site-report')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            payload = response.get_json()
            self.assertEqual(payload['key'], '1:2026-11-03')
            self.assertEqual(payload['html'].count('class="site-report-card feed-site-report"'), 1)
            self.assertIn('href="/reports"', payload['html'])
            self.assertGreater(payload['next_refresh'], instant.timestamp())
            featured.assert_not_called()
            generate.assert_not_called()

    def test_empty_selection_stays_hidden_and_api_requires_login(self):
        with patch('pelagia.fetch_daily_featured_site', return_value=None):
            payload = self.client.get('/api/feed/site-report').get_json()
            self.assertEqual(payload['html'], '')
            self.assertEqual(payload['key'], '')
            self.assertNotIn('class="site-report-card feed-site-report"', self.client.get('/home').get_data(as_text=True))
        self.assertEqual(self.app.test_client().get('/api/feed/site-report').status_code, 302)

    def test_following_the_current_featured_site_changes_the_refresh_key_and_badge(self):
        with patch('pelagia.fetch_daily_featured_site', return_value=site(1, 36.612, -121.902)):
            before = self.client.get('/api/feed/site-report').get_json()
        self.assertTrue(before['key'].endswith(':featured'))
        self.client.post('/api/dive-sites/1/favorite')
        with patch('pelagia.fetch_daily_featured_site') as featured:
            after = self.client.get('/api/feed/site-report').get_json()
            featured.assert_not_called()
        self.assertFalse(after['key'].endswith(':featured'))
        self.assertNotIn('>FEATURED</span>', after['html'])

    def test_bottom_navigation_order_and_active_states(self):
        for path, selected in (('/home', 'Home'), ('/reports', 'Reports'), ('/explore', 'Explore')):
            html = self.client.get(path).get_data(as_text=True)
            mobile = html.split('<nav class="mobile-nav"', 1)[1].split('</nav>', 1)[0]
            labels = ['Home', 'Reports', 'Log dive', 'Explore', 'Profile']
            positions = [mobile.index(f'<span>{label}</span>') for label in labels]
            self.assertEqual(positions, sorted(positions))
            active = mobile.split('class="active"', 1)[1].split('</a>', 1)[0]
            self.assertIn(f'<span>{selected}</span>', active)
            self.assertIn('aria-current="page"', active)


if __name__ == '__main__':
    unittest.main()
