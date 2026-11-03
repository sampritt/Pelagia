import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database
from pelagia.feed_report import report_schedule


def site(site_id, latitude, longitude, followed_at='2026-10-01 12:00:00'):
    return dict(id=site_id, name=f'Site {site_id}', country_or_area='Ocean',
                latitude=latitude, longitude=longitude, followed_at=followed_at)


class FeedReportSelectionTest(unittest.TestCase):
    def select(self, sites, instant):
        return report_schedule(sites, datetime.fromisoformat(instant))

    def test_every_followed_site_stays_in_the_key_across_midnight(self):
        sites = [site(2, -.392, -90.287), site(1, 36.612, -121.902)]
        key, next_refresh = self.select(sites, '2026-11-03T07:59:59+00:00')
        self.assertEqual(key, '2:2026-11-03|1:2026-11-02')
        self.assertEqual(next_refresh, datetime.fromisoformat('2026-11-03T08:00:00+00:00').timestamp())
        self.assertEqual(self.select(sites, '2026-11-03T08:00:00+00:00')[0], '2:2026-11-03|1:2026-11-03')

    def test_refresh_observes_daylight_saving_and_fractional_offsets(self):
        _, next_refresh = self.select([site(1, 40.7128, -74.006)], '2026-03-08T05:30:00+00:00')
        self.assertEqual(next_refresh, datetime.fromisoformat('2026-03-09T04:00:00+00:00').timestamp())
        key, next_refresh = self.select([site(1, 27.7172, 85.3240)], '2026-11-03T18:14:00+00:00')
        self.assertEqual(key, '1:2026-11-03')
        self.assertEqual(next_refresh, datetime.fromisoformat('2026-11-03T18:15:00+00:00').timestamp())

    def test_missing_coordinates_keep_all_sites_and_refresh_at_utc_midnight(self):
        sites = [site(1, None, None), site(2, 1000, float('nan'))]
        key, next_refresh = self.select(sites, '2026-11-03T09:00:00+00:00')
        self.assertEqual(key, '1:2026-11-03|2:2026-11-03')
        self.assertEqual(next_refresh, datetime.fromisoformat('2026-11-04T00:00:00+00:00').timestamp())


class FeedReportPageTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = self.make_app(Path(self.directory.name))
        self.client = self.app.test_client()
        self.signup(self.client)

    def test_featured_fallback_is_a_full_card_linking_to_the_daily_site_report(self):
        with patch('pelagia.fetch_daily_featured_site', return_value=site(1, 36.612, -121.902)):
            for path in ('/home', '/feed', '/welcome'):
                html = self.client.get(path).get_data(as_text=True)
                self.assertEqual(html.count('class="site-report-card feed-site-report"'), 1)
                self.assertIn('class="site-report-card feed-site-report" href="/dive-sites/1#daily-report"', html)
                self.assertIn('data-followed-swell', html)
                self.assertIn('data-followed-wind', html)
                self.assertNotIn('site-report-read-more', html)
                self.assertNotIn('data-report-dot=', html)
                self.assertIn('<span class="site-report-featured">FEATURED</span>', html)

    def test_follows_suppress_featured_and_api_returns_every_full_card(self):
        self.client.post('/api/dive-sites/1/favorite')
        self.client.post('/api/dive-sites/2/favorite')
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_sites SET latitude=36.612, longitude=-121.902 WHERE id=1')
            db.execute('UPDATE dive_sites SET latitude=-.392, longitude=-90.287 WHERE id=2')
            db.commit()
        instant = datetime.fromisoformat('2026-11-03T08:30:00+00:00')
        with patch('pelagia.fetch_daily_featured_site') as featured, \
                patch('pelagia.feed_report.report_schedule', side_effect=lambda sites: report_schedule(sites, instant)), \
                patch('pelagia.site_reports.generate') as generate:
            html = self.client.get('/home').get_data(as_text=True)
            self.assertEqual(html.count('class="site-report-card feed-site-report"'), 2)
            self.assertEqual(html.count('data-report-dot='), 2)
            self.assertIn('id="followedSiteTitle2"', html)
            self.assertIn('id="followedSiteTitle1"', html)
            self.assertNotIn('data-featured-site-report', html)
            response = self.client.get('/api/feed/site-report')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            payload = response.get_json()
            self.assertEqual(set(payload['key'].split('|')), {'1:2026-11-03', '2:2026-11-03'})
            self.assertEqual(payload['html'].count('class="site-report-card feed-site-report"'), 2)
            self.assertIn('href="/dive-sites/1#daily-report"', payload['html'])
            self.assertIn('href="/dive-sites/2#daily-report"', payload['html'])
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

    def test_single_follow_has_no_pagination_and_ten_follows_all_have_cards(self):
        self.client.post('/api/dive-sites/1/favorite')
        with patch('pelagia.fetch_daily_featured_site') as featured:
            html = self.client.get('/home').get_data(as_text=True)
            self.assertEqual(html.count('data-followed-site-report'), 1)
            self.assertNotIn('data-report-dot=', html)
            featured.assert_not_called()
        with self.app.app_context():
            db = database.get_db()
            db.executemany(
                "INSERT INTO dive_sites (id, master_site_id, name, country_or_area) VALUES (?, ?, ?, 'Ocean')",
                [(i, f'EXTRA-{i}', f'Site {i}') for i in range(4, 11)],
            )
            db.commit()
        for site_id in range(2, 11):
            self.assertEqual(self.client.post(f'/api/dive-sites/{site_id}/favorite').status_code, 200)
        with patch('pelagia.fetch_daily_featured_site') as featured:
            html = self.client.get('/api/feed/site-report').get_json()['html']
            self.assertEqual(html.count('data-followed-site-report'), 10)
            self.assertEqual(html.count('data-report-dot='), 10)
            for site_id in range(1, 11):
                self.assertEqual(html.count(f'href="/dive-sites/{site_id}#daily-report"'), 1)
            featured.assert_not_called()

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
