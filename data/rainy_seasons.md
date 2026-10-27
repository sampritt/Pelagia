# Dive-site rainy seasons

`dive_site_rainy_seasons_rads_2025.csv` contains 12,353 reference site IDs and
ISO rainy-season start/end dates. The application reads this CSV once per app
startup and uses the months as a recurring annual season. The rainy period
includes the entire end month; the dry-period label reverses those month names.

Source: [Texas A&M RADS catalog](https://climatology.tamu.edu/research/Rainy-and-Dry-Season-RADS.html),
CPC_UNI 2025, 0.5-degree global grid. Citation: Bombardi, Kinter, and Frauenfeld
(2019), [doi:10.1175/BAMS-D-18-0177.1](https://doi.org/10.1175/BAMS-D-18-0177.1).
The original NetCDF grid is retained alongside this file.

Regenerate with `python scripts/build_rads_mapping.py` (requires `h5py` and
`numpy`; these are build dependencies, not needed to serve the application).
Sites use their nearest grid cell. Empty/pre-2000 dates and seasons outside
30–366 days are replaced with the pair from the nearest originally valid dive
site by unit-sphere Cartesian distance. Cross-year end dates are rolled forward.
This replaced 3,496 pairs; imputation can span substantial distances (Miyaru Kandu
uses an Indian site about 655 km away). These are coarse historical estimates,
including imputed values, rather than live weather predictions.
