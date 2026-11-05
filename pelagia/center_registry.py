"""Refresh the searchable dive-shop table from the deployed CSV."""

import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from pathlib import Path

FIELDS = ("name", "physical_address", "location", "website", "latitude", "longitude")


def _text(value):
    return (value or "").strip()


def _legacy_key(row):
    return tuple(_text(row[field]).casefold() for field in FIELDS[:3])


def _read_rows(content):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = set(FIELDS[:4])
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Dive-center CSV is missing name, address, location or website columns")
    rows = {}
    for source in reader:
        row = {field: _text(source.get(field)) for field in FIELDS}
        if not row["name"]:
            continue
        key = next((f"{provider}:{_text(source.get(field))}" for provider, field in
                    (("padi", "padi_id"), ("overture", "overture_id"), ("padi-url", "padi_url"))
                    if _text(source.get(field))), None)
        if key is None:
            key = "legacy:" + hashlib.sha256(json.dumps(_legacy_key(row)).encode()).hexdigest()
        for field, limit in (("latitude", 90), ("longitude", 180)):
            value = row[field]
            row[field] = float(value) if value else None
            if row[field] is not None and (not math.isfinite(row[field]) or abs(row[field]) > limit):
                raise ValueError(f"Invalid {field} for {row['name']}")
        row["reference_key"] = key
        if key in rows and rows[key] != row:
            raise ValueError(f"Conflicting duplicate dive-center identity: {key}")
        rows[key] = row
    if not rows:
        raise ValueError("Dive-center CSV has no named records")
    return list(rows.values())


def refresh_centers(db, csv_path):
    """Replace catalogue contents once per CSV change, serializing web workers.

    Matching shops keep their integer IDs. Obsolete shops are removed; their
    logged dives retain the recorded shop name and lose the obsolete link.
    """
    content = Path(csv_path).read_bytes()
    digest = hashlib.sha256(b"center-registry-v1\0" + content).hexdigest()
    incoming = _read_rows(content)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("CREATE TABLE IF NOT EXISTS reference_catalog_versions (name TEXT PRIMARY KEY, digest TEXT NOT NULL)")
        previous = db.execute("SELECT digest FROM reference_catalog_versions WHERE name='dive_centers'").fetchone()
        count = db.execute("SELECT COUNT(*) FROM dive_centers").fetchone()[0]
        if previous and previous[0] == digest and count == len(incoming):
            db.commit()
            return {"changed": False, "rows": len(incoming)}
        columns = {row[1] for row in db.execute("PRAGMA table_info(dive_centers)")}
        if "reference_key" not in columns:
            db.execute("ALTER TABLE dive_centers ADD COLUMN reference_key TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_centers_reference_key ON dive_centers(reference_key)")
        cursor = db.execute("SELECT id, reference_key, name, physical_address, location, website FROM dive_centers")
        existing = [dict(zip([field[0] for field in cursor.description], row)) for row in cursor.fetchall()]
        by_identity = {row["reference_key"]: row for row in existing if row["reference_key"]}
        legacy = defaultdict(list)
        for row in existing:
            if not row["reference_key"]:
                legacy[_legacy_key(row)].append(row)
        next_id = max((row["id"] for row in existing), default=0) + 1
        kept = set()
        values = []
        for row in incoming:
            match = by_identity.get(row["reference_key"])
            if match is None:
                matches = legacy.get(_legacy_key(row), [])
                match = next((candidate for candidate in matches if candidate["id"] not in kept), None)
            center_id = match["id"] if match else next_id
            if match is None:
                next_id += 1
            kept.add(center_id)
            values.append((center_id, row["reference_key"], *(row[field] for field in FIELDS)))
        db.execute("CREATE TEMP TABLE center_registry_keep (id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO center_registry_keep VALUES (?)", [(value,) for value in kept])
        # Clear obsolete links explicitly, including databases with legacy
        # dives tables that do not have the modern foreign-key constraint.
        db.execute("""UPDATE dives SET
            dive_center_name=COALESCE(NULLIF(dive_center_name, ''),
                (SELECT name FROM dive_centers WHERE id=dives.dive_center_id)),
            dive_center_id=NULL
            WHERE dive_center_id IN (SELECT id FROM dive_centers
                WHERE id NOT IN (SELECT id FROM center_registry_keep))""")
        for table in ("dive_center_likes", "dive_center_comments"):
            db.execute(f"DELETE FROM {table} WHERE dive_center_id NOT IN (SELECT id FROM center_registry_keep)")
        deleted = db.execute("DELETE FROM dive_centers WHERE id NOT IN (SELECT id FROM center_registry_keep)").rowcount
        db.executemany("""INSERT INTO dive_centers
            (id, reference_key, name, physical_address, location, website, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET reference_key=excluded.reference_key,
                name=excluded.name, physical_address=excluded.physical_address,
                location=excluded.location, website=excluded.website,
                latitude=excluded.latitude, longitude=excluded.longitude""", values)
        db.execute("DROP TABLE center_registry_keep")
        db.execute("INSERT OR REPLACE INTO reference_catalog_versions VALUES ('dive_centers', ?)", (digest,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"changed": True, "rows": len(incoming), "removed": deleted}


def configured_csv(app):
    from .importer import resolve_path
    return resolve_path(app.config["PELAGIA_CONFIG_PATH"], app.config["PELAGIA_LOCAL_CONFIG"].get(
        "data_sources", {}).get("dive_centers_csv", "data/padi_dive_centers.csv"))
