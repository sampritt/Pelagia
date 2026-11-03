# Feed gallery design review

Signed off after reviewing complete dive-card fixtures in the local browser at 320, 390, and 1440 px.

- Multi-slide galleries reserve 28 px, including a 10 px gap, to expose the next visual. Single visuals fill the track.
- Native horizontal scrolling and keyboard navigation retain graph → map → photo order. The final photo aligns to the right with the previous photo visible. No dots or navigation controls.
- Photo sizing targets direct image children, preventing map tiles from stretching. Tiles measure 256 × 256 px and remain centered through responsive resizing; ResizeObserver refreshes the map viewport.
- Graph labels occupy a fixed gutter. Both depth endpoints include units, time endpoints align with the plot, and fixed insets keep mobile and desktop spacing consistent.
- Verified no page overflow at narrow mobile width, map-only full-width layout, photo order, and loaded map tile proportions.

Validation: 19 Python tests (depth profile, unit preferences, static maps), two JavaScript map tests, JS syntax and patch whitespace checks passed.

Local screenshots: output/feed-gallery-refinement/mobile-320.png, desktop-1440.png, map-1440.png. These use representative card fixtures with existing Pelagia imagery; they are not production feed captures.
