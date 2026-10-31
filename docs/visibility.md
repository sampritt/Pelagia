# Visibility history

The dive site page requests ocean conditions first, then checks visibility separately. A single most recent valid daily KD490 measurement from the past seven UTC dates is selected, choosing the nearest valid pixel within 15 km on that date and preferring the multi-year source for ties. The multi-year and near-real-time sources are queried sequentially. Missing coverage produces an unavailable state.

The per-site cache stores one result for the current site-local date and replaces it on the next date or a coordinate change. A database lease prevents duplicate lookups across workers. The report waits until this daily visibility lookup finishes, including a no-data result. The display is a qualitative clarity proxy; satellite surface measurements do not directly measure diver visibility at depth.

## Credentials

Set `COPERNICUS_MARINE_CREDS` to the **entire encoded contents** of `.copernicusmarine/.copernicusmarine-credentials`, as produced by `copernicusmarine login`. It encodes a username/password configuration; it is not a bearer API token. The worker decodes it in memory and passes `username` and `password` to the toolbox. No credential file is written and credentials are not returned to the client or included in the report prompt. In local development, an absent variable uses the toolbox's normal credentials discovery, including the saved login file. The environment variable must be set on the deployed service and the service restarted to pick it up.

The toolbox runs in a bounded child process with a 24-second overall timeout. Credentials are not returned to the client or included in the report prompt.

## Pelagia clarity categories

| Label | KD490 (m⁻¹) |
| --- | --- |
| Excellent | 0 < KD490 ≤ 0.04 |
| Very good | 0.04 < KD490 ≤ 0.07 |
| Good | 0.07 < KD490 ≤ 0.095 |
| Fair | 0.095 < KD490 ≤ 0.19 |
| Poor | 0.19 < KD490 ≤ 0.29 |
| Very poor | KD490 > 0.29 |

These are fixed Pelagia product thresholds, not official Copernicus diver-visibility classes. The [Copernicus Ocean Colour manual](https://documentation.marine.copernicus.eu/PUM/CMEMS-OC-PUM.pdf) defines KD490 as diffuse attenuation of downwelling irradiance, in inverse metres. The [quality document](https://documentation.marine.copernicus.eu/QUID/CMEMS-OC-QUID-009-101to104-111-113-116-118.pdf) describes the retrieval and its validation. Neither supplies a validated six-category diver visibility scale.

The cutoffs span substantially different optical conditions: their reciprocal attenuation lengths are 25, about 14.3, 10.5, 5.3, and 3.4 metres. This supplies a physically interpretable progression without tuning labels to one site's monthly distribution. These lengths describe vertical irradiance decay, not horizontal viewing distances. Categories should eventually be calibrated against paired dive observations. Missing/invalid values have no category.

The report receives the most recent measurement and uses its category only for qualitative recent-visibility commentary.
