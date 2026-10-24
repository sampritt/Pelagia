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

Successful Google login/signup create persistent sessions that survive browser restarts. Sessions expire after 30 days without a request; each request refreshes the expiration for another 30 days. Logout clears the session. Keep the same `SECRET_KEY` across workers, restarts and deployments to preserve existing sessions; changing it invalidates them. Users with older browser-session cookies receive persistent cookies when they next sign in.

For Render, attach a persistent disk at `/var/data`. No database or upload-path environment variables are required there. Configure `SECRET_KEY` and set `SESSION_COOKIE_SECURE=true` for HTTPS deployments.

- `data_sources.dive_sites_csv`: dive-site master CSV path
- `data_sources.species_csv`: dive-site marine-life matches CSV path
- `data_sources.dive_centers_csv`: dive-center CSV path

On first app startup, Pelagia initializes SQLite and imports reference data from the configured CSVs with pandas. Application data, reference data, uploaded-photo paths, likes, and comments are stored in SQLite. Uploaded image files are stored beneath the configured upload directory and served from `/uploads/`.

## Dive site descriptions

Set `OPENAI_API_KEY` in the server environment to enable on-demand dive site summaries. The key stays server-side; do not commit it. Generation uses `gpt-5.6-luna` through the Responses API with one required, low-context web search, low reasoning effort, and bounded output and network timeouts. There are no automatic upstream retries or model substitutions. Search tool calls and model tokens are billed to the key's OpenAI account.

On opening a dive site, Pelagia reads the persistent SQLite `dive_site_descriptions` table. A cached summary appears beneath the name and location with clickable source citations. A site without a cache row loads the rest of its page immediately, requests a summary, and shows the shared two-line skeleton after 160 ms. The search prompt requires sources matching both the site's name and location, using coordinates when available, and limits the summary to 1–2 sentences and 70 words.

The table starts empty; reference CSV descriptions are not imported. A completed search with no confidently verified information saves a row with a **NULL description**. That row renders nothing and permanently prevents automatic generation for the site. Successful summaries also never expire automatically. To deliberately research a completed site again, an operator must remove its cache row from SQLite.

Timeouts, rate limits, missing/invalid credentials, and malformed or incomplete responses do **not** create NULL results. They render no description and allow another visit to retry after a five-minute cooldown. A separate coordination table uses 60-second claims to prevent duplicate generation across Gunicorn workers, without holding a database write transaction during the API call. The browser checks pending requests every two seconds for at most 35 seconds and stops when leaving the page. Responses require login and a same-origin fetch header and are never browser/PWA cached.

Tests mock OpenAI without making billable calls: `.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'` and `node --test tests/*.cjs`.

## Entry Points

- `wsgi.py`: Gunicorn entrypoint
- `pelagia/__init__.py`: Flask app factory and routes
- `pelagia/schema.sql`: SQLite schema
- `pelagia/importer.py`: pandas CSV import

## The Dive Brief

The main feed starts with a compact daily newsletter card, an expand/collapse chevron and estimated reading time. Read the brief opens a full-screen Markdown reader with a persistent Feed back button. The footer's Back to feed link, Escape and browser Back also return to the feed. The feed stays fixed while the reader scrolls, and returning restores its position and collapses the preview. Touch and mouse interactions keep focus without drawing keyboard focus rings; keyboard navigation retains visible focus indicators. Touch gestures, trackpad scrolling, text selection and pinch zoom keep their native browser behavior; the reader has no custom swipe navigation. Reduced-motion preferences disable animated transitions. Editions also have signed-in deep links at `/brief/YYYY-MM-DD`; returning after refreshing the reader consumes its existing history entry. The reader supports headings, emphasis, links, lists, blockquotes, code and tables, with escaped raw HTML and safe link protocols. External sources open in a separate tab.

