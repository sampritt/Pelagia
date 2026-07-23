import json
import os
import uuid
from datetime import date
from functools import wraps
from pathlib import Path
from sqlite3 import IntegrityError
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, UnidentifiedImageError

from . import db as database
from .importer import import_reference_data


EXPOSURES = ("swimsuit", "shorty", "2mm", "3mm", "4mm", "5mm", "6mm", "7mm", "dry suit")
DIVE_TYPES = ("open water", "shore dive", "reef", "wall", "deep", "night", "wreck", "cavern", "cave")
CURRENTS = ("none", "slack", "current", "drift", "surge")
DIVE_TYPE_LABELS = {value: value.title() for value in DIVE_TYPES}
CURRENT_LABELS = {value: value.title() for value in CURRENTS}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
UPLOAD_IMAGE_MAX_DIMENSION = 1600
UPLOAD_IMAGE_JPEG_QUALITY = 82


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    config_path = Path(os.environ.get("PELAGIA_CONFIG", "app_config.json")).resolve()
    config = _load_json_config(config_path)

    app.config.from_mapping(
        SECRET_KEY=config.get("secret_key", "pelagia-dev"),
        DATABASE=str(_resolve_path(config_path, config.get("database_path", "instance/pelagia.sqlite3"))),
        UPLOAD_FOLDER=str(_resolve_path(config_path, config.get("upload_folder", "pelagia/static/uploads"))),
        MAX_CONTENT_LENGTH=24 * 1024 * 1024,
        PELAGIA_LOCAL_CONFIG=config,
        PELAGIA_CONFIG_PATH=str(config_path),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["UPLOAD_FOLDER"], "dives").mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"], "profiles").mkdir(parents=True, exist_ok=True)

    database.init_app(app)
    with app.app_context():
        database.init_db()
        _ensure_reference_data(app)

    register_routes(app)
    return app


def _load_json_config(config_path):
    if not config_path.exists():
        raise FileNotFoundError(f"Missing Pelagia config file: {config_path}")
    return json.loads(config_path.read_text())


def _resolve_path(config_path, value):
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return config_path.parent / path


def _ensure_reference_data(app):
    if (
        database.table_count("dive_sites")
        and database.table_count("species")
        and database.table_count("site_species")
        and database.table_count("dive_centers")
    ):
        return
    import_reference_data(
        app.config["DATABASE"],
        app.config["PELAGIA_LOCAL_CONFIG"],
        app.config["PELAGIA_CONFIG_PATH"],
    )


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if not session.get("user_id"):
            return redirect(url_for("landing"))
        if current_user() is None:
            session.clear()
            return redirect(url_for("landing"))
        return view(**kwargs)

    return wrapped_view


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return (
        database.get_db()
        .execute("SELECT id, username, profile_photo, created_at FROM users WHERE id = ?", (user_id,))
        .fetchone()
    )


