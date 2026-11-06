# Explore dive centers

Explore opens with **Dive sites** selected. Two compact filter buttons switch between dive sites and dive centers while keeping the selected country, region, place and radius. The selected filter is included as `kind=sites|centers` in the URL, so refresh and browser history restore it. Omitting the parameter defaults to sites.

Place searches reuse the existing Cartesian distance calculation. The radius slider, numeric distance and miles/km controls update the selected feed without another geocoding request. Centers rank by average Pelagia review rating descending (unrated centers last), then non-deleted logged dive count descending, then name and ID for stable pagination.

Country and region searches include all centers within 30 miles of any geolocated site in the selected location, including centers across country boundaries. Sites are visited in the same order as the site feed: logged dive count, distinct combined observed species count, name and ID. Each center belongs to the first qualifying site in that order and appears once. Centers within each group use the rating and logged-dive ordering above. Matching uses all sites in the location before paginating centers into pages of 24. Centers without valid coordinates cannot be matched.

Both feeds use the same card template, layout, map and profile link styling. Center cards show their location, average rating when available and nonzero logged dive count. Empty states and retry messages reflect the selected filter. Feed requests are canceled when superseded; changing filters during geocoding reuses the pending lookup and requests the chosen feed using the returned coordinates.

Validation: `python -m unittest discover -s tests -p 'test_explore.py'` and `node --test tests/test_explore.cjs` cover geographic boundaries, antimeridian matching, rating averages, deleted dives, site ordering, deduplication, pagination, URL restoration and request races.

The implementation was also checked in Chrome at 320, 390, 768, 1024 and 1440 pixels and with iPhone touch emulation. Both filters share map dimensions, have 44-pixel button targets, support native keyboard activation and fit without horizontal overflow. Browser checks covered pagination, radius changes, unit conversion, empty results, refresh and history restoration. All 30 Explore Python tests and all 202 JavaScript tests passed. The complete Python suite ran 475 tests with one skip and eight existing failures in email signup and exposure recommendations; the same eight failures reproduced on unchanged main.
