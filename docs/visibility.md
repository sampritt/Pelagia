# Satellite visibility

Dive site pages request `/api/dive-sites/<id>/visibility/monthly` and `/daily`
independently of the existing marine forecast. Both require login and ocean
classification. The nearest NOAA grid cell is fixed to the site's coordinates;
missing observations never trigger a move to a distant pixel.

`pelagia/visibility.py` reads the actual ERDDAP time axis, then queries the latest
12 monthly samples (expanding backward past missing values) or the latest 30
daily samples (expanding backward until a valid day is found). Monthly composites
are NOAA science-quality **means**, as agreed, from `nesdisVHNSQkd490Monthly`.
Daily readings come from `nesdisVHNkd490Daily`. Time axis indices avoid ERDDAP's
implicit date snapping. The monthly chart shows the latest 12 valid months,
which may be older than the last calendar year if coverage has gaps.

SQLite `visibility_cache` stores each site's monthly and daily responses
separately, keyed by site ID and kind with coordinate validation. Monthly results
expire after seven days and daily results after six hours. A 120-second lease
prevents duplicate worker requests. Failures have a five-minute cooldown and
retain existing cached results, marked stale. All request paths have finite
upstream timeouts; a failed refresh is never stored as successful observations.
Schema creation runs through the existing application startup migration.

Clarity categories are an application interpretation of Kd490 (m^-1):

| Kd490 | Score | Label |
| --- | --- | --- |
| <= 0.05 | 5 | Excellent |
| > 0.05 to 0.10 | 4 | Good |
| > 0.10 to 0.20 | 3 | Fair |
| > 0.20 to 0.30 | 2 | Poor |
| > 0.30 | 1 | Very poor |

Bar heights use raw Kd490 with continuous logarithmic interpolation between
the category boundaries; they do not snap to the integer category score. Labels
sit at band centers, and values outside 0.016–32 m^-1 are clipped at the chart
edges. The cached category score remains available for text labels.

These categories do not measure horizontal diver visibility. Raw attenuation,
source coordinates, and observation dates accompany the API response and chart
tooltips. The live value includes its observation date in its tooltip, since the most recent valid
day can be substantially older than today. If fewer than 12 monthly values exist,
all available values are shown; an empty history is explicitly unavailable.

Validation: `python -m unittest discover -s tests -p 'test_visibility.py'` and
`node --test tests/test_marine.cjs`. Existing marine and site report suites cover
integration with the previous conditions behavior.
