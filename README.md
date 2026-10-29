# Pelagia

Pelagia is a Flask/Gunicorn MVP for logging and sharing scuba dives with local SQLite persistence.

## Run Locally

```bash
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt
.venv312/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8010 wsgi:app
```

Open `http://127.0.0.1:8010`.

`gunicorn.conf.py` runs two `gthread` workers with four threads each by default, so the independent
Open-Meteo and OpenAI requests made by a dive-site page can progress concurrently instead of
occupying all synchronous workers. Set `WEB_CONCURRENCY` and `GUNICORN_THREADS` to tune those values
for the deployment. SQLite remains safe for this workload because each request uses its own connection,
WAL mode is enabled, and upstream calls release their short database claims before network I/O.

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

Google and email login/signup that would open the feed first visit `/welcome`: a brief ocean-colored splash with the Pelagia mark and a “Welcome to Pelagia” greeting. The feed renders underneath and the splash lifts away automatically; Dive in or Escape skips the pause. Reduced-motion preferences use a short fade. The splash replaces its browser history entry with `/home`, so refresh, Back and ordinary feed visits do not replay it. Without JavaScript, the page redirects directly to the feed. Sign-ins from shared links retain their original destination.

For Render, attach a persistent disk at `/var/data`. No database or upload-path environment variables are required there. Configure `SECRET_KEY` and set `SESSION_COOKIE_SECURE=true` for HTTPS deployments.

- `data_sources.dive_sites_csv`: dive-site master CSV path
- `data_sources.species_csv`: dive-site marine-life matches CSV path
- `data_sources.dive_centers_csv`: dive-center CSV path

On first app startup, Pelagia initializes SQLite and imports reference data from the configured CSVs with pandas. Application data, reference data, uploaded-photo paths, likes, and comments are stored in SQLite. Uploaded image files are stored beneath the configured upload directory and served from `/uploads/`.

## Daily dive site reports

The collapsible **Today's report** section below the dive site description generates a shared report on first expansion. It uses the server's `OPENAI_API_KEY` and `gpt-5.6-luna` Responses API, with no search tools, to produce at most two sentences from cached site metadata, description, temperature, season classification, and all retrieved marine/weather/rainfall data. The voice is a brisk, natural, lightly sporty dive-weather briefing without hype or forced slang. Personal dive history and exposure recommendations are not sent; the prompt excludes wetsuit advice from the shared report. A completed description lookup with no verified description and a missing catalog season are explicitly unknown; missing, expired, or incomplete marine data prevents generation.

`dive_site_reports` stores one row per site and replaces it when the date changes in the site's forecast timezone. A short atomic SQLite claim prevents concurrent calls across workers; the API call runs outside the transaction. Each site/date permits at most one upstream attempt, including failed or uncertain attempts, to avoid duplicate charges. Failure displays an unavailable state until the next local date. Missing configuration or dependencies do not consume the daily attempt. Browser requests require login and the same-origin fetch header and are never browser/PWA cached. Opening the report shows skeleton loading while dependencies finish and the report generates.

The signed-in feed starts report loading for every followed site as soon as the page is ready. It first checks the shared daily report cache; on a cold site it populates the description and marine caches in parallel, then requests the report. Cards show a four-line preview with an accessible **Read more** / **Show less** disclosure and omit the logged-dive count from this section.

## Dive site descriptions

Set `OPENAI_API_KEY` in the server environment to enable on-demand dive site summaries. The key stays server-side; do not commit it. Generation uses `gpt-5.6-luna` through the Responses API with one required, low-context web search, low reasoning effort, and bounded output and network timeouts. There are no automatic upstream retries or model substitutions. Search tool calls and model tokens are billed to the key's OpenAI account.

On opening a dive site, Pelagia reads the persistent SQLite `dive_site_descriptions` table. A cached summary appears beneath the name and location without coordinates, links, citations, source names, or evidence notes; citation metadata may be retained internally. A site without a cache row loads the rest of its page immediately, requests a summary, and shows the shared two-line skeleton after 160 ms. The search prompt requires sources matching both the site's name and location, uses coordinates only to disambiguate the site, and limits the summary to 1–2 sentences and 70 words.

