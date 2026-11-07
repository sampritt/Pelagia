# Profile certification layout

The Add certification form previously extended about 52px beyond the left edge at a 320px viewport. Its mobile right alignment was relative to the small summary link rather than the available profile width.

The desktop popover now anchors to the profile headline and stays within its available width. At mobile widths, opening the editor gives it a full row and displays the form in the document flow, so it remains inside the profile card and the page can scroll naturally. The suggestions list is bounded by the viewport height and scrolls independently. Input sizing also permits the field to shrink within the card.

Validated in Chromium with touch emulation at 320, 360, 390, 430, 640, 641, 768, 1024 and 1440px widths, plus 844 × 390 landscape and a short 390 × 420 viewport. The form, field, suggestions and long labels stay inside the profile card without horizontal page overflow. Search, no results, loading, request failure, keyboard navigation, Escape, outside dismissal, adding, persistence after reload and removal pass. A long dive count that wraps the trigger also stays contained. No browser errors occurred.

All 15 profile Python tests and whitespace checks pass. Screenshots, the isolated preview and browser validation script are saved locally in `output/certification-layout-review/`.
