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

Successful password and Google login/signup create persistent sessions that survive browser restarts. Sessions expire after 30 days without a request; each request refreshes the expiration for another 30 days. Logout clears the session. Keep the same `SECRET_KEY` across workers, restarts and deployments to preserve existing sessions; changing it invalidates them. Users with older browser-session cookies receive persistent cookies when they next sign in.

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

## Install Pelagia on a Phone (PWA)

Pelagia can be installed from its HTTPS website and opened from a home-screen icon in a standalone window. Its manifest, PNG icons, Apple touch icon, service worker and offline page are included in the app; no additional package, build step or database migration is needed.

- **iPhone/iPad:** open Pelagia in Safari, choose Share → Add to Home Screen (under More on some versions), leave Open as Web App enabled if shown, then tap Add. Installation guidance is available on the login page and your own profile. The installed app may need a separate sign-in.
- **Android:** use the browser's Install app/Add to Home screen action. An Install Pelagia button appears on the login page and your own profile when the browser supplies an installation prompt.

The service worker caches only explicitly listed public assets and a generic offline screen. Dive pages, account pages, APIs, uploads and external map tiles are not cached. Viewing or saving dives still requires internet access. When the browser reports that it is offline, form submissions are blocked and a notice asks users to keep the page open to preserve their changes. This release does not persist offline dive drafts or sync them later.

Asset cache versions are derived automatically from deployed files. An update notice offers Reload to update; an open form is never automatically reloaded. Users should save their changes before accepting an update.

### Deployment configuration

1. Serve the app at a stable **HTTPS origin**. Render's HTTPS URL or an HTTPS custom domain works. Phone testing also needs HTTPS; plain HTTP on a computer's LAN IP is not equivalent to localhost on the phone.
2. Set **`SESSION_COOKIE_SECURE=true`** on the production service. Keep **`SECRET_KEY`** set to the existing stable, long random value across workers and deployments so installed users stay signed in. Do not rotate a working key just for the PWA rollout.
3. Set **`PELAGIA_PUBLIC_BASE_URL=https://YOUR-DOMAIN`** to the same public origin used for installation and sharing (without a trailing slash). This is the existing sharing setting, not a new PWA variable.
4. If Google sign-in is enabled, retain **`GOOGLE_CLIENT_ID`**, **`GOOGLE_CLIENT_SECRET`**, and **`GOOGLE_REDIRECT_URI=https://YOUR-DOMAIN/auth/google/callback`**. The redirect URI must exactly match the Google OAuth client's authorized URI. No Google configuration change is needed if the domain and callback already match.
5. Redeploy from **`main`** (or allow Render's automatic deployment). Keep the existing Gunicorn command and `/var/data` persistent disk. Database and upload path settings are unchanged; no new environment variables, dependencies or disk storage are required for PWA caching, which lives on each user's device.
6. If a CDN or proxy overrides cache headers, preserve revalidation for **`/service-worker.js`**, **`/manifest.webmanifest`**, and **`/offline.html`**, and honor the `v` query parameter on static asset URLs. These public routes must be reachable without authentication and must not be rewritten to a login page. A standard Render deployment needs no special routing or cache configuration.

After deployment, install from the public URL on a real iPhone and Android phone. Check standalone launch, password/Google login, closing and reopening the app, photo uploads, dive sharing and navigation. After the first online launch, enable airplane mode and navigate/relaunch: the branded offline screen should appear, and an already-open form should block saving. Reconnect and retry. With an installed app open, deploy a subsequent update and confirm the update notice only reloads after the user selects it.

Automated PWA checks are included in the normal Python and JavaScript test suites:

```bash
.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_*.cjs
```

## Sharing Logged Dives

The log/edit form stores max depth and an optional average depth in meters. Both accept decimals and display whole values without `.0`. Average depth starts unset; when supplied it is used for SAC calculation, otherwise SAC uses max depth. Clearing average depth restores that fallback. Logged cards and dive headlines show max depth and duration. Average depth appears in the logged dive’s detailed metrics and share images when available. Existing dives keep an unset average depth and their saved SAC rate.

Unit toggles on the form switch depth/visibility between m and ft, weight between kg and lb, pressure between bar and psi, and both temperatures between °C and °F. Converted values and slider bounds display as whole numbers in either direction. Labels update immediately; optional blanks stay blank. Sliders advance by one displayed unit, with pressure advancing by 10 bar or 100 psi. Pressure sliders stop at 200 bar or 3000 psi; numeric inputs allow up to 300 bar (about 4351 psi). Typed pressures above the slider range remain intact for SAC and saving. SAC continues to use the underlying metric measurements. Submission carries the selected unit for each group, and the server converts to metric before clamping, calculating SAC and saving. Toggle-only round trips preserve full precision even when the form rounds a converted display. Existing dives migrate to REAL pressure, visibility and temperature columns so converted measurements retain their fractional metric values. Logged views and editing defaults remain metric.

Dive type and current type dropdowns accept multiple choices using checkboxes. Existing single selections are retained when editing. Selecting None for current clears other current types and disables current strength; any actual current type enables strength. The API includes `dive_types` and `current_types` arrays while retaining the original single `dive_type` and `current` fields for older clients. Site current summaries count each selected current type once per dive.

Every active dive has a permanent public preview at `/share/dive/<id>`. Owners can open **Share** on a dive card or the full logged dive. Below the branded image, **Copy link** copies the public URL, **Save** downloads the JPEG, and **More** opens their device's share sheet with the URL and “Check out my logged dive at <site name>”. Native sharing needs HTTPS (localhost is also supported); if unavailable, More offers the copy-link alternative. A selectable link appears only when clipboard access fails.

On phones that support file sharing, Save opens the image share sheet so the user can select Save Image or another destination. Browsers cannot silently write to the photo library; the available save options depend on the device. The JPEG is prepared before the Save click to preserve the user activation required by native sharing. Unsupported browsers and file-sharing failures fall back to an attachment download at `/share/dive/<id>/preview.jpg?download=1`; cancellation does not trigger a download. Share destinations control how they display the supplied text and URL.

Visitors see the diver's public username and avatar, dive site, location, date, dive type, center, photos, map, depth and duration. The account gate below uses blurred placeholders; notes, marine life, equipment, conditions, buddies and comments are never sent to anonymous visitors. Signed-in visitors go to `/dive/<id>`, and both password and Google authentication retain this destination. Deleted dives return 404 for both the public page and preview image.

Each link includes Open Graph and Twitter metadata and a generated 1200 × 630 JPEG featuring a dive photo, site, location and stats. If no readable photo is attached, the preview uses the dive site's map at the same zoom as the logged dive, with a location pin and OpenStreetMap attribution. Ocean artwork remains the fallback when coordinates are missing or map tiles are unavailable. Preview titles read “username logged a dive”. Messaging apps control whether and when they show or refresh these previews; copies they have already cached cannot be recalled by deleting a dive. Public pages request no search indexing.

Share maps request only the visible viewport from OpenStreetMap and cache tiles for at least seven days in `map_tiles/` beside the SQLite database. Expired tiles use conditional requests and remain available during outages. `MAP_TILE_CACHE_DIR` and `MAP_TILE_URL` can override the cache directory and raster tile provider through Flask configuration; alternate URLs use `{z}`, `{x}`, and `{y}` placeholders. Rendering requires no browser or new dependency.

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
