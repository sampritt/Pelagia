import sqlite3
from pathlib import Path


def resolve_path(config_path, value):
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path(config_path).resolve().parent / path


def import_reference_data(db_path, config, config_path):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError(
            "Pelagia needs pandas to import the local dive-site and species CSV files. "
            "Install requirements.txt, then restart the app."
        ) from exc

    sources = config.get("data_sources", {})
    site_csv = resolve_path(config_path, sources["dive_sites_csv"])
    species_csv = resolve_path(config_path, sources["species_csv"])
    center_csv = resolve_path(config_path, sources.get("dive_centers_csv", "data/padi_dive_centers.csv"))

    sites_raw = pd.read_csv(site_csv, encoding="utf-8-sig")
    species_raw = pd.read_csv(species_csv, encoding="utf-8-sig")
    centers_raw = pd.read_csv(center_csv, encoding="utf-8-sig")

    site_columns = {
        "master_site_id": "master_site_id",
        "dive_site_name": "name",
        "country_or_area": "country_or_area",
        "country_code": "country_code",
        "latitude": "latitude",
        "longitude": "longitude",
        "max_depth_m": "max_depth_m",
    }
    missing_sites = set(site_columns) - set(sites_raw.columns)
    if missing_sites:
        raise ValueError(f"Dive-site CSV is missing columns: {sorted(missing_sites)}")

    missing_species = {"country_or_area", "common_name"} - set(species_raw.columns)
    if missing_species:
        raise ValueError(f"Species CSV is missing columns: {sorted(missing_species)}")
    missing_centers = {"name", "physical_address", "location", "website"} - set(centers_raw.columns)
    if missing_centers:
        raise ValueError(f"Dive-center CSV is missing columns: {sorted(missing_centers)}")

    sites = sites_raw[list(site_columns)].rename(columns=site_columns)
    sites = sites.dropna(subset=["name"]).copy()
    sites["id"] = range(1, len(sites) + 1)
    for column in ("latitude", "longitude", "max_depth_m"):
        sites[column] = pd.to_numeric(sites[column], errors="coerce")
    sites = sites[
        [
            "id",
            "master_site_id",
            "name",
            "country_or_area",
            "country_code",
            "latitude",
            "longitude",
            "max_depth_m",
        ]
    ]

    species = species_raw[["country_or_area", "common_name"]].dropna().copy()
    species["country_or_area"] = species["country_or_area"].astype(str).str.strip()
    species["common_name"] = species["common_name"].astype(str).str.strip()
    species = species[(species["country_or_area"] != "") & (species["common_name"] != "")]
    species = species.drop_duplicates(["country_or_area", "common_name"]).copy()
    species["id"] = range(1, len(species) + 1)
    species = species[["id", "country_or_area", "common_name"]]

    centers = centers_raw[["name", "physical_address", "location", "website"]].dropna(subset=["name"]).copy()
    for column in ("name", "physical_address", "location", "website"):
        centers[column] = centers[column].fillna("").astype(str).str.strip()
    centers = centers[centers["name"] != ""].drop_duplicates(["name", "physical_address", "location"]).copy()
    centers["id"] = range(1, len(centers) + 1)
    centers["latitude"] = None
    centers["longitude"] = None
    centers = centers[["id", "name", "physical_address", "location", "website", "latitude", "longitude"]]

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        sites.to_sql("_import_dive_sites", conn, if_exists="replace", index=False)
        species.to_sql("_import_species", conn, if_exists="replace", index=False)
        centers.to_sql("_import_dive_centers", conn, if_exists="replace", index=False)
        conn.execute("DELETE FROM dive_sites")
        conn.execute("DELETE FROM species")
        conn.execute("DELETE FROM dive_centers")
        conn.execute(
            """
            INSERT INTO dive_sites (
                id, master_site_id, name, country_or_area, country_code,
                latitude, longitude, max_depth_m
            )
            SELECT
                id, master_site_id, name, country_or_area, country_code,
                latitude, longitude, max_depth_m
            FROM _import_dive_sites
            """
        )
        conn.execute(
            """
            INSERT INTO species (id, country_or_area, common_name)
            SELECT id, country_or_area, common_name
            FROM _import_species
            """
        )
        conn.execute(
            """
            INSERT INTO dive_centers (id, name, physical_address, location, website, latitude, longitude)
            SELECT id, name, physical_address, location, website, latitude, longitude
            FROM _import_dive_centers
            """
        )
        conn.execute("DROP TABLE _import_dive_sites")
        conn.execute("DROP TABLE _import_species")
        conn.execute("DROP TABLE _import_dive_centers")
        conn.commit()

    return {"dive_sites": len(sites), "species": len(species), "dive_centers": len(centers)}
