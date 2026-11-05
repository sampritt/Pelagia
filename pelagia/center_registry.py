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


def _legacy_reference(row):
    return "legacy:" + hashlib.sha256(json.dumps(_legacy_key(row)).encode()).hexdigest()


def _read_rows(content):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = set(FIELDS[:4])
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Dive-center CSV is missing name, address, location or website columns")
    rows = {}
    for source in reader:
        row = {field: _text(source.get(field)) for field in FIELDS}
        if not row["name"] or not row["physical_address"] or not row["website"]:
            continue
        key = next((f"{provider}:{_text(source.get(field))}" for provider, field in
                    (("padi", "padi_id"), ("overture", "overture_id"), ("padi-url", "padi_url"))
                    if _text(source.get(field))), None)
        if key is None:
            key = _legacy_reference(row)
        for field, limit in (("latitude", 90), ("longitude", 180)):
            value = row[field]
            row[field] = float(value) if value else None
            if row[field] is not None and (not math.isfinite(row[field]) or abs(row[field]) > limit):
                raise ValueError(f"Invalid {field} for {row['name']}")
        row["reference_key"] = key
        aliases = json.loads(source.get("merged_reference_keys") or "[]")
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias for alias in aliases):
            raise ValueError(f"Invalid merged identities for {row['name']}")
        row["merged_reference_keys"] = aliases
        if key in rows and rows[key] != row:
            raise ValueError(f"Conflicting duplicate dive-center identity: {key}")
        rows[key] = row
    if not rows:
        raise ValueError("Dive-center CSV has no records with a name, address and website")
    identities = {}
    for row in rows.values():
        for key in [row["reference_key"], *row["merged_reference_keys"]]:
            if key in identities and identities[key] != row["reference_key"]:
                raise ValueError(f"Conflicting merged dive-center identity: {key}")
            identities[key] = row["reference_key"]
    return list(rows.values())


def _merge_center_links(db, source_id, target_id):
    """Move community data before removing a duplicate catalogue row."""
    db.execute("""UPDATE dives SET dive_center_id=?,
        dive_center_name=COALESCE(NULLIF(dive_center_name, ''),
            (SELECT name FROM dive_centers WHERE id=?)) WHERE dive_center_id=?""",
        (target_id, source_id, source_id))
    db.execute("""INSERT OR IGNORE INTO dive_center_likes(dive_center_id,user_id,created_at)
        SELECT ?,user_id,created_at FROM dive_center_likes WHERE dive_center_id=?""", (target_id, source_id))
    db.execute("UPDATE dive_center_comments SET dive_center_id=? WHERE dive_center_id=?", (target_id, source_id))
    # Each account has one review per center. Keep the most recently edited
    # review if that account reviewed both duplicate records.
    db.execute("""INSERT INTO dive_center_reviews(dive_center_id,user_id,rating,body,created_at,updated_at)
        SELECT ?,user_id,rating,body,created_at,updated_at FROM dive_center_reviews WHERE dive_center_id=?
        ON CONFLICT(dive_center_id,user_id) DO UPDATE SET rating=excluded.rating,
            body=excluded.body,created_at=excluded.created_at,updated_at=excluded.updated_at
        WHERE excluded.updated_at > dive_center_reviews.updated_at""", (target_id, source_id))
    db.execute("""INSERT INTO dive_center_descriptions(dive_center_id,description,citations_json,model,created_at)
        SELECT ?,description,citations_json,model,created_at FROM dive_center_descriptions WHERE dive_center_id=?
        ON CONFLICT(dive_center_id) DO UPDATE SET description=excluded.description,
            citations_json=excluded.citations_json,model=excluded.model,created_at=excluded.created_at
        WHERE dive_center_descriptions.description IS NULL AND excluded.description IS NOT NULL""",
        (target_id, source_id))


def refresh_centers(db, csv_path):
    """Replace catalogue contents once per CSV change, serializing web workers.

    Matching shops keep their integer IDs; merged shops transfer their links.
    Removed shops' logged dives retain the recorded name and lose the link.
    """
    content = Path(csv_path).read_bytes()
    digest = hashlib.sha256(b"center-registry-v2\0" + content).hexdigest()
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
                legacy[_legacy_reference(row)].append(row)
        next_id = max((row["id"] for row in existing), default=0) + 1
        kept = set()
        values = []
        merged = []
        for row in incoming:
            match = by_identity.get(row["reference_key"])
            matches = {candidate["id"]: candidate for key in
                       [row["reference_key"], _legacy_reference(row), *row["merged_reference_keys"]]
                       for candidate in ([by_identity[key]] if key in by_identity else []) + legacy.get(key, [])}
            if match is None and matches:
                candidates = legacy.get(_legacy_reference(row), []) or matches.values()
                match = min(candidates, key=lambda candidate: candidate["id"])
            center_id = match["id"] if match else next_id
            if match is None:
                next_id += 1
            if center_id in kept:
                raise ValueError("Multiple incoming centers match the same stored identity")
            kept.add(center_id)
            merged.extend((candidate_id, center_id) for candidate_id in matches if candidate_id != center_id)
            values.append((center_id, row["reference_key"], *(row[field] for field in FIELDS)))
        if any(source in kept for source, target in merged):
            raise ValueError("A merged center is also a surviving catalogue identity")
        merge_targets = {}
        for source_id, target_id in merged:
            if source_id in merge_targets and merge_targets[source_id] != target_id:
                raise ValueError("A stored center matches multiple merge destinations")
            merge_targets[source_id] = target_id
        for source_id, target_id in merge_targets.items():
            _merge_center_links(db, source_id, target_id)
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
        for table in ("dive_center_likes", "dive_center_comments", "dive_center_reviews",
                      "dive_center_descriptions", "dive_center_description_attempts"):
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
