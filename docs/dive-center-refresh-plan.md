# Dive-shop registry updates

Deploying a changed `data/padi_dive_centers.csv` automatically replaces the
searchable `dive_centers` catalogue at application startup, including on
populated production databases. Dive-site and species startup behavior is
unchanged.

Each worker checks the CSV checksum. A SQLite transaction serializes the
replacement; subsequent workers skip it once the checksum and row count
match. All named rows are loaded, including distinct Overture identities with
the same name/address. Coordinates come directly from the CSV.

Existing shops retain their integer ID when their source identity matches, or
on the first refresh when their name/address/location match a legacy row.
The catalogue contents are replaced completely: obsolete shops are removed.
Their logged dives keep the shop name as text and lose the obsolete link;
likes and comments attached to removed shops are removed. Matching shops keep
their dive links, likes and comments. New shops receive IDs above the previous
maximum during replacement.

To reload the configured CSV explicitly on the production host, run from the
deployed app directory with its normal environment:

```bash
flask --app wsgi refresh-dive-centers
```

`PELAGIA_DATABASE_PATH` selects the SQLite file (default:
`/var/data/pelagia.sqlite3`). `PELAGIA_CONFIG` selects the configuration JSON;
its `data_sources.dive_centers_csv` selects the CSV. Both autocomplete endpoints
read the refreshed table directly, so the next request sees the new shops.

The refresh is atomic. A validation or SQL error rolls back the table update
and version marker together.
