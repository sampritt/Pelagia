# Feed site reports: design sign-off

October 31, 2026

**Approved for main.** Featured and followed sites now share a compact, aligned card layout that uses Pelagia's existing Avenir typography, ocean colors, white surfaces, corner radii and focus treatments.

- Add a small, accessible **Site reports** heading above both populated and empty states.
- Move the featured marker beside **Today’s report**, removing the reserved label space above every site identity. Use quieter sentence-case labels.
- Share content-sized identity, conditions, label and report rows across cards. Long names and condition labels stay aligned without a fixed-height identity spacer.
- Use consistent 20px desktop / 16px phone card insets, 16px spacing around conditions, and a 12px inset below the divider. Remove stacked section and carousel bottom padding so the next feed card follows the normal feed rhythm.
- Increase condition labels and detail text to 11px at the default text size, including narrow phones. Balance wrapped condition details. Keep report previews at four lines and fit all four skeleton lines into the same reserved space.
- Retain two cards in wide feed columns, one card with a next-card preview in narrow columns, and a full-width single card. Preserve native scrolling, snap positions, keyboard access and whole-card report links.

Validation passed using a disposable local fixture database and controlled report/forecast responses:

- **82 browser checks**, including 0, 1, 3 and 11 cards across 14 viewport widths from 320–1440px; long site names and locations; missing coordinates; 125% and 200% text sizing; long condition labels; loading, short and unavailable reports; keyboard navigation and visible focus; emulated native touch swiping; report deep links, browser Back and the adjacent Dive Brief disclosure.
- No document overflow, overlapping card rows, unequal card heights, clipped skeleton lines, or browser JavaScript errors. Loading and completed reports retained the same card height.
- Python: **364 tests run, one existing skip, no failures**.
- JavaScript: **175 tests passed**.
- `git diff --check` passed.

Final desktop, tablet, phone, empty-state, single-card, loading and large-text screenshots were visually reviewed. Screenshots, the browser harness, machine-readable results and suite logs are retained locally in `output/site-reports-polish/`.

Browser verification used local Chrome and touch emulation. Physical devices and Safari were not exercised. The layout uses CSS subgrid and container queries. No production accounts, stored reports or billable generation services were changed during validation.
