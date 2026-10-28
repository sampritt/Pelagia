"""On-demand marine forecasts, shared across workers with short SQLite leases."""
import json
import math
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from flask import current_app, jsonify, session, url_for
from .db import get_db
from .exposure_recommendations import recommend
from . import water_type

FIELDS = ('ocean_current_velocity', 'sea_level_height_msl', 'sea_surface_temperature')
FIELD_UNITS = dict(zip(FIELDS, ('kn', 'm', '°C')))
NONNEGATIVE_FIELDS = {'ocean_current_velocity'}
WEATHER_FIELDS = ('wind_speed_10m', 'wind_direction_10m')
WEATHER_UNITS = dict(zip(WEATHER_FIELDS, ('kn', '°')))
MOON_PHASES = ('New', 'First Quarter', 'Full', 'Last Quarter')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def strength(value):
    if not number(value) or value < 0:
        return '-'
    return 'Light' if value < .5 else 'Moderate' if value < 1 else 'Strong' if value < 2 else 'Very Strong'


def moon_phase(value):
    """Nearest major phase, including wraparound at new moon."""
    if not number(value) or not 0 <= value <= 1:
        return None
    quarter = math.floor(value * 4 + .5)
    return MOON_PHASES[quarter % 4]


def coordinates(site):
    try:
        lat, lon = float(site['latitude']), float(site['longitude'])
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (ValueError, TypeError):
        pass
    return None


