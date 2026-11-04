#!/usr/bin/env python3
"""Download the complete PADI dive-shop directory.

The public directory is backed by a paginated JSON endpoint, while each shop
profile contains the address and the map coordinates PADI associates with that
address. This script follows every listing page, fetches every profile, and
writes a deduplicated CSV suitable for Pelagia's reference-data importer.

Examples:
  python3 scrape_padi_dive_centers.py
  python3 scrape_padi_dive_centers.py --output data/padi_dive_centers.csv
  python3 scrape_padi_dive_centers.py --geocode-missing

``--geocode-missing`` is deliberately opt-in. It sends one sequential request
per unique unresolved address to OpenStreetMap Nominatim, obeying its public
service rate limit, and should only be used for the small residual set that
does not have coordinates in the PADI profile.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


LIST_URL = "https://travel.padi.com/api/v2/travel/dsl/dive-shops/world/all/"
PROFILE_BASE = "https://www.padi.com"
DEFAULT_OUT_CSV = "data/padi_dive_centers.csv"
DEFAULT_WORKERS = 16
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "PelagiaPadiDirectory/1.0"
CSV_FIELDS = [
    "name",
    "physical_address",
    "location",
    "website",
    "latitude",
    "longitude",
    "coordinate_source",
    "source",
    "padi_url",
    "padi_id",
    "affiliate_id",
    "membership_level",
    "osm_type",
    "osm_id",
    "osm_url",
    "osm_name",
    "osm_address",
    "osm_website",
    "osm_phone",
    "osm_email",
    "osm_primary_tags",
    "osm_tags_json",
    "overture_id",
    "overture_release",
    "overture_match_type",
    "overture_basic_category",
    "overture_taxonomy_primary",
    "overture_taxonomy_alternates",
    "overture_address",
    "overture_locality",
    "overture_region",
    "overture_country",
    "overture_website",
    "overture_phone",
    "overture_email",
]
HEADERS = {
    "User-Agent": "Pelagia/1.0 (+https://www.padi.com/dive-shops/all/)",
    "Accept": "application/json,text/html,*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.padi.com/dive-shops/all/",
}

# The macOS Python framework used by this workspace does not automatically
# load the system keychain. Prefer its standard CA bundle when present, while
# retaining the normal platform defaults elsewhere.
CA_BUNDLE = "/etc/ssl/cert.pem"
SSL_CONTEXT = (
    ssl.create_default_context(cafile=CA_BUNDLE)
    if Path(CA_BUNDLE).exists()
    else ssl.create_default_context()
)


def fetch(url: str, *, expect_json: bool = False, tries: int = 4):
    """Fetch a PADI resource with bounded retries for transient failures."""
    request = urllib.request.Request(url, headers=HEADERS)
    last_error: Exception | None = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=45, context=SSL_CONTEXT) as response:
                body = response.read()
            text = body.decode("utf-8", "replace")
            return json.loads(text) if expect_json else text
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.75 * (attempt + 1)
            time.sleep(min(delay, 10.0))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.75 * (attempt + 1))
    assert last_error is not None
    raise last_error


def clean_text(value: str | None) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _coordinate(profile_html: str, field: str) -> str:
    # PADI renders the center map as `latitude: '...'`, but accept JSON-style
    # quoting as well in case the page template changes.
    match = re.search(rf"\b{field}\s*:\s*['\"](-?\d+(?:\.\d+)?)", profile_html, flags=re.I)
    return match.group(1) if match else ""


def extract_profile_fields(profile_html: str) -> dict[str, str]:
    """Extract the address, website, and PADI's map coordinates from HTML."""
    address = ""
    website = ""

    address_match = re.search(
        r"<h5>\s*Address\s*</h5>.*?<p>(.*?)</p>",
        profile_html,
        flags=re.I | re.S,
    )
    if address_match:
        candidate = clean_text(address_match.group(1))
        if candidate.lower() != "none":
            address = candidate

    website_match = re.search(
        r"<h5>\s*WEBSITE\s*</h5>.*?<a\s+[^>]*href=[\"']([^\"']+)",
        profile_html,
        flags=re.I | re.S,
    )
    if website_match:
        website = html.unescape(website_match.group(1)).strip()

    latitude = _coordinate(profile_html, "latitude")
    longitude = _coordinate(profile_html, "longitude")
    try:
        if not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180):
            latitude = longitude = ""
    except ValueError:
        latitude = longitude = ""

    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", profile_html, flags=re.I | re.S)
    id_match = re.search(r'data-event-label=["\'](\d+)["\']', profile_html, flags=re.I)
    return {
        "name": clean_text(title_match.group(1)) if title_match else "",
        "physical_address": address,
        "website": website,
        "latitude": latitude,
        "longitude": longitude,
        "padi_id": id_match.group(1) if id_match else "",
    }


def list_page(page: int) -> dict:
    query = urllib.parse.urlencode({"page": page, "page_size": 20})
    return fetch(f"{LIST_URL}?{query}", expect_json=True)


