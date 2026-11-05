# Dive-site profiles

Below marine sightings, **Nearby dive centers** shows the ten nearest catalog centers within 10 miles of the site's coordinates, including the boundary. Great-circle distance, coordinate validation, ordering and cached descriptions use the same `place_profiles.py` helpers as nearby sites on center profiles. Missing coordinates and zero matches have explicit empty states; one result has no dots.

The card, carousel deck and pagination are shared with center profiles and Home. Cards include a pinned thumbnail map, name, location, distance and a three-line description preview. Clicking anywhere opens the center profile. Cached center descriptions are reused without generating AI descriptions for the carousel. Unknown descriptions show a short invitation to view the center's details and reviews. Each card fills the carousel width with no adjacent card peeking. Touch/trackpad scrolling, dots, arrow keys, Home/End and reduced motion are supported. The selected card is recorded in the current browser history entry, so Back restores it even when the page is rendered again. Saved links are matched against current cards, and unavailable history writes do not interrupt navigation.

Site comments have been replaced by the same five-star review form and list used on center profiles. Existing comments remain in storage, but their posting endpoint and site-profile UI are retired. `dive_site_reviews` stores one editable review per user and site, with a 1–5 rating and 1–2,000 characters of feedback. The form validates on the server, requires CSRF, retains invalid drafts, escapes text and supports submission without JavaScript. Site and center reviews are stored independently. The site shows average rating, review count, individual reviews and the existing logged-dive feed. Public shared previews continue to gate community reviews and nearby discovery.

Saving redirects directly to `#reviews`, without a confirmation banner. The return uses an immediate anchor jump. Submit buttons recover through browser Back; mobile text uses 16 px to avoid focus zoom, star targets are 44 px, and keyboard selection takes precedence over pointer hover previews. Schema initialization creates the review table and index idempotently. User/site deletion cascades to the associated reviews. PWA asset versioning includes the shared profile script.

Focused validation:

```sh
PYTHONPATH=tests .venv312/bin/python -m unittest test_site_profiles test_center_profiles test_dive_site_sharing test_dive_center_sharing test_feed_report test_site_favorites test_pwa
node --test tests/test_*.cjs
```
