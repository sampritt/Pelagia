# Public search focus follow-up

The original visual-viewport handler resized and re-centered the entire search hero when the keyboard opened. Reproducing a 390×844 mobile layout with a visual viewport reduced to 380px moved the search input from y=425px to y=144px, shortened it from 80px to 60px, and changed the title font size. The previous review resized the whole browser viewport, which did not adequately check this keyboard transition.

Removed the visual-viewport-driven layout and suggestion-height handlers, the compact-mode switch, and the document scroll lock. The hero now has a stable minimum height and content position. Suggestions participate in document flow with a bounded scrollable list, and normal page scrolling can reveal them above the keyboard. The coral backdrop stays fixed while the page scrolls. Input typography explicitly overrides the app's general responsive input rule to stay consistent in landscape.

Updated the native placeholder to “Search dive sites, locations…” and removed the separate mobile placeholder overlay. The new “← Back to home” link reuses the sign-in flow's `auth-back` class and markup. It has the same colors, typography, spacing, touch target, hover state, and keyboard focus ring; only its position is specific to the search page.

## Verification and sign-off

- Reviewed widths 320, 375, 390, 430, 768, 900, 1024, 1440, and 1920, including 320×568 and 844×390 landscape.
- Checked input/title document coordinates, dimensions, and font sizes before focus, after shrinking the visual viewport while keeping the layout viewport unchanged, after suggestions appear, and after dismissing the keyboard. All remain unchanged. At 390×844 the input stays at y=276px and 64px high.
- Compared the actual computed normal, hover, and keyboard-focus styles of the back link against `/login` at 390px and 1440px; all checked values match.
- Verified touch selection, keyboard selection and Escape, Home navigation, landing navigation, region and free-text searches, pagination, site/center filters, radius persistence, both preview gates, empty/error states, and no-JavaScript navigation. No browser JavaScript errors or horizontal overflow.
- 40 Explore Python tests and 20 search/Explore JavaScript tests pass. JavaScript syntax and Git whitespace checks pass.
- Review uses Chromium mobile emulation with simulated visual-viewport keyboard events, not a physical iOS keyboard. External geocoding remains mocked in the browser fixture.

Signed off for the focus correction and style follow-up. Screenshots and validation are local in `output/public-search-focus-review/`.
