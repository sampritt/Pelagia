#!/usr/bin/env python3
"""Resolve Pelagia species into OBIS taxa and ingest nearby occurrences.

The default run resolves all Pelagia common-name tags through WoRMS, then queries
each distinct accepted AphiaID in OBIS for 2020-01-01 through today. It keeps only
presence records whose coordinate uncertainty is strictly below 0.5 miles and
whose coordinates are strictly within 0.5 Cartesian miles of a Pelagia dive site.

The database is committed after every OBIS page. Re-running the command resumes
from the last committed cursor and skips completed taxa.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from pelagia.obis_catalog import (
    JsonApi,
    RADIUS_MILES,
    START_DATE,
    connect_database,
    ingest_all,
    initialize_schema,
    load_overrides,
    resolve_species,
    summary,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("PELAGIA_DATABASE_PATH", "instance/pelagia.sqlite3")),
    )
    parser.add_argument("--start-date", type=date.fromisoformat, default=START_DATE)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=datetime.now(timezone.utc).date(),
    )
    parser.add_argument("--radius-miles", type=float, default=RADIUS_MILES)
    parser.add_argument(
        "--taxon-overrides",
        type=Path,
        help="optional JSON object mapping Pelagia names to AphiaID arrays; null skips a tag",
    )
    parser.add_argument(
        "--species",
        action="append",
        default=[],
        help="process one Pelagia common name (repeatable; default: all)",
    )
    parser.add_argument("--refresh-resolutions", action="store_true")
    parser.add_argument("--resolve-only", action="store_true")
    parser.add_argument("--ingest-only", action="store_true")
    parser.add_argument("--max-taxa", type=int, help="development limit after resolution")
    parser.add_argument("--request-delay", type=float, default=0.1)
    args = parser.parse_args(argv)
    if args.resolve_only and args.ingest_only:
        parser.error("--resolve-only and --ingest-only are mutually exclusive")
    if args.radius_miles <= 0:
        parser.error("--radius-miles must be positive")
    if args.start_date > args.end_date:
        parser.error("--start-date must not be after --end-date")
    if args.max_taxa is not None and args.max_taxa <= 0:
        parser.error("--max-taxa must be positive")

    api = JsonApi(request_delay=max(0, args.request_delay))
    db = connect_database(args.database)
    try:
        initialize_schema(db)
        if not args.ingest_only:
            resolve_species(
                db,
                api,
                overrides=load_overrides(args.taxon_overrides),
                refresh=args.refresh_resolutions,
                selected_names=args.species,
            )
        if not args.resolve_only:
            ingest_all(
                db,
                api,
                start_date=args.start_date,
                end_date=args.end_date,
                radius_miles=args.radius_miles,
                selected_names=args.species,
                max_taxa=args.max_taxa,
            )
        print(json.dumps(summary(db), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
