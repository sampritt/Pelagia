#!/usr/bin/env python3
"""Generate resumable page summaries for the 100 directory sites using the app generator."""
import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pelagia import seo, site_descriptions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'pelagia/seo_site_descriptions.json')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        parser.error('OPENAI_API_KEY is required')
    with (ROOT / 'data/global_dive_sites_master.csv').open(encoding='utf-8') as source:
        catalog = {row['master_site_id']: row for row in csv.DictReader(source)}
    selected = seo.selected_sites()
    results = json.loads(args.output.read_text()) if args.output.exists() else {}
    app = Flask(__name__)
    app.config['OPENAI_API_KEY'] = key

    def generate(master_id):
        row = catalog[master_id]
        site = {field: row[field] for field in ('country_or_area', 'country_code', 'latitude', 'longitude')}
        site['name'] = row['dive_site_name']
        with app.app_context():
            description, citations = site_descriptions.generate_description(site)
        if not description:
            raise site_descriptions.GenerationError('No verified description')
        return dict(description=description, citations=citations, model=site_descriptions.MODEL,
                    generated_at=datetime.now(timezone.utc).isoformat())

    failures = []
    pending = [master_id for master_id in selected if master_id not in results]
    print(f'Generating {len(pending)} summaries; {len(results)} already saved.', flush=True)
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as executor:
        futures = {executor.submit(generate, master_id): master_id for master_id in pending}
        for future in as_completed(futures):
            master_id = futures[future]
            try:
                results[master_id] = future.result()
            except Exception as error:
                failures.append(master_id)
                detail = str(error) if isinstance(error, site_descriptions.GenerationError) else type(error).__name__
                print(f'{master_id}: failed ({detail})', flush=True)
                continue
            temporary = args.output.with_suffix('.tmp')
            temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
            temporary.replace(args.output)
            print(f'{master_id}: saved ({len(results)}/100, {len(results[master_id]["description"].split())} words)', flush=True)
    if failures:
        print('Incomplete: ' + ', '.join(failures), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
