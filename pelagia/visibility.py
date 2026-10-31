"""NOAA Kd490 histories and latest observations, cached independently per site."""
import csv
import io
import json
import math
import time
import uuid
from datetime import datetime
from urllib.parse import quote

import requests
from flask import current_app, jsonify

from .db import get_db
from .marine import coordinates
from . import water_type

BASE = 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/'
DATASETS = {'monthly': 'nesdisVHNSQkd490Monthly', 'daily': 'nesdisVHNkd490Daily'}
LABELS = ('Very poor', 'Poor', 'Fair', 'Good', 'Excellent')


def rating(kd):
    """Application clarity bands; these are not NOAA dive visibility categories."""
    if not isinstance(kd, (int, float)) or isinstance(kd, bool) or not math.isfinite(kd) or kd <= 0:
        return None
    return 5 if kd <= .05 else 4 if kd <= .10 else 3 if kd <= .20 else 2 if kd <= .30 else 1


def rows(dataset, query):
    response = requests.get(BASE + dataset + '.csv?' + quote(query, safe='[]():,.-'), timeout=(3, 20))
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    if 'time' not in (reader.fieldnames or []):
        raise ValueError('Unexpected NOAA response')
    next(reader, None)  # ERDDAP units row
    return list(reader)


def fetch(kind, lat, lon):
    dataset = DATASETS[kind]
    times = [r['time'] for r in rows(dataset, 'time')]
    # Use actual axis indices: date constraints can silently snap to other dates.
    deadline = time.monotonic() + 65
    found = {}
    chunk = 12 if kind == 'monthly' else 30
    for stop in range(len(times) - 1, -1, -chunk):
        if time.monotonic() > deadline:
            raise ValueError('NOAA search timed out')
        start = max(0, stop - chunk + 1)
        query = f'kd_490[{start}:1:{stop}][(0.0)][({lat})][({lon})]'
        for row in rows(dataset, query):
            kd = float(row['kd_490'])
            # ERDDAP replaces fill values with NaN. The NRT valid range is
            # 0.016–32; SQ values must also be positive and finite.
            if not math.isfinite(kd) or kd <= 0 or kd > 32 or (kind == 'daily' and kd < .016):
                continue
            stamp = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
            if stamp.timestamp() > time.time():
                continue
            score = rating(kd)
            point = dict(time=stamp.timestamp(), value=score, kd490=kd, label=LABELS[score - 1],
                         latitude=float(row['latitude']), longitude=float(row['longitude']),
                         dataset=dataset)
            # One monthly composite per month, one daily sample per date.
            key = row['time'][:7] if kind == 'monthly' else row['time'][:10]
            found[key] = point
        points = sorted(found.values(), key=lambda p: p['time'])
        if kind == 'monthly' and len(points) >= 12:
            return dict(status='complete', points=points[-12:])
        if kind == 'daily' and points:
            return dict(status='complete', latest=points[-1])
    if kind == 'daily':
        return dict(status='complete', latest=None)
    return dict(status='complete', points=sorted(found.values(), key=lambda p: p['time'])[-12:])


def load(site, kind, now):
    lat, lon = coordinates(site)
    db = get_db()
    token = uuid.uuid4().hex
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM visibility_cache WHERE site_id=? AND kind=?', (site['id'], kind)).fetchone()
        same = row is not None and row['latitude'] == lat and row['longitude'] == lon
        cached = json.loads(row['payload']) if same and row['payload'] else None
        if cached:
            cached['fetched_at'] = row['fetched_at']
        if same and row['expires_at'] > now and cached:
            db.commit()
            return cached, 200
        if same and (row['lease_until'] > now or row['retry_after'] > now):
            db.commit()
            if cached:
                return dict(cached, stale=True), 200
            pending = row['lease_until'] > now
            return dict(status='pending' if pending else 'unavailable'), 202 if pending else 503
        db.execute('''INSERT INTO visibility_cache (site_id, kind, latitude, longitude, lease_token, lease_until)
            VALUES (?,?,?,?,?,?) ON CONFLICT(site_id,kind) DO UPDATE SET latitude=excluded.latitude,
            longitude=excluded.longitude, lease_token=excluded.lease_token, lease_until=excluded.lease_until,
            payload=CASE WHEN latitude=excluded.latitude AND longitude=excluded.longitude THEN payload ELSE NULL END''',
            (site['id'], kind, lat, lon, token, now + 120))
        db.commit()
    except Exception:
        db.rollback()
        raise
    try:
        result = fetch(kind, lat, lon)
        fetched = time.time()
        result['fetched_at'] = fetched
        ttl = 7 * 86400 if kind == 'monthly' else 6 * 3600
        db.execute('''UPDATE visibility_cache SET payload=?, fetched_at=?, expires_at=?,
            lease_token=NULL, lease_until=0, retry_after=0 WHERE site_id=? AND kind=? AND lease_token=?''',
            (json.dumps(result, allow_nan=False), fetched, fetched + ttl, site['id'], kind, token))
        db.commit()
        return result, 200
    except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError):
        current_app.logger.warning('NOAA visibility unavailable for site %s (%s)', site['id'], kind)
        db.execute('''UPDATE visibility_cache SET lease_token=NULL, lease_until=0, retry_after=?
            WHERE site_id=? AND kind=? AND lease_token=?''', (time.time() + 300, site['id'], kind, token))
        db.commit()
        return (dict(cached, stale=True), 200) if cached else (dict(status='unavailable'), 503)


def init_app(app, login_required):
    @app.get('/api/dive-sites/<int:site_id>/visibility/<kind>')
    @login_required
    def api_site_visibility(site_id, kind):
        if kind not in DATASETS:
            return jsonify(status='unavailable'), 404
        site = get_db().execute('SELECT * FROM dive_sites WHERE id=?', (site_id,)).fetchone()
        if site is None:
            return jsonify(status='unavailable'), 404
        if coordinates(site) is None:
            return jsonify(status='unavailable', reason='coordinates')
        try:
            classification = water_type.classify_site(site)
            if classification['feature'] != 'OCEAN':
                return jsonify(status='not_ocean')
            result, status = load(site, kind, time.time())
        except water_type.ClassificationPending:
            result, status = dict(status='pending'), 202
        except (water_type.ClassificationRetryable, requests.RequestException, ValueError, TypeError, KeyError):
            result, status = dict(status='unavailable'), 503
        response = jsonify(result)
        response.status_code = status
        response.headers['Cache-Control'] = 'no-store'
        return response
