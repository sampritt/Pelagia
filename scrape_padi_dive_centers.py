#!/usr/bin/env python3
import csv
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


LIST_URL = "https://travel.padi.com/api/v2/travel/dsl/dive-shops/world/all/"
PROFILE_BASE = "https://www.padi.com"
OUT_CSV = "padi_dive_centers.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/html,*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.padi.com/dive-shops/all/",
}


def fetch(url, *, expect_json=False, tries=4):
    req = urllib.request.Request(url, headers=HEADERS)
    last_error = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
            text = body.decode("utf-8", "replace")
            return json.loads(text) if expect_json else text
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise last_error


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def extract_profile_fields(profile_html):
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
        r"<h5>\s*WEBSITE\s*</h5>.*?<a\s+[^>]*href=\"([^\"]+)\"",
        profile_html,
        flags=re.I | re.S,
    )
    if website_match:
        website = html.unescape(website_match.group(1)).strip()

    return address, website


def list_page(page):
    query = urllib.parse.urlencode({"page": page, "page_size": 20})
    return fetch(f"{LIST_URL}?{query}", expect_json=True)


def profile_row(item):
    profile_url = urllib.parse.urljoin(PROFILE_BASE, item.get("url", ""))
    address = ""
    website = ""
    error = ""
    try:
        profile = fetch(profile_url)
        address, website = extract_profile_fields(profile)
    except Exception as exc:
        error = repr(exc)

    return {
        "name": clean_text(item.get("title", "")),
        "physical_address": address,
        "location": clean_text(item.get("shortAddress", "")),
        "website": website,
        "_id": item.get("id"),
        "_profile_url": profile_url,
        "_error": error,
    }


def main():
    first = list_page(1)
    count = int(first["count"])
    total_pages = (count + 19) // 20
    items = list(first["results"])

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(list_page, page): page for page in range(2, total_pages + 1)}
        for future in as_completed(futures):
            page = futures[future]
            data = future.result()
            items.extend(data.get("results", []))
            print(f"listed page {page}/{total_pages}: {len(items)}/{count}", flush=True)

    seen = set()
    unique_items = []
    for item in items:
        key = item.get("id") or item.get("url") or item.get("title")
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(item)

    rows = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(profile_row, item): item for item in unique_items}
        for idx, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if idx % 100 == 0 or idx == len(unique_items):
                print(f"profiles {idx}/{len(unique_items)}", flush=True)

    rows.sort(key=lambda row: (row["name"].lower(), row["location"].lower(), str(row["_id"])))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "physical_address", "location", "website"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})

    failures = [row for row in rows if row["_error"]]
    missing_address = sum(1 for row in rows if not row["physical_address"])
    missing_website = sum(1 for row in rows if not row["website"])
    print(
        json.dumps(
            {
                "list_count": count,
                "unique_items": len(unique_items),
                "csv_rows": len(rows),
                "failures": len(failures),
                "missing_address": missing_address,
                "missing_website": missing_website,
                "output": OUT_CSV,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
