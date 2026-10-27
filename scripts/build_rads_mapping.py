"""Map Pelagia dive sites to the nearest 2025 RADS CPC_UNI grid cell."""

import csv
from datetime import date, timedelta
from pathlib import Path

import h5py
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "data" / "global_dive_sites_master.csv"
RADS = ROOT / "data" / "RainyAndDrySeason.dayofyear.CPC_UNI.2025.nc"
OUTPUT = ROOT / "data" / "dive_site_rainy_seasons_rads_2025.csv"
EPOCH = date(1970, 1, 1)
MIN_VALID_YEAR = 2000
MIN_SEASON_DAYS = 30
MAX_SEASON_DAYS = 366


def as_iso_day(days_since_epoch: int) -> str:
    # RADS' unmasked date variables use the Unix epoch (0) when no boundary
    # was detected. It is a sentinel, not a 1970 rainy-season observation.
    if days_since_epoch <= 0:
        return ""
    return (EPOCH + timedelta(days=int(days_since_epoch))).isoformat()


def nearest_index(values: np.ndarray, point: float) -> int:
    """Return the closest grid-coordinate index, handling 0–360° longitude."""
    return int(np.abs(values - point).argmin())


def normalize_season(start_text: str, end_text: str) -> tuple[str, str] | None:
    """Return a valid chronological season, rolling its end into the next year."""
    if not start_text or not end_text:
        return None
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
    except ValueError:
        return None
    if start.year < MIN_VALID_YEAR or end.year < MIN_VALID_YEAR:
        return None
    if end < start:
        end = date(end.year + 1, end.month, end.day)
    duration = (end - start).days
    if not MIN_SEASON_DAYS <= duration <= MAX_SEASON_DAYS:
        return None
    return start.isoformat(), end.isoformat()


def cartesian_coordinates(latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    """Convert latitude/longitude to unit-sphere Cartesian coordinates."""
    latitude_radians = np.radians(latitudes)
    longitude_radians = np.radians(longitudes)
    cos_latitude = np.cos(latitude_radians)
    return np.column_stack(
        (
            cos_latitude * np.cos(longitude_radians),
            cos_latitude * np.sin(longitude_radians),
            np.sin(latitude_radians),
        )
    )


def replace_bad_seasons(rows: list[dict[str, object]]) -> int:
    """Copy dates from the nearest valid dive site into every invalid row."""
    valid_indices_list = []
    for index, row in enumerate(rows):
        normalized = normalize_season(
            str(row["rainy_season_start"]), str(row["rainy_season_end"])
        )
        if normalized is None:
            continue
        row["rainy_season_start"], row["rainy_season_end"] = normalized
        valid_indices_list.append(index)

    valid_indices = np.array(valid_indices_list, dtype=int)
    valid_index_set = set(valid_indices.tolist())
    invalid_indices = np.array(
        [index for index in range(len(rows)) if index not in valid_index_set],
        dtype=int,
    )
    if not len(valid_indices):
        raise RuntimeError("No valid RADS seasons are available for replacement")
    if not len(invalid_indices):
        return 0

    coordinates = cartesian_coordinates(
        np.array([float(row["latitude"]) for row in rows]),
        np.array([float(row["longitude"]) for row in rows]),
    )
    valid_coordinates = coordinates[valid_indices]

    # Maximizing the dot product on a unit sphere minimizes Cartesian chord
    # distance. Work in batches so the search stays memory-efficient.
    batch_size = 512
    for offset in range(0, len(invalid_indices), batch_size):
        batch = invalid_indices[offset : offset + batch_size]
        nearest = np.argmax(coordinates[batch] @ valid_coordinates.T, axis=1)
        for bad_index, nearest_position in zip(batch, nearest, strict=True):
            donor = rows[int(valid_indices[int(nearest_position)])]
            rows[int(bad_index)]["rainy_season_start"] = donor["rainy_season_start"]
            rows[int(bad_index)]["rainy_season_end"] = donor["rainy_season_end"]

    return len(invalid_indices)


def main() -> None:
    with h5py.File(RADS, "r") as grid:
        latitudes = grid["latitude"][:]
        longitudes = grid["longitude"][:]
        onset = grid["onset_date"][0]
        demise = grid["demise_date"][0]

    rows = []
    with SITES.open(newline="", encoding="utf-8") as source:
        for site in csv.DictReader(source):
            latitude = float(site["latitude"])
            longitude = float(site["longitude"])
            # RADS longitudes are 0–360° while Pelagia stores -180–180°.
            grid_longitude = longitude % 360
            lat_index = nearest_index(latitudes, latitude)
            lon_index = nearest_index(longitudes, grid_longitude)
            rows.append(
                {
                    "dive_site_id": site["master_site_id"],
                    "rainy_season_start": as_iso_day(onset[lat_index, lon_index]),
                    "rainy_season_end": as_iso_day(demise[lat_index, lon_index]),
                    "latitude": latitude,
                    "longitude": longitude,
                }
            )

    replaced_count = replace_bad_seasons(rows)

    with OUTPUT.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(
            destination,
            fieldnames=["dive_site_id", "rainy_season_start", "rainy_season_end"],
        )
        writer.writeheader()
        writer.writerows(
            {
                "dive_site_id": row["dive_site_id"],
                "rainy_season_start": row["rainy_season_start"],
                "rainy_season_end": row["rainy_season_end"],
            }
            for row in rows
        )

    print(
        f"Wrote {len(rows):,} rows to {OUTPUT}; "
        f"replaced {replaced_count:,} invalid seasons"
    )


if __name__ == "__main__":
    main()
