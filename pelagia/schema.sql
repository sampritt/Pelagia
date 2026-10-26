PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS certifications (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    google_subject TEXT,
    google_email TEXT,
    profile_photo TEXT,
    bio TEXT,
    explore_location TEXT,
    explore_nearby_json TEXT,
    pressure_unit TEXT NOT NULL DEFAULT 'bar' CHECK (pressure_unit IN ('bar', 'psi')),
    length_unit TEXT NOT NULL DEFAULT 'm' CHECK (length_unit IN ('m', 'ft')),
    temperature_unit TEXT NOT NULL DEFAULT 'c' CHECK (temperature_unit IN ('c', 'f')),
    weight_unit TEXT NOT NULL DEFAULT 'kg' CHECK (weight_unit IN ('kg', 'lb')),
    starting_dive_count INTEGER NOT NULL DEFAULT 0 CHECK (starting_dive_count >= 0),
    certification_id INTEGER REFERENCES certifications(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dive_sites (
    id INTEGER PRIMARY KEY,
    master_site_id TEXT UNIQUE,
    name TEXT NOT NULL,
    country_or_area TEXT,
    country_code TEXT,
    latitude REAL,
    longitude REAL,
    max_depth_m REAL,
    logged_dive_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dive_sites_name ON dive_sites(name);
CREATE INDEX IF NOT EXISTS idx_dive_sites_country ON dive_sites(country_or_area);

CREATE TABLE IF NOT EXISTS dive_site_descriptions (
    dive_site_id INTEGER PRIMARY KEY REFERENCES dive_sites(id) ON DELETE CASCADE,
    description TEXT,
    citations_json TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Pending work and temporary failures must not look like a completed NULL result.
CREATE TABLE IF NOT EXISTS dive_site_description_attempts (
    dive_site_id INTEGER PRIMARY KEY REFERENCES dive_sites(id) ON DELETE CASCADE,
    token TEXT,
    lease_until REAL NOT NULL DEFAULT 0,
    retry_after REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dive_site_obis_species_cache (
    dive_site_id INTEGER PRIMARY KEY REFERENCES dive_sites(id) ON DELETE CASCADE,
    latitude REAL,
    longitude REAL,
    radius_miles REAL NOT NULL,
    start_date TEXT NOT NULL,
    qualifying_taxon_count INTEGER NOT NULL DEFAULT 0,
    model TEXT NOT NULL,
    normalizer_version INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dive_site_obis_species (
    dive_site_id INTEGER NOT NULL REFERENCES dive_sites(id) ON DELETE CASCADE,
    common_name TEXT NOT NULL,
    observation_dates_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (dive_site_id, common_name)
);

CREATE INDEX IF NOT EXISTS idx_dive_site_obis_species_name
ON dive_site_obis_species(common_name);

-- Offline, occurrence-level OBIS catalogue. This stays separate from diver logs
-- and from the on-demand per-site display cache above.
CREATE TABLE IF NOT EXISTS pelagia_species_obis_resolution (
    species_id INTEGER PRIMARY KEY REFERENCES species(id) ON DELETE CASCADE,
    common_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('resolved', 'unresolved', 'skipped')),
    source TEXT NOT NULL,
    note TEXT,
    resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pelagia_species_obis_taxa (
    species_id INTEGER NOT NULL REFERENCES species(id) ON DELETE CASCADE,
    taxon_id INTEGER NOT NULL,
    scientific_name TEXT NOT NULL,
    taxon_rank TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (species_id, taxon_id)
);

CREATE INDEX IF NOT EXISTS idx_pelagia_species_obis_taxa_taxon
ON pelagia_species_obis_taxa(taxon_id);

CREATE TABLE IF NOT EXISTS obis_occurrences (
    obis_id TEXT PRIMARY KEY,
    occurrence_id TEXT,
    queried_taxon_id INTEGER NOT NULL,
    scientific_name TEXT,
    event_date TEXT,
    decimal_latitude REAL NOT NULL,
    decimal_longitude REAL NOT NULL,
    coordinate_uncertainty_m REAL NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obis_occurrences_taxon
ON obis_occurrences(queried_taxon_id);

CREATE TABLE IF NOT EXISTS obis_occurrence_queries (
    obis_id TEXT NOT NULL REFERENCES obis_occurrences(obis_id) ON DELETE CASCADE,
    taxon_id INTEGER NOT NULL,
    PRIMARY KEY (obis_id, taxon_id)
);

CREATE TABLE IF NOT EXISTS dive_site_obis_occurrences (
    dive_site_id INTEGER NOT NULL REFERENCES dive_sites(id) ON DELETE CASCADE,
    species_id INTEGER NOT NULL REFERENCES species(id) ON DELETE CASCADE,
    obis_id TEXT NOT NULL REFERENCES obis_occurrences(obis_id) ON DELETE CASCADE,
    distance_meters REAL NOT NULL,
    PRIMARY KEY (dive_site_id, species_id, obis_id)
);

CREATE INDEX IF NOT EXISTS idx_dive_site_obis_occurrences_species
ON dive_site_obis_occurrences(species_id, dive_site_id);

CREATE TABLE IF NOT EXISTS obis_taxon_ingestion (
    taxon_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete')),
    after_cursor TEXT,
    pages INTEGER NOT NULL DEFAULT 0,
    records_seen INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (taxon_id, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS dive_site_obis_species_attempts (
    dive_site_id INTEGER PRIMARY KEY REFERENCES dive_sites(id) ON DELETE CASCADE,
    token TEXT,
    lease_until REAL NOT NULL DEFAULT 0,
    retry_after REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS species (
    id INTEGER PRIMARY KEY,
    country_or_area TEXT NOT NULL,
    common_name TEXT NOT NULL,
    UNIQUE(country_or_area, common_name)
);

CREATE INDEX IF NOT EXISTS idx_species_country ON species(country_or_area);
CREATE INDEX IF NOT EXISTS idx_species_common_name ON species(common_name);

CREATE TABLE IF NOT EXISTS site_species (
    id INTEGER PRIMARY KEY,
    dive_site_name TEXT NOT NULL,
    common_name TEXT NOT NULL,
    UNIQUE(dive_site_name, common_name)
);

CREATE INDEX IF NOT EXISTS idx_site_species_site ON site_species(dive_site_name);
CREATE INDEX IF NOT EXISTS idx_site_species_common_name ON site_species(common_name);

CREATE TABLE IF NOT EXISTS dive_centers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    physical_address TEXT,
    location TEXT,
    website TEXT,
    latitude REAL,
    longitude REAL
);

CREATE INDEX IF NOT EXISTS idx_dive_centers_name ON dive_centers(name);
CREATE INDEX IF NOT EXISTS idx_dive_centers_location ON dive_centers(location);

CREATE TABLE IF NOT EXISTS dives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    buddy_user_id INTEGER,
    dive_site_id INTEGER,
    dive_center_id INTEGER,
    dive_center_name TEXT,
    date TEXT NOT NULL,
    site_name TEXT NOT NULL,
    country_or_area TEXT,
    latitude REAL,
    longitude REAL,
    depth_m REAL NOT NULL DEFAULT 0,
    average_depth_m REAL,
    duration_min INTEGER NOT NULL DEFAULT 0,
    weight_kg REAL,
    starting_pressure_bar REAL,
    ending_pressure_bar REAL,
    sac_rate_l_min REAL,
    exposure TEXT,
    visibility_m REAL,
    air_temp_c REAL,
    water_temp_c REAL,
    water_type TEXT NOT NULL DEFAULT 'none' CHECK (water_type IN ('none', 'fresh', 'salt')),
    gas_mix TEXT NOT NULL DEFAULT 'Air',
    oxygen_pct INTEGER CHECK (oxygen_pct BETWEEN 0 AND 100),
    helium_pct INTEGER CHECK (helium_pct BETWEEN 0 AND 100 AND oxygen_pct + helium_pct <= 100),
    dive_type TEXT NOT NULL DEFAULT 'open water',
    dive_types_json TEXT,
    current TEXT NOT NULL DEFAULT 'none',
    current_types_json TEXT,
    current_strength TEXT NOT NULL DEFAULT 'none',
    effort_rating INTEGER,
    weight_rating INTEGER,
    temperature_rating INTEGER,
    notes TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(buddy_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(dive_site_id) REFERENCES dive_sites(id) ON DELETE SET NULL,
    FOREIGN KEY(dive_center_id) REFERENCES dive_centers(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_dives_user_created ON dives(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dives_created ON dives(created_at DESC);

CREATE TABLE IF NOT EXISTS dive_computer_data (
    dive_id INTEGER PRIMARY KEY REFERENCES dives(id) ON DELETE CASCADE,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dive_species (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dive_id INTEGER NOT NULL,
    common_name TEXT NOT NULL,
    FOREIGN KEY(dive_id) REFERENCES dives(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dive_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dive_id) REFERENCES dives(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS likes (
    dive_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(dive_id, user_id),
    FOREIGN KEY(dive_id) REFERENCES dives(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dive_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dive_id) REFERENCES dives(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comments_dive ON comments(dive_id, created_at);

CREATE TABLE IF NOT EXISTS dive_center_likes (
    dive_center_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(dive_center_id, user_id),
    FOREIGN KEY(dive_center_id) REFERENCES dive_centers(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dive_center_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dive_center_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dive_center_id) REFERENCES dive_centers(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dive_center_comments_center ON dive_center_comments(dive_center_id, created_at);

CREATE TABLE IF NOT EXISTS dive_site_likes (
    dive_site_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(dive_site_id, user_id),
    FOREIGN KEY(dive_site_id) REFERENCES dive_sites(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dive_site_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dive_site_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(dive_site_id) REFERENCES dive_sites(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dive_site_comments_site ON dive_site_comments(dive_site_id, created_at);

CREATE TABLE IF NOT EXISTS dive_site_water_classifications (
    dive_site_id INTEGER PRIMARY KEY REFERENCES dive_sites(id) ON DELETE CASCADE,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    feature TEXT,
    classified_at TEXT,
    lease_token TEXT,
    lease_until REAL NOT NULL DEFAULT 0,
    retry_after REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS marine_forecast_cache (
    site_id INTEGER PRIMARY KEY REFERENCES dive_sites(id) ON DELETE CASCADE,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    payload TEXT,
    fetched_at REAL NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_until REAL NOT NULL DEFAULT 0,
    retry_after REAL NOT NULL DEFAULT 0
);
