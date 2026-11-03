"""Select the followed site whose local day began most recently, without I/O."""
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


def select_followed_site(sites, now=None):
    """Return the selected site, its local date, and the next midnight to recheck."""
    now = now or datetime.now(timezone.utc)
    ranked, midnights = [], []
    for site in sites:
        point = coordinates(site)
        zone = coordinate_zone(*point) if point else None
        midnight = float('-inf')
        local_date = now.date()
        if zone:
            local_date = now.astimezone(zone).date()
            midnight = datetime.combine(local_date, time.min, zone).timestamp()
            midnights.append(datetime.combine(local_date + timedelta(days=1), time.min, zone).timestamp())
        ranked.append((midnight, site.get('followed_at') or '', site, local_date))
    if not ranked:
        return None, now.date(), None
    # Stable input order resolves the unlikely case of identical follow timestamps.
    _, _, site, local_date = max(ranked, key=lambda entry: entry[:2])
    next_midnight = min(midnights) if midnights else None
    return site, local_date, next_midnight
