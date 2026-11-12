# Dive-center profiles

Dive centers use the dive-site map banner, headline typography, description styling and share control. Map pins use the center's stored coordinates; numeric coordinates are never displayed. The contact panel below the headline contains only the address and website. Public explore and shared profiles use the same headline and cached description and show nearby dive sites and reviews without a review form. Nearby cards link to public site pages. Logged dives require sign-in, and the public footer omits the tagline.

The first visit loads a short description asynchronously through `POST /api/dive-centers/<id>/description` for signed-in visitors or `POST /api/explore/dive-centers/<id>/description` for public explore and shared pages. Both endpoints require the same-origin fetch header. Public requests reuse permanent cached results, including unavailable descriptions, even when forced regeneration is enabled for signed-in visits. It reuses the dive-site description service and `gpt-5.6-luna` Responses API request: low reasoning effort, low web-search context and at most one search call. The prompt includes the center's website, name and location, and asks for verified trips, equipment, courses and guide ratios. Unknown information is omitted. The permanent `dive_center_descriptions` cache is separate from dive-site descriptions and ignores the temporary dive-site regeneration flag. Atomic leases prevent duplicate concurrent requests, stale workers cannot overwrite results, and temporary failures have a five-minute retry cooldown. No database write transaction spans the upstream API call. See the [OpenAI web-search documentation](https://developers.openai.com/api/docs/guides/tools-web-search).

Nearby sites use great-circle distance from the center, include the 30-mile boundary, and show the nearest ten at most. Missing or invalid coordinates produce an empty state. The carousel reuses the shared nearby-place card, Home's deck and dot styling, and the `site-carousel.js` controller. Each card fills the track width, without adjacent cards peeking. Touch, trackpad, pagination dots, arrow keys, Home/End and reduced-motion preferences are supported. Browser Back restores the selected card. Nearby cards use a compact map, name, location and distance layout; the whole card links to the site. Pagination sits below the cards, and browsing them does not generate daily reports.

Reviews require a 1–5 star rating and 1–2,000 characters of written feedback. Both profiles share `_place_reviews.html`, `place-profile.js`, and the review data/persistence helpers in `place_profiles.py`. The CSRF-protected form works without JavaScript, retains invalid drafts, and upserts one review per account and center. Saving returns directly to the reviews section without a confirmation banner. The page shows the average rating, review count and individual reviews. Account and center deletion cascade to reviews. Historical center comments remain in storage, but their posting endpoint and profile workflow have been retired. The logged-dive feed remains below the reviews.

Schema initialization creates the new cache, attempt and review tables idempotently. The PWA release hash and precache include both new scripts.

Focused checks:

```sh
.venv312/bin/python -m unittest discover -s tests -p 'test_center_profiles.py'
.venv312/bin/python -m unittest discover -s tests -p 'test_site_descriptions.py'
.venv312/bin/python -m unittest discover -s tests -p 'test_dive_center_sharing.py'
node --test tests/test_feed_site_reports.cjs tests/test_dive_center_sharing.cjs
```
