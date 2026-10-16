# Pelagia layout and design audit

October 16, 2026

This pass preserves the ocean imagery, light surfaces, blue navigation, existing page structure, and application behavior. It changes presentation and adds small accessibility improvements.

| Area | Finding and polish |
| --- | --- |
| Login, signup, username setup | The Google button was an isolated, narrow element inside a large card. It now fills the card, with consistent heading, switch-link, and legal-copy spacing. Heading color is explicit, columns can shrink safely, and page padding respects device safe areas. |
| Shared typography | Intermediate heavy font weights selected excessively heavy faces on the installed font. Standardized those weights to 700 and improved heading line height. |
| Feed | Added a clear page heading, filled the desktop content grid, reduced card shadow, and made the sidebar date smaller than the dive-count metric. |
| New and edit dive | Centered the existing form width, refined section and footer spacing, and retained every field, control, submission, unit conversion, and calculation. |
| Dive detail and public preview | Improved long-text wrapping, avatar sizing, and phone action placement. Very narrow phones allow a separate action row so author names retain space. |
| Diver, site, and center profiles | Retained identity, maps, metrics, charts, and logbook layouts. Improved wrapping, touch targets, section headings, and form alignment through shared styles. |
| Comments and notes | Preserved intentional line breaks, allowed long strings to wrap, aligned the comment input and Post button, and added accessible input labels. |
| Settings and sharing | Settings now scroll within a short viewport. Sharing heading and close control retain space on small phones. |
| Welcome, legal, offline | Checked responsive layout; allowed welcome navigation and footer to wrap, increased footer link targets, and tightened legal-page spacing and hierarchy. |
| Keyboard access | Added a skip-to-content link and visible disclosure focus styling. |

## Verification

Used a disposable local database and sample uploads, without touching the app's real accounts or data. Browser checks covered 15 routes at widths of 320, 768, 1024, and 1440 pixels: landing, login, signup, username setup, feed, profile, new dive, dive detail, edit dive, site, center, public dive preview, terms, privacy, and offline. All 60 checks had no document-level horizontal overflow or error-page titles. Also inspected 390-pixel phone layouts and opened settings and sharing dialogs.

An isolated checkout containing this design pass over the original revision passed all 82 Python tests. The shared working directory passed 80/82: two tests still expect “SAC over time,” while separate concurrent profile edits use “SAC rate (L/min).” Those profile edits and tests were preserved.

JavaScript checks passed 41/43. The two failures expect “12.0 L/min” while existing code returns “12 L/min”; both failures also reproduce on the original revision. This pass does not change JavaScript or SAC behavior.

Google OAuth and native phone installation/sharing were not exercised against external services. Form, sharing, autocomplete, unit, and PWA behavior remain covered by the existing regression suites. Responsive browser checks do not replace testing on physical phones.
