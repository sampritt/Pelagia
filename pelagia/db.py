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
    _ensure_column(db, "dives", "visibility_ft", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "dives", "air_temp_degrees", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "dives", "water_temp_degrees", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "dives", "dive_type", "TEXT NOT NULL DEFAULT 'reef'")
    _ensure_column(db, "dives", "current", "TEXT NOT NULL DEFAULT 'slack'")
    _ensure_column(db, "dives", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    db.commit()


def _ensure_column(db, table_name, column_name, column_type):
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        try:
            db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise


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
