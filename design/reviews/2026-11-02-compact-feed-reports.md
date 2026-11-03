# Compact site reports in Home

Home, /feed, and /welcome show followed sites and the daily featured site below the Dive Brief and above logged dives. The featured site is deduplicated against followed sites using the same selection as Reports.

Each vertical card contains a small map, site name, location, and the first two rendered lines of its daily report. There are no swell/wind stats or SITE REPORT flags. The existing FEATURED marker remains attached to the daily featured site. Clicking a card opens its full report.

Reviewed browser screenshots at 1440, 1024, 768, 430, 390, and 320 px with deterministic local fixtures. Cards measure about 127 px on desktop and 122–142 px on mobile, including a long site name. Verified two-line clipping, a short report, square map thumbnails, missing-coordinate fallback, vertical placement, and no horizontal page/card overflow. Layout measurements wait for the browser to paint updated report text.

Interactive checks covered stable card height while loading, unavailable reports, zero/one/three/eleven cards, featured deduplication, a missing Brief, keyboard navigation, the full-report destination, and the existing full-text Reports page. Browser checks produced no page errors. Cached feed previews request only their report; description and conditions dependencies load only when a cold report needs them.

Validation: 65 Python tests covering site favorites, the Brief, feed chronology, founder welcome, units, static maps, and PWA assets; 40 JavaScript tests covering reports, Brief interaction, loading states, maps, and navigation. JavaScript syntax and patch whitespace checks passed. Existing chronology fixtures were updated to reflect followed-diver visibility and the shared Home/feed route.

Screenshots and browser measurements are available locally in output/compact-feed-reports/ (home-*.png, cards-*.png, loading-390.png, unavailable-390.png, reports-390.png, validation.json). These are local fixture captures, not production data.
