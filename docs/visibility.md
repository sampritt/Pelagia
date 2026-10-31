# Visibility history

The dive site page requests the existing authenticated conditions endpoint after rendering. Its shared SQLite marine cache includes a trailing 30 UTC-day KD490 series. The cache expires after 15 minutes (or at the site's next midnight), with the existing atomic lease preventing duplicate fetches across workers. Visibility loads together with the other ocean conditions using their shared skeleton lifecycle. The SVG renderer draws a smooth line with an area fill, without point markers. It smoothly connects available measurements across missing days; interpolation is visual only and the stored data still records missing measurements. The curve ends at the latest measurement.

Copernicus multi-year daily L3 multi-sensor transparency is preferred when available; near-real-time L3 extends the tail and can fill a missing multi-year observation. Each selected measurement carries its dataset, pixel coordinates, and distance. The nearest finite positive pixel within 15 km is used. Dates without measurements remain null in the stored data; the displayed curve connects the available measurements. These roughly 4 km satellite pixels describe surface waters; offshore neighbors may not describe local visibility at diving depth. No temporal interpolation or L4 gap filling is used.

## Credentials

Set `COPERNICUS_MARINE_CREDS` to the **entire encoded contents** of `.copernicusmarine/.copernicusmarine-credentials`, as produced by `copernicusmarine login`. It encodes a username/password configuration; it is not a bearer API token. The worker decodes it in memory and passes `username` and `password` to the toolbox. No credential file is written and credentials are not returned to the client or included in the report prompt. In local development, an absent variable uses the toolbox's normal credentials discovery, including the saved login file. The environment variable must be set on the deployed service and the service restarted to pick it up.

The toolbox is pinned in `requirements.txt`; install requirements with the same Python environment used by Gunicorn. The two source requests run concurrently in a child process with at most two source tasks, alongside the weather fetch, with a 24-second overall timeout. Longitude ranges within each source remain sequential. Results merge deterministically with multi-year observations preferred regardless of completion order. Failure leaves visibility unavailable without failing weather or the daily report. Results, including missing visibility, are cached with the marine response for 15 minutes. API requests and subprocess diagnostics never expose credentials to the UI.

## Pelagia clarity categories

| Label | KD490 (m⁻¹) |
| --- | --- |
| Excellent | 0 < KD490 ≤ 0.05 |
| Good | 0.05 < KD490 ≤ 0.10 |
| Fair | 0.10 < KD490 ≤ 0.20 |
| Poor | 0.20 < KD490 ≤ 0.30 |
| Very poor | KD490 > 0.30 |

These are fixed Pelagia product thresholds, not official Copernicus diver-visibility classes. The [Copernicus Ocean Colour manual](https://documentation.marine.copernicus.eu/PUM/CMEMS-OC-PUM.pdf) defines KD490 as diffuse attenuation of downwelling irradiance, in inverse metres. The [quality document](https://documentation.marine.copernicus.eu/QUID/CMEMS-OC-QUID-009-101to104-111-113-116-118.pdf) describes the retrieval and its validation. Neither supplies a validated five-category diver visibility scale.

The cutoffs span substantially different optical conditions: their reciprocal attenuation lengths are 20, 10, 5, and about 3.3 metres. This supplies a physically interpretable progression without tuning labels to one site's monthly distribution. These lengths describe vertical irradiance decay, not horizontal viewing distances. Categories should eventually be calibrated against paired dive observations. Missing/invalid values have no category.

Only the Y-axis text is categorical. The line remains a continuous, inverse linear function of the original KD490 measurements: clearer days sit higher. The scale includes at least 0–0.35 m⁻¹ and expands for higher attenuation; it never rounds values to category centers, and the smooth curve does not overshoot local extrema. Exact attenuation and category remain available to assistive technology and pointer inspection. The visible card contains only its title, axes, and chart.

Daily report generation waits for the combined marine response, including visibility or its completed no-data result. Daily reports receive the raw daily values, dates, categories and source metadata with the cached conditions. The prompt permits qualitative recent visibility observations using the word “visibility” instead of technical measurement terminology, while excluding unsupported predictions and visibility distances. Missing visibility does not block otherwise complete reports.
