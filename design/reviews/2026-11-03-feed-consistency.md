# Feed consistency design sign-off

Signed off for this visual pass after local browser review of the actual Flask templates and interactions with isolated, deterministic data.

Reports and logged dives now share a quieter type scale, card borders, shadows, and blue focus treatment. Cards no longer jump on hover. Galleries lead with map → depth profile → photos, expose a clearer next-slide peek, and fill the width when only one visual exists. Expanded dives use the same gallery, with clickable, accessible indicators, arrow keys, Home/End, and reduced-motion support. Depth charts use a visible title, legible fixed-size axes, subtle grid and fill, and one blue line. Expanded metrics, notes, and comments share calmer panels; comments support multiline drafts and announce successful posting.

Reviewed at 320, 390, 430, 768, 1024, and 1440 px, plus 844 × 390 landscape. No horizontal page overflow. Browser checks covered touch swiping, keyboard navigation, single/no-media and long-title cases, map tile sizing, report pagination/loading/unavailable states, report destinations, likes, comment focus/posting/persistence/failure drafts, edit/share entry points, and public-preview gating. No browser script errors. Screenshots and executable local review fixtures: `output/feed-consistency-review/`. These are Chromium desktop/mobile-emulation captures, not physical-device or production QA.

Validation: all 198 JavaScript tests pass. The targeted Python run passed 65 tests, plus the added gallery contract and three import/photo regression checks. Full Python discovery ran 409 tests: 12 failure reports, two errors, one skip. Every remaining failure/error reproduces on the starting revision (27a36e0), with the pre-existing local site-report edit preserved: obsolete navigation expectations in email/Explore/Garmin tests and two exposure-recommendation data fixtures. No new full-suite failures; two stale gallery expectations were corrected. JS syntax and patch whitespace checks pass.

Existing README and site-report-generation edits, local credentials/data, and unrelated output are excluded from this change.
