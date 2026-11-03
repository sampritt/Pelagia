# Full daily reports on Home — signed off

Home, `/feed`, and `/welcome` use the same full card template as Reports. Each Home card includes the site map, name and location, swell and wind descriptions with measured stats, the first three rendered lines of today's report, and a visible Read more action. The action and the entire card link to `/dive-sites/<id>#daily-report`, which expands the daily report on arrival. Reports retains its vertical list and complete report text.

All followed sites appear in follow-recency order. The daily featured site is fetched only when there are no followed sites. The compact card template, compact styling and loading branch, and single-site midnight ranking have been removed. Site-local dates now schedule refreshes for the full set of cards, including sites without coordinates, daylight saving transitions, and fractional-hour time zones.

Each card fills the Home feed width on desktop and mobile, without peeking. Native horizontal scrolling and mandatory snapping browse multiple cards. Pagination dots below the card are clickable, indicate the selected report, and have accessible site labels. Left/right, Home and End keys work on the carousel and card links; moving a focused card also moves keyboard focus to the selected report. Browser Tab browsing updates the pagination state. A single followed or featured card has no pagination controls.

Live daily refreshes rebuild the carousel, initialize maps, and preserve the selected site and focused pagination control. Resizing keeps the current report aligned. Loading, short and unavailable report text reserve the same three-line preview height. Unavailable conditions retain dashes and a working link to the site. Browser Back, offline retry, page visibility, request cancellation, and interrupted loading retain their existing behavior.

## Visual and interaction review

Signed off using rendered local fixtures in desktop Chromium and touch-mobile emulation. Reviewed screenshots at 320, 390, 768 and 1440 px, plus long names, missing coordinates, loading and unavailable reports. Automated layout checks covered 320, 360, 390, 430, 560, 640, 768, 820, 821, 900, 901, 1024, 1280 and 1440 px with zero, one, three and ten followed sites. Additional checks covered 200% text, long condition labels, a missing Brief, and orientation changes.

The 84 browser checks passed with no page JavaScript errors. They verify full-width cards without neighboring peeks or document overflow, three-line clipping, content containment, stable loading height, placement below the Brief and above logged dives, pagination state, native touch swiping, smooth dot navigation, keyboard activation, correct expanded daily-report destinations, Reports navigation, browser Back, Brief interaction, refresh focus restoration, and orientation alignment. Screenshots, runnable fixture scripts and measurements are available locally under `output/full-home-reports/`; these use deterministic fixtures, not production reports. WebKit was not installed, so this review does not claim a Safari device test.

## Automated validation

- 88 focused Python tests passed across feed selection and refresh, favorites, Brief positioning, chronology, founder welcome, units, maps, PWA assets, and report generation.
- All 195 JavaScript tests passed, including carousel controls, resize alignment, report loading, unit conversion, dependency sharing, cancellation and browser-cache restoration.
- JavaScript syntax and patch whitespace checks passed.
- The broader Python suite still has 14 failures and two errors, plus one skip. The identical failures and errors were reproduced in a clean archive of the unchanged main commit `11ec76b`: stale auth/navigation/gallery expectations and exposure recommendation fixtures. No new failing test cases remain from this change. Existing unrelated local README additions and the report-prompt edit were excluded from the commit.
