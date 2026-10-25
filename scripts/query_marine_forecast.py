#!/usr/bin/env python3
"""Standalone Open-Meteo marine endpoint probe; Python standard library only.

Examples (run from any directory):
  python3 scripts/query_marine_forecast.py --site "Gordon Rocks"
  python3 scripts/query_marine_forecast.py --latitude=-0.5548 --longitude=-90.07141

Name searches use the existing dive-site CSV, not city geocoding. Ambiguous
names require --site-id. No Pelagia imports, database writes, or API key.
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://marine-api.open-meteo.com/v1/marine"
FIELDS = (
    "sea_level_height_msl",
    "sea_surface_temperature",
    "ocean_current_velocity",
    "ocean_current_direction",
)


def find_site(catalog, name, site_id):
    with catalog.open(encoding="utf-8-sig", newline="") as source:
        sites = list(csv.DictReader(source))
    if site_id:
        matches = [s for s in sites if s["master_site_id"] == site_id]
    else:
        matches = [s for s in sites if s["dive_site_name"].casefold() == name.casefold()]
        if not matches:
            matches = [s for s in sites if name.casefold() in s["dive_site_name"].casefold()]
    if len(matches) != 1:
        candidates = "; ".join(
            f'{s["master_site_id"]}: {s["dive_site_name"]} ({s["country_or_area"]})'
            for s in matches[:20]
        )
        raise ValueError(f"Expected one site, found {len(matches)}. "
                         f"Use --site-id to disambiguate. {candidates}")
    site = matches[0]
    return float(site["latitude"]), float(site["longitude"]), site


def fetch_forecast(latitude, longitude, timezone_name):
    if not (math.isfinite(latitude) and -90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (math.isfinite(longitude) and -180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180.")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(FIELDS),
        "forecast_days": 7,
        "timezone": timezone_name,
        "cell_selection": "sea",
        "temperature_unit": "celsius",
        "length_unit": "metric",
        "wind_speed_unit": "kn",
    }
    url = ENDPOINT + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "PelagiaMarineEndpointProbe/1.0"})
    try:
        with urlopen(request, timeout=45) as response:
            status = response.status
            payload = json.load(response)
    except HTTPError as exc:
        raise ValueError(f"Open-Meteo HTTP {exc.code}: "
                         f"{exc.read(2000).decode('utf-8', errors='replace')}") from exc
    if payload.get("error"):
        raise ValueError(f"Open-Meteo: {payload.get('reason', 'unknown API error')}")
    return url, status, payload


def validate(payload):
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if len(times) != 168:
        raise ValueError(f"Expected 168 hourly timestamps, received {len(times)}.")
    parsed = [datetime.fromisoformat(t) for t in times]
    if any(b - a != timedelta(hours=1) for a, b in zip(parsed, parsed[1:])):
        raise ValueError("Forecast timestamps are not consecutive hourly samples.")
    result = {}
    for field in FIELDS:
        values = hourly.get(field)
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError(f"Missing or misaligned hourly array: {field}")
        if not payload.get("hourly_units", {}).get(field):
            raise ValueError(f"Missing unit for {field}")
        present = [v for v in values if v is not None]
        if any(isinstance(v, bool) or not isinstance(v, (float, int))
               or not math.isfinite(v) for v in present):
            raise ValueError(f"Non-numeric or non-finite value for {field}")
        result[field] = {
            "unit": payload["hourly_units"][field],
            "non_null": len(present),
            "missing": len(times) - len(present),
            "min": min(present) if present else None,
            "max": max(present) if present else None,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    lookup = parser.add_mutually_exclusive_group()
    lookup.add_argument("--site", help="Exact site name, or a unique partial name")
    lookup.add_argument("--site-id", help="Dive-site master ID")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/global_dive_sites_master.csv")
    parser.add_argument("--timezone", default="auto", help="IANA zone, default: auto")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/marine-forecast")
    args = parser.parse_args(argv)
    explicit = args.latitude is not None or args.longitude is not None
    if explicit and (args.latitude is None or args.longitude is None):
        parser.error("Supply both --latitude and --longitude.")
    if explicit and (args.site or args.site_id):
        parser.error("Choose a site lookup or explicit coordinates.")
    if not explicit and not (args.site or args.site_id):
        parser.error("Supply --site, --site-id, or --latitude and --longitude.")
    site = None
    try:
        if explicit:
            latitude, longitude = args.latitude, args.longitude
        else:
            latitude, longitude, site = find_site(args.catalog, args.site, args.site_id)
        url, status, payload = fetch_forecast(latitude, longitude, args.timezone)
        stats = validate(payload)
        retrieved = datetime.now(timezone.utc).isoformat()
        report = {
            "retrieved_at_utc": retrieved,
            "http_status": status,
            "request_url": url,
            "requested_coordinates": {"latitude": latitude, "longitude": longitude},
            "site": site,
            "returned_grid_cell": {k: payload.get(k) for k in ("latitude", "longitude")},
            "timezone": payload.get("timezone"),
            "utc_offset_seconds": payload.get("utc_offset_seconds"),
            "hours": len(payload["hourly"]["time"]),
            "first_hour": payload["hourly"]["time"][0],
            "last_hour": payload["hourly"]["time"][-1],
            "fields": stats,
            "notes": [
                "Seven calendar days beginning at local midnight, including earlier hours today.",
                "Current direction is towards: 0 degrees north, 90 east.",
                "Sea level is relative to global mean sea level, not chart datum.",
                "Tide/current grid is approximately 8 km; SST source is six-hourly.",
                "Model output does not resolve site-specific currents or temperature at dive depth.",
            ],
            "attribution": "Open-Meteo; Météo-France / Copernicus Marine; DWD. "
                           "https://open-meteo.com/en/docs/marine-weather-api",
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "forecast.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (args.output_dir / "summary.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        with (args.output_dir / "forecast.csv").open("w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(("time", *FIELDS))
            writer.writerows(zip(payload["hourly"]["time"],
                                 *(payload["hourly"][field] for field in FIELDS)))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"Saved forecast.json, forecast.csv, summary.json to {args.output_dir.resolve()}")
        if any(s["missing"] for s in stats.values()):
            print("WARNING: Partial forecast; null values preserved in output.", file=sys.stderr)
            return 2
        return 0
    except (ValueError, OSError, URLError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
