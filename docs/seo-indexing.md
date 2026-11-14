# Public search indexing

The initial selection contains exactly 100 dive sites across 35 countries and territories and seven regions. This is an editorial selection of well-known diving destinations, balanced geographically; it is not a measured search-volume ranking. Nearby aliases and duplicate catalog records were excluded from the selection. Stable `master_site_id` values resolve to the deployment’s actual database IDs.

Selection context: [PADI’s world dive sites](https://blog.padi.com/the-10-best-dive-sites-in-the-world/), [Caribbean destinations](https://blog.padi.com/best-diving-in-the-caribbean/), [liveaboard sites](https://blog.padi.com/liveaboard-diving-the-10-best-dive-sites-in-the-world/), and [Pacific diving](https://travel.padi.com/diving-in/the-pacific/). The existing catalog retains source URLs and attribution for each record; the links below document that provenance and are not claims of independent verification of every description or coordinate.

## Behavior

- `/dive-sites` is a public directory linked from the homepage footer as “Dive Sites”, styled like the Terms & Conditions and Privacy Policy links, and included in `/sitemap.xml`. All selected sites have ordinary HTML links. The Explore section has no additional directory link.
- Only selected `/explore/dive-sites/<id>` pages are indexable. Their initial HTML includes a cached description or the researched page summary in `pelagia/seo_site_descriptions.json`. The short introductions in `pelagia/seo_sites.tsv` appear only on directory cards, below any species tags.
- Public browse pages do not initiate paid description generation. Existing signed-in and share-page behavior is preserved.
- `/explore/dive-centers/<id>` qualifies only with a nonempty cached description, name, location and valid coordinates.
- Share previews, unselected sites and thin center pages remain noindexed. Search-result pages use `noindex, follow`.
- `/sitemap.xml` contains the homepage, terms, privacy, directory, available selected sites and qualifying centers. Only actual database records are emitted; a deployment missing selected catalog IDs will emit fewer than 100 sites.
- Canonical URLs use `PELAGIA_PUBLIC_BASE_URL`. The existing robots file advertises the sitemap and leaves public HTML crawlable.

## Deployment

Deploy the code, `pelagia/seo_sites.tsv` and `pelagia/seo_site_descriptions.json` together, with the current reference catalog. Set `PELAGIA_PUBLIC_BASE_URL=https://pelagiadivelog.com`. Verify that `/sitemap.xml` contains exactly 100 `/explore/dive-sites/` URLs, then submit it in Search Console. Inspect representative URLs for their rendered descriptions, canonical URLs and indexing eligibility. The application makes pages eligible; Google controls actual indexing and rankings.

The implementation does not overwrite production description caches or modify catalog coordinates. Nonempty cached descriptions are preferred over the bundled researched summaries. These summaries are also available to signed-in profiles, share pages and the description API through the shared cache reader. They are generated with the existing web-grounded `site_descriptions.generate_description` function, with its normal model, instructions and search limits. Run `scripts/generate_selected_site_descriptions.py` with `OPENAI_API_KEY` to resume missing summaries; saved records are reused. Review any catalog location conflicts before changing map positions.

## Selected sites

### Caribbean (18)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS000123 | SS Antilla Wreck | Aruba | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/aruba.json) |
| DS000740 | Great Blue Hole | Belize | [1](https://api.opendivemap.com/v1/sites/3h1iv3) |
| DS000742 | Half Moon Caye Wall | Belize | [1](https://api.opendivemap.com/v1/sites/48g2vj) |
| DS000816 | 1000 Steps | Bonaire | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bonaire.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/bonaire_divesites_osm.csv) |
| DS000838 | Hilma Hooker | Bonaire | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bonaire.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/bonaire_divesites_osm.csv), [3](https://www.padi.com/dive-site/caribbean-netherlands/hilma-hooker/) |
| DS001564 | Salt pier | Bonaire | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bonaire.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/bonaire_divesites_osm.csv), [3](https://www.padi.com/dive-site/caribbean-netherlands/salt-pier/), [4](https://www.padi.com/dive-site/caribbean-netherlands/salt-pier-2/), [5](https://api.opendivemap.com/v1/sites/8clalj) |
| DS001615 | Bloody Bay Wall | Cayman Islands | [1](https://api.opendivemap.com/v1/sites/b196uu) |
| DS001604 | Babylon | Cayman Islands | [1](https://www.padi.com/dive-site/cayman-islands/babylon-2/), [2](https://api.opendivemap.com/v1/sites/1f6xn6) |
| DS001702 | Stingray City | Cayman Islands | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/cayman-islands.json) |
| DS001717 | USS Kittiwake Shipwreck | Cayman Islands | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/cayman-islands.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/united_states_divesites_osm.csv) |
| DS002214 | Superior Producer | Curaçao | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/curacao.json), [2](https://www.padi.com/dive-site/curacao/superior-producer/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/colombia_divesites_osm.csv) |
| DS002273 | Tugboat | Curaçao | [1](https://api.opendivemap.com/v1/sites/ot5oqj) |
| DS001257 | RMS Rhone (Wreck) | British Virgin Islands | [1](https://api.opendivemap.com/v1/sites/45ch04) |
| DS001212 | Chikuzen | British Virgin Islands | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/british-virgin-islands.json) |
| DS000636 | Tiger Beach | Bahamas | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bahamas.json), [2](https://www.padi.com/dive-site/bahamas/tiger-beach/) |
| DS000614 | Dean's Blue Hole | Bahamas | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bahamas.json) |
| DS008235 | Half Moon Bay Wall | Honduras | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/roatan.json) |
| DS002432 | Scotts Head Drop Off | Dominica | [1](https://api.opendivemap.com/v1/sites/54bnjj) |

### Eastern Pacific and North America (10)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS003249 | Darwin's Arch | Ecuador | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/galapagos-islands.json) |
| DS003250 | Gordon Rocks | Ecuador | [1](https://api.opendivemap.com/v1/sites/43fxxc), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/galapagos-islands.json), [3](https://www.padi.com/dive-site/ecuador/gordon-rocks/) |
| DS002553 | KICKER ROCK | Ecuador | [1](https://www.padi.com/dive-site/ecuador/kicker-rock/), [2](https://api.opendivemap.com/v1/sites/cz4pqt), [3](https://www.padi.com/dive-site/ecuador/leon-dormido-kicker-rock/), [4](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/galapagos-islands.json) |
| DS001799 | Bajo Alcyone | Costa Rica | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/cocos-island.json) |
| DS001800 | Dirty Rock | Costa Rica | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/cocos-island.json) |
| DS006037 | Roca Partida | Mexico | [1](https://api.opendivemap.com/v1/sites/ny3tvx) |
| DS005880 | Cenote Dos Ojos | Mexico | [1](https://api.opendivemap.com/v1/sites/xw4fcy), [2](https://www.padi.com/dive-site/mexico/cenote-dos-ojos-3/), [3](https://www.padi.com/dive-site/mexico/cenote-dos-ojos-4/) |
| DS006005 | Palancar Gardens | Mexico | [1](https://api.opendivemap.com/v1/sites/bv75l0) |
| DS010714 | Spiegel Grove | United States | [1](https://www.padi.com/dive-site/united-states-of-america-usa/spiegel-grove/) |
| DS010497 | Blue Heron Bridge | United States | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/south-florida.json), [2](https://www.padi.com/dive-site/united-states-of-america-usa/blue-heron-bridge-2/) |

### Europe and North Atlantic (10)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS008656 | Silfra | Iceland | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/silfra-fissure.json), [2](https://www.padi.com/dive-site/iceland/silfra/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/iceland_divesites_osm.csv) |
| DS010344 | Scapa Flow | United Kingdom | [1](https://www.padi.com/dive-site/united-kingdom/scapa-flow/) |
| DS010322 | HMS Scylla | United Kingdom | [1](https://www.padi.com/dive-site/united-kingdom/hms-scylla/) |
| DS010315 | Farne Islands | United Kingdom | [1](https://www.padi.com/dive-site/united-kingdom/farne-islands/) |
| DS002351 | Zenobia Wreck | Cyprus | [1](https://www.padi.com/dive-site/cyprus/zenobia-wreck-2/) |
| DS005508 | Blue Hole, Dwejra | Malta | [1](https://www.padi.com/dive-site/malta/blue-hole-dwejra/) |
| DS005548 | Inland Sea | Malta | [1](https://www.padi.com/dive-site/malta/inland-sea/), [2](https://www.padi.com/dive-site/malta/inland-sea-3/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/malta-and-gozo.json) |
| DS005585 | Um El Faroud - Oil Tanker | Malta | [1](https://www.padi.com/dive-site/malta/um-el-faroud-oil-tanker/) |
| DS009178 | EL BAJON | Spain | [1](https://www.padi.com/dive-site/spain/el-bajon-5/) |
| DS000601 | princess alice bank | Portugal | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/azores.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/portugal_divesites_osm.csv) |

### Red Sea (9)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS007979 | SS Thistlegorm | Egypt | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/red-sea.json), [2](https://www.padi.com/dive-site/egypt/ss-thistlegorm/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/egypt_divesites_osm.csv) |
| DS002629 | Shark & Yolanda Reef - Ras Mohammed | Egypt | [1](https://www.padi.com/dive-site/egypt/shark-yolanda-reef-ras-mohammed/) |
| DS002589 | Elphinstone Reef | Egypt | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/red-sea.json), [2](https://www.padi.com/dive-site/egypt/elphinstone-reef-3/), [3](https://www.padi.com/dive-site/egypt/elphinstone-reef-2/), [4](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/egypt_divesites_osm.csv) |
| DS007657 | Daedalus Reef | Egypt | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/red-sea.json) |
| DS007762 | Jackson reef | Egypt | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/red-sea.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/egypt_divesites_osm.csv) |
| DS002579 | Blue Hole | Egypt | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/red-sea.json), [2](https://www.padi.com/dive-site/egypt/blue-hole-3/), [3](https://www.padi.com/dive-site/egypt/blue-hole-17/), [4](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/egypt_divesites_osm.csv) |
| DS002636 | The Canyon | Egypt | [1](https://www.padi.com/dive-site/egypt/the-canyon-8/) |
| DS007641 | Big Brother Island | Egypt | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/red-sea.json) |
| DS004876 | Japanese garden | Jordan | [1](https://www.padi.com/dive-site/jordan/japanese-garden/) |

### Africa and Indian Ocean (11)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS008842 | Aliwal Shoal | South Africa | [1](https://api.opendivemap.com/v1/sites/6emx2n) |
| DS008951 | Protea Banks Northern Shark Caves | South Africa | [1](https://www.padi.com/dive-site/south-africa/protea-banks-northern-shark-caves/) |
| DS009003 | Two Mile Reef Sodwana | South Africa | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/south-africa.json) |
| DS006169 | Manta Reef Tofo | Mozambique | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/mozambique.json) |
| DS006203 | Two Mile Reef | Mozambique | [1](https://www.padi.com/dive-site/mozambique/two-mile-reef/) |
| DS005413 | Maaya Thila | Maldives | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/maldives.json), [2](https://www.padi.com/dive-site/maldives/maaya-thila/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/maldives_divesites_osm.csv) |
| DS005321 | Fish Head | Maldives | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/maldives.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/maldives_divesites_osm.csv) |
| DS005408 | Maalhos Thila | Maldives | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/maldives.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/maldives_divesites_osm.csv) |
| DS005369 | Kandooma Thila | Maldives | [1](https://www.padi.com/dive-site/maldives/cocoa-thila/) |
| DS005429 | Miyaru Kandu | Maldives | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/maldives.json), [2](https://www.padi.com/dive-site/maldives/miyaru-kandu/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/maldives_divesites_osm.csv) |
| DS005234 | Alimatha House reef | Maldives | [1](https://www.padi.com/dive-site/maldives/alimatha-house-reef/) |

### Southeast Asia (25)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS007504 | Cape Kri | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/raja-ampat.json), [2](https://www.padi.com/dive-site/indonesia/cape-kri/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/indonesia_divesites_osm.csv) |
| DS004279 | Melissa’s Garden | Indonesia | [1](https://api.opendivemap.com/v1/sites/0u40l8), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/raja-ampat.json), [3](https://www.padi.com/dive-site/indonesia/melissas-garden/), [4](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/indonesia_divesites_osm.csv) |
| DS004093 | Blue Magic | Indonesia | [1](https://api.opendivemap.com/v1/sites/qwqf0f), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/raja-ampat.json), [3](https://www.padi.com/dive-site/indonesia/blue-magic/) |
| DS007543 | Manta Sandy | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/raja-ampat.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/indonesia_divesites_osm.csv) |
| DS007500 | Boo Windows | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/raja-ampat.json) |
| DS004050 | Batu Bolong Komodo | Indonesia | [1](https://api.opendivemap.com/v1/sites/x5v3je) |
| DS004951 | Castle Rock | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/komodo-national-park.json), [2](https://www.padi.com/dive-site/indonesia/castle-rock/) |
| DS004954 | Crystal Rock Dive Site | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/komodo-national-park.json) |
| DS004983 | The Cauldron Dive Site | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/komodo-national-park.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/australia_divesites_osm.csv) |
| DS004950 | Cannibal Rock | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/komodo-national-park.json), [2](https://www.padi.com/dive-site/indonesia/cannibal-rock/) |
| DS000669 | USAT Liberty Wreck | Indonesia | [1](https://api.opendivemap.com/v1/sites/oydkpv), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bali.json), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/australia_divesites_osm.csv) |
| DS000647 | Crystal Bay | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/bali.json), [2](https://www.padi.com/dive-site/indonesia/crystal-bay-2/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/australia_divesites_osm.csv) |
| DS005009 | Nudi Falls | Indonesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/lembeh-strait.json), [2](https://www.padi.com/dive-site/indonesia/nudi-falls/) |
| DS008702 | Barracuda Point | Malaysia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/sipadan.json) |
| DS008708 | South Point | Malaysia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/sipadan.json), [2](https://www.padi.com/dive-site/malaysia/south-point-3/) |
| DS010049 | Richelieu Rock | Thailand | [1](https://www.padi.com/dive-site/thailand/richelieu-rock-2/) |
| DS010050 | Sail Rock | Thailand | [1](https://www.padi.com/dive-site/thailand/sail-rock-3/) |
| DS009954 | Chumphon Pinnacle | Thailand | [1](https://www.padi.com/dive-site/thailand/chumphon-pinnacle/), [2](https://www.padi.com/dive-site/thailand/chumphon-pinnacle-2/) |
| DS010077 | Elephant Head Rock | Thailand | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/thailand-similan-islands.json) |
| DS009997 | Koh Bon | Thailand | [1](https://www.padi.com/dive-site/thailand/koh-bon/) |
| DS009946 | Bida Nok | Thailand | [1](https://www.padi.com/dive-site/thailand/bida-nok/) |
| DS007070 | Kimud Shoal | Philippines | [1](https://www.padi.com/dive-site/philippines/kimud-shoal/) |
| DS007281 | Monad Shoal | Philippines | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/philippines-malapascua.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/philippines_divesites_osm.csv) |
| DS006956 | Apo Island | Philippines | [1](https://www.padi.com/dive-site/philippines/apo-island/) |
| DS007305 | The Canyons | Philippines | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/philippines-puerto-galera.json) |

### Pacific and Oceania (17)

| Catalog ID | Dive site | Country / territory | Catalog sources |
| --- | --- | --- | --- |
| DS006815 | Blue Corner | Palau | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/palau.json), [2](https://www.padi.com/dive-site/palau/blue-corner-2/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/palau_divesites_osm.csv) |
| DS006831 | Ulong Channel | Palau | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/palau.json), [2](https://www.padi.com/dive-site/palau/ulong-channel/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/palau_divesites_osm.csv) |
| DS006816 | Blue Holes | Palau | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/palau.json), [2](https://www.padi.com/dive-site/palau/blue-holes/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/palau_divesites_osm.csv) |
| DS006817 | Chandelier Cave | Palau | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/palau.json), [2](https://www.padi.com/dive-site/palau/chandelier-cave/), [3](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/palau_divesites_osm.csv) |
| DS001776 | Fujikawa Maru | Federated States of Micronesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/chuuk-lagoon.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/micronesia_divesites_osm.csv) |
| DS001796 | Shinkoku Maru | Federated States of Micronesia | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/chuuk-lagoon.json), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/micronesia_divesites_osm.csv) |
| DS003213 | Passe de Tiputa | French Polynesia | [1](https://api.opendivemap.com/v1/sites/ds731y) |
| DS002725 | Great White Wall | Fiji | [1](https://api.opendivemap.com/v1/sites/coujmk) |
| DS002814 | Shark Reef Marine Reserve | Fiji | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/fiji.json) |
| DS010878 | SS President Coolidge | Vanuatu | [1](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/vanuatu.json), [2](https://www.padi.com/dive-site/vanuatu/ss-president-coolidge-3/), [3](https://www.padi.com/dive-site/vanuatu/ss-president-coolidge/), [4](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/vanuatu_divesites_osm.csv) |
| DS010871 | Million Dollar Point | Vanuatu | [1](https://api.opendivemap.com/v1/sites/4ht14c), [2](https://github.com/jbunderwater/dive-vibe-community/blob/main/data/osm_clean/vanuatu.json), [3](https://www.padi.com/dive-site/vanuatu/million-dollar-point/), [4](https://github.com/jbunderwater/dive-vibe-community/blob/main/world_collection_osm/vanuatu_divesites_osm.csv) |
| DS000477 | SS Yongala Wreck | Australia | [1](https://api.opendivemap.com/v1/sites/sahdzj) |
| DS000210 | Cod Hole - Ribbon No 10 Reef - GBR | Australia | [1](https://api.opendivemap.com/v1/sites/o2hcyp) |
| DS000480 | Steve’s Bommie - Ribbon No 3 Reef | Australia | [1](https://api.opendivemap.com/v1/sites/443stb) |
| DS000239 | Exmouth Navy Pier | Australia | [1](https://api.opendivemap.com/v1/sites/uubagz) |
| DS006561 | Rainbow Warrior Wreck | New Zealand | [1](https://www.padi.com/dive-site/new-zealand/rainbow-warrior-wreck-2/) |
| DS010428 | Manta Ray Heaven, Garden Eel Cove | United States | [1](https://api.opendivemap.com/v1/sites/b4trti) |