The table starts empty; reference CSV descriptions are not imported. A completed search with no confidently verified information saves a row with a **NULL description**. That row renders nothing and permanently prevents automatic generation for the site. Successful summaries also never expire automatically. To deliberately research a completed site again, an operator must remove its cache row from SQLite.

Timeouts, rate limits, missing/invalid credentials, and malformed or incomplete responses do **not** create NULL results. They render no description and allow another visit to retry after a five-minute cooldown. A separate coordination table uses 60-second claims to prevent duplicate generation across Gunicorn workers, without holding a database write transaction during the API call. The browser checks pending requests every two seconds for at most 35 seconds and stops when leaving the page. Responses require login and a same-origin fetch header and are never browser/PWA cached.

Tests mock OpenAI without making billable calls: `.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'` and `node --test tests/*.cjs`.

## OBIS species catalogue

The SIGHTINGS panel reads the precomputed `dive_site_obis_occurrences` catalogue and combines its Pelagia species with species from non-deleted logged dives. Logged counts remain attached to their tags. Loading a dive-site page performs no OBIS or OpenAI species-normalization request. Explore cards use the same combined sources, deduplicating species by trimmed, case-insensitive common name and preserving logged counts without adding OBIS occurrence counts.

For an occurrence-level offline catalogue, run `PYTHONPATH=. .venv312/bin/python scripts/ingest_obis_species_occurrences.py`. The restartable job iterates Pelagia's full species vocabulary, resolves common names to the most-specific exact marine WoRMS taxon matches, and queries each distinct AphiaID in OBIS from 2020-01-01 through the current UTC date. It saves the complete source JSON only when coordinate uncertainty is strictly below 0.5 miles and a local Cartesian distance check places the occurrence strictly within 0.5 miles of a Pelagia dive site. Resolution status, accepted taxa, occurrences, distances, and every dive-site/species/occurrence link live in separate tables and never modify diver-recorded species. Use `--taxon-overrides overrides.json` for ambiguous, misspelled, multilingual, or catalogue-only tags; its JSON values are AphiaID arrays, while `null` explicitly skips a tag. `--resolve-only`, `--ingest-only`, repeatable `--species`, and `--max-taxa` support review and staged runs.

## Entry Points

- `wsgi.py`: Gunicorn entrypoint
- `pelagia/__init__.py`: Flask app factory and routes
- `pelagia/schema.sql`: SQLite schema
- `pelagia/importer.py`: pandas CSV import

## Explore

Signed-in users can open **Explore** between Feed and Log dive in the desktop and mobile navigation. Its country/region search autocompletes distinct locations from the dive-site catalog, including named regions such as Komodo National Park. Choosing a suggestion creates one removable location tag and locks typing until the tag is cleared.

Explore initially defaults to the region of the account's most recently logged, non-deleted dive, when that region exists in the site catalog. Selecting a country or region saves it as that account's default, so returning to Explore or signing in on another device restores its tag and site feed. Clearing the tag saves an explicit empty preference instead of restoring the dive-derived default. Device location is not requested. The authenticated `POST /api/explore/location` endpoint validates selections against the site catalog and stores the preference in `users.explore_location`; normal startup adds this nullable column to existing databases.

The location filters a paginated feed of linked dive-site cards with names, locations and map previews. Cards show nonzero logged-dive counts and marine species from non-deleted dives and the precomputed OBIS catalogue, with species tags below the map. Results sort by logged-dive count descending, then combined distinct observed-species count descending, with name and site ID as stable tie-breakers, before pagination. Show more loads another 24 sites. Selections work with keyboard navigation and browser Back/Forward, and location changes discard stale requests. Explore currently contains dive sites only, without category tabs. The authenticated `/api/explore/locations` and `/api/explore` endpoints provide suggestions and rendered feed pages.

