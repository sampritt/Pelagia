"""Daily satellite attenuation history; bounded I/O isolated from web workers."""
import base64
import configparser
import os
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASETS = ('cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D',
            'cmems_obs-oc_glo_bgc-transp_nrt_l3-multi-4km_P1D')


def clarity(value):
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    for upper, label in ((.04, 'excellent'), (.095, 'good'), (.19, 'fair'), (.29, 'poor')):
        if value <= upper:
            return label
    return 'very poor'


def distance(lat, lon, la, ln):
    a, b = math.radians(lat), math.radians(la)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(ln-lon)/2)**2
    return 12742.0176 * math.asin(math.sqrt(min(1, max(0, h))))


def credentials():
    """Accept the encoded contents produced by `copernicusmarine login`."""
    encoded = os.environ.get('COPERNICUS_MARINE_CREDS', '').strip()
    if not encoded:
        return {}  # Toolbox's normal environment variables / local credential file.
    try:
        config = configparser.RawConfigParser()
        config.read_string(base64.b64decode(''.join(encoded.split()), validate=True).decode('utf-8'))
        username, password = config.get('credentials', 'username'), config.get('credentials', 'password')
        if not username or not password:
            raise ValueError()
        return dict(username=username, password=password)
    except (ValueError, UnicodeError, configparser.Error):
        raise ValueError('Invalid COPERNICUS_MARINE_CREDS format') from None


def collect(lat, lon, now):
    import copernicusmarine
    import pandas as pd
    auth = credentials()
    end = datetime.fromtimestamp(now, timezone.utc).date()
    start = end - timedelta(days=6)
    delta = math.degrees(15 / 6371.0088)
    lat_lo, lat_hi = max(-90, lat-delta-.05), min(90, lat+delta+.05)
    lon_delta = 180 if abs(lat)+delta >= 90 else min(180, math.degrees(math.asin(min(1, math.sin(math.radians(delta))/math.cos(math.radians(lat)))))+.05)
    lo, hi = lon-lon_delta, lon+lon_delta
    ranges = [(-180, 180)] if lon_delta >= 180 else ([(lo+360, 180), (-180, hi)] if lo < -180 else [(lo, 180), (-180, hi-360)] if hi > 180 else [(lo, hi)])

    def query_source(item):
        selected, retrieved, failures = {}, set(), 0
        priority, dataset = item
        for lo, hi in ranges:
            try:
                frame = copernicusmarine.read_dataframe(
                    dataset_id=dataset, variables=['KD490'], minimum_longitude=lo,
                    maximum_longitude=hi, minimum_latitude=lat_lo, maximum_latitude=lat_hi,
                    start_datetime=f'{start}T00:00:00', end_datetime=f'{end}T23:59:59',
                    coordinates_selection_method='inside', disable_progress_bar=True, **auth)
                if frame is None:
                    raise ValueError('No data returned')
                frame = frame.reset_index()
                for row in frame.itertuples(index=False):
                    day = pd.Timestamp(row.time).date()
                    if not start <= day <= end:
                        continue
                    retrieved.add(day)
                    kd, la, ln = float(row.KD490), float(row.latitude), float(row.longitude)
                    if clarity(kd) is None or not math.isfinite(la) or not math.isfinite(ln):
                        continue
                    km = distance(lat, lon, la, ln)
                    key = (priority, km, la, ln)
                    if km <= 15 and (day not in selected or key < selected[day][0]):
                        selected[day] = (key, kd, dataset, la, ln, km)
            except Exception:
                failures += 1
        return selected, retrieved, failures

    selected = {}
    failures = 0
    for item in enumerate(DATASETS):
        pixels, _, errors = query_source(item)
        failures += errors
        for day, pixel in pixels.items():
            if day not in selected or pixel[0] < selected[day][0]:
                selected[day] = pixel
    if not selected:
        return dict(status='unavailable' if failures else 'no_data')
    day = max(selected)
    _, value, dataset, la, ln, km = selected[day]
    return dict(status='complete', date=day.isoformat(), value=value, clarity=clarity(value),
                dataset_id=dataset, latitude=la, longitude=ln, distance_km=round(km, 3))


def fetch(lat, lon, now):
    # The toolbox performs several remote reads without an overall deadline.
    # A child process enforces a hard bound and never holds a SQLite lock.
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                 str(lat), str(lon), str(now)], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=24, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError, OSError):
        return dict(status='unavailable')


def read_cache(site, now, zone):
    from .db import get_db
    from zoneinfo import ZoneInfo
    today = datetime.fromtimestamp(now, ZoneInfo(zone)).date().isoformat()
    row = get_db().execute('SELECT * FROM site_visibility_cache WHERE site_id=?', (site['id'],)).fetchone()
    if row is None or row['cache_date'] != today or not row['payload'] or (row['latitude'],row['longitude']) != (float(site['latitude']),float(site['longitude'])):
        return None
    payload = json.loads(row['payload'])
    if payload.get('status') == 'complete':
        try:
            observed = datetime.strptime(payload['date'], '%Y-%m-%d').date()
            today_utc = datetime.fromtimestamp(now, timezone.utc).date()
            if not today_utc - timedelta(days=6) <= observed <= today_utc:
                return dict(status='no_data')
            payload['clarity'] = clarity(payload.get('value'))
            if payload['clarity'] is None:
                return dict(status='no_data')
        except (KeyError, TypeError, ValueError):
            return dict(status='no_data')
    return payload


def load(site, now, zone):
    import time
    import uuid
    from zoneinfo import ZoneInfo
    from .db import get_db
    db=get_db(); lat=float(site['latitude']); lon=float(site['longitude'])
    today=datetime.fromtimestamp(now, ZoneInfo(zone)).date().isoformat(); token=uuid.uuid4().hex
    db.execute('BEGIN IMMEDIATE')
    try:
        cached=read_cache(site,now,zone)
        if cached is not None:
            db.commit(); return cached, 200
        row=db.execute('SELECT * FROM site_visibility_cache WHERE site_id=?',(site['id'],)).fetchone()
        if row and row['cache_date']==today and (row['latitude'],row['longitude'])==(lat,lon) and row['lease_until']>now:
            db.commit(); return dict(status='pending'), 202
        db.execute("""INSERT INTO site_visibility_cache (site_id,cache_date,latitude,longitude,lease_token,lease_until)
            VALUES (?,?,?,?,?,?) ON CONFLICT(site_id) DO UPDATE SET cache_date=excluded.cache_date,
            latitude=excluded.latitude,longitude=excluded.longitude,payload=NULL,lease_token=excluded.lease_token,lease_until=excluded.lease_until""",(site['id'],today,lat,lon,token,now+35))
        db.commit()
    except Exception:
        db.rollback(); raise
    payload=fetch(lat,lon,now)
    with db:
        db.execute('UPDATE site_visibility_cache SET payload=?,lease_token=NULL,lease_until=0 WHERE site_id=? AND lease_token=?',(json.dumps(payload,allow_nan=False),site['id'],token))
    return payload,200


if __name__ == '__main__':
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        result = collect(float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]))
    print(json.dumps(result, allow_nan=False))
