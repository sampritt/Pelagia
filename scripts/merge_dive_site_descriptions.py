#!/usr/bin/env python3
"""Merge conservatively verified research candidates into the dive-site catalogue."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path


CATALOGUE = Path("data/global_dive_sites_master.csv")
CANDIDATE_FILES = (
    Path("output/enrichment/1-auto.jsonl"),
    Path("output/enrichment/2-auto.jsonl"),
    Path("output/enrichment/3-final.jsonl"),
    Path("output/enrichment/4-auto.jsonl"),
)
MANUAL_FILES = (
    Path("output/enrichment/1-manual.jsonl"),
    Path("output/enrichment/2-manual.jsonl"),
)
KNOWN_BAD_IDS = {"DS006207"}  # API country metadata conflicts with these coordinates.


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def padi_country_agrees(row: dict[str, str], source: str) -> bool:
    """Accept only an exact/prefix country label agreement with PADI's URL."""
    parts = source.split("/")
    if len(parts) < 6:
        return False
    country, slug = normalized(row["country_or_area"]), normalized(parts[4])
    return bool(country and slug and (country == slug or country.startswith(slug) or slug.startswith(country)))


def polish(description: str) -> str:
    """Repair only mechanical punctuation from structured PADI metric fields."""
    description = " ".join(description.split())
    description = re.sub(r" is a boat,?\s+", " is a boat-access ", description, count=1, flags=re.I)
    description = re.sub(r" is a shore,?\s+", " is a shore-access ", description, count=1, flags=re.I)
    description = re.sub(r",\s+in\b", " in", description, flags=re.I)
    description = re.sub(
        r" is a ((?:boat|shore)-access) dive, ([^,]+?)(?=, listed| in )",
        r" is a \1 \2 dive",
        description,
        flags=re.I,
    )
    description = re.sub(r",\s+dive\b", " dive", description, flags=re.I)
    return description


def candidate_is_valid(candidate: dict, row: dict[str, str]) -> bool:
    description, provider, source = candidate.get("description", ""), candidate.get("provider", ""), candidate.get("source", "")
    if not description or len(normalized(row["dive_site_name"])) < 3 or candidate.get("master_site_id") in KNOWN_BAD_IDS:
        return False
    if provider == "PADI":
        return source.startswith("https://www.padi.com/dive-site/") and candidate.get("match_km", 999) <= 10 and padi_country_agrees(row, source)
    if provider == "OpenDiveMap":
        return source.startswith("https://api.opendivemap.com/v1/sites/") and candidate.get("match_km", 999) <= 1 and bool(row["country_code"])
    return False


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    with CATALOGUE.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    by_id = {row["master_site_id"]: row for row in rows}
    descriptions: dict[str, str] = {}
    stats: Counter[str] = Counter()

    for path in CANDIDATE_FILES:
        for candidate in load_jsonl(path):
            site_id = candidate.get("master_site_id")
            row = by_id.get(site_id)
            if row and candidate_is_valid(candidate, row):
                descriptions[site_id] = polish(candidate["description"])
                stats[f"accepted_{candidate['provider']}"] += 1
            else:
                stats["rejected_auto_candidate"] += 1

    # Manually researched summaries have already had a site-specific location check;
    # give them precedence over the mechanically generated structured-data sentence.
    for path in MANUAL_FILES:
        for candidate in load_jsonl(path):
            site_id = candidate.get("master_site_id")
            if site_id in by_id and site_id not in KNOWN_BAD_IDS and candidate.get("description") and candidate.get("match_km", 999) <= 5:
                descriptions[site_id] = polish(candidate["description"])
                stats["accepted_manual"] += 1
            else:
                stats["rejected_manual_candidate"] += 1

    if "description" not in fieldnames:
        fieldnames.append("description")
    for row in rows:
        row["description"] = descriptions.get(row["master_site_id"], "")

    with CATALOGUE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    stats["catalogue_rows"] = len(rows)
    stats["descriptions_written"] = len(descriptions)
    stats["descriptions_blank"] = len(rows) - len(descriptions)
    Path("output/enrichment/merge-summary.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
