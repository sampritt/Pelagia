# Home and Reports navigation review

Home now opens with the expanded Dive Brief followed by logged dives. The time-of-day greeting and site reports are removed. The existing /feed URL renders the same Home content for compatibility.

The former Feed navigation item is Reports, linking to /reports. Followed and featured site reports use a vertical list with full report text and content-sized cards. The sidebar summary remains available on desktop. Dive detail navigation belongs to Home.

Reviewed the real Home and Reports routes with local fixture data at 1440, 390, and 320 px. Confirmed active desktop/mobile navigation, expanded Brief, dive cards below the Brief, vertical report placement, loaded conditions, full report text, and no horizontal page/list overflow. Report API responses were deterministic fixtures in this preview.

Validation: 39 Python tests for favorites, page placement, Brief, units and maps; 31 JavaScript tests for report loading, navigation and loading states. Syntax and patch checks passed. Screenshots are in output/home-reports-move/.
