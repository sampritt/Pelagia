# Public Explore search

Added Explore between Product and The Dive Brief in the shared landing navigation. `/search` presents Search Pelagia over the existing coral photograph, with a transparent search field and no document scrolling. The navigation is shared by the landing page, public search, and anonymous Explore results. The requested prompt wraps on narrow screens, and suggestions scroll within the available viewport. Visual viewport changes move the search above a mobile keyboard without adding page scrolling.

Public discovery reuses the app's autocomplete, regional and nearby feeds, radius controls, units, filters, and pagination. Anonymous autocomplete never queries or returns users; the public search form also excludes accounts when opened by a signed-in user. Anonymous searches do not write account preferences. Signed-in app searches retain account suggestions and saved preferences.

Public site and center destinations use `/explore/dive-sites/<id>` and `/explore/dive-centers/<id>`. These reuse the existing preview rendering and account gates; signed-in visitors continue to the complete profile. Existing shared URLs remain supported.

## Verification and sign-off

- Reviewed screenshots at widths 320, 390, 430, 768, 900, 1024, 1440, and 1920, plus 844×390 landscape and 390×380 compact viewport. No horizontal overflow or vertical scrolling on the initial search page.
- Exercised mobile touch, menu dismissal, Escape, keyboard selection, suggestions during viewport resizing, region selection, free-text submission, center/site filters, pagination, radius changes, reload restoration, empty/error states, and public preview gates. No browser JavaScript errors. Navigation remains visible without JavaScript.
- 40 Explore Python tests and 14 site/center preview tests pass. All 214 JavaScript tests pass; the 20 search/Explore JavaScript checks were rerun after the final interaction changes.
- Full Python run: 497 tests, 493 passed, one skipped, three existing failures. All three reproduce in a clean archive of the original `main` commit `62ec1d5`: `test_default_signup_and_returning_login_show_welcome` expects an absent “Site reports” heading; `test_api_refreshes_region_scope_and_history_outside_forecast_cache` and `test_kicker_rock_weight_uses_cached_site_classification_despite_site_logs` receive no exposure recommendation from their forecast fixture.
- Browser geocoding used deterministic fixture responses; the external geocoder was not exercised. Mobile verification used browser emulation, including a reduced viewport for keyboard space.
- JavaScript syntax and Git whitespace checks pass. Local screenshots and browser validation are in `output/public-search-review/` and are not committed.

Signed off for the requested public discovery scope. The three baseline test failures are unrelated to this change.
