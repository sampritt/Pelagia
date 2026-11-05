"""Replace the dive-site catalogue once per CSV version during app startup."""
import csv
import hashlib
import io
import math

from .importer import resolve_path


def _number(value):
    if not value or value.strip().casefold() in {'na', 'nan'}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Non-finite coordinate or depth in dive-site catalogue')
    return number


def apply_catalog(db, csv_path):
    content = csv_path.read_bytes()
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
    # Only the cleaned rollout catalogue carries stable import IDs.
    if 'legacy_import_id' not in (reader.fieldnames or []):
        return False
    required = {'master_site_id', 'dive_site_name', 'country_or_area', 'country_code',
                'latitude', 'longitude', 'max_depth_m'}
    if not required <= set(reader.fieldnames or []):
        raise ValueError('Dive-site catalogue is missing required columns')
    incoming = []
    ids, master_ids = set(), set()
    for index, row in enumerate(reader, 1):
        site_id = int(row.get('legacy_import_id') or index)
        master_id, name = row['master_site_id'].strip(), row['dive_site_name'].strip()
        if site_id <= 0 or site_id in ids or not master_id or master_id in master_ids or not name:
            raise ValueError('Invalid or duplicate identity in dive-site catalogue')
        latitude, longitude = _number(row['latitude']), _number(row['longitude'])
        if latitude is not None and not -90 <= latitude <= 90:
            raise ValueError('Invalid dive-site latitude')
        if longitude is not None and not -180 <= longitude <= 180:
            raise ValueError('Invalid dive-site longitude')
        ids.add(site_id); master_ids.add(master_id)
        incoming.append((site_id, master_id, name, row['country_or_area'], row['country_code'],
                         latitude, longitude, _number(row['max_depth_m'])))
    if not incoming:
        raise ValueError('Refusing to replace dive sites with an empty catalogue')
    digest = hashlib.sha256(b'dive-site-catalog-v1\0' + content).hexdigest()
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS reference_catalog_versions (name TEXT PRIMARY KEY, digest TEXT NOT NULL)')
        previous = db.execute("SELECT digest FROM reference_catalog_versions WHERE name='dive_sites'").fetchone()
        count = db.execute('SELECT COUNT(*) FROM dive_sites').fetchone()[0]
        if previous and previous[0] == digest and count == len(incoming):
            return False
        # Foreign keys detach existing dive logs and clear dependent site data.
        # Logged names, locations, coordinates, and other dive details remain.
        db.execute('DELETE FROM dive_sites')
        db.executemany('''INSERT INTO dive_sites
            (id, master_site_id, name, country_or_area, country_code, latitude, longitude, max_depth_m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', incoming)
        db.execute("INSERT OR REPLACE INTO reference_catalog_versions VALUES ('dive_sites', ?)", (digest,))
    return True


def apply(db, app):
    source = app.config['PELAGIA_LOCAL_CONFIG']['data_sources']['dive_sites_csv']
    return apply_catalog(db, resolve_path(app.config['PELAGIA_CONFIG_PATH'], source))
