"""Location discovery and paginated Explore feeds backed by the reference catalog."""

import json
import math

import requests
from flask import Blueprint, abort, current_app, jsonify, render_template, request, session

from .db import get_db


PAGE_SIZE = 24
SITE_COLUMNS = "id, name, country_or_area, latitude, longitude, logged_dive_count"
SPECIES_COUNT = """(
    SELECT count(*) FROM (
        SELECT lower(trim(ds.common_name)) AS common_name
        FROM dives d JOIN dive_species ds ON ds.dive_id = d.id
        WHERE d.dive_site_id = dive_sites.id AND coalesce(d.is_deleted, 0) = 0
            AND trim(ds.common_name) <> ''
        UNION
        SELECT lower(trim(s.common_name)) AS common_name
        FROM dive_site_obis_occurrences occurrence
        JOIN species s ON s.id = occurrence.species_id
        WHERE occurrence.dive_site_id = dive_sites.id AND trim(s.common_name) <> ''
    )
) AS observed_species_count"""
EARTH_RADIUS_KM = 6371.0088
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
RADIUS_LIMITS = {"mi": 100, "km": 160}


class GeocodingError(RuntimeError):
    """Raised when the geocoding provider cannot complete a request."""


def geocode_place(query):
    """Return the first Nominatim place match, or ``None`` when none exists."""
    endpoint = current_app.config.get("NOMINATIM_ENDPOINT") or NOMINATIM_ENDPOINT
    contact = current_app.config.get("PELAGIA_CONTACT_EMAIL", "info@pelagiadivelog.com")
    user_agent = current_app.config.get("NOMINATIM_USER_AGENT") or f"Pelagia/1.0 ({contact})"
    try:
        response = requests.get(
            endpoint,
            params={"q": query, "format": "jsonv2", "limit": 1},
            headers={"Accept": "application/json", "User-Agent": user_agent},
            timeout=10,
        )
        response.raise_for_status()
        matches = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GeocodingError("Location search is temporarily unavailable.") from exc
    if not isinstance(matches, list):
        raise GeocodingError("Location search returned an unexpected response.")
    if not matches:
        return None
    try:
        latitude = float(matches[0]["lat"])
        longitude = float(matches[0]["lon"])
        display_name = str(matches[0]["display_name"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("Location search returned an incomplete result.") from exc
    if (
        not display_name
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise GeocodingError("Location search returned an invalid result.")
    return {"display_name": display_name, "latitude": latitude, "longitude": longitude}


def cartesian_distance_km(latitude, longitude, other_latitude, other_longitude):
    """Approximate local surface distance with an equirectangular projection."""
    latitude_radians = math.radians(latitude)
    other_latitude_radians = math.radians(other_latitude)
    longitude_delta = (other_longitude - longitude + 180) % 360 - 180
    x = math.radians(longitude_delta) * math.cos(
        (latitude_radians + other_latitude_radians) / 2
    )
    y = other_latitude_radians - latitude_radians
    return EARTH_RADIUS_KM * math.hypot(x, y)


def nearby_feed_data(latitude, longitude, radius_km, display_name, page=1):
    """Return one page of nearby sites ranked by dives, then observed species."""
    rows = get_db().execute(
        f"""SELECT {SITE_COLUMNS} FROM dive_sites
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
    ).fetchall()
    matches = []
    for row in rows:
        distance = cartesian_distance_km(
            latitude, longitude, row["latitude"], row["longitude"]
        )
        if distance <= radius_km:
            matches.append(row)
    matches = add_observations(matches)
    matches.sort(
        key=lambda item: (
            -item["logged_dive_count"],
            -len(item["sightings"]),
            item["name"].casefold(),
            item["id"],
        )
    )
    start = (page - 1) * PAGE_SIZE
    result = {
        "location": display_name,
        "nearby": True,
        "items": matches[start:start + PAGE_SIZE],
        "total": len(matches),
        "next_page": page + 1 if page * PAGE_SIZE < len(matches) else None,
    }
    return result


def parse_nearby_request(source):
    query = source.get("query")
    unit = source.get("unit")
    radius = source.get("radius")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 160:
        abort(400)
    if unit not in RADIUS_LIMITS:
        abort(400)
    if isinstance(radius, bool):
        abort(400)
    try:
        radius = int(radius)
    except (TypeError, ValueError):
        abort(400)
    if (
        str(radius) != str(source.get("radius")).strip()
        or not 1 <= radius <= RADIUS_LIMITS[unit]
    ):
        abort(400)
    return query.strip(), radius, unit


def parse_coordinate(value, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        abort(400)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        abort(400)
    return number


def decode_saved_nearby(raw):
    """Return a validated account-level nearby search, or ``None``."""
    if not raw:
        return None
    try:
        saved = json.loads(raw)
        query = saved["query"].strip()
        display_name = saved["displayName"].strip()
        latitude = float(saved["latitude"])
        longitude = float(saved["longitude"])
        radius = saved["radius"]
        unit = saved["unit"]
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(saved.get("query"), str)
        or not isinstance(saved.get("displayName"), str)
        or isinstance(radius, bool)
        or not isinstance(radius, int)
        or unit not in RADIUS_LIMITS
        or not 1 <= len(query) <= 160
        or not 1 <= len(display_name) <= 300
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
        or not 1 <= radius <= RADIUS_LIMITS[unit]
    ):
        return None
    return {
        "query": query,
        "displayName": display_name,
        "latitude": latitude,
        "longitude": longitude,
        "radius": radius,
        "unit": unit,
    }


def locations():
    return [row[0] for row in get_db().execute(
        """SELECT trim(country_or_area) FROM dive_sites
           WHERE trim(coalesce(country_or_area, '')) <> ''
           GROUP BY trim(country_or_area) COLLATE NOCASE
           ORDER BY trim(country_or_area) COLLATE NOCASE"""
    )]


def resolve_location(value):
    clean = (value or "").strip().casefold()
    return next((name for name in locations() if name.casefold() == clean), "")


def latest_dive_location(user_id):
    row = get_db().execute(
        """SELECT country_or_area FROM dives
           WHERE user_id = ? AND coalesce(is_deleted, 0) = 0
           ORDER BY created_at DESC, id DESC
           LIMIT 1""", (user_id,)
    ).fetchone()
    return row[0] if row else ""


def add_observations(rows):
    items = [dict(row, sightings=[]) for row in rows]
    if not items:
        return items
    by_id = {item["id"]: item for item in items}
    placeholders = ",".join("?" for _ in items)
    sightings = get_db().execute(
        f"""SELECT d.dive_site_id, min(trim(ds.common_name)) AS common_name,
                   count(DISTINCT d.id) AS dive_count
            FROM dive_species ds JOIN dives d ON d.id = ds.dive_id
            WHERE d.dive_site_id IN ({placeholders}) AND coalesce(d.is_deleted, 0) = 0
                AND trim(ds.common_name) <> ''
            GROUP BY d.dive_site_id, lower(trim(ds.common_name))
            ORDER BY dive_count DESC, common_name COLLATE NOCASE""", list(by_id)
    )
    for sighting in sightings:
        by_id[sighting["dive_site_id"]]["sightings"].append(dict(sighting))
    seen = {
        site_id: {sighting["common_name"].casefold() for sighting in item["sightings"]}
        for site_id, item in by_id.items()
    }
    nearby = get_db().execute(
        f"""SELECT occurrence.dive_site_id, min(trim(s.common_name)) AS common_name
            FROM dive_site_obis_occurrences occurrence
            JOIN species s ON s.id = occurrence.species_id
            WHERE occurrence.dive_site_id IN ({placeholders}) AND trim(s.common_name) <> ''
            GROUP BY occurrence.dive_site_id, lower(trim(s.common_name))
            ORDER BY common_name COLLATE NOCASE""", list(by_id)
    )
    for sighting in nearby:
        site_id = sighting["dive_site_id"]
        if sighting["common_name"].casefold() not in seen[site_id]:
            by_id[site_id]["sightings"].append(dict(sighting, dive_count=0))
    return items


def feed_data(location, page=1):
    result = {"location": location, "items": [], "total": 0, "next_page": None}
    if not location:
        return result
    db = get_db()
    result["total"] = db.execute(
        "SELECT count(*) FROM dive_sites WHERE trim(country_or_area) = ? COLLATE NOCASE", (location,)
    ).fetchone()[0]
    rows = db.execute(
        f"""SELECT {SITE_COLUMNS}, {SPECIES_COUNT} FROM dive_sites
           WHERE trim(country_or_area) = ? COLLATE NOCASE
           ORDER BY logged_dive_count DESC, observed_species_count DESC, name COLLATE NOCASE, id
           LIMIT ? OFFSET ?""", (location, PAGE_SIZE, (page - 1) * PAGE_SIZE)
    ).fetchall()
    result["items"] = add_observations(rows)
    if page * PAGE_SIZE < result["total"]:
        result["next_page"] = page + 1
    return result


def init_app(app, login_required):
    blueprint = Blueprint("explore", __name__)

    @blueprint.get("/explore")
    @login_required
    def index():
        saved = get_db().execute(
            "SELECT explore_location, explore_nearby_json FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
        initial_nearby = None
        if "location" not in request.args and "nearby" not in request.args:
            initial_nearby = decode_saved_nearby(saved["explore_nearby_json"])
        if initial_nearby:
            radius_km = (
                initial_nearby["radius"] * 1.609344
                if initial_nearby["unit"] == "mi"
                else initial_nearby["radius"]
            )
            data = nearby_feed_data(
                initial_nearby["latitude"], initial_nearby["longitude"],
                radius_km, initial_nearby["displayName"],
            )
            return render_template(
                "explore.html", initial_nearby=initial_nearby, **data
            )
        if "location" in request.args:
            requested = request.args.get("location")
        else:
            requested = (
                latest_dive_location(session["user_id"])
                if saved["explore_location"] is None
                else saved["explore_location"]
            )
        location = resolve_location(requested)
        return render_template(
            "explore.html", initial_nearby=None, **feed_data(location)
        )

    @blueprint.after_request
    def no_api_cache(response):
        if request.path.startswith("/api/explore"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @blueprint.get("/api/explore/locations")
    @login_required
    def search_locations():
        query = request.args.get("q", "").strip().casefold()
        if not query:
            return jsonify([])
        matches = [name for name in locations() if query in name.casefold()]
        matches.sort(key=lambda name: (not name.casefold().startswith(query), name.casefold()))
        return jsonify(matches[:14])

    @blueprint.get("/api/explore")
    @login_required
    def feed():
        page = request.args.get("page", type=int) if "page" in request.args else 1
        if page is None or page < 1 or page > 10000:
            abort(400)
        data = feed_data(resolve_location(request.args.get("location")), page)
        response = jsonify(
            html=render_template("_explore_results.html", **data),
            next_page=data["next_page"], total=data["total"],
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @blueprint.post("/api/explore/nearby")
    @login_required
    def nearby_search():
        if request.headers.get("X-Requested-With") != "fetch":
            abort(403)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400)
        query, radius, unit = parse_nearby_request(payload)
        try:
            place = geocode_place(query)
        except GeocodingError as exc:
            return jsonify(error="geocoding_unavailable", message=str(exc)), 502
        if place is None:
            return jsonify(error="no_results", query=query)
        radius_km = radius * 1.609344 if unit == "mi" else radius
        data = nearby_feed_data(
            place["latitude"], place["longitude"], radius_km, place["display_name"]
        )
        saved_nearby = {
            "query": query,
            "displayName": place["display_name"],
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "radius": radius,
            "unit": unit,
        }
        db = get_db()
        db.execute(
            "UPDATE users SET explore_location = NULL, explore_nearby_json = ? WHERE id = ?",
            (json.dumps(saved_nearby, separators=(",", ":")), session["user_id"]),
        )
        db.commit()
        return jsonify(
            html=render_template("_explore_results.html", **data),
            next_page=data["next_page"],
            total=data["total"],
            place=place,
            query=query,
            radius=radius,
            unit=unit,
        )

    @blueprint.get("/api/explore/nearby")
    @login_required
    def nearby_page():
        query, radius, unit = parse_nearby_request(request.args)
        display_name = request.args.get("display_name", "").strip()
        if not 1 <= len(display_name) <= 300:
            abort(400)
        page = request.args.get("page", type=int) if "page" in request.args else 1
        if page is None or page < 1 or page > 10000:
            abort(400)
        latitude = parse_coordinate(request.args.get("latitude"), -90, 90)
        longitude = parse_coordinate(request.args.get("longitude"), -180, 180)
        radius_km = radius * 1.609344 if unit == "mi" else radius
        data = nearby_feed_data(latitude, longitude, radius_km, display_name, page)
        return jsonify(
            html=render_template("_explore_results.html", **data),
            next_page=data["next_page"], total=data["total"],
        )

    @blueprint.post("/api/explore/location")
    @login_required
    def save_location():
        if request.headers.get("X-Requested-With") != "fetch":
            abort(403)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("location"), str):
            abort(400)
        location = resolve_location(payload["location"])
        if payload["location"].strip() and not location:
            abort(400)
        db = get_db()
        db.execute(
            "UPDATE users SET explore_location = ?, explore_nearby_json = NULL WHERE id = ?",
            (location, session["user_id"]),
        )
        db.commit()
        return jsonify(location=location)

    app.register_blueprint(blueprint)
