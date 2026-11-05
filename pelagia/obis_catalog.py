"""Bulk OBIS occurrence ingestion for Pelagia's species vocabulary."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


OBIS_ROOT = "https://api.obis.org/v3"
WORMS_ROOT = "https://www.marinespecies.org/rest"
START_DATE = date(2020, 1, 1)
RADIUS_MILES = 0.5
METERS_PER_MILE = 1609.344
EARTH_RADIUS_M = 6_371_008.8
PAGE_SIZE = 10_000
GRID_DEGREES = 0.01
USER_AGENT = "Pelagia-OBIS-catalog-ingest/1.0"

RANK_PRIORITY = {
    "subspecies": 0,
    "species": 1,
    "subgenus": 2,
    "genus": 3,
    "subfamily": 4,
    "family": 5,
    "superfamily": 6,
    "infraorder": 7,
    "suborder": 8,
    "order": 9,
    "superorder": 10,
    "subclass": 11,
    "class": 12,
    "superclass": 13,
    "subphylum": 14,
    "phylum": 15,
    "kingdom": 16,
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS pelagia_species_obis_resolution (
    species_id INTEGER PRIMARY KEY REFERENCES species(id) ON DELETE CASCADE,
    common_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('resolved', 'unresolved', 'skipped')),
    source TEXT NOT NULL,
    note TEXT,
    resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pelagia_species_obis_taxa (
    species_id INTEGER NOT NULL REFERENCES species(id) ON DELETE CASCADE,
    taxon_id INTEGER NOT NULL,
    scientific_name TEXT NOT NULL,
    taxon_rank TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (species_id, taxon_id)
);

CREATE INDEX IF NOT EXISTS idx_pelagia_species_obis_taxa_taxon
ON pelagia_species_obis_taxa(taxon_id);

CREATE TABLE IF NOT EXISTS obis_occurrences (
    obis_id TEXT PRIMARY KEY,
    occurrence_id TEXT,
    queried_taxon_id INTEGER NOT NULL,
    scientific_name TEXT,
    event_date TEXT,
    decimal_latitude REAL NOT NULL,
    decimal_longitude REAL NOT NULL,
    coordinate_uncertainty_m REAL NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obis_occurrences_taxon
ON obis_occurrences(queried_taxon_id);

CREATE TABLE IF NOT EXISTS obis_occurrence_queries (
    obis_id TEXT NOT NULL REFERENCES obis_occurrences(obis_id) ON DELETE CASCADE,
    taxon_id INTEGER NOT NULL,
    PRIMARY KEY (obis_id, taxon_id)
);

CREATE TABLE IF NOT EXISTS dive_site_obis_occurrences (
    dive_site_id INTEGER NOT NULL REFERENCES dive_sites(id) ON DELETE CASCADE,
    species_id INTEGER NOT NULL REFERENCES species(id) ON DELETE CASCADE,
    obis_id TEXT NOT NULL REFERENCES obis_occurrences(obis_id) ON DELETE CASCADE,
    distance_meters REAL NOT NULL,
    PRIMARY KEY (dive_site_id, species_id, obis_id)
);

CREATE INDEX IF NOT EXISTS idx_dive_site_obis_occurrences_species
ON dive_site_obis_occurrences(species_id, dive_site_id);

CREATE TABLE IF NOT EXISTS obis_taxon_ingestion (
    taxon_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete')),
    after_cursor TEXT,
    pages INTEGER NOT NULL DEFAULT 0,
    records_seen INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (taxon_id, start_date, end_date)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalized_longitude_delta(left: float, right: float) -> float:
    return (right - left + 180.0) % 360.0 - 180.0


def cartesian_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Local equirectangular distance: Cartesian x/y on the WGS84 sphere."""
    mean_latitude = math.radians((lat1 + lat2) / 2.0)
    x = math.radians(normalized_longitude_delta(lon1, lon2)) * math.cos(mean_latitude)
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * EARTH_RADIUS_M


@dataclass(frozen=True)
class DiveSite:
    id: int
    latitude: float
    longitude: float


