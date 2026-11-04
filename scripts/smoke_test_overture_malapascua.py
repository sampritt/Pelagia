#!/usr/bin/env python3
"""Run a deliberately small Overture Places GeoParquet smoke test.

This script reads the public Overture Places GeoParquet release in place via
DuckDB.  It does *not* modify Pelagia's canonical dive-center CSV or database.
The spatial filter is a 10-mile circle around Malapascua by default; DuckDB
pushes the bounding-box and column filters to the remote Parquet data before
the exact-radius calculation.

The result deliberately retains two match classes:

* ``taxonomy_dive_center`` -- Overture's current dive-center taxonomy.
* ``name_dive_center`` -- a nearby place whose name contains dive, diving,
  diver, or scuba but has another taxonomy. This keeps it in the dive-center
  set while preserving the source classification. For example, the
  current Overture record for Evolution Dive and Beach Resort is classified as
  a resort, not a scuba-diving center.

Examples:
  .venv312/bin/python scripts/smoke_test_overture_malapascua.py
  .venv312/bin/python scripts/smoke_test_overture_malapascua.py \\
      --radius-miles 5 --output /private/tmp/overture-malapascua.json
  .venv312/bin/python scripts/smoke_test_overture_malapascua.py \\
      --release 2026-10-21.0
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
DEFAULT_LATITUDE = 11.3290191
DEFAULT_LONGITUDE = 124.1208509
DEFAULT_RADIUS_MILES = 10.0
DEFAULT_OUTPUT = "output/overture-malapascua-smoke/dive_centers.json"
RELEASE_PATTERN = re.compile(r"^20\d{2}-\d{2}-\d{2}\.\d+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, default=DEFAULT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LONGITUDE)
    parser.add_argument("--radius-miles", type=float, default=DEFAULT_RADIUS_MILES)
    parser.add_argument(
        "--release",
        default="latest",
        help="Overture release (YYYY-MM-DD.N), or 'latest' to consult the STAC catalog.",
    )
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    return parser.parse_args()


def resolve_release(value: str) -> str:
    if value != "latest":
        if not RELEASE_PATTERN.fullmatch(value):
            raise ValueError("--release must be YYYY-MM-DD.N or 'latest'")
        return value
    with urllib.request.urlopen(CATALOG_URL, timeout=30) as response:  # noqa: S310 -- fixed HTTPS URL
        latest = json.load(response).get("latest")
    if not isinstance(latest, str) or not RELEASE_PATTERN.fullmatch(latest):
        raise RuntimeError(f"Overture STAC catalog returned an invalid latest release: {latest!r}")
    return latest


def bounding_box(latitude: float, longitude: float, radius_miles: float) -> tuple[float, float, float, float]:
    """Return south, west, north, east for a radius-sized prefilter box."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude or longitude is out of range")
    if not 0 < radius_miles <= 100:
        raise ValueError("--radius-miles must be greater than 0 and at most 100")
    latitude_delta = radius_miles / 69.0
    cosine = math.cos(math.radians(latitude))
    if abs(cosine) < 0.01:
        raise ValueError("search center is too close to a pole")
    longitude_delta = radius_miles / (69.172 * cosine)
    return (
        latitude - latitude_delta,
        longitude - longitude_delta,
        latitude + latitude_delta,
        longitude + longitude_delta,
    )


def query_places(
    release: str,
    *,
    latitude: float,
    longitude: float,
    radius_miles: float,
) -> tuple[list[dict[str, object]], tuple[float, float, float, float]]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB is required. Install project requirements with "
            "`.venv312/bin/pip install -r requirements.txt`."
        ) from exc

    south, west, north, east = bounding_box(latitude, longitude, radius_miles)
    path = (
        "s3://overturemaps-us-west-2/"
        f"release/{release}/theme=places/type=place/*"
    )
    # Places are point geometries. bbox.xmin/ymin therefore allow Parquet to
    # discard remote row groups before DuckDB evaluates names/taxonomy.
    query = f"""
        WITH nearby_bbox AS (
            SELECT
                id,
                names.primary AS name,
                basic_category,
                taxonomy.primary AS taxonomy_primary,
                taxonomy.alternates AS taxonomy_alternates,
                addresses[1].freeform AS address,
                addresses[1].locality AS locality,
                addresses[1].region AS region,
                addresses[1].country AS country,
                websites[1] AS website,
                phones[1] AS phone,
                emails[1] AS email,
                ST_Y(geometry) AS latitude,
                ST_X(geometry) AS longitude
            FROM read_parquet('{path}', hive_partitioning=1)
            WHERE bbox.xmin BETWEEN ? AND ?
              AND bbox.ymin BETWEEN ? AND ?
        ), with_distance AS (
            SELECT *,
                3958.7613 * 2 * ASIN(SQRT(
                    POWER(SIN(RADIANS(latitude - ?) / 2), 2)
                    + COS(RADIANS(?)) * COS(RADIANS(latitude))
                    * POWER(SIN(RADIANS(longitude - ?) / 2), 2)
                )) AS distance_miles
            FROM nearby_bbox
        )
        SELECT *,
            CASE
                WHEN taxonomy_primary IN ('diving_center', 'scuba_diving_center')
                    THEN 'taxonomy_dive_center'
                ELSE 'name_dive_center'
            END AS match_type
        FROM with_distance
        WHERE distance_miles <= ?
          AND (
              taxonomy_primary IN ('diving_center', 'scuba_diving_center')
              OR REGEXP_MATCHES(
                  LOWER(COALESCE(name, '')),
                  '(?:dive|diving|diver|divers|scuba)'
              )
          )
        ORDER BY
            CASE WHEN taxonomy_primary IN ('diving_center', 'scuba_diving_center') THEN 0 ELSE 1 END,
            distance_miles,
            name
    """

    connection = duckdb.connect()
    try:
        # Extensions are cached by DuckDB after first installation.  httpfs
        # reads the public S3 files, and spatial decodes GeoParquet geometry.
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute("SET s3_region='us-west-2'")
        result = connection.execute(
            query,
            [west, east, south, north, latitude, latitude, longitude, radius_miles],
        )
        columns = [column[0] for column in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()], (south, west, north, east)
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    try:
        release = resolve_release(args.release)
        rows, bbox = query_places(
            release,
            latitude=args.latitude,
            longitude=args.longitude,
            radius_miles=args.radius_miles,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Overture smoke test failed: {exc}", file=sys.stderr)
        return 1

    taxonomy_count = sum(row["match_type"] == "taxonomy_dive_center" for row in rows)
    payload = {
        "source": "Overture Maps Places GeoParquet",
        "release": release,
        "queried_at": datetime.now(UTC).isoformat(),
        "search_center": {"latitude": args.latitude, "longitude": args.longitude},
        "radius_miles": args.radius_miles,
        "bbox_prefilter": {"south": bbox[0], "west": bbox[1], "north": bbox[2], "east": bbox[3]},
        "match_policy": {
            "taxonomy_dive_center": "taxonomy.primary is diving_center or scuba_diving_center",
            "name_dive_center": "name contains dive, diving, diver, divers, or scuba but taxonomy is different",
        },
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Overture release: {release}")
    print(f"Within {args.radius_miles:g} miles: {len(rows)} candidates ({taxonomy_count} taxonomy dive centers)")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
