#!/usr/bin/env python3
"""Replace OSM enrichment with Overture's global Places GeoParquet registry.

Only PADI-ID rows from the input survive as the base catalogue. OSM-only rows
and every OSM field are discarded, then Overture dive-center rows are matched
to PADI or added as new records. The output is replaced atomically only after
the global cloud query succeeds.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_INPUT = "data/padi_dive_centers.csv"
DEFAULT_OUTPUT = "data/padi_dive_centers.csv"
DEFAULT_AUDIT = "output/overture-global-dive-centers/candidates.json"
CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
RELEASE_PATTERN = re.compile(r"^20\d{2}-\d{2}-\d{2}\.\d+$")
# Match dive terms as terms, rather than arbitrary substrings: this avoids
# classifying names such as "Diversity" as dive businesses.
NAME_PATTERN = r"(?:^|[^[:alpha:]])(?:dive|diving|diver|divers|scuba)(?:$|[^[:alpha:]])"
PYTHON_NAME_PATTERN = re.compile(r"(?<![a-z])(?:dive|diving|diver|divers|scuba)(?![a-z])", flags=re.I)
BASE_FIELDS = [
    "name", "physical_address", "location", "website", "latitude", "longitude",
    "coordinate_source", "source", "padi_url", "padi_id", "affiliate_id", "membership_level",
]
OSM_FIELDS = [
    "osm_type", "osm_id", "osm_url", "osm_name", "osm_address", "osm_website",
    "osm_phone", "osm_email", "osm_primary_tags", "osm_tags_json",
]
OVERTURE_FIELDS = [
    "overture_id", "overture_release", "overture_match_type", "overture_basic_category",
    "overture_taxonomy_primary", "overture_taxonomy_alternates", "overture_address",
    "overture_locality", "overture_region", "overture_country", "overture_website",
    "overture_phone", "overture_email",
]
CSV_FIELDS = [*BASE_FIELDS, *OSM_FIELDS, *OVERTURE_FIELDS]
GENERIC_TOKENS = {"dive", "diving", "diver", "divers", "scuba", "center", "centre", "shop", "resort"}
NAME_DERIVED_EXCLUDED_CATEGORIES = (
    "amusement", "automotive", "bar", "beauty", "b2b_human_resource",
    "bank", "brew", "charging", "furniture", "hair", "health", "home_and_garden",
    "human_resource", "medical", "nightclub", "real_estate", "restaurant", "salon",
    "social_or_community", "winery",
)
NAME_DERIVED_EXCLUDED_PHRASES = (
    re.compile(r"\bdive\s+(?:bar|bar-and-grill)\b", flags=re.I),
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_dive_center_feature(feature: dict[str, object]) -> bool:
    """Apply the agreed taxonomy/name heuristic to an Overture place."""
    taxonomy = clean(feature.get("taxonomy_primary")).casefold()
    if taxonomy in {"diving_center", "scuba_diving_center"}:
        return True
    name = clean(feature.get("name"))
    if not PYTHON_NAME_PATTERN.search(name):
        return False
    if any(pattern.search(name) for pattern in NAME_DERIVED_EXCLUDED_PHRASES):
        return False
    categories = " ".join(
        clean(feature.get(field)).casefold()
        for field in ("basic_category", "taxonomy_primary")
    )
    return not any(category in categories for category in NAME_DERIVED_EXCLUDED_CATEGORIES)


def normalized(value: str) -> str:
    value = "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def tokens(value: str) -> set[str]:
    return {
        part for part in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).casefold())
        if len(part) >= 4 and part not in GENERIC_TOKENS
    }


def website_host(value: str) -> str:
    parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").removeprefix("www.").casefold()


def distance_km(row: dict[str, str], feature: dict[str, object]) -> float | None:
    try:
        lat1, lon1 = float(row["latitude"]), float(row["longitude"])
        lat2, lon2 = float(feature["latitude"]), float(feature["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def resolve_release(requested: str) -> str:
    if requested != "latest":
        if not RELEASE_PATTERN.fullmatch(requested):
            raise ValueError("--release must be YYYY-MM-DD.N or latest")
        return requested
    with urllib.request.urlopen(CATALOG_URL, timeout=30) as response:  # noqa: S310 -- fixed HTTPS URL
        release = json.load(response).get("latest")
    if not isinstance(release, str) or not RELEASE_PATTERN.fullmatch(release):
        raise RuntimeError(f"invalid Overture release: {release!r}")
    return release


def read_overture(
    release: str,
    bbox: tuple[float, float, float, float] | None = None,
    *,
    catalog_view: bool = False,
) -> list[dict[str, object]]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB is required; install requirements.txt") from exc
    path = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
    source = "overture.place" if catalog_view else f"read_parquet('{path}', hive_partitioning=1)"
    spatial_filter = ""
    if bbox is not None:
        south, west, north, east = bbox
        spatial_filter = f"""
          AND bbox.xmin BETWEEN {west:.6f} AND {east:.6f}
          AND bbox.ymin BETWEEN {south:.6f} AND {north:.6f}
        """
    query = f"""
        SELECT id, names.primary AS name, basic_category,
          taxonomy.primary AS taxonomy_primary, taxonomy.alternates AS taxonomy_alternates,
          addresses[1].freeform AS address, addresses[1].locality AS locality,
          addresses[1].region AS region, addresses[1].country AS country,
          websites[1] AS website, phones[1] AS phone, emails[1] AS email,
          ST_Y(geometry) AS latitude, ST_X(geometry) AS longitude,
          CASE WHEN taxonomy.primary IN ('diving_center', 'scuba_diving_center')
            THEN 'taxonomy_dive_center' ELSE 'name_dive_center' END AS match_type
        FROM {source}
        WHERE geometry IS NOT NULL
          AND (
            taxonomy.primary IN ('diving_center', 'scuba_diving_center')
            OR REGEXP_MATCHES(LOWER(COALESCE(names.primary, '')), '{NAME_PATTERN}')
          )
          {spatial_filter}
    """
    connection = duckdb.connect()
    try:
        scope = "globally" if bbox is None else f"for bbox {bbox}"
        print(f"querying Overture Places {scope} from release {release}", flush=True)
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute("SET s3_region='us-west-2'")
        # Path-style requests avoid intermittent DNS failures observed with
        # bucket-prefixed S3 hosts in this environment. Bound each request so
        # a resumable tile job can cache successes and retry only failures.
        connection.execute("SET s3_url_style='path'")
        connection.execute("SET http_keep_alive=false")
        connection.execute("SET http_timeout=15")
        connection.execute("SET http_retries=2")
        if catalog_view:
            # Overture publishes this compact DuckDB file with views over the
            # current release. It avoids an S3 directory-listing request when
            # a particular object-store path is temporarily unavailable.
            connection.execute("ATTACH 'https://stac.overturemaps.org/latest.ddb' AS overture (READ_ONLY)")
        print("extensions loaded; executing filtered GeoParquet scan", flush=True)
        cursor = connection.execute(query)
        headers = [column[0] for column in cursor.description]
        rows: list[dict[str, object]] = []
        while batch := cursor.fetchmany(10_000):
            rows.extend(dict(zip(headers, values, strict=True)) for values in batch)
            print(f"downloaded {len(rows):,} Overture candidates", flush=True)
        return rows
    finally:
        connection.close()


def read_padi_base(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        source = list(csv.DictReader(handle))
    rows = [row for row in source if clean(row.get("padi_id"))]
    if not rows:
        raise RuntimeError(f"no PADI-ID rows in {path}; refusing to replace it")
    for row in rows:
        for field in CSV_FIELDS:
            row.setdefault(field, "")
        for field in [*OSM_FIELDS, *OVERTURE_FIELDS]:
            row[field] = ""
        row["source"] = "PADI"
    return rows


def location(feature: dict[str, object]) -> str:
    return ", ".join(filter(None, (clean(feature.get("locality")), clean(feature.get("region")), clean(feature.get("country")))))


def indexes(rows: list[dict[str, str]]) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    sites, names, terms = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        if host := website_host(row["website"]):
            sites[host].append(row)
        if name := normalized(row["name"]):
            names[name].append(row)
        for term in tokens(row["name"]):
            terms[term].append(row)
    return sites, names, terms


def match(feature: dict[str, object], sites: dict[str, list[dict[str, str]]], names: dict[str, list[dict[str, str]]], terms: dict[str, list[dict[str, str]]]) -> dict[str, str] | None:
    name, host = normalized(clean(feature["name"])), website_host(clean(feature["website"]))
    candidates = [*sites.get(host, []), *names.get(name, [])]
    for term in tokens(clean(feature["name"])):
        candidates.extend(terms.get(term, []))
    seen: set[int] = set()
    best: tuple[float, dict[str, str]] | None = None
    for row in candidates:
        if id(row) in seen:
            continue
        seen.add(id(row))
        distance = distance_km(row, feature)
        row_name = normalized(row["name"])
        same_site = bool(host and host == website_host(row["website"]))
        exact = bool(name and name == row_name)
        contained = bool(name and row_name and (name in row_name or row_name in name))
        if same_site and (distance is None or distance <= 5):
            score = (distance or 0) - 10
        elif exact and distance is not None and distance <= 3:
            score = distance
        elif contained and min(len(name), len(row_name)) >= 6 and distance is not None and distance <= 1:
            score = distance + 0.25
        else:
            continue
        if best is None or score < best[0]:
            best = score, row
    return best[1] if best else None


def add_metadata(row: dict[str, str], feature: dict[str, object], release: str) -> None:
    row["source"] = ";".join(dict.fromkeys([*filter(None, row["source"].split(";")), "Overture"]))
    values = {
        "overture_id": feature["id"], "overture_release": release, "overture_match_type": feature["match_type"],
        "overture_basic_category": feature["basic_category"], "overture_taxonomy_primary": feature["taxonomy_primary"],
        "overture_taxonomy_alternates": json.dumps(feature["taxonomy_alternates"], ensure_ascii=False) if feature.get("taxonomy_alternates") else "",
        "overture_address": feature["address"], "overture_locality": feature["locality"], "overture_region": feature["region"],
        "overture_country": feature["country"], "overture_website": feature["website"], "overture_phone": feature["phone"], "overture_email": feature["email"],
    }
    row.update({field: clean(value) for field, value in values.items()})
    if not row["physical_address"]:
        row["physical_address"] = clean(feature["address"])
    if not row["location"]:
        row["location"] = location(feature)
    if not row["website"]:
        row["website"] = clean(feature["website"])
    if not row["latitude"] or not row["longitude"]:
        row["latitude"], row["longitude"] = f"{float(feature['latitude']):.7f}", f"{float(feature['longitude']):.7f}"
        row["coordinate_source"] = "Overture Maps Places"


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--audit-output", default=DEFAULT_AUDIT)
    parser.add_argument("--release", default="latest")
    args = parser.parse_args()
    try:
        release = resolve_release(args.release)
        raw = read_overture(release)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Overture extraction failed; canonical CSV was not changed: {exc}", file=sys.stderr)
        return 1
    features = list({clean(row["id"]): row for row in raw if clean(row.get("id")) and clean(row.get("name")) and is_dive_center_feature(row)}.values())
    audit = Path(args.audit_output)
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({"release": release, "extracted_at": datetime.now(UTC).isoformat(), "features": features}, ensure_ascii=False), encoding="utf-8")
    rows = read_padi_base(Path(args.input))
    sites, names, terms = indexes(rows)
    matched = added = 0
    for feature in features:
        if row := match(feature, sites, names, terms):
            add_metadata(row, feature, release)
            matched += 1
        else:
            row = {field: "" for field in CSV_FIELDS}
            row.update({"name": clean(feature["name"]), "physical_address": clean(feature["address"]), "location": location(feature), "website": clean(feature["website"]), "latitude": f"{float(feature['latitude']):.7f}", "longitude": f"{float(feature['longitude']):.7f}", "coordinate_source": "Overture Maps Places", "source": "Overture"})
            add_metadata(row, feature, release)
            rows.append(row)
            added += 1
    rows.sort(key=lambda row: (row["name"].casefold(), row["location"].casefold(), row["padi_id"], row["overture_id"]))
    write_csv(Path(args.output), rows)
    print(json.dumps({"release": release, "raw_overture": len(raw), "unique_overture": len(features), "match_types": Counter(clean(row["match_type"]) for row in features), "padi_base": sum(bool(row["padi_id"]) for row in rows), "matched_padi": matched, "added_overture": added, "final_rows": len(rows), "output": args.output, "audit": str(audit)}, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
