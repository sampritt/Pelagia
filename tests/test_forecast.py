from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_reference_autocomplete as fixtures
from test_marine import payload, NOW
from pelagia import marine


class ForecastTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def test_calendar_days_have_eight_local_slots_in_offset_and_dst_zones(self):
        for name, stamp in [('Asia/Kathmandu', '2026-11-06T23:00:00+00:00'),
                            ('America/New_York', '2026-11-01T05:15:00+00:00'),
                            ('America/New_York', '2026-03-08T05:15:00+00:00')]:
            zone = ZoneInfo(name)
            now = datetime.fromisoformat(stamp).timestamp()
            days = marine.forecast_days(now, zone)
            self.assertEqual(len(days), 7)
            self.assertEqual(days[0]['date'], datetime.fromtimestamp(now, zone).date().isoformat())
            for day in days:
                self.assertEqual([datetime.fromtimestamp(t, zone).hour for t in day['times']], list(range(0, 24, 3)))
                self.assertTrue(all(datetime.fromtimestamp(t, zone).minute == 0 for t in day['times']))
                self.assertEqual(datetime.fromtimestamp(day['end'], zone).hour, 0)
            if name == 'America/New_York':
                self.assertEqual((days[0]['end'] - days[0]['start']) / 3600, 25 if '-11-' in stamp else 23)

    def test_forecast_joins_each_sample_by_time_and_includes_all_day_tide_extrema(self):
        raw = payload()
        times = raw['weather']['hourly']['time']
        raw['weather']['hourly']['temperature_2m'] = [10 + i / 10 for i in range(len(times))]
        raw['weather']['hourly_units']['temperature_2m'] = '°C'
        result = marine.normalize(raw, NOW, NOW)
        self.assertEqual(len(result['forecast']['days']), 7)
        for day in result['forecast']['days']:
            self.assertEqual(len(day['slots']), 8)
            self.assertEqual(day['tide'][0]['time'], day['start'])
            self.assertEqual(day['tide'][-1]['time'], day['end'])
            self.assertTrue(day['extrema'])
            for event in day['extrema']:
                self.assertTrue(day['start'] <= event['time'] < day['end'])
                self.assertIn(event['kind'], ['High', 'Low'])
            for slot in day['slots']:
                i = times.index(slot['time'])
                self.assertEqual(slot['current_kn'], .4)
                self.assertEqual(slot['wind_speed_kn'], 12.3)
                self.assertEqual(slot['wind_direction_deg'], 225)
                self.assertEqual(slot['water_temperature_c'], 28.1)
                self.assertEqual(slot['air_temperature_c'], 10 + i / 10)
                self.assertEqual(slot['swell_height_m'], .8)
                self.assertEqual(slot['swell_period_s'], 8)

    def test_tide_turns_fit_subhour_vertices_and_preserve_plateaus_and_gaps(self):
        for sign, kind in [(-1, 'High'), (1, 'Low')]:
            points = [dict(time=i * 3600, value=sign * (i - 1.25) ** 2) for i in range(3)]
            turn, = marine.tide_turns(points)
            self.assertEqual(turn['kind'], kind)
            self.assertAlmostEqual(turn['time'], 4500)  # 1:15, not the sampled 1:00.
            self.assertAlmostEqual(turn['value'], 0)
        plateau = [dict(time=i * 3600, value=v) for i, v in enumerate([0, 2, 2, 0])]
        self.assertEqual(marine.tide_turns(plateau), [dict(time=5400, value=2, kind='High')])
        for values in ([0, None, 0], [None, 2, 0], [0, 2, None], [1, 1, 1], [0, 1, 2]):
            self.assertEqual(marine.tide_turns([dict(time=i * 3600, value=v) for i, v in enumerate(values)]), [])
        self.assertEqual(marine.tide_turns([dict(time=t, value=v) for t, v in [(0, 0), (7200, 2), (10800, 0)]]), [])

    def test_refined_turns_stay_on_curve_and_belong_to_correct_local_day(self):
        start = marine.forecast_days(NOW, ZoneInfo('Pacific/Galapagos'))[0]['start']
        for minutes, day_index in [(15, 0), (24 * 60 - 15, 0), (24 * 60 + 15, 1)]:
            raw = payload()
            vertex = start + minutes * 60
            raw['hourly']['sea_level_height_msl'] = [-((t - vertex) / 3600) ** 2 for t in raw['hourly']['time']]
            days = marine.normalize(raw, NOW, NOW)['forecast']['days']
            self.assertEqual(sum(len(day['extrema']) for day in days), 1)
            event, = days[day_index]['extrema']
            self.assertAlmostEqual(event['time'], vertex)
            self.assertAlmostEqual(event['value'], 0)
            self.assertIn(dict(time=event['time'], value=event['value']), days[day_index]['tide'])

    def test_missing_air_temperature_is_unavailable_and_negative_air_is_valid(self):
        raw = payload()
        result = marine.normalize(raw, NOW, NOW)
        self.assertTrue(all(slot['air_temperature_c'] is None for day in result['forecast']['days'] for slot in day['slots']))
        weather = raw['weather']
        weather['hourly']['temperature_2m'] = [-6] * len(weather['hourly']['time'])
        weather['hourly_units']['temperature_2m'] = '°C'
        marine.validate_weather(weather)
        self.assertEqual(marine.normalize(raw, NOW, NOW)['forecast']['days'][0]['slots'][0]['air_temperature_c'], -6)
        weather['hourly_units']['temperature_2m'] = '°F'
        with self.assertRaises(ValueError):
            marine.validate_weather(weather)

    def test_fractional_zone_samples_interpolate_without_bridging_missing_data(self):
        raw = payload('Asia/Kathmandu')
        times = raw['hourly']['time']
        day = marine.forecast_days(NOW, ZoneInfo(raw['timezone']))[0]
        stamp = day['times'][0]
        before = max(i for i, t in enumerate(times) if t < stamp)
        fraction = (stamp - times[before]) / 3600
        raw['hourly']['ocean_current_velocity'][before] = 1
        raw['hourly']['ocean_current_velocity'][before + 1] = 2
        raw['weather']['hourly']['wind_direction_10m'][before] = 350
        raw['weather']['hourly']['wind_direction_10m'][before + 1] = 10
        slot = marine.normalize(raw, NOW, NOW)['forecast']['days'][0]['slots'][0]
        self.assertEqual(slot['time'], stamp)
        self.assertAlmostEqual(slot['current_kn'], 1 + fraction)
        self.assertAlmostEqual(slot['wind_direction_deg'], (350 + 20 * fraction) % 360)
        raw['hourly']['ocean_current_velocity'][before + 1] = None
        slot = marine.normalize(raw, NOW, NOW)['forecast']['days'][0]['slots'][0]
        self.assertIsNone(slot['current_kn'])

    def test_forecast_auth_followed_selection_and_featured_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _, _ = self.make_app(Path(tmp))
            client = app.test_client()
            self.assertEqual(client.get('/forecast').status_code, 302)
            self.signup(client)
            with patch('pelagia.fetch_daily_featured_site', return_value=dict(id=3, name='Featured Blue Wall', country_or_area='Bonaire', latitude=12.1, longitude=-68.2)):
                page = client.get('/forecast').get_data(as_text=True)
                self.assertIn('Featured Blue Wall', page)
                self.assertNotIn('Your forecast', page)
                self.assertNotIn('class="forecast-heading"', page)
                self.assertNotIn('data-forecast-local', page)
                self.assertIn('class="explore-filter"', page)
                self.assertIn('>Featured Blue Wall</button>', page)
                self.assertNotIn('data-forecast-dot=', page)
                self.assertNotIn('data-forecast-site="1"', page)
            for site_id in [1, 2]:
                self.assertEqual(client.post(f'/api/dive-sites/{site_id}/favorite').status_code, 200)
            with patch('pelagia.fetch_daily_featured_site') as featured:
                page = client.get('/forecast').get_data(as_text=True)
                featured.assert_not_called()
                self.assertEqual(page.count('data-forecast-site='), 2)
                self.assertEqual(page.count('data-forecast-select='), 2)
                self.assertEqual(page.count('data-forecast-day='), 7)
                self.assertIn('data-temperature-unit="c" data-length-unit="m"', page)
                self.assertIn('href="/forecast" aria-current="page"', page)
                self.assertLess(page.index('<span>Log dive</span>'), page.index('<span>Forecast</span>'))
                self.assertLess(page.index('<span>Forecast</span>'), page.index('<span>Profile</span>'))
                self.assertNotIn('data-forecast-site="3"', page)
                self.assertIn('js/forecast.js', page)
                self.assertNotIn('forecast-temperature-icon', page)
                self.assertIn('aria-label="Water temperature">Water</th>', page)
                self.assertIn('aria-label="Air temperature">Air</th>', page)
                self.assertNotIn('class="site-report-dot"', page)
                self.assertNotIn('data-forecast-dot=', page)
                self.assertNotIn('aria-roledescription="carousel"', page.split('data-forecast ', 1)[1].split('</section>', 1)[0])
                self.assertIn('scope="colgroup" colspan="2">Wind</th>', page)
                self.assertIn('scope="colgroup" colspan="2">Swell</th>', page)
                self.assertNotIn('>Direction</th>', page)
                self.assertNotIn('>Swell height</th>', page)
                self.assertNotIn('>Swell period</th>', page)
                self.assertIn('aria-controls="forecastSite1"', page)
                self.assertIn('aria-label="Kelp Garden" hidden inert', page)
                self.assertLess(page.index('class="forecast-dates"'), page.index('class="explore-filters forecast-navigation"'))
                self.assertLess(page.index('class="explore-filters forecast-navigation"'), page.index('class="forecast-card"'))
                for extra in ('data-forecast-prev', 'data-forecast-next', 'Regional surface forecast', 'data-tide-date'):
                    self.assertNotIn(extra, page)

    def test_no_featured_site_has_an_actionable_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _, _ = self.make_app(Path(tmp))
            client = app.test_client()
            self.signup(client)
            with patch('pelagia.fetch_daily_featured_site', return_value=None):
                page = client.get('/forecast').get_data(as_text=True)
            self.assertIn('Explore dive sites', page)
            self.assertNotIn('data-forecast-site=', page)

    def test_site_without_coordinates_still_has_a_week_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _, _ = self.make_app(Path(tmp))
            client = app.test_client()
            self.signup(client)
            with patch('pelagia.fetch_daily_featured_site', return_value=dict(
                id=3, name='Unknown location', latitude=None, longitude=None, country_or_area='')):
                page = client.get('/forecast').get_data(as_text=True)
            self.assertEqual(page.count('data-forecast-day='), 7)
            self.assertIn('data-coordinates="false"', page)
            self.assertIn('data-calendar-label>Today</span>', page)


if __name__ == '__main__':
    unittest.main()
