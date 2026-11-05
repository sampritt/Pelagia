"""Clean the deployed center catalogue and record every removal/merge.

Run from the repository root with --write to replace the CSV. Without it,
only the audit is written. Shared chain sites and shared streets alone do
not establish that two businesses are the same center.
"""

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit


def text_key(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in value if c.isalnum())


def website_key(value):
    value = value.strip()
    if re.match(r"^(mailto|tel|sms|whatsapp|skype|tg|line|viber):", value, re.I) or "@" in value and "://" not in value:
        return value.casefold()
    parts = urlsplit(value if "://" in value else "//" + value)
    host = (parts.hostname or "").casefold().removeprefix("www.")
    # Query IDs distinguish social profiles and individual store pages.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    path = parts.path.rstrip("/")
    if path.lower() in {"/index.html", "/index.htm", "/index.php", "/home"}:
        path = ""
    return host + path + ("?" + urlencode(sorted(query)) if query else "") if host else value


def reference_key(row):
    for provider, field in (("padi", "padi_id"), ("overture", "overture_id"), ("padi-url", "padi_url")):
        if row.get(field, "").strip():
            return provider + ":" + row[field].strip()
    return legacy_reference_key(row)


def legacy_reference_key(row):
    legacy = tuple(row.get(f, "").strip().casefold() for f in ("name", "physical_address", "location"))
    return "legacy:" + hashlib.sha256(json.dumps(legacy).encode()).hexdigest()


def distance(a, b):
    try:
        lat1, lon1, lat2, lon2 = (float(r[f]) for r in (a, b) for f in ("latitude", "longitude"))
    except (ValueError, KeyError, TypeError):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def duplicate_reason(a, b, multi_location=False):
    same_website = website_key(a["website"]) == website_key(b["website"])
    same_address = text_key(a["physical_address"]) == text_key(b["physical_address"])
    same_location = text_key(a["location"]) == text_key(b["location"])
    km = distance(a, b)
    similarity = SequenceMatcher(None, text_key(a["name"]), text_key(b["name"])).ratio()
    similar_name = similarity >= 0.92
    if same_address and same_location and (same_website or similar_name):
        if a.get("padi_id") and b.get("padi_id") and a["padi_id"] != b["padi_id"] and not same_website:
            return None
        return "same_address_and_website_or_similar_name"
    if same_website and km is not None and km <= 0.5:
        # Independently listed PADI branches need an address match too.
        if a.get("padi_id") and b.get("padi_id") and a["padi_id"] != b["padi_id"] and not same_address:
            return None
        if multi_location and not same_address:
            # Nearby shops of the same chain can be separate branches.
            if km > 0.05 or similarity < 0.92:
                return None
        return "same_website_within_500m"
    if same_website and km is None and same_location and similar_name:
        return "same_website_location_and_similar_name"
    return None


def _clean_pass(rows):
    removed = []
    eligible = []
    for row in rows:
        missing = [f for f in ("physical_address", "website") if not row.get(f, "").strip()]
        if missing:
            removed.append({"row": row, "missing": missing})
        else:
            eligible.append(dict(row))
    # Prefer PADI identities, then richer records. This order is stable across runs.
    eligible.sort(key=lambda r: (not bool(r.get("padi_id")), text_key(r["name"]) in {"oldpage", "divingcenter"},
                                 -sum(bool(v) for k, v in r.items() if k != "merged_reference_keys"),
                                 reference_key(r)))
    website_rows = defaultdict(list)
    for row in eligible:
        website_rows[website_key(row["website"])].append(row)
    multi_location = {key for key, members in website_rows.items()
                      if any((km := distance(members[0], row)) is not None and km > 5
                             for row in members[1:])}
    by_website, by_address = defaultdict(list), defaultdict(list)
    kept, merges, groups, parents = [], [], [], []

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def absorb(i, donor, reason):
        target = kept[i]
        # Keep the original canonical identity even if another provider's
        # metadata is filled in. Registry aliases reconnect old app links.
        canonical = reference_key(target)
        aliases = set(json.loads(target.get("merged_reference_keys") or "[]"))
        aliases.add(reference_key(donor))
        aliases.add(legacy_reference_key(donor))
        aliases.update(json.loads(donor.get("merged_reference_keys") or "[]"))
        for field, value in donor.items():
            if field not in {"merged_reference_keys", "padi_id", "padi_url", "overture_id"} and not target.get(field):
                target[field] = value
        aliases.discard(canonical)
        target["merged_reference_keys"] = json.dumps(sorted(aliases), separators=(",", ":")) if aliases else ""
        merges.append({"canonical_reference_key": canonical, "canonical_name": target["name"],
                       "reason": reason, "distance_km": distance(target, donor), "row": donor})

    for row in eligible:
        web, address = website_key(row["website"]), text_key(row["physical_address"])
        candidates = sorted({root(i) for i in by_website[web] + by_address[address]})
        matches = []
        for i in candidates:
            reason = next((reason for member in groups[i]
                           if (reason := duplicate_reason(member, row, web in multi_location))), None)
            if reason:
                matches.append((i, reason))
        if matches:
            i, reason = matches[0]
            absorb(i, row, reason)
            groups[i].append(dict(row))
            for j, reason in matches[1:]:
                absorb(i, kept[j], "transitive_" + reason)
                groups[i].extend(groups[j])
                parents[j] = i
            if i not in by_website[web]:
                by_website[web].append(i)
            if i not in by_address[address]:
                by_address[address].append(i)
        else:
            i = len(kept)
            kept.append(row)
            groups.append([dict(row)])
            parents.append(i)
            by_website[web].append(i)
            by_address[address].append(i)
    kept = [row for i, row in enumerate(kept) if root(i) == i]
    kept.sort(key=lambda r: (r["name"].casefold(), r["location"], reference_key(r)))
    return kept, {"input_rows": len(rows), "removed_missing_contact": len(removed),
                  "merged_duplicate_rows": len(merges), "output_rows": len(kept),
                  "removed": removed, "merges": merges}


