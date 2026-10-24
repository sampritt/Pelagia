# Dive share artwork review — October 23, 2026

The original landscape export gave the text and media separate visual territories. The transparent export gave a large logo almost the same emphasis as the numbers. The revision borrows the clear activity-stat hierarchy familiar from fitness sharing while retaining Pelagia's supplied fin/wordmark and ocean palette.

## Implemented

- The 1200 × 630 JPEG uses a photo or map across the entire canvas. A continuous, eased ocean-colored scrim shades the title and lower stats without a vertical seam. Photo splashes now also include a 314 × 252 rounded map inset in the upper-right, with a subtle border and shadow. It uses the existing map zoom and centered site pin, and is omitted if coordinates or map tiles are unavailable. Without a readable photo, the map fills the background with its geographic center and pin in the open upper-right area.
- Max depth and dive time have larger figures and smaller units. Gas mix and a positive recorded SAC rate appear as secondary metrics, independently, only when available. Air, EANx and Trimix use the same label formatter as the logged dive. Average depth remains in the JPEG footer when recorded.
- Both exports use the supplied white Pelagia fin and wordmark. The transparent PNG keeps the site name, two primary metrics, optional secondary row and smaller logo. A local shadow supports use over light or busy footage. Its canvas and gaps remain transparent.
- Both formats retain full long site names and the viewer's depth units. The existing carousel, download formats and share-sheet behavior continue to work.
- The public data allowlist adds gas composition and saved SAC, without fetching raw tank pressures, notes, buddy identities or other private equipment fields.

## Verification

34 Python tests passed across dive sharing, static maps and unit preferences; all 14 JavaScript dive-sharing tests passed. Coverage includes optional metrics independently omitted, Air/EANx/Trimix, invalid SAC values, full titles, true PNG alpha, map pin geography, photo ordering/fallbacks, attachment downloads, and native sharing. `git diff --check` passed.

Generated samples are in `output/share-artifacts-review/`:

- `splash-photo.jpg`: full photo composition, with representative sample stats.
- `map-layout-proof.jpg`: actual map renderer and offset pin over local solid-color test tiles. This is a layout proof, not a geographic map preview.
- `stats-transparent.png`: actual exported PNG with optional stats.
- `stats-checkerboard-preview.jpg`: transparency visualization; the checkerboard is not in the PNG.
- `stats-minimal.png`: PNG with optional stats absent.
- `splash-long-title.jpg` and `stats-long-title.png`: wrapping and imperial-unit proofs.
- `reel-overlay-preview.jpg`: 9:16 composition using the PNG over a cropped existing Pelagia ocean image.
- `contrast-proof.jpg`: white overlay against ocean imagery and a bright background.

Automatic approval review rejected fetching public map tiles because it treated the sample coordinates as location disclosure. Map layout, tile placement, caching and fallback were verified with local test tiles; a live geographic-map preview was not fetched. No deployment was performed.

Follow-up validation: all 22 dive-sharing tests passed after adding the photo/map inset, including photo preservation and missing-coordinate/tile fallbacks. The updated `splash-photo.jpg` uses local test tiles for the inset.

Long-name follow-up: rendered “Kicker Rock (Leon Dormido)” in both formats at full export size and 390 px wide. Fixed the JPEG's awkward break inside the alternate name: it now reads “Kicker Rock” / “(Leon Dormido)”. The PNG retains the complete name on one line. The title-layout regression checks now use a photo with the upper-right map inset and verify the entire title stays inside the headline area for short, long and unbroken names. All 22 dive-sharing tests passed. Corresponding `kicker-rock-*` proofs are in the sample output directory; their maps use local test tiles.


## Five export styles

The carousel now contains splash JPEG, vertical PNG, horizontal PNG, stacked PNG and map PNG, in that order. Transparent stat layouts use a single shared value font size for all available metrics, fitting the longest value once so gas or SAC never receives smaller type than depth or time.

- Vertical: 720 × 1280, logo at top, one column of stats, site name at bottom.
- Horizontal: 1600 × 600, site name, one row of stats, logo below.
- Stacked: 1200 × 780, site name, two-column grid of equal-size stats, logo below.
- Map: 960 × 1200, site name, rounded map, max depth/time beneath, logo below. The canvas around these elements is transparent. An unavailable map has an explicit outline/message; it does not show a fabricated location.

`transparent-layouts-review.jpg` compares the four new PNGs on an illustrative solid background. The actual transparent exports are `transparent-vertical.png`, `transparent-horizontal.png`, `transparent-stacked.png` and `transparent-map.png`. Map proofs continue to use local test tiles.

Validation covers equal value sizes, optional metrics separately omitted, full long titles, RGBA/empty margins, layout-specific dimensions/download names, viewer depth units, map fallback, five-way carousel navigation and stale PNG preparation. The browser review confirms five pagination controls and the correct selected style.

Final five-style validation: 24 Python dive-sharing tests and 16 JavaScript sharing tests passed. Browser checks at 320 px and 390 px confirmed that the portrait exports, all five pagination controls, and copy/save/share actions fit without clipping. `carousel-phone-widths.png` is the unedited browser proof; map previews use local test tiles. `git diff --check` passed.
