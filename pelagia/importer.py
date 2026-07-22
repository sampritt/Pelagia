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

    missing_species = {"dive_site_name", "species_name"} - set(species_raw.columns)
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

    site_species = species_raw[["dive_site_name", "species_name"]].dropna().copy()
    site_species["dive_site_name"] = site_species["dive_site_name"].astype(str).str.strip()
    site_species["common_name"] = site_species["species_name"].astype(str).str.strip()
    site_species = site_species[(site_species["dive_site_name"] != "") & (site_species["common_name"] != "")]
    site_species = site_species.drop_duplicates(["dive_site_name", "common_name"]).copy()
    site_species["id"] = range(1, len(site_species) + 1)
    site_species = site_species[["id", "dive_site_name", "common_name"]]

    species = site_species[["common_name"]].drop_duplicates().copy()
    species["country_or_area"] = "Global"
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
        staging_tables = (
            "_import_dive_sites",
            "_import_species",
            "_import_site_species",
            "_import_dive_centers",
        )
        for table_name in staging_tables:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        try:
            sites.to_sql("_import_dive_sites", conn, if_exists="replace", index=False)
            species.to_sql("_import_species", conn, if_exists="replace", index=False)
            site_species.to_sql("_import_site_species", conn, if_exists="replace", index=False)
            centers.to_sql("_import_dive_centers", conn, if_exists="replace", index=False)
            conn.execute("CREATE INDEX idx_import_dive_sites_id ON _import_dive_sites(id)")
            conn.execute("CREATE INDEX idx_import_dive_sites_master_site_id ON _import_dive_sites(master_site_id)")
            conn.execute("CREATE INDEX idx_import_species_id ON _import_species(id)")
            conn.execute("CREATE INDEX idx_import_site_species_id ON _import_site_species(id)")
            conn.execute("CREATE INDEX idx_import_dive_centers_id ON _import_dive_centers(id)")
            conn.execute("DELETE FROM species")
            conn.execute("DELETE FROM site_species")
            conn.execute(
                """
                UPDATE dive_sites
                SET
                    name = (
                        SELECT name FROM _import_dive_sites
                        WHERE _import_dive_sites.master_site_id = dive_sites.master_site_id
                    ),
                    country_or_area = (
                        SELECT country_or_area FROM _import_dive_sites
                        WHERE _import_dive_sites.master_site_id = dive_sites.master_site_id
                    ),
                    country_code = (
                        SELECT country_code FROM _import_dive_sites
                        WHERE _import_dive_sites.master_site_id = dive_sites.master_site_id
                    ),
                    latitude = (
                        SELECT latitude FROM _import_dive_sites
                        WHERE _import_dive_sites.master_site_id = dive_sites.master_site_id
                    ),
                    longitude = (
                        SELECT longitude FROM _import_dive_sites
                        WHERE _import_dive_sites.master_site_id = dive_sites.master_site_id
                    ),
                    max_depth_m = (
                        SELECT max_depth_m FROM _import_dive_sites
                        WHERE _import_dive_sites.master_site_id = dive_sites.master_site_id
                    )
                WHERE master_site_id IN (SELECT master_site_id FROM _import_dive_sites)
                """
            )
            conn.execute(
                """
                UPDATE dive_sites
                SET
                    master_site_id = (SELECT master_site_id FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id),
                    name = (SELECT name FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id),
                    country_or_area = (SELECT country_or_area FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id),
                    country_code = (SELECT country_code FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id),
                    latitude = (SELECT latitude FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id),
                    longitude = (SELECT longitude FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id),
                    max_depth_m = (SELECT max_depth_m FROM _import_dive_sites WHERE _import_dive_sites.id = dive_sites.id)
                WHERE id IN (SELECT id FROM _import_dive_sites)
                    AND NOT EXISTS (
                        SELECT 1
                        FROM _import_dive_sites imported
                        JOIN dive_sites existing ON existing.master_site_id = imported.master_site_id
                        WHERE imported.id = dive_sites.id
                            AND existing.id != dive_sites.id
                    )
                """
            )
            conn.execute(
                """
                INSERT INTO dive_sites (
                    id, master_site_id, name, country_or_area, country_code,
                    latitude, longitude, max_depth_m
                )
                SELECT
                    imported.id,
                    imported.master_site_id,
                    imported.name,
                    imported.country_or_area,
                    imported.country_code,
                    imported.latitude,
                    imported.longitude,
                    imported.max_depth_m
                FROM _import_dive_sites imported
                WHERE NOT EXISTS (
                        SELECT 1 FROM dive_sites existing_by_id
                        WHERE existing_by_id.id = imported.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM dive_sites existing_by_master
                        WHERE existing_by_master.master_site_id = imported.master_site_id
                    )
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
                INSERT INTO site_species (id, dive_site_name, common_name)
                SELECT id, dive_site_name, common_name
                FROM _import_site_species
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO dive_centers (id, name, physical_address, location, website, latitude, longitude)
                SELECT id, name, physical_address, location, website, latitude, longitude
                FROM _import_dive_centers
                """
            )
            conn.execute(
                """
                UPDATE dive_centers
                SET
                    name = (SELECT name FROM _import_dive_centers WHERE _import_dive_centers.id = dive_centers.id),
                    physical_address = (
                        SELECT physical_address FROM _import_dive_centers WHERE _import_dive_centers.id = dive_centers.id
                    ),
                    location = (SELECT location FROM _import_dive_centers WHERE _import_dive_centers.id = dive_centers.id),
                    website = (SELECT website FROM _import_dive_centers WHERE _import_dive_centers.id = dive_centers.id),
                    latitude = (SELECT latitude FROM _import_dive_centers WHERE _import_dive_centers.id = dive_centers.id),
                    longitude = (SELECT longitude FROM _import_dive_centers WHERE _import_dive_centers.id = dive_centers.id)
                WHERE id IN (SELECT id FROM _import_dive_centers)
                """
            )
            for table_name in staging_tables:
                conn.execute(f"DROP TABLE {table_name}")
            conn.commit()
        except Exception:
            conn.rollback()
            for table_name in staging_tables:
                conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.commit()
            raise

    return {"dive_sites": len(sites), "species": len(species), "site_species": len(site_species), "dive_centers": len(centers)}
