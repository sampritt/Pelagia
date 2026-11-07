# Landing page refresh

Updated Plan to show **10,000+ dive sites**, **500+ marine species**, and **Global dive center registry**, with all three lead values sharing the same typography.

Replaced the five previous screen assets with the six supplied November 7 screenshots. Plan pairs Batu Bolong's overview with the forecast table and tide chart; Log shows location/metrics and air consumption; Track shows equipment recommendations and current conditions; Connect shows Gordon Rocks' logged dive. The existing CSS phone frames remain, with generic avatar and full-battery overlays calibrated to the new screenshots. The Connect chart uses a CSS crop of the same supplied chart, expanded across its card to cover the neighboring photo peek while preserving the depth trace. Original JPEG pixels remain unchanged. The six images total approximately 556 KiB, down from approximately 3 MiB for the previous five PNGs.

Refined paired-phone spacing on narrow screens, enlarged mobile account tap targets, rounded primary buttons, and added restrained press feedback and one-time section entrance transitions. Reduced-motion preferences disable transitions and immediately reveal content; navigation and content remain usable without JavaScript.

## Verification

- Browser layouts: 320, 390, 430, 768, 1024, 1440, and 1920 pixels wide; no document overflow, broken screen images, or JavaScript page errors.
- Reviewed desktop and mobile captures of all four sections and the full page, including the expanded Connect depth chart.
- Verified mobile menu opening, link selection, Escape with focus restoration, ArrowDown, outside click, anchor offsets, auth destinations, login/signup and legal routes, no-JavaScript rendering, entrance transitions, and live reduced-motion changes.
- Existing Python suites: 20 Google authentication tests, 6 PWA tests, and 20 Dive Brief tests passed.
- JavaScript syntax and Git whitespace checks passed.

Local browser captures and validation data: `output/landing-refresh-2026-11-07/` (not committed).
