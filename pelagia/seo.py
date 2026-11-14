"""One explicit editorial selection shared by public pages and the sitemap."""

import csv
from functools import lru_cache
from pathlib import Path

from .db import get_db


@lru_cache(maxsize=1)
def selected_sites():
    with Path(__file__).with_name("seo_sites.tsv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    if len(rows) != 100 or len({row["master_site_id"] for row in rows}) != 100:
        raise ValueError("The SEO selection must contain exactly 100 unique catalog sites")
    return {row["master_site_id"]: row for row in rows}


def site_selection(site_id):
    row = get_db().execute("SELECT master_site_id FROM dive_sites WHERE id = ?", (site_id,)).fetchone()
    return selected_sites().get(row["master_site_id"]) if row else None


def directory_sites():
    selection = selected_sites()
    placeholders = ",".join("?" for _ in selection)
    rows = get_db().execute(
        f"SELECT id, master_site_id, name, country_or_area, latitude, longitude, logged_dive_count FROM dive_sites "
        f"WHERE master_site_id IN ({placeholders})", tuple(selection),
    )
    return sorted((dict(row, **{key: value for key, value in selection[row["master_site_id"]].items()
                               if key != "master_site_id"}) for row in rows),
                  key=lambda row: (row["region"], row["country"], row["name"].casefold()))


def indexable_centers(center_id=None):
    # Require actual server-rendered descriptive content, not just a map/name.
    return get_db().execute(
        "SELECT c.id FROM dive_centers c JOIN dive_center_descriptions d ON d.dive_center_id = c.id "
        "WHERE trim(coalesce(c.name, '')) <> '' AND trim(coalesce(c.location, '')) <> '' "
        "AND trim(coalesce(d.description, '')) <> '' "
        "AND c.latitude BETWEEN -90 AND 90 AND c.longitude BETWEEN -180 AND 180 "
        + ("AND c.id = ? " if center_id is not None else "") + "ORDER BY c.id",
        (center_id,) if center_id is not None else (),
    ).fetchall()
