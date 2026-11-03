# One daily report on Home

Home, /feed, and /welcome now show one compact daily report between the Dive Brief and logged dives. When sites are followed, the site with the most recent local midnight wins; equal midnight instants use follow recency. The featured site appears only as the fallback when no sites are followed. Sites with missing coordinates fall back to follow recency when none have a known time zone.

Coordinate lookup uses the offline tzfpy boundary data and Python zoneinfo, including daylight saving and fractional-hour offsets. The pinned dependency includes its compatible tzdata requirement. No forecast requests or report generation are needed to choose the card. The dependency's coordinate order and zoneinfo integration follow its [official documentation](https://github.com/ringsaturn/tzfpy).

The card links directly to Reports. DAILY REPORT uses the exact existing FEATURED badge class; the featured fallback carries both badges. The small map, location, and two-line preview retain the existing card style. The mobile navigation order is Home, Reports, Log dive, Explore, Profile; active tab state and native links are preserved.

An authenticated, uncached selection endpoint updates the card at the next followed-site midnight, after restoring Home through browser Back, or after reconnecting. A replacement initializes its map and preserves keyboard focus. An unchanged selection keeps its loaded text without flashing a placeholder. Background tabs defer overdue work until visible; offline failures preserve the existing card and retry. Featured fallback also rechecks at the application day's boundary.

Reviewed actual rendered local fixtures at 1440, 1024, 768, 430, 390, and 320 px. Verified a single card for zero/one/three/ten followed sites, followed-versus-featured behavior, matching badges, long-name wrapping, two-line clipping, no horizontal overflow, and 44 px mobile navigation targets. Cards measured about 127 px on desktop and 163 px on mobile with the deliberately long two-line site name and wrapped badge.

Browser interaction checks passed for card tap and keyboard activation into Reports, active Reports and Explore tabs, browser Back into Home, unavailable-report copy, live local-midnight switching with map and focus preservation, and selection refresh on restored pages. No page errors occurred. Screenshots and measurements are local fixture captures in output/single-feed-report/, including validation.json.

Validation: 76 Python tests and 45 JavaScript tests passed. Coverage includes selection across midnight, daylight saving transitions, fractional-hour offsets, date-line ties, featured-to-followed mode changes, live replacement, unchanged-card preservation, offline retries, visibility, navigation, the Brief, units, maps, and PWA assets. JavaScript syntax and patch whitespace checks passed.
