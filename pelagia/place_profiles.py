"""Shared nearby-place discovery and reviews for dive-site and center profiles."""

import math

from .db import get_db
from . import site_descriptions

RADIUS_MILES = 30
EARTH_RADIUS_MILES = 3958.7613


def coordinates(entity):
    try:
        lat, lon = float(entity['latitude']), float(entity['longitude'])
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (KeyError, TypeError, ValueError):
        pass
    return None


def nearby_sites(center):
    return nearby_places(center, kind="site")


def nearby_centers(site):
    return nearby_places(site, kind="center")


def _prefix(kind):
    if kind not in {"site", "center"}:
        raise ValueError("Unknown place kind")
    return f"dive_{kind}"


def nearby_places(place, *, kind):
    prefix = _prefix(kind)
    origin = coordinates(place)
    if origin is None:
        return []
    lat, lon = map(math.radians, origin)
    # Latitude bounds reduce the catalog scan without excluding antimeridian sites.
    latitude_delta = math.degrees(RADIUS_MILES / EARTH_RADIUS_MILES)
    rows = get_db().execute(
        f"SELECT * FROM {prefix}s "
        "WHERE latitude BETWEEN ? AND ? AND longitude IS NOT NULL",
        (origin[0] - latitude_delta, origin[0] + latitude_delta),
    ).fetchall()
    matches = []
    for row in rows:
        destination = coordinates(row)
        if destination is None:
            continue
        other_lat, other_lon = map(math.radians, destination)
        haversine = math.sin((other_lat - lat) / 2) ** 2 + math.cos(lat) * math.cos(other_lat) * math.sin((other_lon - lon) / 2) ** 2
        distance = 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1, max(0, haversine))))
        if distance <= RADIUS_MILES + 1e-9:
            item = dict(row, distance_miles=distance)
            matches.append(item)
    matches = sorted(matches, key=lambda item: (item['distance_miles'], item['name'].casefold(), item['id']))[:10]
    for item in matches:
        cached = site_descriptions.read_cache(item['id'], kind=kind)
        item['description'] = (cached or {}).get('description')
    return matches


def reviews(place_id, viewer_id, *, kind="center"):
    prefix = _prefix(kind)
    rows = get_db().execute(
        f"SELECT r.*, u.username FROM {prefix}_reviews r JOIN users u ON u.id = r.user_id "
        f"WHERE r.{prefix}_id = ? ORDER BY r.updated_at DESC, r.id DESC", (place_id,),
    ).fetchall()
    return {
        'reviews': rows,
        'review_count': len(rows),
        'average_rating': sum(row['rating'] for row in rows) / len(rows) if rows else None,
        'my_review': next((row for row in rows if row['user_id'] == viewer_id), None),
    }


def save_review(place_id, user_id, rating, body, *, kind):
    prefix = _prefix(kind)
    db = get_db()
    with db:
        db.execute(
            f"INSERT INTO {prefix}_reviews({prefix}_id, user_id, rating, body) "
            f"VALUES (?, ?, ?, ?) ON CONFLICT({prefix}_id, user_id) DO UPDATE SET "
            "rating=excluded.rating, body=excluded.body, updated_at=CURRENT_TIMESTAMP",
            (place_id, user_id, rating, body),
        )