**Advanced search** opens a compact distance frame with synchronized whole-number slider and numeric controls plus miles/km switching, capped at 100 miles or 160 km. Submitting a place makes one server-side Nominatim request, then projects the returned latitude/longitude into local Cartesian distance and loads all catalog dive sites inside the radius, using the same dive-count and species-count ranking as country/region results. The returned Nominatim display name—not the typed query—appears in the removable location tag and feed summary. Successful searches are saved to the account, so returning to Explore restores the tag, controls, coordinates, and current site feed without geocoding again; the next standard or advanced search replaces that saved state. No-result searches remain in the distance frame with an inline message. Pagination reuses the returned coordinates and never geocodes the same submitted search again. Requests identify Pelagia, and `NOMINATIM_ENDPOINT` and `NOMINATIM_USER_AGENT` can override the public defaults for a managed geocoder deployment.

## Garmin dive imports

New and Edit dive forms offer **Import from dive computer → Garmin → Choose FIT file**. Other listed brands are disabled. Export a single-gas scuba dive from Garmin Dive using **Export Dive as FIT File**. Selecting the file immediately fills its recorded date, depths, bottom time, gas composition, water temperature, and GPS coordinates. The nearest catalog dive site is matched across all valid site coordinates using Cartesian chord distance, with no distance cutoff. Recorded coordinates are retained, and all imported values can be reviewed before saving. Fields absent from the file and unrelated entries, including photos and notes, are preserved. No separate air temperature is inferred from the water sensor.

The authenticated `POST /api/dive-import/garmin` endpoint accepts the FIT file as a raw `application/octet-stream` body, requires `X-Requested-With: fetch`, limits input to 10 MiB, validates FIT integrity with `garmin-fit-sdk==21.218.0`, and returns uncached JSON. It reads the upload in memory and never stores the original file or uses multipart temporary-file spooling. Multi-session, multi-gas, apnea, closed-circuit, non-Garmin, and damaged files are rejected without changing the form.

Parsed computer data stays in the mounted browser form until **Save dive/Save changes**. Saving atomically adds or replaces its one-to-one `dive_computer_data` row. Version 1 stores the source, UTC start, exact bottom/recording durations in seconds, and every valid depth measurement as `{elapsed_seconds, depth_m}`, without interpolation or downsampling (up to 100,000 measurements). Existing data survives ordinary edits and is removed by cascading account/dive deletion. Profiles are excluded from feed and sharing payloads. Signed-in dive details render a filled, downward depth chart as the first slide above the map, followed by attached photos. Native swipe, arrow controls and keyboard arrows navigate the gallery. Tiny axes follow the viewer’s depth units. Rendering preserves time spacing and bucket extrema while bounding SVG size; stored measurements remain unchanged. Empty or single-time profiles omit the chart. The form shows bottom time rounded to whole minutes. Depth and duration numeric entries can exceed the 45 m/120 minute slider ranges.

Supported browsers request Downloads as the initial file location and remember the import picker directory. Safari/iPhone use the native picker, whose starting location is controlled by the platform. Back, Escape, cancellation, and failed imports preserve the mounted form and selected photos. Reloading or leaving the page does not persist an unsaved draft.

The new table is created by normal application initialization; existing dives require no backfill. Install the updated requirements when deploying. Tests generate synthetic FIT files in memory. To additionally check the personal sample without copying it into the repository:

```bash
PELAGIA_GARMIN_SAMPLE='/path/to/92 Single-Gas Dive.fit' .venv312/bin/python -m unittest discover -s tests -p 'test_garmin_fit.py'
```

## The Dive Brief

The main feed starts with a compact daily newsletter card, an expand/collapse chevron and estimated reading time. Read the brief opens a full-screen Markdown reader with a persistent Feed back button. The footer's Back to feed link, Escape and browser Back also return to the feed. The feed stays fixed while the reader scrolls, and returning restores its position and collapses the preview. Touch and mouse interactions keep focus without drawing keyboard focus rings; keyboard navigation retains visible focus indicators. Touch gestures, trackpad scrolling, text selection and pinch zoom keep their native browser behavior; the reader has no custom swipe navigation. Reduced-motion preferences disable animated transitions. Editions also have signed-in deep links at `/brief/YYYY-MM-DD`; returning after refreshing the reader consumes its existing history entry. The reader supports headings, emphasis, links, lists, blockquotes, code and tables, with escaped raw HTML and safe link protocols. External sources open in a separate tab.

