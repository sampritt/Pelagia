"""Clean the reference catalogue and retain a complete, reviewable audit.

Run once on the original catalogue: python scripts/clean_dive_sites.py --write
Without --write, output files are produced but the catalogue is not changed.
"""
import argparse
import csv
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data/global_dive_sites_master.csv'
AUDIT = ROOT / 'data/dive_site_cleanup_audit.json'
INVALID = ROOT / 'data/dive_site_location_pending_review.csv'
DUPLICATES = ROOT / 'data/dive_site_duplicate_review.csv'


def normalize(value):
    value = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in value if not unicodedata.combining(c))))


def distance(a, b):
    try:
        lat1, lon1, lat2, lon2 = (float(row[key]) for row in (a, b) for key in ('latitude', 'longitude'))
        if not all(math.isfinite(x) for x in (lat1, lon1, lat2, lon2)) or not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
            return None
    except (ValueError, TypeError):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 12742 * math.asin(min(1, math.sqrt(h)))


def name_reason(a, b):
    x, y = a['dive_site_name'], b['dive_site_name']
    if normalize(x) == normalize(y):
        return 'same normalized name'
    if all('kicker rock' in normalize(n) for n in (x, y)):
        return 'known Kicker Rock alias'
    for short, long in ((x, y), (y, x)):
        shortkey = normalize(short)
        # Parentheses usually introduce an alias or site number, but directional
        # and structural qualifiers can identify separate nearby sites.
        m = re.fullmatch(r'\s*(.*?)\s*\(([^()]*)\)\s*', long)
        if m and normalize(m.group(1)) == shortkey:
            qualifier = set(normalize(m.group(2)).split())
            if not qualifier & {'north', 'south', 'east', 'west', 'wreck', 'reef', 'wall', 'point', 'deep', 'shallow', 'inner', 'outer', 'jetty', 'puerto'}:
                return 'parenthesized alias or number'
        # Comma suffixes are accepted only when they name a geography visible in
        # either record, plus Galapagos (a common regional qualifier for Ecuador).
        m = re.fullmatch(r'\s*([^,]+),\s*(.+)', long)
        if m and normalize(m.group(1)) == shortkey:
            suffix = normalize(m.group(2))
            geo = ' '.join(normalize(r.get(k, '')) for r in (a, b) for k in ('country_or_area', 'country_code'))
            if suffix and (suffix in geo or suffix == 'galapagos' and 'ecuador' in geo):
                return 'geographic comma suffix'
    return None


def clean(rows):
    invalid, valid = [], []
    for index, original in enumerate(rows, 1):
        row = dict(original)
        row.setdefault('legacy_import_id', str(index))
        if normalize(row.get('country_or_area', '')) in {'', 'na', 'nan', 'location pending'}:
            invalid.append(row)
        else:
            valid.append(row)
    grid = defaultdict(list)
    groups = []
    for row in valid:
        try:
            lat, lon = float(row['latitude']), float(row['longitude'])
            if not math.isfinite(lat) or not math.isfinite(lon):
                raise ValueError
        except (ValueError, TypeError):
            groups.append([row]); continue
        cell = (math.floor(lat * 100), math.floor(lon * 100))
        # Longitude degrees shrink at high latitude; longitude buckets are
        # widened accordingly, with wrapped cells at the antimeridian.
        radius = min(18000, math.ceil(1 / max(0.001, 1.11 * abs(math.cos(math.radians(lat))))) + 1)
        candidates = set()
        for di in range(-1, 2):
            for dj in range(-radius, radius + 1):
                for loncell in (cell[1] + dj, cell[1] + dj - 36000, cell[1] + dj + 36000):
                    candidates.update(grid[(cell[0]+di, loncell)])
        matches = []
        for i in sorted(candidates):
            # Every pair in a group must be near and independently match. This
            # prevents a broad regional name from joining several sub-sites.
            if all((d := distance(row, member)) is not None and d <= 1 and name_reason(row, member) for member in groups[i]):
                matches.append(i)
        if len(matches) == 1:
            idx = matches[0]; groups[idx].append(row)
        else:
            idx = len(groups); groups.append([row])
        grid[cell].append(idx)
    kept, merges = [], []
    union_fields = ('sources', 'source_record_ids', 'source_urls', 'licenses_and_attribution', 'data_quality_notes')
    for group in groups:
        # Preserve the most sourced original record and its site identity.
        canonical = max(group, key=lambda r: (int(r.get('source_record_count') or 0), bool(r.get('description')), -int(r['legacy_import_id'])))
        merged = dict(canonical)
        if len(group) > 1:
            for field in union_fields:
                values = []
                for member in group:
                    for value in member.get(field, '').split(' | '):
                        value = value.strip()
                        if value and value != 'NA' and value not in values: values.append(value)
                merged[field] = ' | '.join(values) or 'NA'
            merged['source_count'] = str(len(merged['sources'].split(' | ')))
            merged['source_record_count'] = str(len(merged['source_record_ids'].split(' | ')))
            if not merged.get('description'):
                merged['description'] = next((r['description'] for r in group if r.get('description')), '')
            merges.append({'canonical_id': canonical['master_site_id'], 'canonical_name': canonical['dive_site_name'],
                           'members': [{'distance_km': round(distance(canonical, r), 4), 'reason': 'canonical' if r is canonical else name_reason(canonical, r), 'row': r} for r in group]})
        kept.append(merged)
    kept.sort(key=lambda r: int(r['legacy_import_id']))
    return kept, invalid, merges


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--write', action='store_true'); args = parser.parse_args()
    with CATALOG.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f); fields = list(reader.fieldnames); rows = list(reader)
    if 'legacy_import_id' in fields:
        raise SystemExit('Catalogue already cleaned; refusing to overwrite the original review files.')
    fields.append('legacy_import_id')
    kept, invalid, merges = clean(rows)
    with INVALID.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(invalid)
    with DUPLICATES.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['canonical_id', 'canonical_name', 'site_id', 'site_name', 'geography', 'latitude', 'longitude', 'distance_km', 'reason'])
        writer.writeheader()
        for group in merges:
            for member in group['members']:
                row = member['row']
                writer.writerow({'canonical_id': group['canonical_id'], 'canonical_name': group['canonical_name'],
                                 'site_id': row['master_site_id'], 'site_name': row['dive_site_name'],
                                 'geography': row['country_or_area'], 'latitude': row['latitude'],
                                 'longitude': row['longitude'], 'distance_km': member['distance_km'], 'reason': member['reason']})
    AUDIT.write_text(json.dumps({'original_count': len(rows), 'invalid_count': len(invalid), 'duplicate_groups': len(merges), 'duplicate_records_removed': sum(len(m['members'])-1 for m in merges), 'remaining_count': len(kept), 'merges': merges}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if args.write:
        with CATALOG.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(kept)
    print(f'{len(rows)} input; {len(invalid)} location pending; {sum(len(m["members"])-1 for m in merges)} duplicates; {len(kept)} retained')


if __name__ == '__main__': main()
