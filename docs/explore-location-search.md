# Catalog location search modes

Audit date: 2026-11-11. Source: `data/global_dive_sites_master.csv`.

Reviewed all 236 distinct, trimmed location labels: 150 use tag matching and 86 retain radius matching. There are no continent-wide labels in the current catalog.

## Matching rules

- `TAG_MATCH_LOCATIONS` in `pelagia/explore.py` stores the case-folded country/territory labels and catalog aliases listed below.
- For these labels, selection matches `trim(country_or_area)` case-insensitively. All matching sites are eligible, including sites without coordinates. Ranking and pagination are unchanged.
- This restores location-tag matching: selecting `Mexico` does not also select `Cozumel`, merge aliases, or filter by country code.
- Smaller named regions keep the median-coordinate center and a radius of 4.5 times the population standard deviation of Cartesian distances. Explicit geocoder/radius searches and dive-center searches are unchanged.

The [UN M49 countries and areas list](https://unstats.un.org/unsd/methodology/m49/) was used to check whole-country and whole-territory names. Catalog spellings and aliases are retained, including the three United States labels, Cape Verde/Cabo Verde, Curacao/Curaçao, Malta and Gozo, Mauritius/Republic Of Mauritius, and the Saint/St. variants. `KY` is the Cayman Islands code used as a location tag in this catalog.

Named components of a broader country/area remain local regions: for example Galápagos Islands, Bonaire, Saba, Sint Eustatius, Svalbard, Tobago, and Cook Islands Rarotonga. States/provinces and named sea regions such as Alaska, British Columbia, Great Lakes, and Red Sea are also retained as regions; they are not whole countries or continents.

This audit classifies labels, not coordinate accuracy. Existing mislabeled sites remain eligible under their stored tag (for example the suspect `inland` record tagged Mexico).

## Tag matching: 150 country/territory labels and aliases

| Location tag | Sites | Recorded country codes |
| --- | ---: | --- |
| Albania | 2 | AL: 1, NA: 1 |
| Antigua and Barbuda | 10 | AG: 10 |
| Argentina | 13 | AR: 3, NA: 10 |
| Aruba | 38 | AW: 38 |
| Australia | 416 | AU: 416 |
| Austria | 58 | AT: 31, NA: 27 |
| Azerbaijan | 1 | NA: 1 |
| Bahamas | 33 | BS: 33 |
| Barbados | 41 | BB: 41 |
| Belgium | 15 | BE: 5, NA: 10 |
| Belize | 30 | BZ: 30 |
| Benin | 1 | NA: 1 |
| Bermuda | 28 | BM: 28 |
| Brazil | 151 | BR: 127, NA: 24 |
| British Indian Ocean Territory | 1 | NA: 1 |
| British Virgin Islands | 78 | VG: 78 |
| Brunei | 8 | NA: 8 |
| Bulgaria | 9 | NA: 9 |
| Cabo Verde | 1 | CV: 1 |
| Cambodia | 32 | KH: 1, NA: 31 |
| Canada | 61 | CA: 61 |
| Cape Verde | 10 | NA: 10 |
| Caribbean Netherlands | 71 | BQ: 62, NA: 9 |
| Cayman Islands | 121 | KY: 121 |
| Chile | 29 | CL: 6, NA: 23 |
| China | 11 | NA: 11 |
| Christmas Island | 8 | CX: 8 |
| Colombia | 101 | CO: 101 |
| Cook Islands | 30 | CK: 30 |
| Costa Rica | 74 | CR: 74 |
| Croatia | 77 | HR: 77 |
| Cuba | 3 | CU: 3 |
| Curacao | 48 | CW: 48 |
| Curaçao | 56 | CW: 56 |
| Cyprus | 73 | CY: 73 |
| Czech Republic | 17 | CZ: 17 |
| Denmark | 22 | NA: 22 |
| Djibouti | 11 | DJ: 11 |
| Dominica | 39 | DM: 39 |
| Dominican Republic | 77 | DO: 77 |
| Ecuador | 31 | EC: 31 |
| Egypt | 83 | EG: 83 |
| El Salvador | 2 | NA: 1, SV: 1 |
| Federated States Of Micronesia | 4 | NA: 4 |
| Fiji | 197 | FJ: 197 |
| Finland | 2 | NA: 2 |
| France | 308 | FR: 308 |
| French Polynesia | 93 | PF: 93 |
| Germany | 210 | DE: 162, NA: 48 |
| Gibraltar | 3 | NA: 3 |
| Greece | 167 | GR: 167 |
| Greenland | 6 | GL: 6 |
| Grenada | 106 | GD: 106 |
| Guadeloupe | 42 | GP: 42 |
| Guam | 31 | GU: 31 |
| Guatemala | 2 | GT: 2 |
| Honduras | 88 | HN: 88 |
| Hungary | 2 | NA: 2 |
| Iceland | 5 | IS: 5 |
| India | 33 | IN: 33 |
| Indonesia | 506 | ID: 506 |
| Iran | 1 | NA: 1 |
| Ireland | 6 | NA: 6 |
| Israel | 52 | IL: 52 |
| Italy | 194 | IT: 194 |
| Jamaica | 44 | JM: 44 |
| Japan | 24 | JP: 24 |
| Jordan | 12 | JO: 12 |
| Kenya | 23 | KE: 18, NA: 5 |
| Kuwait | 3 | NA: 3 |
| KY | 1 | NA: 1 |
| Latvia | 1 | NA: 1 |
| Libya | 1 | NA: 1 |
| Madagascar | 46 | MG: 46 |
| Malaysia | 104 | MY: 104 |
| Maldives | 264 | MV: 264 |
| Malta | 90 | MT: 3, NA: 87 |
| Malta and Gozo | 105 | MT: 105 |
| Marshall Islands | 38 | MH: 38 |
| Martinique | 21 | MQ: 21 |
| Mauritius | 38 | MU: 38 |
| Mexico | 218 | MX: 218 |
| Montenegro | 5 | NA: 5 |
| Mozambique | 76 | MZ: 76 |
| Netherlands | 52 | NA: 43, NL: 9 |
| New Caledonia | 72 | NC: 72 |
| New Zealand | 258 | NZ: 258 |
| Nicaragua | 7 | NI: 7 |
| Niue | 7 | NA: 7 |
| Northern Mariana Islands | 10 | NA: 10 |
| Oman | 23 | OM: 23 |
| Palau | 17 | PW: 17 |
| Panama | 29 | PA: 29 |
| Papua New Guinea | 58 | PG: 58 |
| Peru | 19 | NA: 6, PE: 13 |
| Philippines | 300 | PH: 300 |
| Poland | 4 | NA: 4 |
| Portugal | 40 | PT: 40 |
| Puerto Rico | 19 | PR: 19 |
| Qatar | 3 | NA: 3 |
| Republic Of Mauritius | 14 | NA: 14 |
| Reunion | 2 | RE: 2 |
| Romania | 1 | NA: 1 |
| Russia | 4 | NA: 4 |
| Réunion | 12 | RE: 12 |
| Saint Kitts Nevis | 3 | NA: 3 |
| Saint Vincent The Grenadines | 3 | NA: 3 |
| Saudi Arabia | 8 | NA: 8 |
| Seychelles | 62 | SC: 62 |
| Singapore | 4 | NA: 4 |
| Sint Maarten | 27 | NA: 3, SX: 24 |
| Slovakia | 2 | NA: 2 |
| Slovenia | 2 | NA: 2 |
| Solomon Islands | 106 | SB: 106 |
| South Africa | 183 | ZA: 183 |
| South Korea | 6 | KR: 6 |
| Spain | 405 | ES: 21, NA: 384 |
| Sri Lanka | 43 | LK: 43 |
| St. Kitts & Nevis | 3 | KN: 3 |
| St. Kitts and Nevis | 10 | KN: 10 |
| St. Lucia | 17 | LC: 17 |
| St. Vincent & Grenadines | 30 | VC: 30 |
| St. Vincent and the Grenadines | 9 | VC: 9 |
| Sudan | 5 | SD: 5 |
| Sweden | 19 | NA: 19 |
| Switzerland | 117 | CH: 49, NA: 68 |
| São Tomé & Príncipe | 3 | ST: 3 |
| Taiwan | 3 | NA: 3 |
| Tanzania | 114 | TZ: 114 |
| Thailand | 142 | TH: 142 |
| The Guadeloupe Islands | 5 | NA: 5 |
| Timor Leste East Timor | 1 | NA: 1 |
| Tonga | 19 | TO: 19 |
| Trinidad & Tobago | 1 | TT: 1 |
| Trinidad And Tobago | 12 | NA: 12 |
| Tunisia | 4 | NA: 4 |
| Turkey | 62 | TR: 62 |
| Turks and Caicos | 10 | TC: 10 |
| Turks And Caicos Islands | 1 | NA: 1 |
| United Arab Emirates | 18 | AE: 18 |
| United Kingdom | 78 | GB: 78 |
| United States | 99 | US: 99 |
| United States of America | 10 | US: 10 |
| United States Of America Usa | 278 | NA: 278 |
| United States Virgin Islands | 35 | NA: 35 |
| US Virgin Islands | 13 | VI: 13 |
| Vanuatu | 25 | VU: 25 |
| Venezuela | 12 | NA: 6, VE: 6 |
| Vietnam | 21 | NA: 21 |
| Western Sahara | 1 | NA: 1 |

## Radius matching: 86 regional labels

| Location tag | Sites | Recorded country codes |
| --- | ---: | --- |
| Alaska | 31 | US: 31 |
| Alor Archipelago | 11 | ID: 11 |
| Ambon | 10 | ID: 10 |
| Andaman Islands | 9 | IN: 9 |
| Azores | 14 | PT: 14 |
| Bali | 31 | ID: 31 |
| Banda Sea | 13 | ID: 13 |
| Belize Barrier Reef | 10 | BZ: 10 |
| Bocas del Toro | 13 | PA: 13 |
| Bonaire | 56 | BQ: 56 |
| British Columbia | 172 | CA: 172 |
| Cabo Pulmo | 12 | MX: 12 |
| California Channel Islands | 10 | US: 10 |
| Cape Town | 22 | ZA: 22 |
| Chuuk Lagoon | 25 | FM: 25 |
| Cocos Island | 8 | CR: 8 |
| Coiba National Park | 9 | PA: 9 |
| Cook Islands Rarotonga | 10 | CK: 10 |
| Cozumel | 23 | MX: 23 |
| Dry Tortugas | 9 | US: 9 |
| Florida Keys | 13 | US: 13 |
| Flower Garden Banks | 8 | US: 8 |
| Galápagos Islands | 15 | EC: 15 |
| Gili Islands | 13 | ID: 13 |
| Great Barrier Reef | 26 | AU: 26 |
| Great Lakes | 72 | US: 72 |
| Halmahera | 16 | ID: 16 |
| Hawaii - Kauai | 10 | US: 10 |
| Hawaii - Maui | 8 | US: 8 |
| Hawaii - Oahu | 18 | US: 18 |
| Hawaii Big Island | 10 | US: 10 |
| Jordan - Aqaba | 14 | JO: 14 |
| Kenya Coast | 10 | KE: 10 |
| Koh Tao | 13 | TH: 13 |
| Komodo National Park | 42 | ID: 42 |
| La Paz & Sea of Cortez | 10 | MX: 10 |
| Lembeh Strait | 13 | ID: 13 |
| Lombok | 9 | ID: 9 |
| Lord Howe Island | 8 | AU: 8 |
| Los Cabos | 12 | MX: 12 |
| Manado & Bunaken | 26 | ID: 26 |
| Micronesia - Yap | 15 | FM: 15 |
| Monterey Bay | 13 | US: 13 |
| New England | 48 | US: 48 |
| New Jersey Shore | 11 | US: 11 |
| Newfoundland | 10 | CA: 10 |
| Ningaloo Reef | 12 | AU: 12 |
| North Carolina | 14 | US: 14 |
| Norway Lofoten Islands | 11 | NO: 11 |
| Nova Scotia | 54 | CA: 54 |
| Okinawa | 4 | JP: 4 |
| Philippines Anilao | 24 | PH: 24 |
| Philippines Bohol | 8 | PH: 8 |
| Philippines Donsol | 10 | PH: 10 |
| Philippines Malapascua | 16 | PH: 16 |
| Philippines Palawan | 8 | PH: 8 |
| Philippines Puerto Galera | 15 | PH: 15 |
| Philippines Tubbataha Reefs | 8 | PH: 8 |
| Poor Knights Islands | 14 | NZ: 14 |
| Port-Cros | 18 | FR: 18 |
| Providencia Island | 10 | CO: 10 |
| Puerto Vallarta | 21 | MX: 21 |
| Puget Sound | 12 | US: 12 |
| Raja Ampat | 97 | ID: 97 |
| Red Sea | 467 | EG: 467 |
| Roatán | 422 | HN: 422 |
| Saba | 8 | BQ: 8 |
| San Diego - La Jolla | 10 | US: 10 |
| Sangalaki (Derawan Islands) | 12 | ID: 12 |
| Sardinia | 10 | IT: 10 |
| Scapa Flow | 10 | GB: 10 |
| Silfra Fissure | 7 | IS: 7 |
| Sint Eustatius | 6 | BQ: 6 |
| Sipadan | 10 | MY: 10 |
| Socorro Islands | 8 | MX: 8 |
| South Australia Neptune Islands | 10 | AU: 10 |
| South Florida | 10 | US: 10 |
| Sumbawa | 14 | ID: 14 |
| Svalbard | 8 | NO: 8 |
| Thailand Similan Islands | 14 | TH: 14 |
| Tobago | 13 | TT: 13 |
| Triton Bay | 10 | ID: 10 |
| UAE - Fujairah | 7 | AE: 7 |
| Ustica | 13 | IT: 13 |
| Utila | 11 | HN: 11 |
| Vancouver Island | 13 | CA: 13 |