def tide_phase(points, now):
    """Find extrema including plateaus; never bridge a gap in hourly samples."""
    extrema = []
    i = 1
    while i < len(points) - 1:
        start = i
        while i + 1 < len(points) and points[i + 1]['value'] == points[start]['value']:
            i += 1
        end = i
        window = points[start - 1:end + 2]
        if end + 1 < len(points) and all(number(p['value']) for p in window) and all(
            b['time'] - a['time'] == 3600 for a, b in zip(window, window[1:])
        ):
            before, value, after = points[start - 1]['value'], points[start]['value'], points[end + 1]['value']
            kind = 'High' if value > before and value > after else 'Low' if value < before and value < after else None
            if kind:
                extrema.append(((points[start]['time'] + points[end]['time']) / 2, kind))
        i += 1
    near = [(abs(t - now), t, label) for t, label in extrema if abs(t - now) <= 3600]
    if near:
        return min(near)[2]
    hour = points[0]['time'] + int((now - points[0]['time']) // 3600) * 3600
    # At an exact hour use one sample on each side; between hours use the enclosing pair.
    left = hour - 3600 if now == hour else hour
    right = hour + 3600
    lookup = {p['time']: p['value'] for p in points}
    required = (left, hour, right)
    if all(number(lookup.get(t)) for t in required):
        slope = lookup[right] - lookup[left]
        if slope:
            return 'Rising' if slope > 0 else 'Falling'
    return '-'


def validate(payload):
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('Invalid marine response')
    ZoneInfo(payload['timezone'])
    hourly = payload['hourly']
    times = hourly['time']
    if not isinstance(times, list) or len(times) < 2 or not all(number(t) for t in times):
        raise ValueError('Invalid timestamps')
    if any(b - a != 3600 for a, b in zip(times, times[1:])):
        raise ValueError('Invalid hourly interval')
    for field in FIELDS:
        values = hourly.get(field)
        if values is None:
            hourly[field] = [None] * len(times)
            continue
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError('Misaligned hourly arrays')
        if payload.get('hourly_units', {}).get(field) != FIELD_UNITS[field]:
            raise ValueError('Unexpected marine units')
        hourly[field] = [v if number(v) and (field not in NONNEGATIVE_FIELDS or v >= 0) else None for v in values]
    current = payload.get('current')
    if not isinstance(current, dict):
        payload['current'] = {}
    else:
        for field in (*FIELDS, 'time'):
            if not number(current.get(field)):
                current[field] = None
    return payload


def validate_weather(payload):
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('Invalid weather response')
    ZoneInfo(payload['timezone'])
    hourly = payload['hourly']
    times = hourly['time']
    if not isinstance(times, list) or not times or not all(number(t) for t in times):
        raise ValueError('Invalid weather timestamps')
    if any(b - a != 3600 for a, b in zip(times, times[1:])):
        raise ValueError('Invalid weather hourly interval')
    for field in WEATHER_FIELDS:
        values = hourly.get(field)
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError('Misaligned weather hourly arrays')
        if payload.get('hourly_units', {}).get(field) != WEATHER_UNITS[field]:
            raise ValueError('Unexpected weather units')
        if field == 'wind_speed_10m':
            hourly[field] = [v if number(v) and v >= 0 else None for v in values]
        else:
            hourly[field] = [v if number(v) and 0 <= v <= 360 else None for v in values]
    daily = payload['daily']
    daily_times, phases = daily['time'], daily['moon_phase']
    if (not isinstance(daily_times, list) or not all(number(t) for t in daily_times)
            or not isinstance(phases, list) or len(phases) != len(daily_times)
            or payload.get('daily_units', {}).get('moon_phase') != 'fraction'):
        raise ValueError('Invalid moon phase data')
    daily['moon_phase'] = [v if number(v) and 0 <= v <= 1 else None for v in phases]
    return payload


def trailing_month_range(now, zone):
    """Return the twelve complete calendar months before the site's current month."""
    current = datetime.fromtimestamp(now, zone).date().replace(day=1)
    month_index = current.year * 12 + current.month - 1 - 12
    start = current.replace(year=month_index // 12, month=month_index % 12 + 1)
    return start, current - timedelta(days=1)


def validate_rainfall(payload, start, end, zone):
    """Validate daily rain and reduce it to complete calendar-month totals."""
    if not isinstance(payload, dict) or payload.get('error') or payload.get('timezone') != str(zone):
        raise ValueError('Invalid rainfall response')
    daily = payload.get('daily') or {}
    times, values = daily.get('time'), daily.get('rain_sum')
    if (not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values)
            or payload.get('daily_units', {}).get('rain_sum') != 'mm'):
        raise ValueError('Invalid rainfall arrays')
    expected = []
    day = start
    while day <= end:
        expected.append(day.isoformat())
        day += timedelta(days=1)
    if times != expected or not all(number(value) and value >= 0 for value in values):
        raise ValueError('Incomplete rainfall history')
    totals = {}
    for stamp, value in zip(times, values):
        day = datetime.strptime(stamp, '%Y-%m-%d').date()
        totals[(day.year, day.month)] = totals.get((day.year, day.month), 0) + value
    points = []
    year, month = start.year, start.month
    for _ in range(12):
        points.append(dict(time=datetime(year, month, 1, tzinfo=zone).timestamp(),
                           value=round(totals[(year, month)], 2)))
        month = month % 12 + 1
        if month == 1:
            year += 1
    return points


def normalize(payload, now, fetched):
    zone = ZoneInfo(payload['timezone'])
    today = datetime.fromtimestamp(now, zone).date()
    times = payload['hourly']['time']
    series = {field: [dict(time=t, value=v) for t, v in zip(times, payload['hourly'].get(field, [None] * len(times)))] for field in FIELDS}
    hour = times[0] + int((now - times[0]) // 3600) * 3600
    current = payload.get('current') or {}
    current_time = current.get('time')
    fresh = number(current_time) and abs(now - current_time) <= 1800
    values, timestamps = {}, {}
    for field in FIELDS:
        value = current.get(field)
        valid = number(value) and (field not in NONNEGATIVE_FIELDS or value >= 0)
        if fresh and valid and payload.get('current_units', {}).get(field) == FIELD_UNITS[field]:
            values[field], timestamps[field] = value, current_time
        else:
            values[field] = next((p['value'] for p in series[field] if p['time'] == hour), None)
            timestamps[field] = hour if values[field] is not None else None
    daily = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        samples = [p['value'] for p in series[FIELDS[0]] if datetime.fromtimestamp(p['time'], zone).date() == day and number(p['value'])]
        daily.append(dict(time=datetime.combine(day, datetime.min.time(), zone).timestamp(), value=max(samples) if samples else None))
    def window(field, count):
        lookup = {p['time']: p['value'] for p in series[field]}
        return [dict(time=hour + i * 3600, value=lookup.get(hour + i * 3600)) for i in range(count)]
    weather = payload.get('weather') or {}
    weather_hourly = weather.get('hourly') or {}
    weather_times = weather_hourly.get('time') or []
    wind = []
    speed_lookup = dict(zip(weather_times, weather_hourly.get('wind_speed_10m') or []))
    direction_lookup = dict(zip(weather_times, weather_hourly.get('wind_direction_10m') or []))
    for i in range(48):
        timestamp = hour + i * 3600
        wind.append(dict(time=timestamp, speed_kn=speed_lookup.get(timestamp),
                         direction_deg=direction_lookup.get(timestamp)))
    wind_speed = speed_lookup.get(hour)
    timestamps['wind_speed_10m'] = hour if number(wind_speed) else None
    wind_daily = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        samples = [(t, speed) for t, speed in speed_lookup.items()
                   if number(speed) and datetime.fromtimestamp(t, zone).date() == day]
        peak_time, peak = max(samples, key=lambda sample: sample[1]) if samples else (None, None)
        wind_daily.append(dict(time=datetime.combine(day, datetime.min.time(), zone).timestamp(),
                               value=peak, direction_deg=direction_lookup.get(peak_time)))
    weather_daily = weather.get('daily') or {}
    # Open-Meteo's daily Unix dates use its fixed utc_offset_seconds, even
    # across DST. Match calendar dates, then emit actual site-local midnights.
    offset = weather.get('utc_offset_seconds')
    daily_zone = timezone(timedelta(seconds=offset)) if number(offset) else zone
    phases = {datetime.fromtimestamp(t, daily_zone).date(): value for t, value in
              zip(weather_daily.get('time') or [], weather_daily.get('moon_phase') or [])}
    moon = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        timestamp = datetime.combine(day, datetime.min.time(), zone).timestamp()
        phase = phases.get(day)
        moon.append(dict(time=timestamp, value=phase, phase=None))
    # One marker for the whole week: the closest daily sample to any major
    # phase. Round distance noise so equally close days choose the earlier day.
    closest_moon = min((point for point in moon if moon_phase(point['value']) is not None),
                       key=lambda point: (round(abs(point['value'] * 4 - math.floor(point['value'] * 4 + .5)), 12),
                                          point['time']), default=None)
    if closest_moon is not None:
        closest_moon['phase'] = moon_phase(closest_moon['value'])
    return dict(status='complete', timezone=payload['timezone'], fetched_at=fetched,
                current=dict(velocity_kn=values[FIELDS[0]], strength=strength(values[FIELDS[0]]),
                             temperature_c=values[FIELDS[2]], sea_level_m=values[FIELDS[1]],
                             wind_speed_kn=wind_speed,
                             moon_phase=moon_phase(moon[0]['value']),
                             tide=tide_phase(series[FIELDS[1]], now), timestamps=timestamps),
                charts=dict(rainfall_monthly=payload.get('rainfall_monthly') or [],
                            current_daily=daily, current_hourly=window(FIELDS[0], 48),
                            tide_hourly=window(FIELDS[1], 24),
                            wind_hourly=wind, wind_daily=wind_daily, moon_phase_daily=moon))


def request_json(url, params):
    response = requests.get(url, params=params, timeout=(3, 10))
    response.raise_for_status()
    return response.json()


def fetch(lat, lon, now=None):
    now = time.time() if now is None else now
    key = current_app.config.get('OPEN_METEO_API_KEY') or os.environ.get('OPEN_METEO_API_KEY')
    common = dict(latitude=lat, longitude=lon, forecast_days=7, past_days=1,
                  timezone='auto', timeformat='unixtime', wind_speed_unit='kn')
    marine_params = dict(common, hourly=','.join(FIELDS), current=','.join(FIELDS),
                         cell_selection='sea', temperature_unit='celsius', length_unit='metric')
    weather_params = dict(common, hourly=','.join(WEATHER_FIELDS), daily='moon_phase')
    if key:
        marine_params['apikey'] = weather_params['apikey'] = key
    marine_host = 'customer-marine-api.open-meteo.com' if key else 'marine-api.open-meteo.com'
    weather_host = 'customer-api.open-meteo.com' if key else 'api.open-meteo.com'
    with ThreadPoolExecutor(max_workers=2) as pool:
        marine_future = pool.submit(request_json, f'https://{marine_host}/v1/marine', marine_params)
        weather_future = pool.submit(request_json, f'https://{weather_host}/v1/forecast', weather_params)
        marine_payload = validate(marine_future.result())
        weather_payload = validate_weather(weather_future.result())
    if weather_payload['timezone'] != marine_payload['timezone']:
        raise ValueError('Mismatched forecast timezones')
    marine_payload['weather'] = weather_payload
    zone = ZoneInfo(marine_payload['timezone'])
    start, end = trailing_month_range(now, zone)
    rainfall_params = dict(latitude=lat, longitude=lon, start_date=start.isoformat(),
                           end_date=end.isoformat(), daily='rain_sum', timezone=str(zone),
                           precipitation_unit='mm', cell_selection='nearest')
    if key:
        rainfall_params['apikey'] = key
    archive_host = 'customer-archive-api.open-meteo.com' if key else 'archive-api.open-meteo.com'
    rainfall_payload = request_json(f'https://{archive_host}/v1/archive', rainfall_params)
    marine_payload['rainfall_monthly'] = validate_rainfall(rainfall_payload, start, end, zone)
    return marine_payload


def load(site, now):
    coords = coordinates(site)
    if coords is None:
        return dict(status='unavailable', reason='coordinates'), 200
    lat, lon = coords
    db = get_db()
    token = uuid.uuid4().hex
    # Claim and recheck atomically, then release the lock before upstream I/O.
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM marine_forecast_cache WHERE site_id = ?', (site['id'],)).fetchone()
        same = row is not None and row['latitude'] == lat and row['longitude'] == lon
        if same and row['expires_at'] > now and row['payload']:
            db.commit()
            return normalize(json.loads(row['payload']), now, row['fetched_at']), 200
        if same and row['lease_until'] > now:
            db.commit()
            return dict(status='pending'), 202
        if same and row['retry_after'] > now:
            db.commit()
            return dict(status='unavailable', reason='upstream'), 503
        db.execute('''INSERT INTO marine_forecast_cache
            (site_id, latitude, longitude, lease_token, lease_until)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(site_id) DO UPDATE SET
            latitude=excluded.latitude, longitude=excluded.longitude, lease_token=excluded.lease_token,
            lease_until=excluded.lease_until, expires_at=0, payload=NULL, retry_after=0''',
            (site['id'], lat, lon, token, now + 30))
        db.commit()
    except Exception:
        db.rollback()
        raise
    try:
        payload = fetch(lat, lon, now)
        fetched = time.time()
        zone = ZoneInfo(payload['timezone'])
        tomorrow = datetime.fromtimestamp(fetched, zone).date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, datetime.min.time(), zone).timestamp()
        result = normalize(payload, now, fetched)
        db.execute('''UPDATE marine_forecast_cache SET payload=?, fetched_at=?, expires_at=?,
                   lease_until=0, lease_token=NULL, retry_after=0 WHERE site_id=? AND lease_token=?''',
                   (json.dumps(payload, allow_nan=False), fetched, min(fetched + 900, midnight), site['id'], token))
        db.commit()
        return result, 200
    except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError, ZoneInfoNotFoundError):
        current_app.logger.warning('Marine forecast unavailable for site %s', site['id'])
        db.execute('''UPDATE marine_forecast_cache SET lease_until=0, lease_token=NULL, retry_after=?
                   WHERE site_id=? AND lease_token=?''', (time.time() + 60, site['id'], token))
        db.commit()
        return dict(status='unavailable', reason='upstream'), 503