Editions live on disk as `the_dive_brief_YYYY-MM-DD.md`. `PELAGIA_DIVE_BRIEF_DIR` defaults to `dive_briefs/` beside the SQLite database (`/var/data/dive_briefs` in production). The filename and feed selection use **today's publication date** in `PELAGIA_DIVE_BRIEF_TIMEZONE` (default `America/New_York`); the digest can cover T−1 news. File changes are picked up without restarting. The feed shows the brief only when today's valid edition exists. There is no sample, previous-day, or latest-edition fallback. Historical signed-in deep links still work; future editions remain unavailable.

The feed card starts collapsed, showing its icon, title and date. Tap or click the compact header (or use Enter/Space) to reveal the summary and Read the brief link. Returning from the full reader collapses it again, and every feed load starts from the compact state.

The supplied September 4 example in `data/dive_briefs/` is a format reference only. `PELAGIA_DIVE_BRIEF_SAMPLE_PATH` is retired and ignored.

### Upload API

Send `POST /api/dive-brief` with `Authorization: Bearer <API_KEY>` and the Markdown file as the raw UTF-8 request body (`Content-Type: text/markdown`; `text/plain` is also accepted). Use HTTPS in production. The API does not use login cookies, query-string credentials, client filenames or client-supplied publication dates.

Provision a key on the app host, using the same database/path configuration as the running app:

```bash
.venv312/bin/flask --app wsgi create-dive-brief-key
```

Copy the printed key once. The command generates a random 256-bit secret and stores only its SHA-256 digest in `dive_brief_api_key.sha256` beside the database (mode `0600`). `PELAGIA_DIVE_BRIEF_API_KEY_FILE` overrides that path. All workers read that file per upload, so `create-dive-brief-key --rotate` revokes the old key immediately without restarting. Creating a second key without `--rotate` fails.

For managed deployments, set the secret environment variable **`PELAGIA_DIVE_BRIEF_API_KEY_SHA256`** to the generated digest instead; it takes precedence over the file. Keep the raw API key in the publishing client's secret store. Environment-based rotation requires updating the digest and restarting/redeploying all workers. The CLI refuses to generate a file key while an environment digest takes precedence. Never commit keys or credential files. Missing or invalid server authentication configuration disables uploads with HTTP 503.

```bash
# Set PELAGIA_DIVE_BRIEF_API_KEY in your publishing environment.
curl --fail-with-body --request POST 'https://YOUR-DOMAIN/api/dive-brief' \
  --header "Authorization: Bearer $PELAGIA_DIVE_BRIEF_API_KEY" \
  --header 'Content-Type: text/markdown; charset=utf-8' \
  --data-binary @'/path/to/edition.md'
```

The written date inside the Markdown **must match today's publication date**. A mismatched date returns 422 with `expected_date`; the server does not silently rewrite editorial content. Valid uploads are atomically saved as `the_dive_brief_YYYY-MM-DD.md` with mode `0600`, replacing that day's previous edition. An invalid upload or failed replacement leaves the existing edition intact. A successful upload appears on the next feed request, without restarting the app. The authenticated reader remains signed-in only.

Responses are JSON with `Cache-Control: no-store`: 201 includes `date`, `filename`, `url` and a `Location` header; 401 means an absent/invalid API key; 413 means the 256 KiB payload limit was exceeded; 415 means unsupported media type/charset; 422 means invalid UTF-8 or Markdown structure/date; 503 means authentication or disk storage is unavailable. Multipart uploads are not accepted; use `--data-binary` as shown above.

Use this Markdown structure (the written date must match the filename):

```markdown
# The Dive Brief

**Friday, September 4, 2026**

**A one-sentence summary of today's ocean news.**

---

## THE BIG STORY

### A story headline

Story paragraphs, with **bold** and *italic* text as needed.

[Read more](https://example.com/source)
```

Repeat the section heading, story headline, paragraphs and source link for each story. Horizontal rules between sections are optional. Install the updated `requirements.txt` for the Mistune Markdown renderer.

## Terms of Use and Privacy Policy

Profile → Settings includes Terms of Use (`/terms`) and Privacy Policy (`/privacy`). Both pages are also accessible without signing in and linked from the authentication screen, including Google signup.

