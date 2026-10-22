# Full app validation

October 21, 2026

## Changes validated

- Visibility sliders advance by 1 m or 5 ft. Visibility displayed in feet rounds to the nearest 5 on the form, dive details, site conditions and chart tooltips.
- Full-cylinder pressure displays use the requested 200 bar / 3000 psi labels. Exact pressure conversion, stored measurements, form serialization and SAC calculations retain their physical values. Switching units and blurring rounded fields preserve those values.
- Conditions includes Water type immediately after water temperature, with unset (`-`), Fresh and Salt choices. It uses the same card styling as the other conditions, a two-column desktop layout and a single column on phones. Selections save, restore on edit, clear, and appear in dive details. Existing databases gain an unset default without rewriting dive measurements.

## Responsive and visual review

Reviewed 25 page/state combinations at 320×740, 390×844, 768×1024, 1024×900, 1440×1000 and 844×390. Coverage includes landing, login/signup, email start/verification/signup, Google username setup, feed, owner/other/long-name profiles, settings, new/edit/detail dives, populated/empty sites and centers, public dive sharing, public/authenticated legal pages, and offline.

The initial sweep also covered 14 authenticated views in installed-app mode at phone and desktop widths: 178 layout checks passed. After refinements, 78 desktop/mobile page and installed-mode captures passed again. The condition controls were additionally checked at all six widths. No horizontal document overflow, broken rendered images or JavaScript page errors were found. Desktop and mobile contact sheets and full captures were visually inspected, including conditions, long names/emails, chart tables, maps, missing data and sharing dialogs.

## Interactive validation

- Primary navigation, profile settings, active navigation states, browser history, keyboard skip links and unit radios, delayed navigation skeletons, reduced motion, global search, recoverable search errors and Escape dismissal.
- All profile chart metrics and data tables, bio save/cancel, certification selection/removal and profile-photo upload.
- Settings persistence, independent unit preferences, starting dive count, unsaved-change discard, legal links and logout.
- Site, center, buddy and species autocomplete; unit changes; gas calculations; dive/current multi-selects; current strength; exposure; photo previews/uploads/removal; dive create/edit/delete; correct detail-page destinations after saving.
- Water type pointer and keyboard selection, matching condition-card styling, 1 m / 5 ft visibility slider steps, 200 bar / 3000 psi labels, and actual browser save/reopen/clear with exact measurement preservation.
- Dive, site and center likes/comments; sharing carousel, clipboard copy, JPEG/PNG downloads and native-share fallback.
- Local Google/email onboarding and code verification; install guidance; actual service-worker control and offline fallback; exclusion of private settings from caches; offline submission blocking and reconnection with unsaved form contents retained.

## Results and limits

- 114 Python tests passed.
- 56 JavaScript tests passed.
- Browser layout and interaction checks passed without page errors.
- `git diff --check` passed.

Validation used isolated local SQLite data, accounts and uploads. Screenshots and machine-readable results are retained locally in `output/full-app-validation/`. Chrome supplied viewport testing and installed-mode simulation; external Google/Resend delivery, Safari/WebKit and physical-device native install/share sheets were not exercised. Provider and native-share branches are additionally covered by mocked automated tests.

Unrelated reference-data enrichment changes and earlier local review artifacts were left outside this commit.