def init_app(app, login_required):
    @app.get('/api/dive-sites/<int:site_id>/conditions')
    @login_required
    def api_site_conditions(site_id):
        site = get_db().execute('SELECT * FROM dive_sites WHERE id=?', (site_id,)).fetchone()
        if site is None:
            result, status = dict(status='unavailable'), 404
        elif coordinates(site) is None:
            result, status = dict(status='unavailable', reason='coordinates'), 200
        else:
            try:
                classification = water_type.classify_site(site)
            except water_type.ClassificationPending:
                result, status = dict(status='pending'), 202
            except water_type.ClassificationRetryable:
                result, status = dict(status='unavailable', reason='classification'), 503
            except (requests.RequestException, ValueError, TypeError, KeyError):
                current_app.logger.warning('Water classification unavailable for site %s', site['id'])
                result, status = dict(status='unavailable', reason='classification'), 503
            else:
                if classification['feature'] == 'OCEAN':
                    result, status = load(site, time.time())
                else:
                    result, status = dict(status='not_ocean', feature=classification['feature']), 200
        if status == 200 and result.get('status') == 'complete':
            from . import dive_site_recent_conditions
            logged_temperature = dive_site_recent_conditions(site_id)['water_temp_c']
            if logged_temperature is not None:
                result['current']['temperature_c'] = logged_temperature
            result['recommendations'] = recommend(get_db(), session['user_id'], site_id,
                                                   result['current']['temperature_c'], time.time(),
                                                   salinity=classification['water_type'])
            advice = result['recommendations']
            if advice and advice['source_dive_id']:
                advice['source_dive_url'] = url_for('dive_detail', dive_id=advice['source_dive_id'])
        response = jsonify(result)
        response.status_code = status
        response.headers['Cache-Control'] = 'private, no-store'
        if status in (202, 503):
            response.headers['Retry-After'] = '2' if status == 202 else '60'
        return response
