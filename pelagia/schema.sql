PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    profile_photo TEXT,
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
    max_depth_m REAL
);

CREATE INDEX IF NOT EXISTS idx_dive_sites_name ON dive_sites(name);
CREATE INDEX IF NOT EXISTS idx_dive_sites_country ON dive_sites(country_or_area);

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
    dive_site_id INTEGER,
    dive_center_id INTEGER,
    dive_center_name TEXT,
    date TEXT NOT NULL,
    site_name TEXT NOT NULL,
    country_or_area TEXT,
    latitude REAL,
    longitude REAL,
    depth_ft INTEGER NOT NULL DEFAULT 0,
    duration_min INTEGER NOT NULL DEFAULT 0,
    weight_lbs INTEGER NOT NULL DEFAULT 0,
    exposure TEXT NOT NULL,
    visibility_ft INTEGER NOT NULL DEFAULT 0,
    air_temp_degrees INTEGER NOT NULL DEFAULT 0,
    water_temp_degrees INTEGER NOT NULL DEFAULT 0,
    dive_type TEXT NOT NULL DEFAULT 'open water',
    current TEXT NOT NULL DEFAULT 'none',
    notes TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(dive_site_id) REFERENCES dive_sites(id) ON DELETE SET NULL,
    FOREIGN KEY(dive_center_id) REFERENCES dive_centers(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_dives_user_created ON dives(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dives_created ON dives(created_at DESC);

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