def profile_row(item: dict) -> dict[str, str]:
    profile_url = urllib.parse.urljoin(PROFILE_BASE, item.get("url", ""))
    fields = {
        "name": clean_text(item.get("title")),
        "physical_address": "",
        "location": clean_text(item.get("shortAddress")),
        "website": "",
        "latitude": "",
        "longitude": "",
        "coordinate_source": "",
        "source": "PADI",
        "padi_url": profile_url,
        "padi_id": str(item.get("id") or ""),
        "affiliate_id": str(item.get("affiliateId") or ""),
        "membership_level": clean_text(item.get("membershipLevel")),
        "osm_type": "",
        "osm_id": "",
        "osm_url": "",
        "osm_name": "",
        "osm_address": "",
        "osm_website": "",
        "osm_phone": "",
        "osm_email": "",
        "osm_primary_tags": "",
        "osm_tags_json": "",
        "_error": "",
    }
    try:
        extracted = extract_profile_fields(fetch(profile_url))
        if extracted.get("name"):
            fields["name"] = extracted["name"]
        if extracted.get("padi_id"):
            fields["padi_id"] = extracted["padi_id"]
        fields.update({key: value for key, value in extracted.items() if key not in {"name", "padi_id"}})
        if fields["latitude"] and fields["longitude"]:
            fields["coordinate_source"] = "PADI profile map"
    except Exception as exc:  # keep a failed profile visible for a later retry
        fields["_error"] = repr(exc)
    return fields


def geocode_address(address: str, *, timeout: float = 45) -> dict[str, str]:
    query = urllib.parse.urlencode(
        {"q": address, "format": "jsonv2", "limit": 1}
    )
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{query}",
        headers={"User-Agent": NOMINATIM_USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        results = json.loads(response.read().decode("utf-8", "replace"))
    if not results:
        return {}
    result = results[0]
    try:
        latitude = float(result["lat"])
        longitude = float(result["lon"])
    except (KeyError, TypeError, ValueError):
        return {}
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return {}
    return {
        "latitude": f"{latitude:.7f}",
        "longitude": f"{longitude:.7f}",
        "coordinate_source": "OpenStreetMap Nominatim",
    }


def apply_geocoding(rows: list[dict[str, str]], *, delay: float) -> int:
    """Fill unresolved rows from an address, or a listed location as fallback."""
    unresolved = {}
    for row in rows:
        query = row["physical_address"] or row["location"]
        if not row["latitude"] and query:
            unresolved.setdefault(query, None)

    resolved = 0
    for index, address in enumerate(unresolved, start=1):
        try:
            result = geocode_address(address)
        except Exception as exc:
            print(f"geocode failed for {address!r}: {exc}", flush=True)
            result = {}
        unresolved[address] = result
        if result:
            resolved += 1
        print(f"geocoded {index}/{len(unresolved)}", flush=True)
        if index < len(unresolved):
            time.sleep(delay)

    for row in rows:
        query = row["physical_address"] or row["location"]
        result = unresolved.get(query, {})
        if not row["latitude"] and result:
            if not row["physical_address"]:
                result = {**result, "coordinate_source": "OpenStreetMap Nominatim (listed location)"}
            row.update(result)
    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUT_CSV, help="output CSV path")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--max-pages", type=int, help="only fetch the first N listing pages")
    parser.add_argument("--max-profiles", type=int, help="only fetch the first N profiles")
    parser.add_argument("--geocode-missing", action="store_true")
    parser.add_argument("--geocode-delay", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    first = list_page(1)
    count = int(first["count"])
    total_pages = (count + 19) // 20
    if args.max_pages:
        total_pages = min(total_pages, args.max_pages)
    items = list(first.get("results", [])) if total_pages else []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(list_page, page): page
            for page in range(2, total_pages + 1)
        }
        for future in as_completed(futures):
            page = futures[future]
            data = future.result()
            items.extend(data.get("results", []))
            print(f"listed page {page}/{total_pages}: {len(items)} records", flush=True)

    unique_items = []
    seen_ids = set()
    for item in items:
        key = item.get("id") or item.get("url") or item.get("title")
        if key in seen_ids:
            continue
        seen_ids.add(key)
        unique_items.append(item)
    unique_items.sort(key=lambda item: (clean_text(item.get("title")).lower(), str(item.get("id"))))
    if args.max_profiles:
        unique_items = unique_items[:args.max_profiles]

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(profile_row, item): item for item in unique_items}
        for index, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if index % 100 == 0 or index == len(unique_items):
                print(f"profiles {index}/{len(unique_items)}", flush=True)

    rows.sort(key=lambda row: (row["name"].lower(), row["location"].lower(), row["padi_id"]))
    if args.geocode_missing:
        apply_geocoding(rows, delay=max(args.geocode_delay, 1.0))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)

    failures = [row for row in rows if row["_error"]]
    missing_address = sum(not row["physical_address"] for row in rows)
    missing_coordinates = sum(not (row["latitude"] and row["longitude"]) for row in rows)
    print(
        json.dumps(
            {
                "listed_count": count,
                "pages_fetched": total_pages,
                "unique_items": len(unique_items),
                "csv_rows": len(rows),
                "profile_failures": len(failures),
                "missing_address": missing_address,
                "missing_coordinates": missing_coordinates,
                "coordinate_sources": {
                    source or "unresolved": sum(row["coordinate_source"] == source for row in rows)
                    for source in sorted({row["coordinate_source"] for row in rows})
                },
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
