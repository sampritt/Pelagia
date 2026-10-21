# Navigation and profile UX review

October 21, 2026

## Completed changes

- Removed page Back arrows from installed-app navigation, authentication and legal views. Legal pages retain a Pelagia brand link home.
- Removed the first-letter avatars from dive site and center headers. Names and locations align with the header padding, with actions alongside on desktop and below on phones. The site map banner remains in place.
- Moved profile Settings to `/you/settings`, reached through the existing gear link. The page contains units, starting dive count, account email, legal links, attribution and logout. Save confirms success and stays on Settings. Profile remains active in the primary navigation, and delayed navigation uses the shared form skeleton.
- New dive submissions now open the saved dive's detail page. Edit submissions continue to open that dive's detail page. Delete keeps its existing destination.

## Final responsive and visual pass

Reviewed 25 page/state combinations at 320×740, 390×844, 768×1024, 1024×900, 1440×1000 and 844×390. Coverage includes the landing page, login/signup, email start/verification/username setup, Google username setup, feed, owner/other-diver/long-username profiles, Settings, new/edit/detail dive views, site/center views with populated and missing data, public shared dives, public/authenticated terms and privacy, and offline.

Also reviewed all fourteen authenticated views in installed-app mode at phone and desktop widths: **178 layout checks passed**. No document-level horizontal overflow, broken rendered images, remaining page Back controls, or JavaScript page errors were detected. Reviewed desktop/mobile contact sheets, complete phone-page sections, map and photo placement, chart/table layout, long names and emails, missing-data states, and sharing previews in portrait and landscape. Final captures were taken after scrolling settled so fixed navigation is captured in its correct position.

## Feature checks

- Primary navigation, Settings gear navigation, active navigation states, delayed page skeletons, browser history, keyboard skip link and unit controls, reduced motion, global search, error recovery and Escape dismissal.
- All four profile history metrics and recorded-value tables, bio save/cancel, certification removal/selection and automatic profile-photo upload.
- Settings persistence across reloads, independent unit preferences, starting dive count, profile updates, leaving without saving, legal links and logout.
- Site/center/buddy/species autocomplete, metric/imperial conversion, gas calculations, exposure, dive/current multi-selects, photo uploads/removal, and dive create/edit/delete. Confirmed actual browser navigation to the matching detail page after both Save dive and Save changes.
- Likes and comments on dives, sites and centers; both sharing styles; copying links; JPEG/PNG downloads; native-sharing fallback; installation instructions; offline submission blocking and reconnection.
- Local Google/email onboarding and code verification reach the profile and Settings. The actual service worker controls navigation, keeps private Settings out of its cache, and serves the branded offline fallback.

## Regression results and evidence

- **112 Python tests passed.** Includes authenticated Settings access, account isolation, invalid-input atomicity, unit preference coverage and saved-dive redirect checks.
- **55 JavaScript tests passed.** Removed obsolete modal/Back-handler tests and added Settings to the navigation-loading coverage.
- `git diff --check` passed. No outstanding application regressions were found in this pass.

Machine-readable browser results and representative desktop/mobile screenshots are saved in `output/final-navigation-review/`. Additional local captures include the complete page/contact-sheet review and sharing dialogs.

Validation used disposable local accounts, uploads and SQLite data. Browser coverage used Chrome viewport testing and installed-mode simulation; external Google/Resend delivery and physical-device native share/install sheets were not exercised. Authentication/provider behavior and native-sharing branches also remain covered by the existing mocked suites.
