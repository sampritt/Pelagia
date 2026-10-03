import sqlite3
from pathlib import Path

import click
from flask import current_app, g


def get_db():
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    schema = Path(current_app.root_path, "schema.sql").read_text()
    db.executescript(schema)
    _ensure_column(db, "users", "google_subject", "TEXT")
    _ensure_column(db, "users", "google_email", "TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_subject ON users(google_subject)")
    _ensure_column(db, "dives", "buddy_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
    _ensure_column(db, "dives", "dive_center_id", "INTEGER")
    _ensure_column(db, "dives", "dive_center_name", "TEXT")
    _ensure_column(db, "dives", "exposure", "TEXT")
    _ensure_column(db, "dives", "gas_mix", "TEXT NOT NULL DEFAULT 'Air'")
    _ensure_column(db, "dives", "dive_type", "TEXT NOT NULL DEFAULT 'open water'")
    _ensure_column(db, "dives", "current", "TEXT NOT NULL DEFAULT 'none'")
    _ensure_column(db, "dives", "current_strength", "TEXT NOT NULL DEFAULT 'none'")
    _ensure_column(db, "dives", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "dive_sites", "logged_dive_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_metric_dive_schema(db)
    _normalize_current_values(db)
    _ensure_dive_site_counts(db)
    db.execute("CREATE INDEX IF NOT EXISTS idx_dives_buddy_user ON dives(buddy_user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dive_sites_logged_dive_count ON dive_sites(logged_dive_count DESC)")
    db.commit()


def _ensure_column(db, table_name, column_name, column_type):
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        try:
            db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise


def _normalize_current_values(db):
    db.execute("UPDATE dives SET current = 'none' WHERE current NOT IN ('none', 'slack', 'tidal', 'surge', 'drift', 'rip', 'vertical')")
    db.execute(
        "UPDATE dives SET current_strength = 'none' "
        "WHERE current_strength NOT IN ('none', 'light', 'moderate', 'strong', 'very strong')"
    )
    db.execute(
        """
        UPDATE dives
        SET exposure = NULL
        WHERE exposure IS NOT NULL
            AND exposure NOT IN ('swimsuit', 'shorty', '2mm', '3mm', '4mm', '5mm', '6mm', '7mm', 'dry suit')
        """
    )
    db.execute("UPDATE dives SET gas_mix = 'Air' WHERE gas_mix NOT IN ('Air', '30%', '32%', '34%', '36%', '38%', '40%', 'Other')")


def _ensure_dive_site_counts(db):
    db.execute(
        """
        UPDATE dive_sites
        SET logged_dive_count = (
            SELECT COUNT(*)
            FROM dives
            WHERE dives.dive_site_id = dive_sites.id
                AND COALESCE(dives.is_deleted, 0) = 0
        )
        """
    )
    db.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS increment_dive_site_count_after_insert
        AFTER INSERT ON dives
        WHEN NEW.dive_site_id IS NOT NULL AND COALESCE(NEW.is_deleted, 0) = 0
        BEGIN
            UPDATE dive_sites
            SET logged_dive_count = logged_dive_count + 1
            WHERE id = NEW.dive_site_id;
        END;

        CREATE TRIGGER IF NOT EXISTS update_dive_site_count_after_update
        AFTER UPDATE OF dive_site_id, is_deleted ON dives
        BEGIN
            UPDATE dive_sites
            SET logged_dive_count = MAX(logged_dive_count - 1, 0)
            WHERE id = OLD.dive_site_id
                AND OLD.dive_site_id IS NOT NULL
                AND COALESCE(OLD.is_deleted, 0) = 0;

            UPDATE dive_sites
            SET logged_dive_count = logged_dive_count + 1
            WHERE id = NEW.dive_site_id
                AND NEW.dive_site_id IS NOT NULL
                AND COALESCE(NEW.is_deleted, 0) = 0;
        END;

        CREATE TRIGGER IF NOT EXISTS decrement_dive_site_count_after_delete
        AFTER DELETE ON dives
        WHEN OLD.dive_site_id IS NOT NULL AND COALESCE(OLD.is_deleted, 0) = 0
        BEGIN
            UPDATE dive_sites
            SET logged_dive_count = MAX(logged_dive_count - 1, 0)
            WHERE id = OLD.dive_site_id;
        END;
        """
    )


def _ensure_metric_dive_schema(db):
    _ensure_column(db, "dives", "depth_m", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "dives", "weight_kg", "REAL")
    _ensure_column(db, "dives", "starting_pressure_bar", "INTEGER")
    _ensure_column(db, "dives", "ending_pressure_bar", "INTEGER")
    _ensure_column(db, "dives", "sac_rate_l_min", "REAL")
    _ensure_column(db, "dives", "visibility_m", "INTEGER")
    _ensure_column(db, "dives", "air_temp_c", "INTEGER")
    _ensure_column(db, "dives", "water_temp_c", "INTEGER")
    columns = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(dives)").fetchall()
    }
    legacy_columns = {"depth_ft", "weight_lbs", "visibility_ft", "air_temp_degrees", "water_temp_degrees"}
    optional_columns = (
        "weight_kg",
        "starting_pressure_bar",
        "ending_pressure_bar",
        "sac_rate_l_min",
        "exposure",
        "visibility_m",
        "air_temp_c",
        "water_temp_c",
    )
    has_legacy_units = bool(legacy_columns.intersection(columns))
    optional_columns_are_nullable = all(
        column in columns and columns[column]["notnull"] == 0
        for column in optional_columns
    )
    weight_column_is_real = (
        "weight_kg" in columns and columns["weight_kg"]["type"].upper() == "REAL"
    )
    if not has_legacy_units and optional_columns_are_nullable and weight_column_is_real:
        return

    depth_expression = (
        "CAST(ROUND(depth_ft * 0.3048) AS INTEGER)"
        if "depth_ft" in columns
        else "depth_m"
    )
    weight_expression = (
        "CASE WHEN weight_lbs IS NULL THEN NULL ELSE CAST(ROUND(weight_lbs * 0.45359237) AS INTEGER) END"
        if "weight_lbs" in columns
        else "weight_kg"
    )
    visibility_expression = (
        "CASE WHEN visibility_ft IS NULL THEN NULL ELSE CAST(ROUND(visibility_ft * 0.3048) AS INTEGER) END"
        if "visibility_ft" in columns
        else "visibility_m"
    )
    air_temp_expression = (
        "CASE WHEN air_temp_degrees IS NULL THEN NULL ELSE CAST(ROUND((air_temp_degrees - 32) * 5.0 / 9.0) AS INTEGER) END"
        if "air_temp_degrees" in columns
        else "air_temp_c"
    )
    water_temp_expression = (
        "CASE WHEN water_temp_degrees IS NULL THEN NULL ELSE CAST(ROUND((water_temp_degrees - 32) * 5.0 / 9.0) AS INTEGER) END"
        if "water_temp_degrees" in columns
        else "water_temp_c"
    )

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            f"""
            CREATE TABLE dives_rebuild (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                buddy_user_id INTEGER,
                dive_site_id INTEGER,
                dive_center_id INTEGER,
                dive_center_name TEXT,
                date TEXT NOT NULL,
                site_name TEXT NOT NULL,
                country_or_area TEXT,
                latitude REAL,
                longitude REAL,
                depth_m INTEGER NOT NULL DEFAULT 0,
                duration_min INTEGER NOT NULL DEFAULT 0,
                weight_kg REAL,
                starting_pressure_bar INTEGER,
                ending_pressure_bar INTEGER,
                sac_rate_l_min REAL,
                exposure TEXT,
                visibility_m INTEGER,
                air_temp_c INTEGER,
                water_temp_c INTEGER,
                gas_mix TEXT NOT NULL DEFAULT 'Air',
                dive_type TEXT NOT NULL DEFAULT 'open water',
                current TEXT NOT NULL DEFAULT 'none',
                current_strength TEXT NOT NULL DEFAULT 'none',
                notes TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(buddy_user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(dive_site_id) REFERENCES dive_sites(id) ON DELETE SET NULL,
                FOREIGN KEY(dive_center_id) REFERENCES dive_centers(id) ON DELETE SET NULL
            );

            INSERT INTO dives_rebuild (
                id, user_id, buddy_user_id, dive_site_id, dive_center_id, dive_center_name, date, site_name,
                country_or_area, latitude, longitude, depth_m, duration_min, weight_kg,
                starting_pressure_bar, ending_pressure_bar, sac_rate_l_min,
                exposure, visibility_m, air_temp_c, water_temp_c, gas_mix, dive_type,
                current, current_strength, notes, is_deleted, created_at
            )
            SELECT
                id, user_id, buddy_user_id, dive_site_id, dive_center_id, dive_center_name, date, site_name,
                country_or_area, latitude, longitude, {depth_expression}, duration_min, {weight_expression},
                starting_pressure_bar, ending_pressure_bar, sac_rate_l_min,
                exposure, {visibility_expression}, {air_temp_expression}, {water_temp_expression}, gas_mix, dive_type,
                current, current_strength, notes, is_deleted, created_at
            FROM dives;

            DROP TABLE dives;
            ALTER TABLE dives_rebuild RENAME TO dives;
            CREATE INDEX IF NOT EXISTS idx_dives_user_created ON dives(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dives_created ON dives(created_at DESC);
            """
        )
        db.commit()
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def table_count(table_name):
    row = get_db().execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"]) if row else 0


@click.command("init-db")
def init_db_command():
    init_db()
    click.echo("Initialized the Pelagia database.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
