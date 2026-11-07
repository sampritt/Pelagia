# Forecast week and tide design sign-off

The previous calendar and site pills competed for attention, and the tide plot used different insets from its heading. Its labels followed individual point heights into cramped positions. Formatting minutes did not improve the underlying hourly peak detection.

Forecast now opens with seven site-local dates, from today through six days ahead. Unselected dates have no box treatment; the chosen date retains Pelagia's existing blue selection. All seven fit across desktop. On phones, a native horizontal date scroller reveals the remaining dates with a partial neighboring date as the affordance. Scrolling that strip changes neither the selected date nor the site. Arrow keys, Home and End select and reveal dates without scrolling the whole page. Smaller site buttons sit beneath the dates, flow horizontally, and wrap long names without truncating them. Their typography, spacing and selected treatment are quieter than the previous Explore pills. The navigation skeleton follows the same order and includes seven dates.

The tide heading, plot and axis share 24px desktop / 18px phone insets. The 180px chart reserves separate aligned rows for high labels, the curve, low labels and the time axis. Larger type, short dotted leaders and edge-clamped labels keep times readable, including events near midnight. A monotone cubic curve passes through the model samples and fitted vertices without overshooting. Missing samples and discontinuous hours break the curve. The chart observes its own container so changes in breakpoint padding are measured correctly during resize.

High and low turns use the vertex of a parabola fitted to three consecutive hourly samples. Plateaus use their midpoint; incomplete or nonconsecutive samples cannot produce a turn. The fitted height and time are inserted into the plotted data so markers stay on the curve. Times round to minutes in the site's timezone. “Est. local time” and accessible descriptions identify these as interpolated model estimates; minute display does not imply tide-station accuracy. Events are assigned to local calendar days using their fitted timestamps. The existing seven-day upstream requests and shared raw forecast cache supply the full week without new date-switch requests.

## Validation

- Inspected Chromium screenshots at 320, 360, 390, 430, 768, 1024 and 1440px widths, plus 844 × 390 landscape and 125% text. No page overflow, clipped tide text or overlapping labels across all seven dates. The heading and plot left edges match exactly; grouped table headings remain centered.
- All seven dates retain eight rows, selected state and chart links. Date switching makes no requests; loaded site switching uses the client cache. Site and date selection, including the scrolled final date, survive browser Back.
- Chromium touch emulation scrolled the dates 108px while leaving the stats table at 0px and the selected date unchanged. Tapping the last date selects it. This is emulation, not a physical-device review.
- Featured-only, multiple-site, long-name, imperial, empty, unavailable/retry, delayed loading and HTTP 202 polling states were checked. Missing coordinates keep a usable calendar and issue no forecast request. Loading and completed card heights both measure 640.5px at the reviewed phone size.
- Resizing the same loaded page from phone to desktop and back updates the SVG width to its actual container. Scrolling to the end clears the fixed mobile navigation.
- All 212 JavaScript tests and 64 focused Python tests pass. Coverage includes sub-hour high/low vertices, plateaus, gaps, flat data, local-midnight assignment, DST and fractional-offset calendars, curve overshoot, minute rounding and the seven-date loading skeleton. Whitespace checks pass.

Screenshots and measurements are saved locally in `output/forecast-refinement/`.

Signed off as Pelagia Design Lead for the Forecast calendar, site controls and tide chart changes.
