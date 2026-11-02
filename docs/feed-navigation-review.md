# Home and Feed design review

Home (`/home`) retains The Dive Brief and site reports. The community dive log moves to the signed-in Feed view (`/feed`). Desktop and mobile navigation share the order Home, Explore, Log dive, Feed, Profile, with an activity icon for Feed. Dive details select Feed; the brief returns to Home.

The views reuse Pelagia’s colors, typography, card surfaces, icon stroke weights, content widths and desktop summary rail. Mobile has five equal tabs with existing safe-area spacing, touch feedback and selected states. At compact desktop widths, the Profile tab provides account access while redundant header account controls are hidden, keeping navigation clear of the search field. Home and Feed show loading placeholders appropriate to their content. Returning from the brief preserves its expanded preview and restores focus and scroll.

## Validation

- Visually reviewed Home and Feed at 320, 390, 768, 821, 1024 and 1440 pixels.
- Automated layout checks passed for both views at 13 widths from 320 to 1440 pixels: no document overflow, clipped navigation links or header overlap; consistent tab order and active state; appropriate content separation.
- Browser interaction checks cover desktop and touch mobile: tab navigation, likes, comments, dive-detail selection, sharing, tapping the active tab to return to the top, brief return to Home, Back/Forward and destination-specific loading placeholders.
- All 182 feature and integration tests passed, including navigation, login destinations, chronology, unit preferences, site reports, brief, sharing and Garmin gallery coverage.
- The full suite ran 370 tests: 362 passed, one skipped and seven exposure-recommendation errors. The same seven errors reproduce on unchanged main; they are outside this navigation change.
- All 187 JavaScript tests passed, including separate Home/Feed loading layouts and the existing brief-preview behavior. JavaScript syntax and Git whitespace checks passed.

Design sign-off: approved for the Home/Feed split after desktop, tablet and mobile review. Browser validation uses Chrome desktop and touch emulation; physical-device testing was not performed.

Local review screenshots, browser results and test logs are in `output/feed-view-review/`.
