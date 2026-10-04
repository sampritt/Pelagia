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

For Render, attach a persistent disk at `/var/data`. No database or upload-path environment variables are required there. Configure `SECRET_KEY` and set `SESSION_COOKIE_SECURE=true` for HTTPS deployments.

- `data_sources.dive_sites_csv`: dive-site master CSV path
- `data_sources.species_csv`: dive-site marine-life matches CSV path
- `data_sources.dive_centers_csv`: dive-center CSV path

On first app startup, Pelagia initializes SQLite and imports reference data from the configured CSVs with pandas. Application data, reference data, uploaded-photo paths, likes, and comments are stored in SQLite. Uploaded image files are stored beneath the configured upload directory and served from `/uploads/`.

## Entry Points

- `wsgi.py`: Gunicorn entrypoint
- `pelagia/__init__.py`: Flask app factory and routes
- `pelagia/schema.sql`: SQLite schema
- `pelagia/importer.py`: pandas CSV import

## Sharing Logged Dives

Every active dive has a permanent public preview at `/share/dive/<id>`. Owners can open **Share** on a dive card or the full logged dive to copy the link, view the preview, or open their device's share sheet in browsers that support the Web Share API. Native sharing needs HTTPS (localhost is also supported); clipboard or app sharing failures leave a selectable link available.

Visitors see the diver's public username and avatar, dive site, location, date, dive type, center, photos, map, depth and duration. The account gate below uses blurred placeholders; notes, marine life, equipment, conditions, buddies and comments are never sent to anonymous visitors. Signed-in visitors go to `/dive/<id>`, and both password and Google authentication retain this destination. Deleted dives return 404 for both the public page and preview image.

Each link includes Open Graph and Twitter metadata and a generated 1200 × 630 JPEG featuring a dive photo (or the ocean artwork), site, location and stats. Preview titles read “username logged a dive”. Messaging apps control whether and when they show or refresh these previews; copies they have already cached cannot be recalled by deleting a dive. Public pages request no search indexing.

Set `PELAGIA_PUBLIC_BASE_URL` to your public HTTPS origin in production, for example `https://YOUR-DOMAIN`. This keeps copied links and image metadata correct behind a reverse proxy. Without this setting, the app uses the request origin, which is convenient for local development. Sharing needs no database migration or external image service.

Run the sharing and authentication tests with the Python command below, plus the JavaScript checks:

```bash
node --test tests/test_*.cjs
```

## Google Sign-In (Optional)

Username/password signup and login remain available. The Google button appears when both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are configured; without them, Google routes are disabled.

1. In [Google Auth Platform](https://console.cloud.google.com/auth/overview), create/select a project and configure its branding and audience. For a public app, choose an external audience; while in testing, add the Google accounts that will test sign-in.
2. Create an OAuth client of type **Web application**. Add the exact authorized redirect URI for each environment:
   - Local: `http://127.0.0.1:8010/auth/google/callback`
   - Production: `https://YOUR-DOMAIN/auth/google/callback`
3. Install the updated requirements and configure these environment variables (keep the secret out of source control):

```bash
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your-client-secret"
export GOOGLE_REDIRECT_URI="http://127.0.0.1:8010/auth/google/callback"
```

On Render, add those variables to the service environment, using the production HTTPS callback for `GOOGLE_REDIRECT_URI`. This explicit URL prevents a proxy's internal HTTP address from becoming the callback. Also set a long random `SECRET_KEY` and `SESSION_COOKIE_SECURE=true`. Restart/redeploy after changing configuration. Use `SESSION_COOKIE_SECURE=false` for local HTTP development. If the redirect URI is omitted, the app generates it from the request URL; an explicit value is recommended in production.

Google authentication uses [Authlib's OpenID Connect integration](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html) with state, nonce and PKCE checks. Only `openid email` scopes are requested, and provider tokens are not persisted. Identities are matched by Google's stable `sub` ID, [as Google recommends](https://developers.google.com/identity/openid-connect/openid-connect), rather than by email or public username.

New Google users choose a unique public username before an account is created. Their Google email is stored privately and is not returned by profile or user APIs. Existing users should log in with their username/password, then select **Link Google account** on their own profile. Linking preserves the user ID, dives and password login. Accounts are never automatically merged, and a Google account can belong to only one Pelagia account.

Startup adds nullable `google_subject`/`google_email` columns and a unique identity index to existing SQLite databases, preserving existing rows and relationships. Google-only accounts use an empty `password_hash` as a disabled-password marker; the password login explicitly rejects these accounts. This avoids rebuilding the existing users table. Back up production SQLite using your normal deployment procedure before rolling out schema changes.

Run the authentication and existing app tests with:

```bash
.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The tests exercise signed OpenID Connect tokens with local discovery/JWKS data and a mocked token exchange. Before enabling sign-in for everyone, complete a real Google sign-in, logout/re-login, and existing-account link using the deployed callback URL.
