# Dive share artwork review — updated October 24, 2026

The five-style carousel combines Pelagia's supplied white fin/wordmark, ocean palette and clear activity stats. The splash uses continuous shading across its image rather than separate text and media panels.

## Shared stat rule

The splash and the vertical, horizontal and stacked PNGs select the first four available values in this exact order:

1. Max depth
2. Average depth
3. Dive time
4. Gas mix
5. SAC rate
6. Weight
7. Exposure

All selected values share one type size within their image. The longest value determines the size for every stat, so neither the splash nor a PNG makes individual stats smaller. Missing values are skipped; fewer than four are shown when necessary. Stored zeroes remain valid recorded measurements; negative and nonfinite numeric values are omitted. Depth and weight use the viewer's unit preferences. The splash no longer duplicates average depth as a smaller footer value.

The map PNG remains the exception: it shows only max depth and dive time.

## Five export styles

- Splash JPEG: 1200 × 630, full-bleed photo or map, smooth ocean-colored fade, site name and location, one row of equally sized selected stats, diver/date footer. Photo splashes include a 314 × 252 rounded map inset in the upper-right. Without a readable photo, the map fills the background with its pin clear of the title.
- Vertical PNG: 720 × 1280, logo at top and one column of selected stats. No site name.
- Horizontal PNG: 1600 × 600, one row of selected stats and logo below. No site name.
- Stacked PNG: 1200 × 780, site name, two-column grid of selected stats, logo below.
- Map PNG: 960 × 1200, site name, rounded map, max depth/time beneath it, logo below. An unavailable map shows an outline/message rather than a fabricated location.

PNG canvases and gaps remain transparent, with a local shadow to improve legibility over footage. Long site names retain all words; trailing parenthetical aliases stay together when they fit. Public share data includes the eligible display fields; raw tank pressures, notes, buddy identities and comments remain excluded.

## Verification

27 Python dive-sharing tests, 8 unit-preference tests, 5 static-map tests and 16 JavaScript sharing tests passed (56 total). Stat selection is checked across all 128 availability combinations, plus identical ordered selection and equal type size across the four relevant renderers, weight conversions, map-only stats, removed vertical/horizontal titles, full long titles, PNG alpha, downloads and carousel switching. `git diff --check` passed.

The earlier generated samples are in `output/share-artifacts-review/`: `splash-photo.jpg`, `transparent-layouts-review.jpg`, and each `transparent-<vertical|horizontal|stacked|map>.png` with a solid-background `-preview.jpg`. Map proofs use local test tiles. Earlier browser screenshots in the same folder predate the latest stat priority/title changes. A previous live tile fetch was blocked by automatic approval review over sample coordinate disclosure, so geographic-map appearance remains unverified against live tiles.


## Final design sign-off

Reviewed all five layouts at export size and phone-scale width, including seven representative scenarios: a complete log, Trimix without average depth, weight/exposure fallbacks in ft/lb, three recorded stats, two recorded stats, a long reserve name, and unavailable coordinates. Also reviewed all four PNGs over an existing Pelagia ocean photo inside 1080 × 1920 Reel frames, plus bright and dark backing proofs.

Final small refinements: stat labels are now consistently 24 px for stronger small-screen readability; the title-free horizontal composition is vertically centered; the stacked composition uses more balanced title/grid/logo spacing, including a separate two-stat balance; and the splash omits the redundant caption below its map inset. Equal stat-value sizing, the first-four priority rule, and the title-free vertical/horizontal exports remain intact.

Signed off for the export compositions, PNG transparency, text/brand hierarchy, consistent spacing and reviewed footage contrasts. The geographic appearance of live map tiles remains outside this visual sign-off; map proofs use local test tiles, while map placement, caching and fallback are covered by tests.

Final local proofs are in `output/share-artifacts-final-review/`: `all-five-layouts.jpg`, `reels-proof.jpg`, `contrast-proof.jpg`, and individual exports for each reviewed scenario. These illustrative proofs are not application runtime assets.
