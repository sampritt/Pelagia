"""Schedule daily refreshes for all Home report cards without network I/O."""
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzfpy import get_tz

from .marine import coordinates


@lru_cache(maxsize=4096)
def coordinate_zone(latitude, longitude):
    name = get_tz(longitude, latitude)
    try:
        return ZoneInfo(name) if name else None
    except ZoneInfoNotFoundError:
        return None


def report_schedule(sites, now=None):
    """Identify every displayed site's local day and the next day boundary."""
    now = now or datetime.now(timezone.utc)
    keys, midnights = [], []
    for site in sites:
        point = coordinates(site)
        zone = coordinate_zone(*point) if point else None
        local_date = now.date()
        if zone:
            local_date = now.astimezone(zone).date()
            midnights.append(datetime.combine(local_date + timedelta(days=1), time.min, zone).timestamp())
        else:
            midnights.append(datetime.combine(local_date + timedelta(days=1), time.min, timezone.utc).timestamp())
        keys.append(f"{site['id']}:{local_date}" + (":featured" if site.get('featured') else ""))
    return '|'.join(keys), min(midnights) if midnights else None
