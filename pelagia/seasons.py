"""In-memory recurring rainy seasons keyed by reference catalog site ID."""

import calendar
import csv
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app


def init_app(app):
    path = Path(app.root_path).parent / "data" / "dive_site_rainy_seasons_rads_2025.csv"
    seasons = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            start = date.fromisoformat(row["rainy_season_start"])
            end = date.fromisoformat(row["rainy_season_end"])
            seasons[row["dive_site_id"]] = (start.month, end.month)
    app.extensions["rainy_seasons"] = seasons


def for_site(master_site_id, today=None):
    months = current_app.extensions["rainy_seasons"].get(master_site_id)
    if months is None:
        return None
    if today is None:
        today = datetime.now(ZoneInfo("America/New_York")).date()
    start, end = months
    # Month-level display includes the entire rainy-season end month.
    rainy = (start <= today.month <= end if start <= end
             else today.month >= start or today.month <= end)
    first, last = (start, end) if rainy else (end, start)
    return {"label": "Rainy season" if rainy else "Dry season",
            "start_month": calendar.month_name[first],
            "end_month": calendar.month_name[last]}
