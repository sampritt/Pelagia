"""Classify dive coordinates as fresh or salt water using Is On Water."""
import math
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import current_app, jsonify, request
from .db import get_db


DEFAULT_API_URL = "https://is-on-water.balbona.me/api/v1/get"
FEATURES = {"LAND", "OCEAN", "LAKE", "RIVER", "UNKNOWN"}
LEASE_SECONDS = 30
COOLDOWN_SECONDS = 60


class ClassificationPending(Exception):
    pass


class ClassificationRetryable(Exception):
    pass


def coordinates(latitude, longitude):
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _lookup(base_url, lat, lon):
    response = requests.get(f"{base_url}/{lat}/{lon}", timeout=(2, 5))
    response.raise_for_status()
    payload = response.json()
    feature = payload.get("feature") if isinstance(payload, dict) else None
    if not isinstance(feature, str) or feature.strip().upper() not in FEATURES:
        raise ValueError("Invalid Is On Water response")
    feature = feature.strip().upper()
    return {"water_type": "salt" if feature == "OCEAN" else "fresh", "feature": feature}


def nearby_coordinates(latitude, longitude):
    """Eight points, each half a mile away, at 45-degree bearings."""
    angular = 804.672 / 6371000
    lat, lon = math.radians(latitude), math.radians(longitude)
    for index in range(8):
        bearing = index * math.pi / 4
        target_lat = math.asin(math.sin(lat) * math.cos(angular) +
                               math.cos(lat) * math.sin(angular) * math.cos(bearing))
        target_lon = lon + math.atan2(math.sin(bearing) * math.sin(angular) * math.cos(lat),
                                      math.cos(angular) - math.sin(lat) * math.sin(target_lat))
        yield math.degrees(target_lat), (math.degrees(target_lon) + 180) % 360 - 180


def classify(latitude, longitude):
    values = coordinates(latitude, longitude)
    if values is None:
        raise ValueError("Invalid coordinates")
    base_url = current_app.config["IS_ON_WATER_API_URL"].rstrip("/")
    result = _lookup(base_url, *values)
    if result["feature"] == "OCEAN":
        return result
    errors = []
    ocean = False
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_lookup, base_url, lat, lon) for lat, lon in nearby_coordinates(*values)]
        for future in as_completed(futures):
            try:
                ocean |= future.result()["feature"] == "OCEAN"
            except (requests.RequestException, ValueError, TypeError, KeyError) as error:
                errors.append(error)
    if ocean:
        return {"water_type": "salt", "feature": "OCEAN"}
    if errors:
        raise errors[0]
    return result


def classify_site(site):
    """Return the site's permanent classification, looking it up when absent."""
    values = coordinates(site["latitude"], site["longitude"])
    if values is None:
        raise ValueError("Invalid coordinates")
    latitude, longitude = values
    db = get_db()
    now = time.time()
    token = None
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM dive_site_water_classifications WHERE dive_site_id = ?",
            (site["id"],),
        ).fetchone()
        if row is not None and row["feature"] in FEATURES:
            result = {"feature": row["feature"], "water_type": "salt" if row["feature"] == "OCEAN" else "fresh"}
        elif row is not None and row["lease_until"] > now:
            raise ClassificationPending()
        elif row is not None and row["retry_after"] > now:
            raise ClassificationRetryable()
        else:
            token = uuid.uuid4().hex
            db.execute(
                """INSERT INTO dive_site_water_classifications
                   (dive_site_id, latitude, longitude, feature, classified_at, lease_token, lease_until, retry_after)
                   VALUES (?, ?, ?, NULL, NULL, ?, ?, 0)
                   ON CONFLICT(dive_site_id) DO UPDATE SET
                     latitude=excluded.latitude, longitude=excluded.longitude, feature=NULL,
                     classified_at=NULL, lease_token=excluded.lease_token,
                     lease_until=excluded.lease_until, retry_after=0""",
                (site["id"], latitude, longitude, token, now + LEASE_SECONDS),
            )
            result = None
        db.commit()
    except (ClassificationPending, ClassificationRetryable):
        db.commit()
        raise
    except Exception:
        db.rollback()
        raise
    if result is not None:
        return result
    try:
        result = classify(latitude, longitude)
    except Exception:
        with db:
            db.execute(
                """UPDATE dive_site_water_classifications
                   SET lease_token=NULL, lease_until=0, retry_after=?
                   WHERE dive_site_id=? AND lease_token=?""",
                (time.time() + COOLDOWN_SECONDS, site["id"], token),
            )
        raise
    with db:
        saved = db.execute(
            """UPDATE dive_site_water_classifications
               SET feature=?, classified_at=CURRENT_TIMESTAMP, lease_token=NULL, lease_until=0, retry_after=0
               WHERE dive_site_id=? AND lease_token=?""",
            (result["feature"], site["id"], token),
        ).rowcount
    if not saved:
        raise ClassificationPending()
    return result


def init_app(app, login_required):
    app.config.setdefault(
        "IS_ON_WATER_API_URL",
        os.environ.get("PELAGIA_IS_ON_WATER_API_URL", DEFAULT_API_URL),
    )

    @app.get("/api/water-type")
    @login_required
    def api_water_type():
        site_id = request.args.get("site_id", type=int)
        if site_id is not None:
            site = get_db().execute("SELECT id, latitude, longitude FROM dive_sites WHERE id = ?", (site_id,)).fetchone()
            if site is None:
                return jsonify({"status": "unavailable", "reason": "site"}), 404
            try:
                result = {"status": "complete", **classify_site(site)}
                status = 200
            except ClassificationPending:
                result, status = {"status": "pending"}, 202
            except ClassificationRetryable:
                result, status = {"status": "unavailable", "reason": "upstream"}, 503
            except (requests.RequestException, ValueError, TypeError, KeyError):
                current_app.logger.warning("Water type lookup unavailable for site %s", site_id)
                result, status = {"status": "unavailable", "reason": "upstream"}, 503
            response = jsonify(result)
            response.status_code = status
            response.headers["Cache-Control"] = "private, no-store"
            if status in (202, 503):
                response.headers["Retry-After"] = "2" if status == 202 else str(COOLDOWN_SECONDS)
            return response
        values = coordinates(request.args.get("latitude"), request.args.get("longitude"))
        if values is None:
            return jsonify({"status": "unavailable", "reason": "coordinates"}), 400
        try:
            result = {"status": "complete", **classify(*values)}
            status = 200
        except (requests.RequestException, ValueError, TypeError, KeyError):
            current_app.logger.warning("Water type lookup unavailable")
            result, status = {"status": "unavailable", "reason": "upstream"}, 503
        response = jsonify(result)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        return response
