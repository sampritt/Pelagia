# Dive center catalogue cleanup

The deployed catalogue is `data/padi_dive_centers.csv`, configured in
`app_config.json`. Raw PADI scrape parts are historical inputs, not the deployed
catalogue.

Every retained center must have a nonblank name, physical address **and** website
or contact link. Email addresses, `mailto:`, telephone and messaging links, and
social profiles are valid contact links. The registry also enforces these
required fields when it imports a replacement CSV.

`scripts/clean_dive_centers.py` compares normalized addresses and URLs, using
coordinates, location, names and provider identities to distinguish duplicate
records from different businesses or branches. URL normalization preserves
social profile IDs and store-page query parameters. Shared chain homepages and
shared beaches, streets or marinas alone do not establish a duplicate. A center
with a dead primary website can use a working website from its duplicate record.

Merged rows retain their old provider and legacy identities in the CSV's
`merged_reference_keys` column. On startup, `pelagia/center_registry.py` retains
the surviving center's database ID and moves linked dives, likes, comments,
reviews and cached descriptions before deleting duplicates. A user who reviewed
both duplicates retains their most recently edited review. Removed centers'
logged dives retain the recorded center name and lose only the catalogue link.

`create_app()` invokes the registry directly during app startup. The registry
locks the database and records the CSV digest, so multiple workers and later
restarts do not repeat an unchanged catalogue update. The temporary rollout
hook has been removed. Center descriptions use their persistent cache by
default; forced refresh on every profile visit is disabled.

Website checks use bounded requests and write resumable JSONL evidence with
timestamps, HTTP statuses, redirects and failure reasons. Social profiles and
contact links are preserved. Apparent failures receive a separate retry pass;
HTTP/HTTPS and hostname variants are checked, and a dead deep link may be
repaired to a working homepage. Repeated 404/410 responses, explicit domain
parking or expired/suspended pages, and hosting domain-mapping errors are dead
links. DNS failures additionally require an independent public DNS response
confirming NXDOMAIN. Bot blocks, rate limits, TLS errors, timeouts, and temporary
server failures alone are inconclusive and are retained.

Run from the repository root using the project's Python environment:

```sh
.venv312/bin/python scripts/check_center_websites.py --workers 64
.venv312/bin/python scripts/check_center_websites.py --retry --workers 64
.venv312/bin/python scripts/check_center_websites.py --confirm-dns --workers 32
.venv312/bin/python scripts/clean_dive_centers.py \
  --website-evidence output/center-cleanup/website_checks.jsonl
```

Without `--write`, cleanup writes an audit but leaves the CSV alone. Review
`data/dive_center_cleanup_audit.json`, then run the same cleanup command with
`--write` to update the catalogue. A later import of fresh source data should
use a new evidence file so that old reachability results are not reused.

Validation:

```sh
PYTHONPATH=tests .venv312/bin/python -m unittest \
  test_center_registry test_clean_dive_centers test_reference_autocomplete \
  test_center_profiles test_dive_center_sharing
```