Editions live on disk as `the_dive_brief_YYYY-MM-DD.md`. `PELAGIA_DIVE_BRIEF_DIR` defaults to `dive_briefs/` beside the SQLite database (`/var/data/dive_briefs` in production). The filename and feed selection use **today's publication date** in `PELAGIA_DIVE_BRIEF_TIMEZONE` (default `America/New_York`); the digest can cover T−1 news. File changes are picked up without restarting. The feed shows the brief only when today's valid edition exists. There is no sample, previous-day, or latest-edition fallback. Historical signed-in deep links still work; future editions remain unavailable.

The feed card starts collapsed, showing its icon, title and date. Tap or click the compact header (or use Enter/Space) to reveal the summary and Read the brief link. Returning from the full reader collapses it again, and every feed load starts from the compact state.

The reader's share icon sits beside the edition date and reading time. It opens the device's native share sheet when supported over HTTPS, with a copy-link fallback. Shared links use `/share/brief/YYYY-MM-DD`, where the entire edition can be read and shared again without an account, with no Feed or app navigation controls. The link stays tied to that edition after the publication day changes. Public pages include link-preview metadata; missing, invalid and future editions return 404.

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

Settings includes a red **Delete Account** action below Log out. It opens a confirmation page; **Keep my account** returns to settings, while the CSRF-protected **Delete account** submission permanently removes the signed-in user, their authentication challenges, preferences, active and previously soft-deleted dives, dive species, uploaded profile/dive photos, likes, and comments. Buddy references on other users’ dives are cleared, other accounts and shared reference data are preserved, and the session is cleared before returning to the landing page. Deletion requires no database migration.

Profile → Settings includes Terms of Use (`/terms`) and Privacy Policy (`/privacy`). Both pages are also accessible without signing in and linked from the authentication screen, including Google signup.

Set `PELAGIA_OPERATOR_NAME` to the person or entity operating the app and `PELAGIA_CONTACT_EMAIL` to a monitored public email address. Defaults are “Pelagia” and `info@pelagiadivelog.com`. The contact address appears as a mail link in the Questions section of both legal pages. Supply the actual operator name before public release. Hosting/log retention and any deployment-specific data practices should also be verified by the operator.

