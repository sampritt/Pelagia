# Swell chart review and sign-off

The dive site view now includes Swell after Wind, using the existing marine chart card, bar styling, axes, spacing, loading states, and independent 7 days / 24h controls. Bars show swell height in the user's meters or feet setting. Daily bars use each site's local calendar day and its maximum swell height; the associated period comes from that same hourly sample. Periods appear as tiny whole-second values (for example, `4s`) centered at the wind arrows' top-row position, without a separate period label. Missing periods omit the annotation, and missing heights remain gaps.

The chart extends normalization of the swell data already fetched from Open-Meteo. Both ranges use the existing persisted marine forecast payload and its shared SQLite lease, expiry, coordinate invalidation, and retry behavior. Switching ranges makes no additional network requests. No new upstream request, field, cache table, or migration is required. Existing cached raw payloads produce the daily series on read.

Chromium visual review covered 320, 360, 390, 430, 768, 1024, and 1440 px widths, plus 844 × 390 landscape, both ranges, hourly start/end, metric and imperial heights, and unavailable data. Swell and Wind share 220 px plot height, identical card padding and width, and the same marker row center. Period labels use 10 px text and align to the exact bar center. Daily charts fit without horizontal scrolling; hourly charts retain a fixed Y axis and scroll inside the card. Headings and controls do not collide, and the page has no horizontal overflow. Browser screenshots were inspected for sizing, alignment, margins, typography, and consistency. Keyboard End reaches the last hour. A 390 px mobile touch-emulation swipe scrolled the hourly plot 266 px without page overflow. Touch validation used Chrome emulation, not a physical device.

Local screenshots and measurements: `output/swell-chart-review-2026-11-06/`.

Validation: all 27 marine Python tests and all 204 JavaScript tests pass; whitespace checks pass. Full Python discovery ran 477 tests with one skip, seven errors in exposure recommendation API tests, and one outdated Site reports expectation in the welcome test. The exact same eight failures were reproduced against unchanged main (`c6c6bed`) in an isolated baseline copy. They are outside this change.

Signed off for the requested Swell feature, with the existing full-suite failures documented above.