Set `PELAGIA_OPERATOR_NAME` to the person or entity operating the app and `PELAGIA_CONTACT_EMAIL` to a monitored public email address. Defaults are “Pelagia” and `info@pelagiadivelog.com`. The contact address appears as a mail link in the Questions section of both legal pages. Supply the actual operator name before public release. Hosting/log retention and any deployment-specific data practices should also be verified by the operator.

The short documents adapt the account security, availability, third-party services, security, and update boilerplate from [App Privacy Policy Generator’s Privacy Policy and Terms & Conditions templates](https://mobile-privacy.github.io/generator/) (accessed October 16, 2026). Its disclaimer expressly permits using the templates when compiling your own policy. App-specific collection, sharing, cookies, and retention disclosures follow this repository’s implementation. The templates were shortened and do not assert jurisdiction-specific compliance, a governing law, or an unverified business identity. They are template-based drafts, not a legal compliance certification.

## Install Pelagia on a Phone (PWA)

Pelagia can be installed from its HTTPS website and opened from a home-screen icon in a standalone window. Its manifest, PNG icons, Apple touch icon, service worker and offline page are included in the app; no additional package, build step or database migration is needed.

- **iPhone/iPad:** open Pelagia in Safari, choose Share → Add to Home Screen (under More on some versions), leave Open as Web App enabled if shown, then tap Add. Installation guidance is available on the login page and your own profile. The installed app may need a separate sign-in.
- **Android:** use the browser's Install app/Add to Home screen action. Your profile also offers native installation when supported.

The service worker caches only explicitly listed public assets and a generic offline screen. Dive pages, account pages, APIs, uploads and external map tiles are not cached. Viewing or saving dives still requires internet access. When the browser reports that it is offline, form submissions are blocked and a notice asks users to keep the page open to preserve their changes. This release does not persist offline dive drafts or sync them later.

Asset cache versions are derived automatically from deployed files. An update notice offers Reload to update; an open form is never automatically reloaded. Users should save their changes before accepting an update.

### Deployment configuration

1. Serve the app at a stable **HTTPS origin**. Render's HTTPS URL or an HTTPS custom domain works. Phone testing also needs HTTPS; plain HTTP on a computer's LAN IP is not equivalent to localhost on the phone.
2. Set **`SESSION_COOKIE_SECURE=true`** on the production service. Keep **`SECRET_KEY`** set to the existing stable, long random value across workers and deployments so installed users stay signed in. Do not rotate a working key just for the PWA rollout.
3. Set **`PELAGIA_PUBLIC_BASE_URL=https://YOUR-DOMAIN`** to the same public origin used for installation and sharing (without a trailing slash). This is the existing sharing setting, not a new PWA variable.
4. If Google sign-in is enabled, retain **`GOOGLE_CLIENT_ID`**, **`GOOGLE_CLIENT_SECRET`**, and **`GOOGLE_REDIRECT_URI=https://YOUR-DOMAIN/auth/google/callback`**. The redirect URI must exactly match the Google OAuth client's authorized URI. No Google configuration change is needed if the domain and callback already match.
5. Redeploy from **`main`** (or allow Render's automatic deployment). Keep the existing Gunicorn command and `/var/data` persistent disk. Database and upload path settings are unchanged; no new environment variables, dependencies or disk storage are required for PWA caching, which lives on each user's device.
6. If a CDN or proxy overrides cache headers, preserve revalidation for **`/service-worker.js`**, **`/manifest.webmanifest`**, and **`/offline.html`**, and honor the `v` query parameter on static asset URLs. These public routes must be reachable without authentication and must not be rewritten to a login page. A standard Render deployment needs no special routing or cache configuration.

After deployment, install from the public URL on a real iPhone and Android phone. Check standalone launch, Google login, closing and reopening the app, photo uploads, dive sharing and navigation. After the first online launch, enable airplane mode and navigate/relaunch: the branded offline screen should appear, and an already-open form should block saving. Reconnect and retry. With an installed app open, deploy a subsequent update and confirm the update notice only reloads after the user selects it.

Automated PWA checks are included in the normal Python and JavaScript test suites:

```bash
.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_*.cjs
```

## Loading feedback

Pelagia shares one skeleton system across page navigation, autocomplete searches (global search, dive sites, centers, buddies, marine life and certifications), species suggestions, photos, map tiles, share previews and save/like/comment actions. Navigation placeholders follow the destination's feed, profile, detail, form or authentication layout while the navigation bars remain available. Already-rendered server content and instant local interactions appear immediately.

Placeholders appear only after 160 ms and clear as soon as their own work finishes. Search input cancels stale requests; empty and failed searches show useful messages. Loading respects reduced-motion preferences, announces busy states to assistive technology, restores pages after history navigation, and releases stalled navigation or media states after 15 seconds. Native submissions preserve the form while showing feedback on the submit button. The loading script participates in the versioned public PWA asset cache.

Behavior checks run with `node --test tests/test_loading.cjs` alongside the existing JavaScript suite.

## Sharing Logged Dives

The log/edit form stores max depth and an optional average depth in meters. Both accept decimals and display whole values without `.0`. Average depth starts unset; when supplied it is used for SAC calculation, otherwise SAC uses max depth. Clearing average depth restores that fallback. Logged cards and dive headlines show max depth and duration. Average depth appears in the logged dive’s detailed metrics and full share image when available. Existing dives keep an unset average depth and their saved SAC rate.

Unit toggles on the form switch depth/visibility between m and ft, weight between kg and lb, pressure between bar and psi, and both temperatures between °C and °F. Converted values and slider bounds display as whole numbers in either direction, with weight displayed in half units. Visibility advances by 1 m or 5 ft, and visibility displayed in feet rounds to the nearest 5 throughout the app. Labels update immediately; optional blanks stay blank. Other sliders advance by one displayed unit, with pressure advancing by 10 bar or 100 psi. Pressure sliders stop at 200 bar or 3000 psi; numeric inputs allow up to 300 bar (about 4351 psi). Full-cylinder pressure labels pair 200 bar with 3000 psi in the form and logged views, while stored measurements, submission conversions and SAC retain the exact physical conversion. Typed pressures above the slider range remain intact for SAC and saving. Submission carries the selected unit for each group, and the server converts to metric before clamping, calculating SAC and saving. Toggle-only round trips preserve full precision even when the form rounds a converted display. Existing dives migrate to REAL pressure, visibility and temperature columns so converted measurements retain their fractional metric values. Logged views use the viewer’s saved unit preferences, and new/edit forms initialize their toggles from those preferences.

Conditions includes a Water type control immediately after water temperature. Like Exposure, its heading starts at `-` (unset) with neither option selected, and the only two buttons are Fresh and Salt. The selection is saved with the dive, restored on edit, and shown in the detailed conditions. Existing dives default to unset.

Dive type and current type dropdowns accept multiple choices using checkboxes. Existing single selections are retained when editing. Selecting None for current clears other current types and disables current strength; any actual current type enables strength. The API includes `dive_types` and `current_types` arrays while retaining the original single `dive_type` and `current` fields for older clients. Site current summaries count each selected current type once per dive.

Every active dive has a permanent public preview at `/share/dive/<id>`. Owners can open **Share** on a dive card or the full logged dive. The image preview offers a full JPEG and a transparent PNG. Users can swipe horizontally, select the pagination dots or arrows, or focus the preview and use the left/right arrow keys. The dialog keeps the image central, with a compact navigation row and no explanatory copy. Pagination dots have accessible style labels and a screen-reader announcement tracks the selected image. The transparent version contains only the site name, max depth and dive time, and the supplied stacked white Pelagia fin and wordmark. Its checkerboard preview indicates transparency and is never part of the saved file. Both versions respect the viewer's depth units. Below the preview, **Copy link** copies the public URL, **Save image** saves the selected image in its original format, and **More** opens their device's share sheet with the URL and “Check out my logged dive at <site name>”. Native sharing needs HTTPS (localhost is also supported); if unavailable, More offers the copy-link alternative. A selectable link appears only when clipboard access fails.

On phones that support file sharing, Save opens the image share sheet so the user can select Save Image or another destination. Browsers cannot silently write to the photo library; the available save options depend on the device. The selected JPEG or PNG is prepared before the Save click to preserve the user activation required by native sharing. Switching styles invalidates unfinished image preparation, so Save always uses the currently selected format. Unsupported browsers and file-sharing failures fall back to an attachment download at `/share/dive/<id>/preview.jpg?download=1` or `/share/dive/<id>/transparent.png?download=1`; cancellation does not trigger a download. Share destinations control how they display the supplied text and URL.

Visitors see the diver's public username and avatar, dive site, location, date, dive type, center, photos, map, depth and duration. The account gate below uses blurred placeholders; notes, marine life, equipment, conditions, buddies and comments are never sent to anonymous visitors. Signed-in visitors go to `/dive/<id>`, and Google authentication retains this destination. Deleted dives return 404 for both the public page and preview image.

Each link includes Open Graph and Twitter metadata and a generated 1200 × 630 JPEG featuring a dive photo, site, location and stats. If no readable photo is attached, the preview uses the dive site's map at the same zoom as the logged dive, with a location pin and OpenStreetMap attribution. Ocean artwork remains the fallback when coordinates are missing or map tiles are unavailable. Preview titles read “username logged a dive”. Messaging apps control whether and when they show or refresh these previews; copies they have already cached cannot be recalled by deleting a dive. Public pages request no search indexing.

Share maps request only the visible viewport from OpenStreetMap and cache tiles for at least seven days in `map_tiles/` beside the SQLite database. Expired tiles use conditional requests and remain available during outages. `MAP_TILE_CACHE_DIR` and `MAP_TILE_URL` can override the cache directory and raster tile provider through Flask configuration; alternate URLs use `{z}`, `{x}`, and `{y}` placeholders. Rendering requires no browser or new dependency.

Set `PELAGIA_PUBLIC_BASE_URL` to your public HTTPS origin in production, for example `https://YOUR-DOMAIN`. This keeps copied links and image metadata correct behind a reverse proxy. Without this setting, the app uses the request origin, which is convenient for local development. Sharing needs no database migration or external image service.

Run the sharing and authentication tests with the Python command below, plus the JavaScript checks:

```bash
node --test tests/test_*.cjs
```

## Google Sign-In (Required)

Google and passwordless email codes are supported. Configure both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`; without them, Google routes are disabled; email remains available when configured. `/login` and `/signup` are GET-only screens; credential POSTs are rejected.

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

New Google users choose a unique public username before an account is created. Their Google email is stored privately and is not returned by profile or user APIs. Existing Google users keep their user ID and dives. Google users can also sign in by verifying an email code sent to their stored Google address. No extra setup is required. Password-only accounts retain their data but cannot sign in until an administrator verifies ownership and assigns their Google subject ID; email and username matches never automatically merge accounts. A Google account can belong to only one Pelagia account.

Startup adds nullable `google_subject`/`google_email` columns and a unique identity index to existing SQLite databases, preserving existing rows and relationships. Startup removes the retired `password_hash` column using SQLite `DROP COLUMN` (SQLite 3.35+), without rebuilding the users table or changing IDs. No direct Werkzeug dependency or imports remain; Flask still uses Werkzeug internally. Back up production SQLite using your normal deployment procedure before rolling out schema changes.

Run the authentication and existing app tests with:

```bash
.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The tests exercise signed OpenID Connect tokens with local discovery/JWKS data and a mocked token exchange. Before enabling sign-in for everyone, complete a real Google sign-in, logout/re-login, and existing-account link using the deployed callback URL.

## Profiles

Profile → Settings opens a dedicated page at `/you/settings`. Save keeps you on this page and confirms your changes. Units lets you save independent pressure (bar/psi), distance (m/ft), temperature (°C/°F), and weight (kg/lb) preferences for each account. New and existing accounts default to metric. Preferences control display conversions across feeds, dive details, profiles, site conditions, charts, and signed-in share image previews. Displays round to whole numbers, except weight rounds to the nearest half unit. Stored dive measurements and API values remain metric and retain their precision. Anonymous share previews use metric defaults.

Log a Dive and Edit Dive start their existing unit toggles in the account’s preferred units. Users can override any toggle for that form without changing their saved preferences; calculations, limits, and submission conversions keep their existing behavior.

User profiles show every active logged dive, newest first. Owners can change their avatar, edit or clear a bio (up to 500 characters), and select one optional certification from autocomplete. The nine certification options are stored in SQLite and validated on save; free-text certifications are rejected. Startup adds the nullable profile fields and seeds the reference options without changing existing users or dives.

Profile metrics show dives logged in Pelagia and maximum depth. In profile settings, owners can save a non-negative integer **Starting dive count** for dives not logged in the app. The headline total adds that starting count to active dives logged in Pelagia; the metrics and logbook continue to reflect logged dives. Existing accounts start at zero.

The chronological SAC chart takes the median recorded SAC in L/min for each day and spaces observations by date. Dives with no recorded SAC remain in the log and do not affect the chart. The chart includes an expandable table of daily values.

Dive site profiles use the site's coordinate map as their header, with a pending state when coordinates are missing. Dive centers use a compact header without a banner image.

## Public landing page and search

The public `/` page introduces Pelagia and links to dedicated `/login` and `/signup` screens. Set `PELAGIA_PUBLIC_BASE_URL` to the canonical HTTPS origin: canonical, Open Graph, Twitter card, JSON-LD and sitemap URLs all use it. `/sitemap.xml` lists the landing page, terms and privacy policy. `/robots.txt` blocks crawling OAuth endpoints, APIs and uploads. The `/login` and `/signup` pages remain crawlable so search engines can read their `noindex` directive. Homepage navigation and account controls use `data-nosnippet` to exclude interface text from search snippets. Search directives do not replace access controls.

After deployment, confirm `PELAGIA_PUBLIC_BASE_URL=https://pelagiadivelog.com`, inspect the homepage in Google Search Console (including its rendered HTML and canonical URL), submit `/sitemap.xml`, and request homepage indexing. Google chooses titles and descriptions and may take time to recrawl; metadata does not guarantee exact search-result wording.


### Email sign-in with Resend

Set these environment variables on the Render web service:

- `RESEND_API_KEY`: a Resend API key with sending permission for your verified domain.
- `PELAGIA_EMAIL_FROM`: a sender on that domain, e.g. `Pelagia <login@your-domain.com>`.
- `SESSION_COOKIE_SECURE=true` for production HTTPS. Keep a strong, stable `SECRET_KEY` across deployments and workers.

Restart/redeploy after setting the variables. The email option appears only when both Resend settings are present. No SMTP configuration or additional Python dependency is required. Resend must show the sending domain as verified; merely adding DNS records is not sufficient until verification completes.

Users enter their email, receive a six-digit code, then enter it in the same browser/app. New users choose a public username; returning users retain their account and 30-day session. Codes expire after ten minutes, allow five attempts, and are consumed atomically in SQLite. Only keyed hashes are stored. Resends have a one-minute cooldown; email/address combinations are limited to ten sends per hour. Challenge records are pruned after one day. Failed deliveries show a retry message without logging credentials or codes.

Existing Google users can choose Continue with email and verify a code sent to their Google email address. They sign into the same user ID with all their dives, without an enable/link step. Matching is case-insensitive across both Google and email sign-in addresses. If an address matches multiple accounts, email login stops and asks the user to continue with Google or contact support; it never selects an account arbitrarily. Google login remains independent; email-only accounts cannot automatically add Google login by matching addresses.

Before production release, run `.venv312/bin/python -m unittest tests.test_email_auth tests.test_google_auth`, then test actual email delivery, spam placement, new signup, logout/re-login and email code sign-in for an existing Google account on the deployed app. Each code request counts toward Resend’s sending quota; monitor provider usage. Tests mock delivery and never send real emails.
