# Pelagia

Pelagia is a Flask/Gunicorn MVP for logging and sharing scuba dives with local SQLite persistence.

## Run Locally

```bash
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt
.venv312/bin/gunicorn --bind 127.0.0.1:8010 --workers 2 wsgi:app
```

Open `http://127.0.0.1:8010`.

## Configuration

Pelagia defaults to persistent Render disk paths:

- SQLite database: `/var/data/pelagia.sqlite3`
- Photo uploads: `/var/data/uploads`

Override those paths for local development:

```bash
export PELAGIA_DATABASE_PATH="$PWD/instance/pelagia.sqlite3"
export PELAGIA_UPLOAD_FOLDER="$PWD/pelagia/static/uploads"
```

Set `SECRET_KEY` to a long random value in production. Local development falls back to the value in `app_config.json`.

For Render, attach a persistent disk at `/var/data`. No database or upload-path environment variables are required there; only configure `SECRET_KEY`.

- `data_sources.dive_sites_csv`: dive-site master CSV path
- `data_sources.species_csv`: dive-site marine-life matches CSV path
- `data_sources.dive_centers_csv`: dive-center CSV path

On first app startup, Pelagia initializes SQLite and imports reference data from the configured CSVs with pandas. Application data, reference data, uploaded-photo paths, likes, and comments are stored in SQLite. Uploaded image files are stored beneath the configured upload directory and served from `/uploads/`.

## Entry Points

- `wsgi.py`: Gunicorn entrypoint
- `pelagia/__init__.py`: Flask app factory and routes
- `pelagia/schema.sql`: SQLite schema
- `pelagia/importer.py`: pandas CSV import