class DiveSiteIndex:
    """Small in-memory grid followed by an exact local Cartesian check."""

    def __init__(self, sites, radius_m: float):
        self.radius_m = radius_m
        self.cells = defaultdict(list)
        for site in sites:
            self.cells[self._cell(site.latitude, site.longitude)].append(site)

    @staticmethod
    def _cell(latitude: float, longitude: float):
        return (
            math.floor((latitude + 90.0) / GRID_DEGREES),
            math.floor(((longitude + 180.0) % 360.0) / GRID_DEGREES),
        )

    def nearby(self, latitude: float, longitude: float):
        center_lat, center_lon = self._cell(latitude, longitude)
        lat_cells = math.ceil(math.degrees(self.radius_m / EARTH_RADIUS_M) / GRID_DEGREES) + 1
        cosine = max(abs(math.cos(math.radians(latitude))), 1e-6)
        lon_cells = min(
            36_000,
            math.ceil(math.degrees(self.radius_m / EARTH_RADIUS_M / cosine) / GRID_DEGREES) + 1,
        )
        longitude_cell_count = round(360.0 / GRID_DEGREES)
        matches = []
        for lat_cell in range(center_lat - lat_cells, center_lat + lat_cells + 1):
            for lon_offset in range(-lon_cells, lon_cells + 1):
                lon_cell = (center_lon + lon_offset) % longitude_cell_count
                for site in self.cells.get((lat_cell, lon_cell), ()):
                    distance = cartesian_distance_m(
                        latitude, longitude, site.latitude, site.longitude
                    )
                    if distance < self.radius_m:
                        matches.append((site, distance))
        return matches


class JsonApi:
    def __init__(self, *, timeout=45, retries=4, request_delay=0.0, session=None):
        self.timeout = timeout
        self.retries = retries
        self.request_delay = request_delay
        self.session = session or requests.Session()

    def get(self, url, *, params=None, allow_empty=False):
        for attempt in range(self.retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    timeout=(5, self.timeout),
                )
                if allow_empty and response.status_code in (204, 404):
                    return []
                if response.status_code in (429, 500, 502, 503, 504):
                    delay = finite_number(response.headers.get("Retry-After"))
                    if attempt + 1 < self.retries:
                        time.sleep(delay if delay is not None else 2 ** attempt)
                        continue
                response.raise_for_status()
                payload = response.json()
                if self.request_delay:
                    time.sleep(self.request_delay)
                return payload
            except (requests.RequestException, ValueError) as error:
                if attempt + 1 == self.retries:
                    raise RuntimeError(f"GET {url} failed: {error}") from error
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")


def initialize_schema(db):
    db.executescript(SCHEMA)
    db.commit()


