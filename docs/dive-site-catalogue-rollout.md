The cleaned dive-site catalogue contains 10,585 records. Original removals,
merges, and recovery decisions remain in the `data/dive_site_*review.csv` files
and `data/dive_site_cleanup_audit.json`.

`create_app()` calls `pelagia/dive_site_cleanup_startup.py` after reference-data
initialization. It reads the configured dive-site CSV, validates it, and fully
replaces the contents of the SQLite `dive_sites` table in one transaction.
It uses the CSV's `legacy_import_id` for SQLite IDs. Custom catalogues without
that column are outside this rollout.

The hook records the CSV digest in `reference_catalog_versions`, using the same
startup pattern as dive centers. Starting additional workers or restarting with
the same catalogue and row count skips replacement. A different CSV triggers a
new replacement. No separate deployment command is needed.

SQLite foreign keys remain enabled. Replacement clears site-dependent favorites,
comments, reviews, and caches. Existing dive logs retain their recorded names,
locations, coordinates, and other details, but their `dive_site_id` links become
NULL. These links can be repaired manually after deployment.