def register_routes(app):
    app.jinja_env.globals["current_user"] = current_user
    app.jinja_env.globals["dive_type_label"] = dive_type_label
    app.jinja_env.globals["current_label"] = current_label

    @app.route("/")
    def landing():
        if session.get("user_id"):
            return redirect(url_for("home"))
        return render_template("landing.html")

    @app.route("/signup", methods=("POST",))
    def signup():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 6:
            flash("Use a username of 3+ characters and a password of 6+ characters.")
            return redirect(url_for("landing"))
        try:
            cur = database.get_db().execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            database.get_db().commit()
        except IntegrityError:
            flash("That username is already taken.")
            return redirect(url_for("landing"))
        session.clear()
        session["user_id"] = cur.lastrowid
        return redirect(url_for("home"))

    @app.route("/login", methods=("POST",))
    def login():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = database.get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Username or password does not match.")
            return redirect(url_for("landing"))
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("home"))

    @app.route("/logout", methods=("POST",))
    def logout():
        session.clear()
        return redirect(url_for("landing"))

    @app.route("/home")
    @login_required
    def home():
        dives = fetch_dives(scope="all", user_id=session["user_id"])
        latest_my_dives = fetch_dives(scope="mine", user_id=session["user_id"], limit=1)
        stats = get_profile_stats(session["user_id"])
        return render_template(
            "home.html",
            dives=dives,
            latest_my_dive=latest_my_dives[0] if latest_my_dives else None,
            stats=stats,
            user=current_user(),
        )

    @app.route("/dive/new", methods=("GET", "POST"))
    @login_required
    def log_dive():
        if request.method == "POST":
            create_dive_from_request(session["user_id"], request)
            flash("Dive logged.")
            return redirect(url_for("home"))
        return render_template(
            "log_dive.html",
            exposures=EXPOSURES,
            dive_types=DIVE_TYPES,
            dive_type_labels=DIVE_TYPE_LABELS,
            currents=CURRENTS,
            current_labels=CURRENT_LABELS,
            today=date.today().isoformat(),
            dive=None,
            is_edit=False,
            next_url="",
        )

    @app.route("/dive/<int:dive_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_dive(dive_id):
        dive = fetch_owned_dive(dive_id, session["user_id"])
        if dive is None:
            abort(404)
        if request.method == "POST":
            update_dive_from_request(dive_id, session["user_id"], request)
            flash("Dive updated.")
            return redirect(_url_with_open(_safe_next_url(request.form.get("next")), dive_id))
        return render_template(
            "log_dive.html",
            exposures=EXPOSURES,
            dive_types=DIVE_TYPES,
            dive_type_labels=DIVE_TYPE_LABELS,
            currents=CURRENTS,
            current_labels=CURRENT_LABELS,
            today=date.today().isoformat(),
            dive=dive,
            is_edit=True,
            next_url=_safe_next_url(request.args.get("next") or request.referrer),
        )

    @app.route("/dive/<int:dive_id>/delete", methods=("POST",))
    @login_required
    def delete_dive(dive_id):
        if fetch_owned_dive(dive_id, session["user_id"]) is None:
            abort(404)
        database.get_db().execute(
            "UPDATE dives SET is_deleted = 1 WHERE id = ? AND user_id = ?",
            (dive_id, session["user_id"]),
        )
        database.get_db().commit()
        flash("Dive deleted.")
        return redirect(_url_without_open(_safe_next_url(request.form.get("next"))))

    @app.route("/you", methods=("GET", "POST"))
    @login_required
    def profile():
        if request.method == "POST":
            photo = request.files.get("profile_photo")
            if photo and photo.filename and _allowed_file(photo.filename):
                filename = _save_upload(photo, "profiles")
                database.get_db().execute(
                    "UPDATE users SET profile_photo = ? WHERE id = ?",
                    (filename, session["user_id"]),
                )
                database.get_db().commit()
                flash("Profile photo updated.")
            return redirect(url_for("profile"))

        user = current_user()
        stats = get_profile_stats(user["id"])
        recent_dives = fetch_dives(scope="mine", user_id=user["id"], limit=6)
        return render_template("profile.html", user=user, stats=stats, recent_dives=recent_dives)

    @app.route("/map")
    @login_required
    def map_view():
        return render_template("map.html")

    @app.route("/api/sites", methods=("GET",))
    @login_required
    def api_sites():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify([])
        like = f"%{query.lower()}%"
        prefix = f"{query.lower()}%"
        rows = database.get_db().execute(
            """
            SELECT id, name, country_or_area, country_code, latitude, longitude, max_depth_m
            FROM dive_sites
            WHERE lower(name) LIKE ? OR lower(country_or_area) LIKE ?
            ORDER BY
                CASE WHEN lower(name) LIKE ? THEN 0 ELSE 1 END,
                name
            LIMIT 14
            """,
            (like, like, prefix),
        ).fetchall()
        return jsonify([site_payload(row) for row in rows])

    @app.route("/api/species", methods=("GET",))
    @login_required
    def api_species():
        query = request.args.get("q", "").strip()
        country = request.args.get("country", "").strip()
        if not query:
            return jsonify([])
        like = f"%{query.lower()}%"
        if country:
            rows = database.get_db().execute(
                """
                SELECT common_name, '' AS country_or_area
                FROM species
                WHERE lower(common_name) LIKE ?
                GROUP BY lower(common_name)
                ORDER BY common_name
                LIMIT 14
                """,
                (like,),
            ).fetchall()
        else:
            rows = database.get_db().execute(
                """
                SELECT common_name, '' AS country_or_area
                FROM species
                WHERE lower(common_name) LIKE ?
                GROUP BY lower(common_name)
                ORDER BY common_name
                LIMIT 14
                """,
                (like,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.route("/api/dive-centers", methods=("GET",))
    @login_required
    def api_dive_centers():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify([])
        like = f"%{query.lower()}%"
        prefix = f"{query.lower()}%"
        rows = database.get_db().execute(
            """
            SELECT id, name, physical_address, location, website, latitude, longitude
            FROM dive_centers
            WHERE lower(name) LIKE ? OR lower(location) LIKE ? OR lower(physical_address) LIKE ?
            ORDER BY
                CASE WHEN lower(name) LIKE ? THEN 0 ELSE 1 END,
                name
            LIMIT 14
            """,
            (like, like, like, prefix),
        ).fetchall()
        return jsonify([center_payload(row) for row in rows])

    @app.route("/api/species-suggestions", methods=("GET",))
    @login_required
    def api_species_suggestions():
        site_id = request.args.get("site_id", type=int)
        country = request.args.get("country", "").strip()
        if site_id:
            rows = species_suggestions_for_site(site_id)
        elif country:
            rows = species_suggestions_for_country(country)
        else:
            rows = []
        return jsonify([row["common_name"] for row in rows])

    @app.route("/api/dives/mine", methods=("GET",))
    @login_required
    def api_my_dives():
        return jsonify([dive_to_json(dive) for dive in fetch_dives(scope="mine", user_id=session["user_id"], limit=500)])

    @app.route("/api/dives/<int:dive_id>", methods=("GET",))
    @login_required
    def api_dive(dive_id):
        dive = fetch_dive(dive_id, session["user_id"])
        if dive is None:
            abort(404)
        return jsonify(dive_to_json(dive))

    @app.route("/api/dives/<int:dive_id>/like", methods=("POST",))
    @login_required
    def api_like(dive_id):
        db = database.get_db()
        if fetch_dive(dive_id, session["user_id"]) is None:
            abort(404)
        exists = db.execute(
            "SELECT 1 FROM likes WHERE dive_id = ? AND user_id = ?",
            (dive_id, session["user_id"]),
        ).fetchone()
        if exists:
            db.execute("DELETE FROM likes WHERE dive_id = ? AND user_id = ?", (dive_id, session["user_id"]))
            liked = False
        else:
            db.execute("INSERT OR IGNORE INTO likes (dive_id, user_id) VALUES (?, ?)", (dive_id, session["user_id"]))
            liked = True
        db.commit()
        count = db.execute("SELECT COUNT(*) AS count FROM likes WHERE dive_id = ?", (dive_id,)).fetchone()["count"]
        return jsonify({"liked": liked, "count": count})

    @app.route("/api/dives/<int:dive_id>/comments", methods=("POST",))
    @login_required
    def api_comment(dive_id):
        body = request.form.get("body", "").strip()
        if not body:
            return jsonify({"error": "Comment cannot be empty."}), 400
        db = database.get_db()
        if fetch_dive(dive_id, session["user_id"]) is None:
            abort(404)
        db.execute(
            "INSERT INTO comments (dive_id, user_id, body) VALUES (?, ?, ?)",
            (dive_id, session["user_id"], body[:600]),
        )
        db.commit()
        dive = fetch_dive(dive_id, session["user_id"])
        return jsonify({"comments": [dict(comment) for comment in dive["comments"]]})

    @app.route("/dive-centers/<int:center_id>")
    @login_required
    def dive_center_profile(center_id):
        center = fetch_dive_center(center_id, session["user_id"])
        if center is None:
            abort(404)
        recent_dives = fetch_dives(scope="center", user_id=session["user_id"], center_id=center_id, limit=6)
        return render_template("dive_center_profile.html", center=center, recent_dives=recent_dives)

    @app.route("/api/dive-centers/<int:center_id>/like", methods=("POST",))
    @login_required
    def api_dive_center_like(center_id):
        db = database.get_db()
        if db.execute("SELECT 1 FROM dive_centers WHERE id = ?", (center_id,)).fetchone() is None:
            abort(404)
        exists = db.execute(
            "SELECT 1 FROM dive_center_likes WHERE dive_center_id = ? AND user_id = ?",
            (center_id, session["user_id"]),
        ).fetchone()
        if exists:
            db.execute(
                "DELETE FROM dive_center_likes WHERE dive_center_id = ? AND user_id = ?",
                (center_id, session["user_id"]),
            )
            liked = False
        else:
            db.execute(
                "INSERT OR IGNORE INTO dive_center_likes (dive_center_id, user_id) VALUES (?, ?)",
                (center_id, session["user_id"]),
            )
            liked = True
        db.commit()
        count = db.execute(
            "SELECT COUNT(*) AS count FROM dive_center_likes WHERE dive_center_id = ?",
            (center_id,),
        ).fetchone()["count"]
        return jsonify({"liked": liked, "count": count})

    @app.route("/api/dive-centers/<int:center_id>/comments", methods=("POST",))
    @login_required
    def api_dive_center_comment(center_id):
        body = request.form.get("body", "").strip()
        if not body:
            return jsonify({"error": "Comment cannot be empty."}), 400
        db = database.get_db()
        if db.execute("SELECT 1 FROM dive_centers WHERE id = ?", (center_id,)).fetchone() is None:
            abort(404)
        db.execute(
            "INSERT INTO dive_center_comments (dive_center_id, user_id, body) VALUES (?, ?, ?)",
            (center_id, session["user_id"], body[:600]),
        )
        db.commit()
        center = fetch_dive_center(center_id, session["user_id"])
        return jsonify({"comments": [dict(comment) for comment in center["comments"]]})


def create_dive_from_request(user_id, form_request):
    values = dive_values_from_request(form_request)
    db = database.get_db()
    cur = db.execute(
        """
        INSERT INTO dives (
            user_id, dive_site_id, dive_center_id, dive_center_name, date, site_name, country_or_area, latitude, longitude,
            depth_ft, duration_min, weight_lbs, exposure, visibility_ft, air_temp_degrees, water_temp_degrees,
            dive_type, current, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            values["dive_site_id"],
            values["dive_center_id"],
            values["dive_center_name"][:160],
            values["date"],
            values["site_name"],
            values["country_or_area"],
            values["latitude"],
            values["longitude"],
            values["depth_ft"],
            values["duration_min"],
            values["weight_lbs"],
            values["exposure"],
            values["visibility_ft"],
            values["air_temp_degrees"],
            values["water_temp_degrees"],
            values["dive_type"],
            values["current"],
            values["notes"],
        ),
    )
    dive_id = cur.lastrowid
    replace_dive_species(dive_id, values["species_names"], db)
    save_dive_photos(dive_id, form_request, db)
    db.commit()
    return dive_id


def update_dive_from_request(dive_id, user_id, form_request):
    values = dive_values_from_request(form_request)
    db = database.get_db()
    db.execute(
        """
        UPDATE dives
        SET dive_site_id = ?,
            dive_center_id = ?,
            dive_center_name = ?,
            date = ?,
            site_name = ?,
            country_or_area = ?,
            latitude = ?,
            longitude = ?,
            depth_ft = ?,
            duration_min = ?,
            weight_lbs = ?,
            exposure = ?,
            visibility_ft = ?,
            air_temp_degrees = ?,
            water_temp_degrees = ?,
            dive_type = ?,
            current = ?,
            notes = ?
        WHERE id = ? AND user_id = ? AND COALESCE(is_deleted, 0) = 0
        """,
        (
            values["dive_site_id"],
            values["dive_center_id"],
            values["dive_center_name"][:160],
            values["date"],
            values["site_name"],
            values["country_or_area"],
            values["latitude"],
            values["longitude"],
            values["depth_ft"],
            values["duration_min"],
            values["weight_lbs"],
            values["exposure"],
            values["visibility_ft"],
            values["air_temp_degrees"],
            values["water_temp_degrees"],
            values["dive_type"],
            values["current"],
            values["notes"],
            dive_id,
            user_id,
        ),
    )
    replace_dive_species(dive_id, values["species_names"], db)
    save_dive_photos(dive_id, form_request, db)
    db.commit()
    return dive_id


def dive_values_from_request(form_request):
    form = form_request.form
    depth = clamp_int(form.get("depth_ft"), 0, 140)
    duration = clamp_int(form.get("duration_min"), 0, 120)
    weight = clamp_int(form.get("weight_lbs"), 0, 20)
    exposure = form.get("exposure") if form.get("exposure") in EXPOSURES else "3mm"
    visibility = clamp_int(form.get("visibility_ft"), 0, 100)
    air_temp = clamp_int(form.get("air_temp_degrees"), 0, 100)
    water_temp = clamp_int(form.get("water_temp_degrees"), 0, 100)
    dive_type = form.get("dive_type") if form.get("dive_type") in DIVE_TYPES else "open water"
    current = form.get("current") if form.get("current") in CURRENTS else "none"
    date_value = form.get("date") or date.today().isoformat()
    site_name = form.get("site_name", "").strip() or "Unlisted site"
    country = form.get("country_or_area", "").strip()
    latitude = maybe_float(form.get("latitude"))
    longitude = maybe_float(form.get("longitude"))
    dive_site_id = maybe_int(form.get("dive_site_id"))
    dive_center_id = maybe_int(form.get("dive_center_id"))
    dive_center_name = form.get("dive_center_name", "").strip()

    db = database.get_db()
    if dive_center_id:
        center = db.execute("SELECT id, name FROM dive_centers WHERE id = ?", (dive_center_id,)).fetchone()
        if center:
            dive_center_name = center["name"]
        else:
            dive_center_id = None
    if not dive_center_name:
        dive_center_id = None

    species_names = []
    try:
        species_names = json.loads(form.get("species_json", "[]"))
    except json.JSONDecodeError:
        species_names = []
    return {
        "dive_site_id": dive_site_id,
        "dive_center_id": dive_center_id,
        "dive_center_name": dive_center_name,
        "date": date_value,
        "site_name": site_name,
        "country_or_area": country,
        "latitude": latitude,
        "longitude": longitude,
        "depth_ft": depth,
        "duration_min": duration,
        "weight_lbs": weight,
        "exposure": exposure,
        "visibility_ft": visibility,
        "air_temp_degrees": air_temp,
        "water_temp_degrees": water_temp,
        "dive_type": dive_type,
        "current": current,
        "notes": form.get("notes", "").strip(),
        "species_names": species_names,
    }


def replace_dive_species(dive_id, species_names, db):
    db.execute("DELETE FROM dive_species WHERE dive_id = ?", (dive_id,))
    for common_name in valid_species_names(dedupe_species(species_names), db):
        db.execute(
            "INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
            (dive_id, common_name),
        )


def save_dive_photos(dive_id, form_request, db):
    for photo in form_request.files.getlist("photos"):
        if photo and photo.filename and _allowed_file(photo.filename):
            filename = _save_upload(photo, "dives")
            db.execute("INSERT INTO photos (dive_id, filename) VALUES (?, ?)", (dive_id, filename))


def species_suggestions_for_site(site_id, limit=5):
    db = database.get_db()
    site = db.execute("SELECT name, country_or_area FROM dive_sites WHERE id = ?", (site_id,)).fetchone()
    if site is None:
        return []

    selected = []
    seen = set()
    rows = db.execute(
        """
        SELECT common_name
        FROM site_species
        WHERE dive_site_name = ?
        ORDER BY id
        LIMIT ?
        """,
        (site["name"], limit),
    ).fetchall()
    for row in rows:
        key = row["common_name"].lower()
        if key not in seen:
            selected.append({"common_name": row["common_name"]})
            seen.add(key)

    if len(selected) < limit and site["country_or_area"]:
        selected.extend(
            species_suggestions_for_country(
                site["country_or_area"],
                limit=limit - len(selected),
                excluded=seen,
            )
        )
    return selected[:limit]


def species_suggestions_for_country(country, limit=5, excluded=None):
    excluded = excluded or set()
    db = database.get_db()
    site_rows = db.execute(
        """
        SELECT name
        FROM dive_sites
        WHERE lower(country_or_area) = lower(?)
        """,
        (country,),
    ).fetchall()
    site_names = {row["name"].lower() for row in site_rows}
    if not site_names:
        return []

    selected = []
    seen = set(excluded)
    rows = db.execute(
        """
        SELECT dive_site_name, common_name
        FROM site_species
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        key = row["common_name"].lower()
        if row["dive_site_name"].lower() in site_names and key not in seen:
            selected.append({"common_name": row["common_name"]})
            seen.add(key)
            if len(selected) >= limit:
                break
    return selected


def fetch_dives(scope, user_id, limit=80, center_id=None):
    clauses = ["COALESCE(d.is_deleted, 0) = 0"]
    params = []
    if scope == "mine":
        clauses.append("d.user_id = ?")
        params.append(user_id)
    elif scope == "center":
        clauses.append("d.dive_center_id = ?")
        params.append(center_id)
    where = "WHERE " + " AND ".join(clauses)
    params.append(limit)
    rows = database.get_db().execute(
        f"""
        SELECT
            d.*,
            u.username,
            u.profile_photo,
            dc.name AS linked_dive_center_name,
            (SELECT COUNT(*) FROM likes WHERE dive_id = d.id) AS like_count,
            (SELECT COUNT(*) FROM comments WHERE dive_id = d.id) AS comment_count,
            EXISTS(SELECT 1 FROM likes WHERE dive_id = d.id AND user_id = ?) AS liked_by_me
        FROM dives d
        JOIN users u ON u.id = d.user_id
        LEFT JOIN dive_centers dc ON dc.id = d.dive_center_id
        {where}
        ORDER BY d.date DESC, d.created_at DESC
        LIMIT ?
        """,
        [user_id] + params,
    ).fetchall()
    return [hydrate_dive(row) for row in rows]


def fetch_dive(dive_id, viewer_user_id):
    row = database.get_db().execute(
        """
        SELECT
            d.*,
            u.username,
            u.profile_photo,
            dc.name AS linked_dive_center_name,
            (SELECT COUNT(*) FROM likes WHERE dive_id = d.id) AS like_count,
            (SELECT COUNT(*) FROM comments WHERE dive_id = d.id) AS comment_count,
            EXISTS(SELECT 1 FROM likes WHERE dive_id = d.id AND user_id = ?) AS liked_by_me
        FROM dives d
        JOIN users u ON u.id = d.user_id
        LEFT JOIN dive_centers dc ON dc.id = d.dive_center_id
        WHERE d.id = ?
            AND COALESCE(d.is_deleted, 0) = 0
        """,
        (viewer_user_id, dive_id),
    ).fetchone()
    if row is None:
        return None
    return hydrate_dive(row)


def fetch_owned_dive(dive_id, user_id):
    row = database.get_db().execute(
        """
        SELECT
            d.*,
            u.username,
            u.profile_photo,
            dc.name AS linked_dive_center_name,
            (SELECT COUNT(*) FROM likes WHERE dive_id = d.id) AS like_count,
            (SELECT COUNT(*) FROM comments WHERE dive_id = d.id) AS comment_count,
            EXISTS(SELECT 1 FROM likes WHERE dive_id = d.id AND user_id = ?) AS liked_by_me
        FROM dives d
        JOIN users u ON u.id = d.user_id
        LEFT JOIN dive_centers dc ON dc.id = d.dive_center_id
        WHERE d.id = ?
            AND d.user_id = ?
            AND COALESCE(d.is_deleted, 0) = 0
        """,
        (user_id, dive_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return hydrate_dive(row)


def hydrate_dive(row):
    db = database.get_db()
    dive = dict(row)
    dive["photos"] = db.execute("SELECT filename FROM photos WHERE dive_id = ?", (row["id"],)).fetchall()
    dive["species"] = db.execute(
        "SELECT common_name FROM dive_species WHERE dive_id = ? ORDER BY common_name",
        (row["id"],),
    ).fetchall()
    dive["comments"] = db.execute(
        """
        SELECT c.id, c.body, c.created_at, u.username
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.dive_id = ?
        ORDER BY c.created_at
        """,
        (row["id"],),
    ).fetchall()
    return dive


def get_profile_stats(user_id):
    db = database.get_db()
    stats = db.execute(
        """
        SELECT
            COUNT(*) AS dive_count,
            COALESCE(SUM(duration_min), 0) AS total_minutes,
            COUNT(DISTINCT NULLIF(country_or_area, '')) AS country_count,
            COUNT(DISTINCT site_name || '|' || COALESCE(country_or_area, '')) AS location_count,
            MIN(date) AS first_dive
        FROM dives
        WHERE user_id = ? AND COALESCE(is_deleted, 0) = 0
        """,
        (user_id,),
    ).fetchone()
    pins = db.execute(
        """
        SELECT id, site_name, latitude, longitude, date
        FROM dives
        WHERE user_id = ? AND COALESCE(is_deleted, 0) = 0 AND latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY date DESC
        LIMIT 200
        """,
        (user_id,),
    ).fetchall()
    account_age = db.execute(
        "SELECT CAST(julianday('now') - julianday(created_at) AS INTEGER) AS days FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    summary = dict(stats)
    summary["account_age_days"] = int(account_age["days"] or 0)
    return {"summary": summary, "pins": [dict(pin) for pin in pins]}


def fetch_dive_center(center_id, viewer_user_id):
    row = database.get_db().execute(
        """
        SELECT
            dc.*,
            (SELECT COUNT(*) FROM dive_center_likes WHERE dive_center_id = dc.id) AS like_count,
            (SELECT COUNT(*) FROM dive_center_comments WHERE dive_center_id = dc.id) AS comment_count,
            EXISTS(
                SELECT 1 FROM dive_center_likes
                WHERE dive_center_id = dc.id AND user_id = ?
            ) AS liked_by_me
        FROM dive_centers dc
        WHERE dc.id = ?
        """,
        (viewer_user_id, center_id),
    ).fetchone()
    if row is None:
        return None
    center = dict(row)
    center["comments"] = database.get_db().execute(
        """
        SELECT c.id, c.body, c.created_at, u.username
        FROM dive_center_comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.dive_center_id = ?
        ORDER BY c.created_at
        """,
        (center_id,),
    ).fetchall()
    return center


def dive_to_json(dive):
    return {
        "id": dive["id"],
        "username": dive["username"],
        "date": dive["date"],
        "site_name": dive["site_name"],
        "dive_center_id": dive["dive_center_id"],
        "dive_center_name": dive["linked_dive_center_name"] or dive["dive_center_name"],
        "country_or_area": dive["country_or_area"],
        "latitude": dive["latitude"],
        "longitude": dive["longitude"],
        "depth_ft": dive["depth_ft"],
        "duration_min": dive["duration_min"],
        "weight_lbs": dive["weight_lbs"],
        "exposure": dive["exposure"],
        "visibility_ft": dive["visibility_ft"],
        "air_temp_degrees": dive["air_temp_degrees"],
        "water_temp_degrees": dive["water_temp_degrees"],
        "dive_type": dive["dive_type"],
        "current": dive["current"],
        "notes": dive["notes"],
        "like_count": dive["like_count"],
        "comment_count": dive["comment_count"],
        "liked_by_me": bool(dive["liked_by_me"]),
        "is_owner": dive["user_id"] == session.get("user_id"),
        "photos": [url_for("static", filename=photo["filename"]) for photo in dive["photos"]],
        "species": [species["common_name"] for species in dive["species"]],
        "comments": [dict(comment) for comment in dive["comments"]],
    }


def site_payload(row):
    max_depth_ft = None
    if row["max_depth_m"] is not None:
        max_depth_ft = min(140, round(float(row["max_depth_m"]) * 3.28084))
    return {
        "id": row["id"],
        "name": row["name"],
        "country_or_area": row["country_or_area"],
        "country_code": row["country_code"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "max_depth_ft": max_depth_ft,
    }


def center_payload(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "physical_address": row["physical_address"],
        "location": row["location"],
        "website": row["website"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
    }


def clamp_int(value, minimum, maximum):
    try:
        parsed = int(float(value) + 0.5)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def maybe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def dive_type_label(value):
    return DIVE_TYPE_LABELS.get(value, DIVE_TYPE_LABELS["open water"])


def current_label(value):
    return CURRENT_LABELS.get(value, CURRENT_LABELS["none"])


def _safe_next_url(value):
    if not value:
        return url_for("home")
    try:
        parsed = urlsplit(value)
    except ValueError:
        return url_for("home")
    if parsed.scheme or parsed.netloc:
        if parsed.netloc != request.host:
            return url_for("home")
    elif not value.startswith("/") or value.startswith("//"):
        return url_for("home")
    path = parsed.path or url_for("home")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


def _url_with_open(value, dive_id):
    base = _safe_next_url(value)
    path, _, query = base.partition("?")
    params = parse_qs(query, keep_blank_values=True)
    params["open"] = [str(dive_id)]
    return f"{path}?{urlencode(params, doseq=True)}"


def _url_without_open(value):
    base = _safe_next_url(value)
    path, _, query = base.partition("?")
    params = parse_qs(query, keep_blank_values=True)
    params.pop("open", None)
    encoded = urlencode(params, doseq=True)
    return f"{path}?{encoded}" if encoded else path


def dedupe_species(values):
    seen = set()
    clean = []
    for value in values:
        name = str(value).strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            clean.append(name[:100])
    return clean[:40]


def valid_species_names(values, db):
    valid = []
    for value in values:
        row = db.execute(
            """
            SELECT common_name
            FROM species
            WHERE lower(common_name) = lower(?)
            ORDER BY id
            LIMIT 1
            """,
            (value,),
        ).fetchone()
        if row:
            valid.append(row["common_name"])
    return valid


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_upload(file_storage, folder):
    safe_name = secure_filename(file_storage.filename)
    suffix = safe_name.rsplit(".", 1)[-1].lower()
    upload_id = uuid.uuid4().hex
    filename = f"{folder}/{upload_id}.jpg"
    target = Path(current_app.config["UPLOAD_FOLDER"], filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _save_resized_image(file_storage, target)
    except (OSError, UnidentifiedImageError):
        filename = f"{folder}/{upload_id}.{suffix}"
        target = Path(current_app.config["UPLOAD_FOLDER"], filename)
        file_storage.stream.seek(0)
        file_storage.save(target)
    return f"uploads/{filename}"


def _save_resized_image(file_storage, target):
    file_storage.stream.seek(0)
    with Image.open(file_storage.stream) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((UPLOAD_IMAGE_MAX_DIMENSION, UPLOAD_IMAGE_MAX_DIMENSION), Image.Resampling.LANCZOS)
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, "#0b1118")
            background.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.save(target, "JPEG", quality=UPLOAD_IMAGE_JPEG_QUALITY, optimize=True, progressive=True)
