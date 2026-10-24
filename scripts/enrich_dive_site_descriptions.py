#!/usr/bin/env python3
"""Collect conservative, fact-only description candidates from cited site pages.

The script deliberately emits JSONL candidates instead of changing the catalogue.
A candidate is produced only after the cited page/API confirms the site name and
coordinates (and, for OpenDiveMap, country code).  It uses structured fields,
not prose descriptions, so the final sentence is original rather than copied.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CSV_PATH = Path("data/global_dive_sites_master.csv")
PADI_URL = re.compile(r"https://www\.padi\.com/dive-site/[^|\s]+")
ODM_URL = re.compile(r"https://api\.opendivemap\.com/v1/sites/[^|\s]+")
TAG = re.compile(r"<[^>]+>")


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch(url: str) -> str:
    # urllib is denied egress in the desktop sandbox even for an approved task;
    # curl is the approved network client and preserves the same low-concurrency
    # behaviour controlled by the caller's worker count.
    try:
        response = subprocess.run(
            ["curl", "--fail", "--location", "--silent", "--show-error", "--max-time", "30", url],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=35,
        )
        return response.stdout.decode("utf-8", "replace")
    except (subprocess.SubprocessError, OSError):
        pass
    request = Request(url, headers={"User-Agent": "Pelagia dive-site catalogue research/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise AssertionError("unreachable")


def clean(value: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", value)).split())


def padi_candidate(row: dict[str, str], url: str) -> dict | None:
    page = fetch(url)
    lat = re.search(r"latitude:\s*'(-?[0-9.]+)'", page)
    lon = re.search(r"longitude:\s*'(-?[0-9.]+)'", page)
    title = re.search(r"<title>\s*(.*?)\s+dive site\s*\|\s*PADI\s*</title>", page, re.I | re.S)
    if not (lat and lon and title):
        return None
    shown_name = clean(title.group(1))
    site_name = row["dive_site_name"]
    # PADI occasionally expands a known abbreviation, so require substantial overlap.
    a, b = norm(site_name), norm(shown_name)
    if not (a == b or a in b or b in a):
        return None
    km = distance_km(float(row["latitude"]), float(row["longitude"]), float(lat.group(1)), float(lon.group(1)))
    if km > 10:
        return None
    def metric(label: str) -> str | None:
        pattern = rf"<div[^>]*>{label}</div>\s*<span[^>]*>(.*?)</span>"
        match = re.search(pattern, page, re.I | re.S)
        return clean(match.group(1)) if match else None
    dive_type, entry, sightings = metric("Dive Types"), metric("Entry"), metric("Common Sightings")
    if not (entry or dive_type):
        return None
    dive_type = dive_type.rstrip(" ,") if dive_type else None
    access = {"boat": "boat-access", "shore": "shore-access", "shore/beach": "shore-access"}.get(
        entry.lower(), f"{entry.lower()}-access"
    ) if entry else None
    if access and dive_type:
        kind = f"a {access} {dive_type.lower()} dive"
    elif access:
        kind = f"a {access} dive"
    else:
        kind = f"a {dive_type.lower()} dive"
    sentence = f"{site_name} is {kind} in {row['country_or_area']}"
    if row["max_depth_m"] and row["max_depth_m"] != "NA":
        sentence += f", listed to {row['max_depth_m']} m"
    if sightings and len(sightings) < 80:
        sentence += f", with PADI listing sightings such as {sightings.lower()}"
    sentence += "."
    return {"master_site_id": row["master_site_id"], "description": sentence, "source": url, "match_km": round(km, 2), "provider": "PADI"}


def odm_candidate(row: dict[str, str], url: str) -> dict | None:
    data = json.loads(fetch(url))
    props = data.get("properties", {})
    coords = data.get("geometry", {}).get("coordinates", [])
    if len(coords) < 2 or norm(props.get("name", "")) != norm(row["dive_site_name"]):
        return None
    if props.get("country_code") and props["country_code"] != row["country_code"]:
        return None
    km = distance_km(float(row["latitude"]), float(row["longitude"]), float(coords[1]), float(coords[0]))
    if km > 1:
        return None
    bits = []
    entry = props.get("entry")
    if entry:
        bits.append(f"a {entry}-access dive")
    max_depth = props.get("max_depth") or row["max_depth_m"]
    if max_depth not in (None, "", "NA"):
        bits.append(f"listed to {max_depth} m")
    visibility = props.get("tags", {}).get("average_vis_m")
    if visibility not in (None, ""):
        bits.append(f"community logs average {visibility} m visibility")
    if not bits:
        return None
    sentence = f"{row['dive_site_name']} is " + ", ".join(bits) + f" in {row['country_or_area']}."
    return {"master_site_id": row["master_site_id"], "description": sentence, "source": url, "match_km": round(km, 2), "provider": "OpenDiveMap"}


def process(row: dict[str, str]) -> dict | None:
    urls = row["source_urls"]
    # Prefer the API because it offers an exact name/country/coordinate response.
    for pattern, parser in ((ODM_URL, odm_candidate), (PADI_URL, padi_candidate)):
        match = pattern.search(urls)
        if match:
            try:
                candidate = parser(row, match.group(0))
                if candidate:
                    return candidate
            except Exception as exc:  # a failed source is not evidence for a description
                return {"master_site_id": row["master_site_id"], "error": type(exc).__name__}
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="first master-site id, inclusive")
    parser.add_argument("--end", required=True, help="last master-site id, inclusive")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    start, end = int(args.start.removeprefix("DS")), int(args.end.removeprefix("DS"))
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        rows = [
            r for r in csv.DictReader(handle)
            if start <= int(r["master_site_id"].removeprefix("DS")) <= end
        ]
    with ThreadPoolExecutor(max_workers=args.workers) as pool, args.output.open("w", encoding="utf-8") as out:
        futures = {pool.submit(process, row): row["master_site_id"] for row in rows}
        for future in as_completed(futures):
            result = future.result()
            if result:
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