The short documents adapt the account security, availability, third-party services, security, and update boilerplate from [App Privacy Policy Generator’s Privacy Policy and Terms & Conditions templates](https://mobile-privacy.github.io/generator/) (accessed October 16, 2026). Its disclaimer expressly permits using the templates when compiling your own policy. App-specific collection, sharing, cookies, and retention disclosures follow this repository’s implementation. The templates were shortened and do not assert jurisdiction-specific compliance, a governing law, or an unverified business identity. They are template-based drafts, not a legal compliance certification.

## Install Pelagia on a Phone (PWA)

Pelagia can be installed from its HTTPS website and opened from a home-screen icon in a standalone window. Its manifest, PNG icons, Apple touch icon, service worker and offline page are included in the app; no additional package, build step or database migration is needed.

- **iPhone/iPad:** open Pelagia in Safari, choose Share → Add to Home Screen (under More on some versions), leave Open as Web App enabled if shown, then tap Add. Installation guidance is available on the login page and your own profile. The installed app may need a separate sign-in.
- **Android:** use the browser's Install app/Add to Home screen action. Your profile also offers native installation when supported.

The service worker caches only explicitly listed public assets and a generic offline screen. Dive pages, account pages, APIs, uploads and external map tiles are not cached. Viewing or saving dives still requires internet access. When the browser reports that it is offline, form submissions are blocked and a notice asks users to keep the page open to preserve their changes. This release does not persist offline dive drafts or sync them later.

Asset cache versions are derived automatically from deployed files. An update notice offers Reload to update; an open form is never automatically reloaded. Users should save their changes before accepting an update.

Installed launch screens use the Pelagia logo on the manifest's dark blue background. Android generates its screen from the existing manifest; iPhone/iPad use bundled `apple-touch-startup-image` PNGs for matching screen sizes in portrait and landscape. An inline dark background also prevents a white flash before CSS loads. The OS controls how long the launch screen stays visible; no artificial loading delay is added. Startup images are public static assets, fetched by iOS as needed rather than all precached by the service worker. To regenerate them after changing the app icon, run `.venv312/bin/python scripts/generate_pwa_startup_images.py` and commit the generated `pelagia/static/img/startup/` files. After deployment, open the installed app online, fully close it, then relaunch to check the startup screen on a real device. iOS may retain an older launch image until the Home Screen app is re-added.

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

## Sharing Dive Sites

Dive site pages have a small share icon beside the like button beneath the description. It opens native sharing over HTTPS (or localhost), with a copy-link fallback. Public links use `/share/dive-site/<id>` and show the map, coordinates, name, location, cached description, like count and aggregate marine sightings. Conditions, charts, individual logged dives and comments are not loaded for guests. A blurred placeholder offers a free account to access live dive site conditions and the dive log; signup and login return to that site. Signed-in visitors to a shared link open the full site. Guest previews never trigger paid description generation.

## Sharing Dive Centers

Dive centers have a share icon beside the like button, with native sharing and a copy-link fallback. Public links at `/share/dive-center/<id>` show the center's name, location, address, website and like count. The logged dive feed and community comments are never loaded for guests; a blurred placeholder offers a free Pelagia account to access them. Public previews open directly on the center, without a top banner. Login and signup return to that center, and signed-in visitors to shared links open its full page.

## Sharing Logged Dives

The log/edit form stores max depth and an optional average depth in meters. Both accept decimals and display whole values without `.0`. Average depth starts unset; when supplied it is used for SAC calculation, otherwise SAC uses max depth. Clearing average depth restores that fallback. Logged cards and dive headlines show max depth and duration. Average depth appears in the logged dive’s detailed metrics and full share image when available. Existing dives keep an unset average depth and their saved SAC rate.

Unit toggles on the form switch depth/visibility between m and ft, weight between kg and lb, pressure between bar and psi, and both temperatures between °C and °F. Converted values and slider bounds display as whole numbers in either direction, with weight displayed in half units. Visibility advances by 1 m or 5 ft, and visibility displayed in feet rounds to the nearest 5 throughout the app. Labels update immediately; optional blanks stay blank. Other sliders advance by one displayed unit, with pressure advancing by 10 bar or 100 psi. Pressure sliders stop at 200 bar or 3000 psi; numeric inputs allow up to 300 bar (about 4351 psi). Full-cylinder pressure labels pair 200 bar with 3000 psi in the form and logged views, while stored measurements, submission conversions and SAC retain the exact physical conversion. Typed pressures above the slider range remain intact for SAC and saving. Submission carries the selected unit for each group, and the server converts to metric before clamping, calculating SAC and saving. Toggle-only round trips preserve full precision even when the form rounds a converted display. Existing dives migrate to REAL pressure, visibility and temperature columns so converted measurements retain their fractional metric values. Logged views use the viewer’s saved unit preferences, and new/edit forms initialize their toggles from those preferences.

Conditions includes a Water type control immediately after water temperature. Like Exposure, its heading starts at `-` (unset) with neither option selected, and the only two buttons are Fresh and Salt. The selection is saved with the dive, restored on edit, and shown in the detailed conditions. Existing dives default to unset.

On a new dive, selecting a catalog site, importing coordinates from Garmin, opening the form from a dive-site page, or entering valid latitude/longitude coordinates asks the Is On Water API to prefill Water type. `OCEAN` selects Salt; every other valid feature selects Fresh. The request goes through Pelagia's authenticated `/api/water-type` endpoint so browser CORS does not affect the form. Lookup failures leave the existing selection unchanged, and edit forms preserve the saved value until coordinates change. Set `PELAGIA_IS_ON_WATER_API_URL` to override the upstream base URL.

Dive type and current type dropdowns accept multiple choices using checkboxes. Existing single selections are retained when editing. Selecting None for current clears other current types and disables current strength; any actual current type enables strength. The API includes `dive_types` and `current_types` arrays while retaining the original single `dive_type` and `current` fields for older clients. Site current summaries count each selected current type once per dive.

Every active dive has a permanent public preview at `/share/dive/<id>`. Owners can open **Share** on a dive card or the full logged dive. The image preview offers five swipeable styles: the full JPEG splash and four transparent PNGs (vertical, horizontal, stacked, and map). Users can swipe horizontally, select the pagination dots or arrows, or focus the preview and use the left/right arrow keys. The dialog keeps the image central, with a compact navigation row and no explanatory copy. Pagination dots have accessible style labels and a screen-reader announcement tracks the selected image. The splash and vertical, horizontal and stacked PNGs use the same stat selection: take the first four available values in this order—max depth, average depth, dive time, gas mix, SAC rate, weight, exposure. Fewer than four are shown when fewer values are available. Stored zeroes count as values; missing, nonfinite and negative numeric values are skipped. Every selected value uses the same type size within its image, fitting the longest value once for all stats. Consistent 24 px labels and balanced spacing keep the exports legible at social-media sizes. The vertical PNG places the supplied logo at the top and stats in one column; horizontal uses a single stats row and logo below. Neither vertical nor horizontal includes the site name. Stacked keeps the site name above a two-column stats grid. The map PNG contains only the site name, a rounded map with site pin, max depth and dive time beneath it, and the logo. A missing map shows a Map unavailable outline without inventing a location. All transparent versions use the supplied stacked white Pelagia fin and wordmark, with a subtle local shadow for legibility over photos and video. Its canvas remains transparent; the checkerboard preview is never part of the saved file. The JPEG uses a full-bleed photo or map with a continuous ocean-colored fade. Average depth appears in the main stats row when selected; the footer contains only the diver and date. Photo splashes include a rounded map inset in the upper-right with the site pin; the inset is omitted if coordinates or map tiles are unavailable. Without a readable photo, the map fills the background with its pin offset clear of the title. All five styles respect the viewer's depth units, and weight uses the viewer's kg/lb preference when selected. The PNG layouts have their own export dimensions and fit inside the share preview without cropping, with five accessible pagination controls. Below the preview, **Copy link** copies the public URL, **Save image** saves the selected image in its original format, and **More** opens their device's share sheet with the URL and “Check out my logged dive at <site name>”. Native sharing needs HTTPS (localhost is also supported); if unavailable, More offers the copy-link alternative. A selectable link appears only when clipboard access fails.

On phones that support file sharing, Save opens the image share sheet so the user can select Save Image or another destination. Browsers cannot silently write to the photo library; the available save options depend on the device. The selected JPEG or PNG is prepared before the Save click to preserve the user activation required by native sharing. Switching styles invalidates unfinished image preparation, so Save always uses the currently selected format and layout. Unsupported browsers and file-sharing failures fall back to an attachment download at `/share/dive/<id>/preview.jpg?download=1` or `/share/dive/<id>/transparent.png?download=1&layout=<vertical|horizontal|stacked|map>`; cancellation does not trigger a download. Share destinations control how they display the supplied text and URL.

Visitors see the diver's public username and avatar, dive site, location, date, dive type, center, photos, map, depth and duration. Share images can also include recorded average depth, gas mix, SAC rate, weight and exposure when selected by the priority rule. The account gate below uses blurred placeholders; notes, marine life, raw tank pressures, other equipment, conditions, buddies and comments are never sent to anonymous visitors. Signed-in visitors go to `/dive/<id>`, and Google authentication retains this destination. Deleted dives return 404 for both the public page and preview image.

Each link includes Open Graph and Twitter metadata and a generated 1200 × 630 JPEG featuring a dive photo, site, location and stats. If no readable photo is attached, the preview uses the dive site's map at the same zoom as the logged dive, with a location pin and OpenStreetMap attribution. Ocean artwork remains the fallback when coordinates are missing or map tiles are unavailable. Preview titles read “username logged a dive”. Messaging apps control whether and when they show or refresh these previews; copies they have already cached cannot be recalled by deleting a dive. Public pages request no search indexing.

Share maps request only the visible viewport from OpenStreetMap and cache tiles for at least seven days in `map_tiles/` beside the SQLite database. Expired tiles use conditional requests and remain available during outages. `MAP_TILE_CACHE_DIR` and `MAP_TILE_URL` can override the cache directory and raster tile provider through Flask configuration; alternate URLs use `{z}`, `{x}`, and `{y}` placeholders. Rendering requires no browser or new dependency.

Set `PELAGIA_PUBLIC_BASE_URL` to your public HTTPS origin in production, for example `https://YOUR-DOMAIN`. This keeps copied links and image metadata correct behind a reverse proxy. Without this setting, the app uses the request origin, which is convenient for local development. Sharing needs no database migration or external image service. PNG URLs accept `layout=vertical`, `horizontal`, `stacked`, or `map`; omitting it selects stacked, and unknown layouts return 400. Layout-specific downloads include the layout name in the filename.

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

## Dive-site marine conditions

Signed-in dive-site pages load marine conditions after the page renders through
`GET /api/dive-sites/<id>/conditions`. The conditions box shows water temperature, tide level,
moon phase, and wind speed. Water temperature uses the median from the latest
logged dive day within seven days, falling back to Open-Meteo sea surface temperature
when that day has no logged temperature. Logged temperature renders immediately and
stays visible without a forecast. Pelagia first classifies the site's coordinates with Is On Water and
persists that feature per dive site. Later views reuse the classification without another upstream request;
changing a site's coordinates invalidates it. Only `OCEAN` proceeds to Open-Meteo. Every other feature
skips Open-Meteo and replaces the current, tide, and wind charts with availability messages. Tide phase and the
three regional forecast charts for ocean sites come from Open-Meteo using the site's stored coordinates. Logged
dive measurements remain unchanged. Public previews show only the gated labels.

The server concurrently requests the marine and main weather APIs for seven local calendar
forecast days plus yesterday, then requests the Historical Weather API for daily rain over the twelve
complete calendar months before the current site-local month. Those daily values are aggregated into
monthly totals in millimeters. The marine request includes hourly/current ocean velocity, sea level, and sea surface temperature;
the weather request includes hourly 10 m wind speed and direction plus daily moon phase. The
conditions response exposes 48-hour paired `wind_hourly` series, seven
`wind_daily` maxima and `moon_phase_daily` values, and current wind speed from the current hourly sample. The conditions
box shows wind speed to one decimal in knots, matching the wind chart, and today's nearest
major moon phase (New, First Quarter, Full, or Last Quarter). The seven-day current chart shows
one small moon icon on the day closest to any of these four phases, including wraparound at new
moon. Equally close days use the earlier day; missing moon data omits the icon. Hourly current bars
have no moon icons. Current velocities are classified in **knots**: Light below 0.5, Moderate
from 0.5 to below 1, Strong from 1 to below 2, Very Strong at 2 or above. Tide
labels use hourly local extrema (including plateau midpoints) within one hour,
otherwise the surrounding slope. Flat or incomplete series show `-`. These are
modeled surface conditions, not measurements at dive depth; the tide/current grid
is about 8 km and SST's source resolution is six-hourly. Sea level is relative to
global mean sea level, not chart datum.

The rainfall chart appears below the rainy-season summary and shows the trailing twelve complete monthly
totals. The regional current chart defaults to seven daily maxima; its two-day view shows the next
48 hourly samples. Tide level shows the next 24 hourly samples. Both use the site's
timezone and preserve null-data gaps. The seven daily bars fit on phones; hourly
charts scroll horizontally with a fixed Y axis. Tap or point at the chart, or focus
it and use arrow keys, to inspect accessible values. Exact chart values remain
available to screen readers, while the visible charts end at their axes. Tide
forecasts render as a continuous line without hourly point markers. Temperature
and tide values respect account units. Below tide level, the wind chart uses the same 7-day/2-day
bar layout with a numeric knots axis. Daily bars use maximum 10 m wind speed and the direction at
that peak (the earliest peak wins ties); hourly bars use each hourly speed/direction. Tiny compass
arrows above the bars point toward the wind's origin, rounded to 16 headings at 22.5° increments.
Only Current Strength retains the regional
forecast note; chart titles omit the regional suffix and the other charts have no explanatory copy.
Direction and moon labels are also available in chart inspection and accessible text.
The current and wind toggles operate independently and do not issue additional API requests.

The idempotent schema initialization adds `marine_forecast_cache`. Responses are
shared across workers for 15 minutes, capped at site-local midnight, and invalidated
when coordinates change. A 30-second claim prevents duplicate upstream requests;
failures have a 60-second cooldown. No database transaction stays open during the
network call. Missing coordinates or upstream failures stop loading, retain
logged water temperature, and show an unavailable state. Browser requests time out after 20
seconds and stop on navigation. API responses are private/no-store and excluded
from the service worker cache.

The default public endpoint needs no key for evaluation and noncommercial use.
For commercial use, set `OPEN_METEO_API_KEY` server-side; this selects
`customer-marine-api.open-meteo.com` and `customer-api.open-meteo.com`. Never expose the key to the browser. See
[Open-Meteo pricing and usage terms](https://open-meteo.com/en/pricing).
Attribution: [Open-Meteo marine API](https://open-meteo.com/en/docs/marine-weather-api),
[Open-Meteo weather API](https://open-meteo.com/en/docs),
[Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api),
Météo-France / Copernicus Marine, and DWD.

Focused tests: `.venv312/bin/python -m unittest discover -s tests -p 'test_marine.py'`
and `node --test tests/test_marine.cjs`. These tests mock upstream calls.

Below site conditions, exposure advice uses the displayed water temperature, preferring
recent logged measurements over the marine surface forecast.
Default Fahrenheit bands are: above 80°F swimsuit or shorty, above 68°F 3mm, above
60°F 5mm, above 50°F 7mm, and 50°F or below drysuit. Comparisons use unrounded
Celsius values, independently of display units. When no temperature is available,
the recommendation block stays hidden.

Personalization searches the signed-in user's non-deleted, non-future dives. If
the user has history in the site's country/region, only that regional history is
considered for exposure advice. Otherwise search all of the user's dives. Region
matching ignores case and surrounding spaces, using the recorded region or the
linked site's region when the recorded region is missing. A site without a region
uses global history. Regional history without qualifying feedback falls back to
the default exposure rather than borrowing feedback from elsewhere.

Within that scope, require valid exposure, temperature, and temperature feedback
within ±3°F (about ±1.67°C), inclusive. Among all neutral (3/5) dives in that
window, recommend the minimum recorded exposure, regardless of frequency or
whether a thicker suit was logged at a closer temperature. For the winning
exposure, link the most recent supporting dive by date/ID whose temperature and
weight feedback are both neutral (3/5, feels right) and recorded suit matches.
If no neutral feedback exists in the window, use the closest rated measurements
and adjust exposure one protection step warmer for ratings 1–2 or lighter for
ratings 4–5. If those measurements suggest different exposures, use the minimum
adjusted exposure. Matching personal feedback takes
precedence over the default temperature band, with no limit on how far the suit
differs from that default. The matching window is independent of display units.
The protection order is swimsuit, shorty, 2mm, 3mm, 5mm, 6mm, 7mm, drysuit. Without comparable feedback,
use the default bands.
Whenever a qualifying log with neutral temperature and weight feedback confirms the recommended suit, including confirmation of
the default, exposure advice carries an asterisk and “Based on your dive log
history”; “history” links to the most recent qualifying supporting dive for the
winning exposure. Without such a log, omit the history link and its asterisk.
Cold/warm feedback can adjust the recommendation but does not qualify for a history link.
The advice sits in a divided footer inside the conditions card, with two aligned
columns on desktop and stacked equipment rows on phones. History links refresh
when returning from a logged dive, including browser Back/Forward restoration.

Weight estimates require an exact exposure match and a neutral weight rating
(3/5), using the user's most recent qualifying log and current kg/lb preference.
Salinity must match the dive site's cached Is On Water classification (`OCEAN`
is Salt; every other valid feature is Fresh), rather than the water type recorded
on dives previously logged at that site. If the site has no classification, no
estimate is shown. For the
swimsuit-or-shorty default, either exposure may match; matching still requires the exact
exposure and salinity. Only the converted weight is displayed, with equipment and weight emphasized
in bold. Missing matches display `-`; confirmed estimates
carry the requested asterisk and guidance caveat. Recommendations are recomputed
per authenticated request and never written to the shared marine cache.
