"""Map dive sites to five-year median RADS CPC_UNI season boundaries."""

import csv
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "data" / "global_dive_sites_master.csv"
RADS_YEARS = tuple(range(2021, 2026))
RADS_FILES = tuple(
    ROOT / "data" / f"RainyAndDrySeason.dayofyear.CPC_UNI.{year}.nc"
    for year in RADS_YEARS
)
OUTPUT = ROOT / "data" / "dive_site_rainy_seasons_rads_2021_2025_median.csv"
OUTPUT_YEAR = RADS_YEARS[-1]
DAY_OF_YEAR_REFERENCE = date(2001, 1, 1)  # Non-leap year; RADS uses 1–365.
DAYS_PER_YEAR = 365
MIN_VALID_YEARS = 3
MIN_VALID_YEAR = 2000
MIN_SEASON_DAYS = 30
MAX_SEASON_DAYS = 366


def as_iso_day(day_of_year: float) -> str:
    """Convert a RADS 1–365 day of year to the output reference year."""
    if not np.isfinite(day_of_year):
        return ""
    rounded_day = int(np.floor(day_of_year + 0.5))
    if not 1 <= rounded_day <= DAYS_PER_YEAR:
        return ""
    reference = DAY_OF_YEAR_REFERENCE + timedelta(days=rounded_day - 1)
    return date(OUTPUT_YEAR, reference.month, reference.day).isoformat()


def median_dayofyear_grid(grids: list[np.ndarray]) -> np.ndarray:
    """Return robust medians for annual 1–365 boundary grids.

    Most cells use the ordinary median, which rejects a single annual outlier.
    When at least two observations fall on each side of the largest internal
    gap and that gap is larger than the gap across New Year, the observations
    are a genuine December/January cluster. In that case the low days are
    unwrapped into the following year before taking the median.
    """
    values = np.stack(grids).astype(float, copy=False)
    valid = np.isfinite(values) & (values >= 1) & (values <= DAYS_PER_YEAR)
    values = np.where(valid, values, np.nan)
    valid_count = valid.sum(axis=0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        ordinary_median = np.nanmedian(values, axis=0)

    sorted_values = np.sort(values, axis=0)
    internal_gaps = np.diff(sorted_values, axis=0)
    internal_gaps = np.where(np.isfinite(internal_gaps), internal_gaps, -np.inf)
    split_index = np.argmax(internal_gaps, axis=0)
    largest_internal_gap = np.max(internal_gaps, axis=0)
    split_value = np.take_along_axis(
        sorted_values, split_index[np.newaxis, ...], axis=0
    )[0]

    last_index = np.maximum(valid_count - 1, 0)[np.newaxis, ...]
    last_value = np.take_along_axis(sorted_values, last_index, axis=0)[0]
    wrap_gap = sorted_values[0] + DAYS_PER_YEAR - last_value
    lower_count = split_index + 1
    upper_count = valid_count - lower_count
    unwrap = (
        (valid_count >= MIN_VALID_YEARS)
        & (lower_count >= 2)
        & (upper_count >= 2)
        & (largest_internal_gap > wrap_gap)
    )

    unwrapped_values = np.where(
        np.isfinite(values) & (values <= split_value),
        values + DAYS_PER_YEAR,
        values,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        unwrapped_median = np.nanmedian(unwrapped_values, axis=0)
    unwrapped_median = ((unwrapped_median - 1) % DAYS_PER_YEAR) + 1

    result = np.where(unwrap, unwrapped_median, ordinary_median)
    return np.where(valid_count >= MIN_VALID_YEARS, result, np.nan)


def load_median_boundaries() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load annual RADS grids and return shared coordinates plus medians."""
    import h5py

    latitudes = None
    longitudes = None
    onset_grids = []
    demise_grids = []
    for path in RADS_FILES:
        with h5py.File(path, "r") as grid:
            annual_latitudes = grid["latitude"][:]
            annual_longitudes = grid["longitude"][:]
            if latitudes is None:
                latitudes = annual_latitudes
                longitudes = annual_longitudes
            elif not (
                np.array_equal(latitudes, annual_latitudes)
                and np.array_equal(longitudes, annual_longitudes)
            ):
                raise RuntimeError(f"RADS grid coordinates differ in {path}")
            onset_grids.append(grid["onset_dayofyear"][0])
            demise_grids.append(grid["demise_dayofyear"][0])

    assert latitudes is not None and longitudes is not None
    return (
        latitudes,
        longitudes,
        median_dayofyear_grid(onset_grids),
        median_dayofyear_grid(demise_grids),
    )


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
    latitudes, longitudes, onset, demise = load_median_boundaries()

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
            lineterminator="\n",
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
        f"replaced {replaced_count:,} invalid median seasons"
    )


if __name__ == "__main__":
    main()