def load_sites(db):
    rows = db.execute(
        "SELECT id, latitude, longitude FROM dive_sites "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    sites = []
    for row in rows:
        latitude, longitude = finite_number(row["latitude"]), finite_number(row["longitude"])
        if latitude is not None and longitude is not None and -90 <= latitude <= 90 and -180 <= longitude <= 180:
            sites.append(DiveSite(row["id"], latitude, longitude))
    return sites


def _worms_records(api: JsonApi, path: str):
    records, offset = [], 1
    while True:
        payload = api.get(
            f"{WORMS_ROOT}/{path}",
            params={"like": "false", "marine_only": "true", "offset": offset},
            allow_empty=True,
        )
        if not isinstance(payload, list):
            raise RuntimeError("WoRMS returned an unexpected taxonomy response")
        records.extend(record for record in payload if isinstance(record, dict))
        if len(payload) < 50:
            return records
        offset += 50


def _accepted_taxa(records):
    candidates = {}
    for record in records:
        if record.get("isMarine") not in (1, True, None):
            continue
        taxon_id = record.get("valid_AphiaID") or record.get("AphiaID")
        try:
            taxon_id = int(taxon_id)
        except (TypeError, ValueError):
            continue
        rank = str(record.get("rank") or "").strip()
        candidates[taxon_id] = {
            "taxon_id": taxon_id,
            "scientific_name": str(
                record.get("valid_name") or record.get("scientificname") or ""
            ).strip(),
            "taxon_rank": rank or None,
        }
    if not candidates:
        return []
    best_rank = min(RANK_PRIORITY.get(value["taxon_rank"].casefold(), 100) for value in candidates.values())
    return sorted(
        (
            value for value in candidates.values()
            if RANK_PRIORITY.get((value["taxon_rank"] or "").casefold(), 100) == best_rank
        ),
        key=lambda value: (value["scientific_name"].casefold(), value["taxon_id"]),
    )


def resolve_name(api: JsonApi, common_name: str):
    encoded = quote(common_name, safe="")
    records = _worms_records(api, f"AphiaRecordsByVernacular/{encoded}")
    source = "worms_vernacular"
    if not records:
        records = _worms_records(api, f"AphiaRecordsByName/{encoded}")
        source = "worms_scientific_name"
    return _accepted_taxa(records), source


def load_overrides(path: Path | None):
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("taxon override file must contain a JSON object")
    overrides = {}
    for name, ids in payload.items():
        if ids is None:
            overrides[str(name).casefold()] = []
            continue
        if not isinstance(ids, list) or not all(isinstance(value, int) and value > 0 for value in ids):
            raise ValueError(f"override for {name!r} must be a list of positive AphiaIDs or null")
        overrides[str(name).casefold()] = sorted(set(ids))
    return overrides


def _obis_taxon(api: JsonApi, taxon_id: int):
    payload = api.get(f"{OBIS_ROOT}/taxon/{taxon_id}")
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"OBIS has no taxon {taxon_id}")
    row = rows[0]
    return {
        "taxon_id": int(row.get("acceptedNameUsageID") or row.get("taxonID") or taxon_id),
        "scientific_name": str(row.get("acceptedNameUsage") or row.get("scientificName") or "").strip(),
        "taxon_rank": str(row.get("taxonRank") or "").strip() or None,
    }


def resolve_species(db, api: JsonApi, *, overrides=None, refresh=False, selected_names=None, progress=print):
    overrides = overrides or {}
    selected = {name.casefold() for name in selected_names or []}
    rows = db.execute("SELECT id, common_name FROM species ORDER BY common_name COLLATE NOCASE").fetchall()
    for index, row in enumerate(rows, 1):
        species_id, common_name = row["id"], row["common_name"]
        if selected and common_name.casefold() not in selected:
            continue
        if not refresh and db.execute(
            "SELECT 1 FROM pelagia_species_obis_resolution WHERE species_id = ?", (species_id,)
        ).fetchone():
            continue
        key = common_name.casefold()
        if key in overrides:
            ids = overrides[key]
            taxa = [_obis_taxon(api, taxon_id) for taxon_id in ids]
            source = "manual_override"
            status = "resolved" if taxa else "skipped"
        else:
            taxa, source = resolve_name(api, common_name)
            status = "resolved" if taxa else "unresolved"
        with db:
            db.execute("DELETE FROM pelagia_species_obis_taxa WHERE species_id = ?", (species_id,))
            db.execute(
                "INSERT INTO pelagia_species_obis_resolution "
                "(species_id, common_name, status, source, note, resolved_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(species_id) DO UPDATE SET common_name=excluded.common_name, "
                "status=excluded.status, source=excluded.source, note=excluded.note, "
                "resolved_at=excluded.resolved_at",
                (species_id, common_name, status, source, None, utc_now()),
            )
            db.executemany(
                "INSERT INTO pelagia_species_obis_taxa "
                "(species_id, taxon_id, scientific_name, taxon_rank, source) VALUES (?, ?, ?, ?, ?)",
                [
                    (species_id, taxon["taxon_id"], taxon["scientific_name"], taxon["taxon_rank"], source)
                    for taxon in taxa
                ],
            )
        progress(f"resolve {index}/{len(rows)} {common_name}: {status} ({len(taxa)} taxa)")


