# Forecast tag consistency correction

Forecast now uses Explore's actual `explore-filter` component rather than custom site-button styling. Selected and unselected tags share Explore's typography, 9px/17px padding, 44px minimum height, pill border, colors, hover/active styles and focus ring. The Forecast focus override excludes these shared buttons.

The site group sits below the dates in one nonwrapping native horizontal scroller. Individual names remain on one line, with their full text reachable by swiping. Scrolling the sites does not select a site or move the dates or stats. Keyboard selection, focus and browser Back reveal the relevant tag. Extra scroller padding preserves the shared focus ring without changing alignment with the dates and card. The loading skeleton uses one row of matching pill shapes.

Browser validation compared computed styles against the actual Explore page for selected, unselected and focused controls; all compared component styles match exactly. Reviewed screenshots at 320, 360, 390, 430, 768, 1024 and 1440px widths, 844 × 390 landscape, and 125% text. All tags retain a single baseline and one line of text, with no horizontal page overflow. Touch emulation scrolled the site strip 261px while dates and stats stayed at 0px and selection stayed unchanged. Tapping a revealed site, Arrow/Home/End navigation and Back restoration pass. No browser errors occurred. Touch validation used Chromium emulation.

All 212 JavaScript tests, 15 focused Forecast/PWA Python tests, and whitespace checks pass. Local screenshots and measurements are in `output/forecast-tag-consistency/`.

Signed off for Explore-consistent site tags and single-row horizontal scrolling. This correction supersedes the custom wrapping site buttons described in the earlier week-and-tides review.
