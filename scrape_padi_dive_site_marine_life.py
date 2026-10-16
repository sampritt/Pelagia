#!/usr/bin/env python3
import csv
import html
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


LIST_URL = "https://travel.padi.com/api/v2/travel/dive-guide/continent/all/dive-sites/"
DETAIL_URL = "https://travel.padi.com/api/v2/travel/dsl/dive-sites/{id}/map/"
MASTER_CSV = Path("data/global_dive_sites_master.csv")
OUT_CSV = Path("padi_dive_site_marine_life_matches.csv")
AUDIT_JSON = Path("padi_dive_site_marine_life_matches_audit.json")
PAGE_SIZE = 20
MAX_WORKERS = 16
MATCH_RADIUS_M = 250.0
NEAR_DUPLICATE_RADIUS_M = 1000.0
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/html,*/*",
    "Referer": "https://www.padi.com/dive-sites/all/",
}


def fetch_json(url, params=None, tries=4):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    last_error = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
            return json.loads(body)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
    raise last_error


def normalize(value):
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[’'`]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def distance_m(lat1, lon1, lat2, lon2):
    radius = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_master():
    by_name = {}
    by_padi_id = {}
    with MASTER_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                row["_lat"] = float(row["latitude"])
                row["_lon"] = float(row["longitude"])
            except (TypeError, ValueError):
                continue
            row["_norm_name"] = normalize(row["dive_site_name"])
            by_name.setdefault(row["_norm_name"], []).append(row)
            for padi_id in re.findall(r"PADI Global Dive Sites:(\d+)", row.get("source_record_ids", "")):
                by_padi_id.setdefault(padi_id, []).append(row)
    return by_name, by_padi_id


def list_page(page):
    data = fetch_json(LIST_URL, {"page": page, "page_size": PAGE_SIZE})
    return page, data


def scrape_list():
    first = fetch_json(LIST_URL, {"page": 1, "page_size": PAGE_SIZE})
    count = int(first["count"])
    total_pages = math.ceil(count / PAGE_SIZE)
    items = list(first.get("results", []))
    print(f"listed page 1/{total_pages}: {len(items)}/{count}", flush=True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(list_page, page): page for page in range(2, total_pages + 1)}
        for future in as_completed(futures):
            page, data = future.result()
            items.extend(data.get("results", []))
            if page % 10 == 0 or len(items) >= count:
                print(f"listed page {page}/{total_pages}: {len(items)}/{count}", flush=True)

    seen = set()
    unique = []
    for item in items:
        key = item.get("id") or item.get("travelUrl") or item.get("title")
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return count, unique


def marine_life_names(item):
    names = []
    for species in item.get("marineLife") or []:
        if isinstance(species, str):
            name = species
        elif isinstance(species, dict):
            name = species.get("title") or species.get("name")
        else:
            name = ""
        name = re.sub(r"\s+", " ", str(name)).strip()
        if name:
            names.append(name)
    return names


def detail_for_item(item):
    detail = fetch_json(DETAIL_URL.format(id=item["id"]))
    return item["id"], detail


def add_details(items, master_by_padi_id):
    need_details = [
        item
        for item in items
        if marine_life_names(item) and len(master_by_padi_id.get(str(item.get("id")), [])) != 1
    ]
    details = {}
    failures = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(detail_for_item, item): item for item in need_details}
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                item_id, detail = future.result()
                details[item_id] = detail
            except Exception as exc:
                failures[item.get("id")] = repr(exc)
            if index % 100 == 0 or index == len(need_details):
                print(f"details {index}/{len(need_details)}", flush=True)
    return details, failures


def match_master(item, detail, master_by_name):
    norm_name = normalize(item.get("title"))
    try:
        padi_lat = float(detail["latitude"])
        padi_lon = float(detail["longitude"])
    except (KeyError, TypeError, ValueError):
        return None, "missing_coordinates"

    candidates = []
    near_duplicates = []
    for row in master_by_name.get(norm_name, []):
        distance = distance_m(padi_lat, padi_lon, row["_lat"], row["_lon"])
        if distance <= MATCH_RADIUS_M:
            candidates.append((distance, row))
        if distance <= NEAR_DUPLICATE_RADIUS_M:
            near_duplicates.append((distance, row))

    if len(candidates) != 1:
        return None, f"candidate_count_{len(candidates)}"
    if len(near_duplicates) != 1:
        return None, f"near_duplicate_count_{len(near_duplicates)}"
    return candidates[0][1], "matched"


def main():
    master_by_name, master_by_padi_id = load_master()
    api_count, items = scrape_list()
    details, detail_failures = add_details(items, master_by_padi_id)
    output_rows = []
    stats = {
        "api_count": api_count,
        "unique_list_items": len(items),
        "with_marine_life": 0,
        "matched_sites": 0,
        "output_rows": 0,
        "detail_failures": len(detail_failures),
        "skips": {},
    }
    matched_site_ids = set()

    for item in items:
        species_names = marine_life_names(item)
        if not species_names:
            continue
        stats["with_marine_life"] += 1
        padi_id_matches = master_by_padi_id.get(str(item.get("id")), [])
        if len(padi_id_matches) == 1:
            match = padi_id_matches[0]
            reason = "matched_by_padi_id"
        else:
            detail = details.get(item.get("id"))
            if not detail:
                reason = "detail_fetch_failed"
                stats["skips"][reason] = stats["skips"].get(reason, 0) + 1
                continue
            match, reason = match_master(item, detail, master_by_name)
        if not match:
            stats["skips"][reason] = stats["skips"].get(reason, 0) + 1
            continue
        matched_site_ids.add(match["master_site_id"])
        for species in sorted(set(species_names), key=str.lower):
            output_rows.append(
                {
                    "dive_site_name": match["dive_site_name"],
                    "species_name": species,
                }
            )

    output_rows.sort(key=lambda row: (row["dive_site_name"].lower(), row["species_name"].lower()))
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["dive_site_name", "species_name"])
        writer.writeheader()
        writer.writerows(output_rows)

    stats["matched_sites"] = len(matched_site_ids)
    stats["output_rows"] = len(output_rows)
    stats["output_csv"] = str(OUT_CSV)
    stats["audit_json"] = str(AUDIT_JSON)
    stats["detail_failure_ids"] = detail_failures
    AUDIT_JSON.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
