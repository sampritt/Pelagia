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

Every replacement rebuilds `dive_site_obis_occurrences` from saved OBIS
observations and their Pelagia taxon mappings in the same transaction. It uses
the ingestion rule: coordinate uncertainty and Cartesian distance must each be
strictly below 0.5 miles. Observations can link to every qualifying new site;
old site IDs and names do not determine the match. No OBIS requests are made.

A separate version marker runs this repair once for databases that already
received the original catalogue rollout, without replacing their sites again.
Later workers and unchanged restarts skip the repair. Saved observations,
taxonomy resolutions, and ingestion cursors remain intact. This remaps the
existing observation corpus; it does not fetch additional observations for
newly added or relocated sites.

SQLite foreign keys remain enabled. Replacement clears site-dependent favorites,
comments, reviews, and caches. Existing dive logs retain their recorded names,
locations, coordinates, and other details, but their `dive_site_id` links become
NULL. These links can be repaired manually after deployment.
