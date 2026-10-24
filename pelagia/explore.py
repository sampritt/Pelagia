"""Location discovery and paginated Explore feeds backed by the reference catalog."""

from flask import Blueprint, abort, jsonify, render_template, request, session

from .db import get_db


PAGE_SIZE = 24


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


def default_location(user_id):
    # Use the most recent log, including a backdated import, and ignore deleted dives.
    row = get_db().execute(
        """SELECT coalesce(nullif(trim(s.country_or_area), ''), d.country_or_area) AS location
           FROM dives d LEFT JOIN dive_sites s ON s.id = d.dive_site_id
           WHERE d.user_id = ? AND d.is_deleted = 0
           ORDER BY d.created_at DESC, d.id DESC LIMIT 1""", (user_id,)
    ).fetchone()
    return resolve_location(row["location"]) if row else ""


def feed_data(location, page=1):
    result = {"location": location, "items": [], "total": 0, "next_page": None}
    if not location:
        return result
    db = get_db()
    result["total"] = db.execute(
        "SELECT count(*) FROM dive_sites WHERE trim(country_or_area) = ? COLLATE NOCASE", (location,)
    ).fetchone()[0]
    rows = db.execute(
        """SELECT id, name, country_or_area, latitude, longitude FROM dive_sites
           WHERE trim(country_or_area) = ? COLLATE NOCASE
           ORDER BY logged_dive_count DESC, name COLLATE NOCASE, id
           LIMIT ? OFFSET ?""", (location, PAGE_SIZE, (page - 1) * PAGE_SIZE)
    ).fetchall()
    result["items"] = rows
    if page * PAGE_SIZE < result["total"]:
        result["next_page"] = page + 1
    return result


def init_app(app, login_required):
    blueprint = Blueprint("explore", __name__)

    @blueprint.get("/explore")
    @login_required
    def index():
        location = resolve_location(request.args["location"]) if "location" in request.args else default_location(session["user_id"])
        return render_template("explore.html", **feed_data(location))

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

    app.register_blueprint(blueprint)
