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
    _ensure_column(db, "dives", "dive_center_id", "INTEGER")
    _ensure_column(db, "dives", "dive_center_name", "TEXT")
    _ensure_column(db, "dives", "weight_lbs", "INTEGER")
    _ensure_column(db, "dives", "exposure", "TEXT")
    _ensure_column(db, "dives", "visibility_ft", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "dives", "air_temp_degrees", "INTEGER")
    _ensure_column(db, "dives", "water_temp_degrees", "INTEGER")
    _ensure_column(db, "dives", "dive_type", "TEXT NOT NULL DEFAULT 'open water'")
    _ensure_column(db, "dives", "current", "TEXT NOT NULL DEFAULT 'none'")
    _ensure_column(db, "dives", "current_strength", "TEXT NOT NULL DEFAULT 'none'")
    _ensure_column(db, "dives", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    _ensure_nullable_dive_metadata(db)
    _normalize_current_values(db)
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


def _ensure_nullable_dive_metadata(db):
    columns = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(dives)").fetchall()
    }
    optional_columns = ("weight_lbs", "exposure", "air_temp_degrees", "water_temp_degrees")
    if all(column in columns and columns[column]["notnull"] == 0 for column in optional_columns):
        return

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            """
            CREATE TABLE dives_rebuild (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                dive_site_id INTEGER,
                dive_center_id INTEGER,
                dive_center_name TEXT,
                date TEXT NOT NULL,
                site_name TEXT NOT NULL,
                country_or_area TEXT,
                latitude REAL,
                longitude REAL,
                depth_ft INTEGER NOT NULL DEFAULT 0,
                duration_min INTEGER NOT NULL DEFAULT 0,
                weight_lbs INTEGER,
                exposure TEXT,
                visibility_ft INTEGER NOT NULL DEFAULT 0,
                air_temp_degrees INTEGER,
                water_temp_degrees INTEGER,
                dive_type TEXT NOT NULL DEFAULT 'open water',
                current TEXT NOT NULL DEFAULT 'none',
                current_strength TEXT NOT NULL DEFAULT 'none',
                notes TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(dive_site_id) REFERENCES dive_sites(id) ON DELETE SET NULL,
                FOREIGN KEY(dive_center_id) REFERENCES dive_centers(id) ON DELETE SET NULL
            );

            INSERT INTO dives_rebuild (
                id, user_id, dive_site_id, dive_center_id, dive_center_name, date, site_name,
                country_or_area, latitude, longitude, depth_ft, duration_min, weight_lbs,
                exposure, visibility_ft, air_temp_degrees, water_temp_degrees, dive_type,
                current, current_strength, notes, is_deleted, created_at
            )
            SELECT
                id, user_id, dive_site_id, dive_center_id, dive_center_name, date, site_name,
                country_or_area, latitude, longitude, depth_ft, duration_min, weight_lbs,
                exposure, visibility_ft, air_temp_degrees, water_temp_degrees, dive_type,
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