def qualifying_occurrence(row, radius_m):
    if row.get("absence") is True or str(row.get("occurrenceStatus") or "").casefold() == "absent":
        return None
    latitude = finite_number(row.get("decimalLatitude"))
    longitude = finite_number(row.get("decimalLongitude"))
    uncertainty = finite_number(row.get("coordinateUncertaintyInMeters"))
    if (
        latitude is None or longitude is None or uncertainty is None
        or not -90 <= latitude <= 90 or not -180 <= longitude <= 180
        or uncertainty < 0 or uncertainty >= radius_m
    ):
        return None
    return latitude, longitude, uncertainty


def occurrence_key(row):
    value = row.get("id") or row.get("occurrenceID")
    if value:
        return str(value)
    stable = json.dumps(
        {
            key: row.get(key)
            for key in ("dataset_id", "eventID", "scientificName", "eventDate", "decimalLatitude", "decimalLongitude")
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    import hashlib
    return "derived:" + hashlib.sha256(stable.encode()).hexdigest()


def _save_page(db, taxon_id, species_ids, rows, site_index, start_date, end_date, next_after, complete):
    accepted = links = 0
    with db:
        for row in rows:
            if not isinstance(row, dict):
                continue
            coordinates = qualifying_occurrence(row, site_index.radius_m)
            if coordinates is None:
                continue
            latitude, longitude, uncertainty = coordinates
            nearby = site_index.nearby(latitude, longitude)
            if not nearby:
                continue
            obis_id = occurrence_key(row)
            db.execute(
                "INSERT INTO obis_occurrences "
                "(obis_id, occurrence_id, queried_taxon_id, scientific_name, event_date, "
                "decimal_latitude, decimal_longitude, coordinate_uncertainty_m, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(obis_id) DO UPDATE SET occurrence_id=excluded.occurrence_id, "
                "scientific_name=excluded.scientific_name, event_date=excluded.event_date, "
                "decimal_latitude=excluded.decimal_latitude, decimal_longitude=excluded.decimal_longitude, "
                "coordinate_uncertainty_m=excluded.coordinate_uncertainty_m, raw_json=excluded.raw_json",
                (
                    obis_id, row.get("occurrenceID"), taxon_id, row.get("scientificName"),
                    row.get("eventDate"), latitude, longitude, uncertainty,
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO obis_occurrence_queries (obis_id, taxon_id) VALUES (?, ?)",
                (obis_id, taxon_id),
            )
            accepted += 1
            for site, distance in nearby:
                for species_id in species_ids:
                    cursor = db.execute(
                        "INSERT OR IGNORE INTO dive_site_obis_occurrences "
                        "(dive_site_id, species_id, obis_id, distance_meters) VALUES (?, ?, ?, ?)",
                        (site.id, species_id, obis_id, distance),
                    )
                    links += cursor.rowcount
        prior = db.execute(
            "SELECT pages, records_seen FROM obis_taxon_ingestion "
            "WHERE taxon_id=? AND start_date=? AND end_date=?",
            (taxon_id, start_date.isoformat(), end_date.isoformat()),
        ).fetchone()
        pages = (prior["pages"] if prior else 0) + 1
        seen = (prior["records_seen"] if prior else 0) + len(rows)
        db.execute(
            "INSERT INTO obis_taxon_ingestion "
            "(taxon_id, start_date, end_date, status, after_cursor, pages, records_seen, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(taxon_id, start_date, end_date) DO UPDATE SET "
            "status=excluded.status, after_cursor=excluded.after_cursor, pages=excluded.pages, "
            "records_seen=excluded.records_seen, updated_at=excluded.updated_at",
            (
                taxon_id, start_date.isoformat(), end_date.isoformat(),
                "complete" if complete else "running", next_after, pages, seen, utc_now(),
            ),
        )
    return accepted, links


def ingest_taxon(db, api: JsonApi, taxon_id, species_ids, site_index, start_date, end_date, progress=print):
    state = db.execute(
        "SELECT * FROM obis_taxon_ingestion WHERE taxon_id=? AND start_date=? AND end_date=?",
        (taxon_id, start_date.isoformat(), end_date.isoformat()),
    ).fetchone()
    if state is not None and state["status"] == "complete":
        progress(f"taxon {taxon_id}: already complete")
        return
    after = state["after_cursor"] if state is not None else None
    while True:
        params = {
            "taxonid": taxon_id,
            "startdate": start_date.isoformat(),
            "enddate": end_date.isoformat(),
            "size": PAGE_SIZE,
        }
        if after:
            params["after"] = after
        payload = api.get(f"{OBIS_ROOT}/occurrence", params=params)
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"OBIS returned an unexpected occurrence page for taxon {taxon_id}")
        complete = len(rows) < PAGE_SIZE
        next_after = None if complete else (str(rows[-1].get("id") or "") if rows else "")
        if not complete and (not next_after or next_after == after):
            raise RuntimeError(f"OBIS pagination stopped advancing for taxon {taxon_id}")
        accepted, links = _save_page(
            db, taxon_id, species_ids, rows, site_index,
            start_date, end_date, next_after, complete,
        )
        progress(
            f"taxon {taxon_id}: page {len(rows)} records, "
            f"{accepted} nearby occurrences, {links} new site links"
        )
        if complete:
            return
        after = next_after


def ingest_all(db, api: JsonApi, *, start_date=START_DATE, end_date=None,
               radius_miles=RADIUS_MILES, selected_names=None, max_taxa=None, progress=print):
    end_date = end_date or datetime.now(timezone.utc).date()
    radius_m = radius_miles * METERS_PER_MILE
    sites = load_sites(db)
    site_index = DiveSiteIndex(sites, radius_m)
    selected = {name.casefold() for name in selected_names or []}
    query = (
        "SELECT mappings.taxon_id, mappings.species_id, species.common_name "
        "FROM pelagia_species_obis_taxa mappings "
        "JOIN species ON species.id = mappings.species_id "
        "ORDER BY mappings.taxon_id, mappings.species_id"
    )
    by_taxon = defaultdict(list)
    for row in db.execute(query):
        if selected and row["common_name"].casefold() not in selected:
            continue
        by_taxon[row["taxon_id"]].append(row["species_id"])
    items = list(by_taxon.items())
    if max_taxa is not None:
        items = items[:max_taxa]
    progress(f"ingesting {len(items)} distinct OBIS taxa against {len(sites)} dive sites")
    for index, (taxon_id, species_ids) in enumerate(items, 1):
        progress(f"[{index}/{len(items)}] taxon {taxon_id} for {len(species_ids)} Pelagia tags")
        ingest_taxon(
            db, api, taxon_id, species_ids, site_index, start_date, end_date, progress
        )


def summary(db):
    return {
        "pelagia_species": db.execute("SELECT COUNT(*) FROM species").fetchone()[0],
        "resolved_species": db.execute(
            "SELECT COUNT(*) FROM pelagia_species_obis_resolution WHERE status='resolved'"
        ).fetchone()[0],
        "unresolved_species": db.execute(
            "SELECT COUNT(*) FROM pelagia_species_obis_resolution WHERE status='unresolved'"
        ).fetchone()[0],
        "skipped_species": db.execute(
            "SELECT COUNT(*) FROM pelagia_species_obis_resolution WHERE status='skipped'"
        ).fetchone()[0],
        "distinct_obis_taxa": db.execute(
            "SELECT COUNT(DISTINCT taxon_id) FROM pelagia_species_obis_taxa"
        ).fetchone()[0],
        "saved_occurrences": db.execute("SELECT COUNT(*) FROM obis_occurrences").fetchone()[0],
        "site_species_occurrence_links": db.execute(
            "SELECT COUNT(*) FROM dive_site_obis_occurrences"
        ).fetchone()[0],
        "mapped_site_species_pairs": db.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT dive_site_id, species_id "
            "FROM dive_site_obis_occurrences)"
        ).fetchone()[0],
    }


def connect_database(path: Path):
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db
