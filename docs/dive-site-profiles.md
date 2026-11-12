# Dive-site profiles

Below marine sightings, **Nearby dive centers** shows the ten nearest catalog centers within 30 miles of the site's coordinates, including the boundary. Great-circle distance, coordinate validation and ordering use the same `place_profiles.py` helpers as nearby sites on center profiles. Missing coordinates and zero matches have explicit empty states; one result has no dots.

Nearby cards are shared with center profiles, using Home’s card styling, carousel track and pagination controls. Cards include a pinned thumbnail map, name, location and distance, with the entire card acting as the link and pagination below it. Clicking anywhere opens the center profile. Navigation prompts and placeholder descriptions are omitted to keep card height compact and consistent. Each card fills the carousel width with no adjacent card peeking. Touch/trackpad scrolling, dots, arrow keys, Home/End and reduced motion are supported. The selected card is recorded in the current browser history entry, so Back restores it even when the page is rendered again. Saved links are matched against current cards, and unavailable history writes do not interrupt navigation.

Site comments have been replaced by the same five-star review form and list used on center profiles. Existing comments remain in storage, but their posting endpoint and site-profile UI are retired. `dive_site_reviews` stores one editable review per user and site, with a 1–5 rating and 1–2,000 characters of feedback. The form validates on the server, requires CSRF, retains invalid drafts, escapes text and supports submission without JavaScript. Site and center reviews are stored independently. The site shows average rating, review count, individual reviews and the existing logged-dive feed. Public explore and shared pages show nearby dive centers and reviews without a review form; nearby cards link to public center pages. Live conditions and logged dives require sign-in. Public pages omit the rainy/dry season label, rainfall charts and footer tagline.

Saving redirects directly to `#reviews`, without a confirmation banner. The return uses an immediate anchor jump. Submit buttons recover through browser Back; mobile text uses 16 px to avoid focus zoom, star targets are 44 px, and keyboard selection takes precedence over pointer hover previews. Schema initialization creates the review table and index idempotently. User/site deletion cascades to the associated reviews. PWA asset versioning includes the shared profile script.

Focused validation:

```sh
PYTHONPATH=tests .venv312/bin/python -m unittest test_site_profiles test_center_profiles test_dive_site_sharing test_dive_center_sharing test_feed_report test_site_favorites test_pwa
node --test tests/test_*.cjs
```
