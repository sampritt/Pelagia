# Dive-site rainy seasons

`dive_site_rainy_seasons_rads_2021_2025_median.csv` contains 12,353 reference
site IDs and median ISO rainy-season start/end dates from the five most recent
complete CPC_UNI years, 2021–2025. The application reads this CSV once per app
startup and uses the months as a recurring annual season. The rainy period
includes the entire end month; the dry-period label reverses those month names.

Source: [Texas A&M RADS catalog](https://climatology.tamu.edu/research/Rainy-and-Dry-Season-RADS.html),
CPC_UNI 2021–2025, 0.5-degree global grids. Citation: Bombardi, Kinter, and
Frauenfeld (2019), [doi:10.1175/BAMS-D-18-0177.1](https://doi.org/10.1175/BAMS-D-18-0177.1).
The five original NetCDF grids are retained alongside this file.

Regenerate with `python scripts/build_rads_mapping.py` (requires `h5py` and
`numpy`; these are build dependencies, not needed to serve the application).
Each boundary requires at least three valid annual observations. Medians are
calculated by day of year, with balanced December/January clusters unwrapped
across New Year before aggregation. Sites then use their nearest median grid
cell. Empty dates and seasons outside 30–366 days are replaced with the pair
from the nearest originally valid dive site by unit-sphere Cartesian distance.
Cross-year end dates are rolled forward. This replaced 2,726 pairs. These are
coarse historical estimates, including imputed values, rather than live weather
predictions.