def clean(rows):
    kept, audit = _clean_pass(rows)
    while True:
        next_rows, next_audit = _clean_pass(kept)
        if not next_audit["merges"]:
            break
        audit["merges"].extend(next_audit["merges"])
        kept = next_rows
    final_keys = {alias: reference_key(row) for row in kept
                  for alias in [reference_key(row), *json.loads(row.get("merged_reference_keys") or "[]")]}
    final_names = {reference_key(row): row["name"] for row in kept}
    for merge in audit["merges"]:
        merge["canonical_reference_key"] = final_keys[merge["canonical_reference_key"]]
        merge["canonical_name"] = final_names[merge["canonical_reference_key"]]
    audit["merged_duplicate_rows"] = len(audit["merges"])
    audit["output_rows"] = len(kept)
    return kept, audit


def apply_website_evidence(rows, audit, evidence):
    """Remove dead groups, retaining a working alternative from a duplicate."""
    try:
        from .check_center_websites import is_contact, is_social, normalize
    except ImportError:
        from check_center_websites import is_contact, is_social, normalize

    confirmed_hosting = {attempt["url"]: check for check in evidence.values()
                         if check["classification"] == "dead_confirmed"
                         for attempt in check.get("attempts", []) if attempt["outcome"] == "dead_hosting"}
    working_evidence = {check["working_url"]: check for check in evidence.values()
                        if check.get("working_url") and check["classification"] in {"live", "social_preserved"}}
    working_evidence.update({attempt["final_url"]: check for check in evidence.values()
                            if check["classification"] == "live"
                            for attempt in check.get("attempts", []) if attempt.get("final_url") and attempt["outcome"] == "live"})

    def result(row):
        url = row["website"].strip()
        if is_contact(url) or is_social(url):
            return {"classification": "contact_preserved"}
        check = evidence.get(url) or working_evidence.get(url)
        if check is None or check["classification"] == "needs_retry":
            check = working_evidence.get(url)
        if check is None:
            raise ValueError(f"Website check/retry is incomplete: {url}")
        if check["classification"] == "unresolved" and url in confirmed_hosting:
            check = confirmed_hosting[url]
        if check["classification"] == "dead_confirmed" and check.get("attempts") and all(
                attempt["outcome"] == "dead_dns" for attempt in check["attempts"]):
            if not check.get("dns_confirmation") or any(status != 3 for status in check["dns_confirmation"].values()):
                raise ValueError(f"Independent DNS confirmation is incomplete: {url}")
        return check

    members = defaultdict(list)
    for merge in audit["merges"]:
        members[merge["canonical_reference_key"]].append(merge["row"])
    kept, removed, repaired = [], [], []
    counts = Counter()
    for row in rows:
        alternatives = [row, *members[reference_key(row)]]
        checked = [(candidate, result(candidate)) for candidate in alternatives]
        live = [(candidate, check) for candidate, check in checked if
                check["classification"] in {"live", "social_preserved", "contact_preserved"}]
        usable = live or [(candidate, check) for candidate, check in checked
                          if not check["classification"].startswith("dead_")]
        if not usable:
            removed.append({"row": row, "evidence": [check for _, check in checked]})
            continue
        candidate, check = usable[0]
        website = check.get("working_url", candidate["website"])
        # Follow confirmed business-domain moves. Keep social/directory links
        # intact; generic login or directory redirects do not identify a shop.
        successful = next((a for a in reversed(check.get("attempts", []))
                           if a["outcome"] == "live" and a.get("final_url")), None)
        if successful:
            final_url = successful["final_url"]
            old_host = (urlsplit(normalize(website)).hostname or "").removeprefix("www.")
            new_host = (urlsplit(final_url).hostname or "").removeprefix("www.")
            directories = {"booking.com", "google.com", "goo.gl", "g.page", "maps.app.goo.gl", "padi.com"}
            if old_host != new_host and not is_social(final_url) and not any(
                    new_host == host or new_host.endswith("." + host) for host in directories):
                website = final_url
        if "http://:" in website or "https://:" in website:
            website = normalize(website)
        if row["website"] != website:
            repaired.append({"reference_key": reference_key(row), "name": row["name"],
                             "old_website": row["website"], "website": website})
            row["website"] = website
        counts[check["classification"]] += 1
        kept.append(row)
    audit.update({"removed_dead_website": len(removed), "dead_websites": removed,
                  "website_repairs": repaired, "retained_website_status": dict(counts), "output_rows": len(kept)})
    return kept


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("data/padi_dive_centers.csv"))
    parser.add_argument("--audit", type=Path, default=Path("data/dive_center_cleanup_audit.json"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--website-evidence", type=Path)
    args = parser.parse_args()
    with args.csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    kept, audit = clean(rows)
    if args.website_evidence:
        from check_center_websites import read_evidence
        evidence = read_evidence(args.website_evidence)
        kept = apply_website_evidence(kept, audit, evidence)
        # Repaired homepage URLs can expose an additional duplicate.
        kept, final_audit = clean(kept)
        audit["merges"].extend(final_audit["merges"])
        audit["merged_duplicate_rows"] = len(audit["merges"])
        audit["output_rows"] = len(kept)
        final_destinations = {key: row for row in kept for key in
                              [reference_key(row), *json.loads(row.get("merged_reference_keys") or "[]")]}
        for merge in audit["merges"]:
            target = final_destinations.get(merge["canonical_reference_key"])
            if target:
                merge["canonical_reference_key"] = reference_key(target)
                merge["canonical_name"] = target["name"]
        from check_center_websites import is_contact, is_social
        statuses = {url: check["classification"] for url, check in evidence.items()}
        statuses.update({check["working_url"]: check["classification"] for check in evidence.values()
                         if check.get("working_url") and check["classification"] in {"live", "social_preserved"}})
        statuses.update({attempt["final_url"]: "live" for check in evidence.values()
                         if check["classification"] == "live" for attempt in check.get("attempts", [])
                         if attempt.get("final_url") and attempt["outcome"] == "live"})
        audit["retained_website_status"] = dict(Counter(
            "contact_preserved" if is_contact(row["website"]) else
            "social_preserved" if is_social(row["website"]) else statuses.get(row["website"], "unresolved")
            for row in kept))
        audit["website_evidence"] = {
            "path": str(args.website_evidence), "distinct_urls": len(evidence),
            "first_checked_at": min(r["checked_at"] for r in evidence.values()),
            "last_checked_at": max(r["checked_at"] for r in evidence.values()),
            "classifications": dict(Counter(r["classification"] for r in evidence.values())),
        }
    audit["source_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    # Keep audit entries useful to a reviewer without repeating every raw
    # Overture taxonomy and source-metadata field thousands of times.
    audit_fields = {"name", "physical_address", "location", "website", "latitude", "longitude", "source",
                    "padi_id", "padi_url", "overture_id", "merged_reference_keys"}
    for entry in [*audit["removed"], *audit["merges"], *audit.get("dead_websites", [])]:
        row = entry["row"]
        entry["row"] = {"reference_key": reference_key(row),
                        **{k: v for k, v in row.items() if k in audit_fields and (v or k in
                           {"name", "physical_address", "location", "website"})}}
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    if args.write:
        if "merged_reference_keys" not in fields:
            fields.append("merged_reference_keys")
        temporary = args.csv.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(kept)
        temporary.replace(args.csv)
    print(json.dumps({k: v for k, v in audit.items() if k not in
                     {"removed", "merges", "dead_websites", "website_repairs"}}, indent=2))


if __name__ == "__main__":
    main()
