"""Location discovery and paginated Explore feeds backed by the reference catalog."""

from flask import Blueprint, abort, jsonify, render_template, request, session

from .db import get_db


PAGE_SIZE = 24
SITE_COLUMNS = "id, name, country_or_area, latitude, longitude, logged_dive_count"


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
        f"""SELECT {SITE_COLUMNS} FROM dive_sites
           WHERE trim(country_or_area) = ? COLLATE NOCASE
           ORDER BY logged_dive_count DESC, name COLLATE NOCASE, id
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
        saved = get_db().execute("SELECT explore_location FROM users WHERE id = ?", (session["user_id"],)).fetchone()[0]
        if "location" in request.args:
            requested = request.args.get("location")
        else:
            requested = latest_dive_location(session["user_id"]) if saved is None else saved
        location = resolve_location(requested)
        return render_template("explore.html", **feed_data(location))

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
        db.execute("UPDATE users SET explore_location = ? WHERE id = ?", (location, session["user_id"]))
        db.commit()
        return jsonify(location=location)

    app.register_blueprint(blueprint)
