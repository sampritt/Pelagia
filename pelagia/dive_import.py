"""Memory-only FIT import endpoint and transactional normalized-data storage."""

import json

from flask import jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from .db import get_db
from .garmin_fit import MAX_FIT_BYTES, FitImportError, nearest_dive_site, parse_garmin_fit, validate_computer_data


def init_app(app, current_user):
    @app.post("/api/dive-import/garmin")
    def import_garmin_dive():
        def respond(payload, status=200):
            response = jsonify(payload)
            response.status_code = status
            response.headers["Cache-Control"] = "no-store"
            return response

        if current_user() is None:
            return respond({"error": "Sign in again before importing your dive."}, 401)
        if request.headers.get("X-Requested-With") != "fetch":
            return respond({"error": "Import the file from the Log a Dive form."}, 403)
        if request.mimetype != "application/octet-stream":
            return respond({"error": "Choose a FIT file using the file importer."}, 415)
        if request.content_length is not None and request.content_length > MAX_FIT_BYTES:
            return respond({"error": "Choose a FIT file smaller than 10 MiB."}, 413)
        try:
            # Raw bounded input avoids Werkzeug's multipart disk-spooling path.
            raw = request.stream.read(MAX_FIT_BYTES + 1)
            if len(raw) > MAX_FIT_BYTES:
                return respond({"error": "Choose a FIT file smaller than 10 MiB."}, 413)
            result = parse_garmin_fit(raw)
        except RequestEntityTooLarge:
            return respond({"error": "Choose a FIT file smaller than 10 MiB."}, 413)
        except FitImportError as error:
            return respond({"error": str(error)}, 422)

        fields = result["fields"]
        result["matched_site"] = None
        if "latitude" in fields and "longitude" in fields:
            sites = get_db().execute("SELECT id, name, country_or_area, latitude, longitude FROM dive_sites")
            matched = nearest_dive_site(fields["latitude"], fields["longitude"], sites)
            if matched:
                result["matched_site"] = matched
                fields.update(dive_site_id=matched["id"], site_name=matched["name"],
                              country_or_area=matched["country_or_area"] or "")
            else:
                # Do not retain a stale site association for a different imported location.
                fields.update(dive_site_id="", site_name="", country_or_area="")
                result["notices"].append("No dive sites with usable coordinates were available; choose the site manually.")
        return respond(result)


def computer_data_from_form(form):
    raw = form.get("dive_computer_data_json", "")
    if not raw:
        return None
    if len(raw) > MAX_FIT_BYTES:
        raise FitImportError("The imported depth profile is too large. Import a shorter dive.")
    try:
        return validate_computer_data(json.loads(raw))
    except (ValueError, TypeError, RecursionError) as error:
        raise FitImportError("The imported depth profile is invalid. Import the FIT file again.") from error


def save_computer_data(db, dive_id, data):
    if data is not None:
        db.execute(
            "INSERT INTO dive_computer_data (dive_id, data_json) VALUES (?, ?) "
            "ON CONFLICT(dive_id) DO UPDATE SET data_json = excluded.data_json",
            (dive_id, json.dumps(data, allow_nan=False, separators=(",", ":"))),
        )


def computer_data_summary(db, dive_id):
    row = db.execute("SELECT data_json FROM dive_computer_data WHERE dive_id = ?", (dive_id,)).fetchone()
    if row is None:
        return None
    data = json.loads(row["data_json"])
    return {"source": "Garmin", "sample_count": len(data["depth_profile"])}
