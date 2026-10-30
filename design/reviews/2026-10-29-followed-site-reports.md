# Followed dive sites: design and UX sign-off

October 29, 2026

**Approved for main.** The Site reports section prioritizes the daily outlook, with compact site identities and predictable card sizing that match Pelagia's existing surfaces, ocean colors, typography and actions. The final interaction is a quiet, native horizontal track: no site count, position text, arrows or visible scrollbar.

## Design decisions

- Replace the large map panels with 56px mobile / 64px desktop map thumbnails. Names and locations support two lines, retain their complete accessible text and link to the site. Missing coordinates use a compass placeholder.
- Show two complete cards in wider feed columns and one card with a preview of the next in narrower columns. A single followed site fills the available width. Container queries adapt to the actual feed column, including desktops with a profile rail.
- Keep four-line report previews aligned across short, long, loading and unavailable reports. Read more expands only its own report; View site remains a separate, explicit action. The action grid also accommodates enlarged text.
- Keep Explore in the section heading alongside the date.
- Support touch swipes and trackpad scrolling without visible carousel chrome. The focused track also supports keyboard Left/Right/Home/End and retains a visible focus state.
- Give the empty state an explanation and a direct Explore action. Unavailable reports retain a route to site conditions. Loading reserves the report's space; stalled requests terminate, outstanding work stops on departure, and interrupted reports resume after browser-cache restoration.
- Render map tiles using the thumbnail's actual dimensions, preserving the location beneath the centered pin.

## Validation

A disposable fixture database and local Chrome browser exercised 0, 1, 2, 3 and 10 followed sites at 320, 360, 390, 430, 560, 640, 641, 768, 820, 900, 901, 1024, 1280 and 1440px: **70 layout combinations**. Assertions checked document overflow, section containment, aligned collapsed cards, map-pin alignment and touch-target heights.

**102 browser checks passed**, including the layout matrix, long names, short and expanded reports, missing coordinates, delayed loading, unavailable responses, 125% and 200% text sizing, actual emulated touch dragging, focus retention, site/header links, Explore navigation, browser Back, no-JavaScript navigation, and opening/closing Dive Brief beside the redesigned section. A final follow-up confirmed hidden scrollbars, absent counts and controls, swipe/trackpad overflow, and keyboard access at 320, 390, 768 and 1440px. No browser JavaScript errors occurred.

Repository checks passed:

- Python: 338 tests run, one existing skip, no failures (`.venv312/bin/python -m unittest discover -s tests -p 'test_*.py'`).
- JavaScript: 171 tests passed (`node --test tests/*.cjs`), including keyboard track behavior, report expansion, dependency loading, request timeout/cancellation, restoration and thumbnail geography.
- `git diff --check` passed.

Local screenshots and the machine-readable browser results are in `output/followed-sites-overhaul/`. Reports and forecast dependencies used controlled fixture responses; no paid generation calls or production account mutations were needed. Mobile verification used Chrome touch emulation; physical iOS/Android devices and Safari were not exercised.
