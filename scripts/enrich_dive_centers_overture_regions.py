#!/usr/bin/env python3
"""Build a resumable Overture registry across Pelagia's country/region coverage.

Rather than scan the entire worldwide Places collection in one query, this
uses the Pelagia dive-site catalogue to form shared geographic tiles. Nested
regions naturally collapse into the same tile (for example, Bali/Indonesia and
Galápagos/Ecuador). Each successful tile is cached. The canonical CSV is only
replaced after every tile has succeeded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.enrich_dive_centers_overture import (
    add_metadata,
    indexes,
    is_dive_center_feature,
    match,
    read_overture,
    read_padi_base,
    resolve_release,
    write_csv,
)


DEFAULT_SITES = "data/global_dive_sites_master.csv"
DEFAULT_INPUT = "data/padi_dive_centers.csv"
DEFAULT_OUTPUT = "data/padi_dive_centers.csv"
DEFAULT_CACHE = ".cache/overture-dive-center-regions"
DEFAULT_AUDIT = "output/overture-global-dive-centers/candidates.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-catalog", default=DEFAULT_SITES)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE)
    parser.add_argument("--audit-output", default=DEFAULT_AUDIT)
    parser.add_argument("--release", default="latest")
    parser.add_argument("--tile-degrees", type=float, default=10.0)
    parser.add_argument("--overlap-degrees", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-tiles", type=int, help="smoke-test only; do not use for a final merge")
    parser.add_argument("--retry-failures", action="store_true", help="retry only bboxes in cache-dir/failures.json")
    return parser.parse_args()


def coverage_tiles(path: Path, step: float, overlap: float) -> tuple[list[tuple[float, float, float, float]], dict[str, set[str]]]:
    if not 0 < step <= 30 or not 0 <= overlap < step / 2:
        raise ValueError("tile degrees must be 0–30 and overlap must be less than half a tile")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    cells: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in rows:
        try:
            latitude, longitude = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        key = (math.floor(latitude / step), math.floor(longitude / step))
        label = row.get("country_or_area", "").strip()
        if label:
            cells[key].add(label)
    tiles = []
    labels: dict[str, set[str]] = {}
    for (lat_index, lon_index), tile_labels in sorted(cells.items()):
        south, west = lat_index * step, lon_index * step
        bbox = (
            max(-90.0, south - overlap),
            max(-180.0, west - overlap),
            min(90.0, south + step + overlap),
            min(180.0, west + step + overlap),
        )
        key = ",".join(f"{value:.4f}" for value in bbox)
        tiles.append(bbox)
        labels[key] = tile_labels
    return tiles, labels


def cache_path(cache_dir: Path, release: str, bbox: tuple[float, float, float, float]) -> Path:
    identity = f"{release}:" + ",".join(f"{value:.6f}" for value in bbox)
    return cache_dir / f"tile_{hashlib.sha256(identity.encode()).hexdigest()[:16]}.json"


def fetch_tile(
    release: str,
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    split: bool = False,
    catalog_view: bool = False,
) -> tuple[list[dict], str]:
    path = cache_path(cache_dir, release, bbox)
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)["features"], "cache"
    if split:
        south, west, north, east = bbox
        middle_latitude, middle_longitude = (south + north) / 2, (west + east) / 2
        features = []
        for part in (
            (south, west, middle_latitude, middle_longitude),
            (south, middle_longitude, middle_latitude, east),
            (middle_latitude, west, north, middle_longitude),
            (middle_latitude, middle_longitude, north, east),
        ):
            features.extend(read_overture(release, part, catalog_view=catalog_view))
    else:
        features = read_overture(release, bbox, catalog_view=catalog_view)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"release": release, "bbox": bbox, "features": features}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return features, "Overture"


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    try:
        release = resolve_release(args.release)
        all_tiles, tile_labels = coverage_tiles(Path(args.site_catalog), args.tile_degrees, args.overlap_degrees)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Could not build regional coverage: {exc}", file=sys.stderr)
        return 1
    if args.max_tiles:
        tiles = tiles[:args.max_tiles]
    cache_dir = Path(args.cache_dir)
    tiles = all_tiles
    failures_path = cache_dir / "failures.json"
    if args.retry_failures:
        try:
            recorded = json.loads(failures_path.read_text(encoding="utf-8"))
            wanted = {tuple(item["bbox"]) for item in recorded}
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Could not load recorded failures: {exc}", file=sys.stderr)
            return 1
        tiles = [bbox for bbox in all_tiles if bbox in wanted]
        if not tiles:
            print("No recorded failures match the current coverage manifest", file=sys.stderr)
            return 1
    manifest = {
        "release": release,
        "tile_degrees": args.tile_degrees,
        "overlap_degrees": args.overlap_degrees,
        "tiles": [{"bbox": bbox, "labels": sorted(tile_labels[','.join(f'{value:.4f}' for value in bbox)])} for bbox in tiles],
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "coverage_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"regional coverage: {len(tiles)} {'failed ' if args.retry_failures else ''}tile(s); {args.workers} worker(s)", flush=True)

    features: list[dict] = []
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_tile, release, bbox, cache_dir, args.retry_failures, args.retry_failures): bbox
            for bbox in tiles
        }
        for index, future in enumerate(as_completed(futures), start=1):
            bbox = futures[future]
            try:
                result, origin = future.result()
                features.extend(result)
                print(f"tile {index}/{len(tiles)} {bbox}: {len(result)} features ({origin})", flush=True)
            except Exception as exc:
                failures.append({"bbox": bbox, "error": repr(exc)})
                print(f"tile failed {bbox}: {exc}", flush=True)
    if failures:
        failures_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
        print(f"{len(failures)} tiles failed; canonical CSV was not changed", file=sys.stderr)
        return 1
    if args.max_tiles:
        print("--max-tiles was used; refusing to merge incomplete coverage", file=sys.stderr)
        return 1

    if args.retry_failures:
        missing = [bbox for bbox in all_tiles if not cache_path(cache_dir, release, bbox).exists()]
        if missing:
            print(f"{len(missing)} cache entries are still missing; canonical CSV was not changed", file=sys.stderr)
            return 1
        features = []
        for bbox in all_tiles:
            with cache_path(cache_dir, release, bbox).open(encoding="utf-8") as handle:
                features.extend(json.load(handle)["features"])
    failures_path.unlink(missing_ok=True)

    unique = {
        str(feature["id"]): feature
        for feature in features
        if feature.get("id") and feature.get("name") and is_dive_center_feature(feature)
    }
    audit_path = Path(args.audit_output)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({"release": release, "extracted_at": datetime.now(UTC).isoformat(), "features": list(unique.values())}, ensure_ascii=False), encoding="utf-8")
    rows = read_padi_base(Path(args.input))
    sites, names, terms = indexes(rows)
    matched = added = 0
    for feature in unique.values():
        row = match(feature, sites, names, terms)
        if row is None:
            from scripts.enrich_dive_centers_overture import CSV_FIELDS, clean, location
            row = {field: "" for field in CSV_FIELDS}
            row.update({"name": clean(feature["name"]), "physical_address": clean(feature["address"]), "location": location(feature), "website": clean(feature["website"]), "latitude": f"{float(feature['latitude']):.7f}", "longitude": f"{float(feature['longitude']):.7f}", "coordinate_source": "Overture Maps Places", "source": "Overture"})
            rows.append(row)
            added += 1
        else:
            matched += 1
        add_metadata(row, feature, release)
    rows.sort(key=lambda row: (row["name"].casefold(), row["location"].casefold(), row["padi_id"], row["overture_id"]))
    write_csv(Path(args.output), rows)
    print(json.dumps({"release": release, "tiles": len(all_tiles), "raw_features": len(features), "unique_features": len(unique), "match_types": Counter(str(feature["match_type"]) for feature in unique.values()), "matched_padi": matched, "added_overture": added, "final_rows": len(rows), "output": args.output, "audit": str(audit_path)}, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
