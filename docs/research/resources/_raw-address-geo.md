# Address + Geo Normalization — Verified Resource Inventory

Scope: everything useful for normalizing postal addresses, postcodes, countries, regions and coordinates *before* entity resolution, in a read-only Python engine with a clean license inventory.

**License legend:** ✅ = permissive (MIT/BSD/Apache/CC0/CC-BY), ⚠️ = copyleft or share-alike (GPL/LGPL/AGPL/ODbL/CC-BY-SA) — usable but constrains distribution, 💰 = commercial / paid / restrictive licence, ❓ = licence not stated on the page I checked.

Everything below was opened or search-verified. Items I could not confirm are marked **(unverified)**.

---

## 1. Address parsing / normalization libraries (core)

| # | Resource | URL | What it gives us / when to use | Licence |
|---|---|---|---|---|
| 1 | **libpostal** | https://github.com/openvenues/libpostal | The reference C library: statistical (CRF) international address parser + `expand_address` normalizer + near-dupe hashing. Trained on ~1B OSM/OpenAddresses examples. This is the default backbone for cross-country address normalization. ~4.9k stars, MIT. | ✅ MIT (code) — see #5 for model-data caveat |
| 2 | **libpostal LICENSE (verbatim)** | https://github.com/openvenues/libpostal/blob/master/LICENSE | Confirms MIT for the code, for the license inventory. | ✅ MIT |
| 3 | **libpostal releases (1.1 "near-dupe" features)** | https://github.com/openvenues/libpostal/releases | Documents `near_dupe_hashes`, expanded per-country training data, place-only models — the deduping primitives most people don't know exist. | ✅ |
| 4 | **pypostal (official Python bindings)** | https://github.com/openvenues/pypostal | `from postal.expand import expand_address` / `from postal.parser import parse_address`. Published on PyPI as `postal`. The binding we should standardize on. | ✅ MIT |
| 5 | **Senzing/libpostal-data** | https://github.com/Senzing/libpostal-data | Notes + mirrors about libpostal's ~2GB model data files. Important for the license inventory: the *models* derive from OSM/OpenAddresses, so data-side obligations differ from the MIT code. | ❓ / ⚠️ data derived from ODbL sources |
| 6 | **deepparse** | https://github.com/GRAAL-Research/deepparse | Seq2seq (FastText/BPEmb + attention) multinational address parser, 20 countries trained, ≥99% on clean data, fine-tunable, has CLI + FastAPI server. Use when libpostal's tag set is too coarse or we need retraining on our own labels. Python ≥3.10. | ⚠️ **LGPL-3.0** — license-hostile-ish: fine to call as a separate process/service, avoid static linkage into proprietary distribution |
| 7 | **deepparse docs** | https://deepparse.org/ | API, retraining recipes, tag customization. | ⚠️ |
| 8 | **deepparse on PyPI** | https://pypi.org/project/deepparse/ | Version/activity check + install. | ⚠️ LGPL-3.0 |
| 9 | **deepparse-address-data** | https://github.com/GRAAL-Research/deepparse-address-data | The multinational labelled address training/eval dataset behind deepparse — useful as an independent benchmark set for *our* parser. | ❓ check repo terms before redistribution |
| 10 | **usaddress (DataMade)** | https://github.com/datamade/usaddress | CRF parser for unstructured **US** address strings; battle-tested, fast, tiny. Use as the US-specific second opinion / tie-breaker against libpostal. | ✅ MIT |
| 11 | **usaddress docs** | https://usaddress.readthedocs.io/ | Tag list and `tag()` vs `parse()` semantics (important: `tag()` is the one that merges components). | ✅ |
| 12 | **usaddress on PyPI** | https://pypi.org/project/usaddress/ | Install/activity. | ✅ MIT |
| 13 | **probablepeople** | https://github.com/datamade/probablepeople | Same CRF machinery as usaddress but for **person/company name** strings — needed because "recipient" lines get mixed into address blobs. | ✅ MIT |
| 14 | **probablepeople on PyPI** | https://pypi.org/project/probablepeople/ | Install/activity. | ✅ |
| 15 | **usaddress-scourgify** | https://github.com/GreenBuildingRegistry/usaddress-scourgify | Wraps usaddress to emit **USPS Publication 28 / RESO**-normalized address lines (line1/line2/city/state/postal). Exactly the "canonical US form" step we need after parsing. | ✅ (see repo) |
| 16 | **usaddress-scourgify on PyPI** | https://pypi.org/project/usaddress-scourgify/ | Install/activity. | ✅ |
| 17 | **pyap** | https://github.com/vladimarius/pyap | Regex-based address *detector* (finds addresses inside free text) for US/CA/GB. Use for extraction from notes/description fields, not for canonicalization. | ✅ MIT |
| 18 | **pyap2 (maintained fork)** | https://github.com/argyle-engineering/pyap | Actively maintained fork of pyap; prefer this if we adopt pyap. | ✅ MIT |
| 19 | **pyap on PyPI** | https://pypi.org/project/pyap/ | Install/activity. | ✅ |
| 20 | **addressit** | https://github.com/DamonOehlman/addressit | Node freeform street-address parser focused on the *street* part, dumping the rest into a generic `regions` array. Useful as a cheap cross-check oracle; last published ~3y ago, so treat as reference not dependency. | ❓ README shows no explicit licence badge |
| 21 | **postal-address (Scaleway)** | https://github.com/scaleway/postal-address | Python parse/normalize/**render** of postal addresses with strong territory (country/subdivision) normalization — the "which subdivision is this really" logic. Low activity; good algorithm reference. | ✅ BSD-2-Clause |
| 22 | **google-i18n-address (mirumee)** | https://github.com/mirumee/google-i18n-address | Packages Google's i18n address metadata for Python: per-country required fields, allowed subdivisions, postcode regex, and a `normalize_address()` validator. Best single library for *country-aware field validation*. | ✅ (data CC-BY, see #24) |
| 23 | **google-i18n-address on PyPI** | https://pypi.org/project/google-i18n-address/ | Install/activity. | ✅ |
| 24 | **Geo::StreetAddress::US (Perl, canonical regex parser)** | https://github.com/timbunce/Geo-StreetAddress-US | The original regex US parser whose abbreviation/suffix tables every port copies. Use its tables, not the code. | ❓ Perl-ish licence, check dist |
| 25 | **parse-address (JS port of the above)** | https://github.com/hassansin/parse-address | Handy for validating our own suffix/unit-designator tables against a widely used implementation. | ✅ (repo) |

## 2. Address formatting / rendering templates

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 26 | **OpenCage address-formatting** | https://github.com/OpenCageData/address-formatting | Per-territory mustache templates + thousands of test cases for rendering structured components into the locally correct address string. libpostal itself trains against these. Our canonical "render" step. | ✅ MIT (LICENSE.txt confirmed) |
| 27 | **worldwide.yaml (the template file)** | https://github.com/OpenCageData/address-formatting/blob/master/conf/countries/worldwide.yaml | The actual country → template mapping; parse this directly rather than reimplementing. | ✅ MIT |
| 28 | **components.yaml (component aliases)** | https://github.com/OpenCageData/address-formatting/blob/master/conf/components.yaml | Canonical component names + aliases (road/street/highway…). Use as our internal field vocabulary. | ✅ MIT |
| 29 | **OpenCage "Guide to address formatting"** | https://opencagedata.com/guides/formatting-addresses | Explains why formatting ≠ postal delivery, and the scope limits (no PO boxes/floors). Read before we promise "postal-correct" output. | — docs |
| 30 | **OpenCage: "Good looking addresses — solving the `Berlin, Berlin` bug"** | https://blog.opencagedata.com/post/99059889253/good-looking-addresses-solving-the-berlin-berlin | The classic write-up on duplicate-component suppression in rendered addresses. | — blog |
| 31 | **OpenCage: how to format a forward-geocoding query** | https://opencagedata.com/guides/how-to-format-your-geocoding-query | Practical rules for building query strings from partial components — directly applicable to our geocode fallback path. | — docs |

## 3. Google address metadata (the single best free i18n validation dataset)

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 32 | **google/libaddressinput** | https://github.com/google/libaddressinput | Google's postal address library (C++/Java) powering Chromium & Android address forms: field order, required fields, sublocality naming, postcode patterns. | ✅ Apache-2.0 (repo) |
| 33 | **AddressValidationMetadata wiki (how to use the data)** | https://github.com/google/libaddressinput/wiki/AddressValidationMetadata | Documents key construction `data/<CC>/<Admin>/<Locality>--<lang>`, `sub_keys`, `zip`/`zipex` regexes. This is the doc to implement against. | — docs |
| 34 | **Address Data Service (live endpoint)** | https://chromium-i18n.appspot.com/ssl-address | The live JSON metadata endpoint. Page states the data is **licensed by Google under CC-BY 4.0** — clean for us with attribution. Snapshot it; Google gives no uptime guarantee. | ✅ CC-BY 4.0 |

## 4. Geocoders / address services we can self-host

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 35 | **Nominatim** | https://github.com/osm-search/Nominatim | OSM geocoder; even if we don't geocode, its normalization pipeline is the reference implementation for multilingual name cleanup. | ⚠️ **GPL-3.0-or-later** (Python code) — do not link into our engine; run as a service only |
| 36 | **Nominatim: Tokenizers** | https://nominatim.org/release-docs/latest/customize/Tokenizers | The ICU tokenizer: transliteration, abbreviation expansion, variant generation. Copy the *approach* (and the ICU rules) for our token normalizer. | — docs |
| 37 | **Nominatim: Sanitizers** | https://nominatim.org/release-docs/develop/customize/Sanitizers/ | Pre-index name cleanup hooks (split housenumbers, strip brackets, tag-based rules) — a good taxonomy for our own cleaning rules. | — docs |
| 38 | **Nominatim: ICU tokenizer modules (custom)** | https://nominatim.org/release-docs/latest/develop/ICU-Tokenizer-Modules/ | How to write custom sanitizer/analysis modules; useful design pattern for pluggable normalizers. | — docs |
| 39 | **Nominatim: External data — Postcodes** | https://nominatim.org/release-docs/latest/customize/Postcodes/ | How to inject authoritative postcode centroids and country-specific postcode patterns. | — docs |
| 40 | **Nominatim: Per-country settings** | https://nominatim.org/release-docs/latest/customize/Country-Settings | Country → languages + postcode format table; a ready-made per-country config we can mine. | — docs |
| 41 | **Nominatim: external data sources list** | https://nominatim.org/release-docs/latest/develop/data-sources/ | Where GB postcodes / US TIGER housenumbers come from and how they're licensed. | — docs |
| 42 | **Nominatim blog: "The state of postcodes"** | https://nominatim.org/2022/06/26/state-of-postcodes.html | Sarah Hoffmann on postcode coverage/quality in OSM and how postcodes are actually used in matching. Required reading before trusting OSM postcodes. | — blog |
| 43 | **Photon (komoot)** | https://github.com/komoot/photon | Java/OpenSearch OSM geocoder with excellent typo-tolerant autocomplete. Apache-2.0 makes it the license-friendliest self-hosted geocoder. | ✅ Apache-2.0 (LICENSE confirmed) |
| 44 | **Pelias** | https://github.com/pelias/pelias | Modular open-data geocoder (OA + OSM + WOF + GeoNames). Its importers are a gold mine of per-source normalization code. | ✅ MIT |
| 45 | **Pelias Placeholder** | https://github.com/pelias/placeholder | Standalone **coarse** geocoder: resolves "city, region, country" strings to WOF ids with synonyms/abbreviations. Perfect for normalizing the admin tail of an address without a full geocoder. | ✅ MIT |
| 46 | **Pelias OpenAddresses importer** | https://github.com/pelias/openaddresses | Reference code for ingesting/cleaning OA CSVs (street/number/unit dedup rules). | ✅ MIT |
| 47 | **geocode.earth: one-line coarse geocoding with Docker** | https://geocode.earth/blog/2019/almost-one-line-coarse-geocoding/ | How to run Placeholder standalone — our fastest path to admin-hierarchy normalization. | — blog |
| 48 | **libpostal-rest (Go)** | https://github.com/johnlonganecker/libpostal-rest | Thin Go REST wrapper: `/parser`, `/expand`. Best way to keep libpostal's 2GB models in one sidecar instead of every worker. | ✅ MIT |
| 49 | **libpostal-rest-docker** | https://github.com/johnlonganecker/libpostal-rest-docker | Dockerfile for the above; the de-facto standard image lineage (many forks: matchory, cleydson, gnupablo). | ✅ MIT |
| 50 | **oozman/libpostal-rest-docker + Docker Hub image** | https://github.com/oozman/libpostal-rest-docker · https://hub.docker.com/r/oozman/libpostal-rest | A currently-published prebuilt image (`docker run -p 8080:8080 oozman/libpostal-rest`) if we don't want to build. | ❓ |
| 51 | **pasupulaphani/libpostal (Docker Hub)** | https://hub.docker.com/r/pasupulaphani/libpostal | Long-lived base image with libpostal compiled + models; notes the 4GB memory requirement. There is **no official openvenues image** — don't assume one exists. | ❓ |
| 52 | **Gisgraphy** | https://github.com/gisgraphy/gisgraphy | Java geocoder + **standalone address parser** web service over GeoNames/OSM/OA. Useful third-party parser opinion. | ⚠️ **LGPL** (gisgraphy.com/license.php) + commercial offering |
| 53 | **geopy** | https://github.com/geopy/geopy | Uniform client for ~30 geocoding services + Vincenty/geodesic distance. Use for the optional enrichment path only. | ✅ MIT |
| 54 | **DenisCarriere/geocoder** | https://github.com/DenisCarriere/geocoder | Alternative multi-provider geocoding client; low activity but handy CLI. | ✅ MIT |
| 55 | **OpenCage Geocoding API** | https://opencagedata.com/api | Paid open-data geocoder that returns both normalized components and a `formatted` string; the cheapest sane external truth source. | 💰 commercial API |

## 5. Reference datasets — addresses, places, admin hierarchy

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 56 | **OpenAddresses** | https://openaddresses.io/ | The free global address point collection (600M+ points) — our ground truth for "does this house number exist on this street". | ✅ mostly attribution-only; per-source |
| 57 | **OpenAddresses repo (source definitions)** | https://github.com/openaddresses/openaddresses | Per-jurisdiction source configs + field mappings. Repo licence BSD-3-Clause; `sources/` declared public domain. | ✅ BSD-3 / PD |
| 58 | **OpenAddresses attribution requirements** | https://openaddresses.io/attribution/ | The list of sources that legally require attribution — feed this straight into our license inventory. | ✅ read carefully |
| 59 | **OpenAddresses Batch (downloads)** | https://batch.openaddresses.io/ | Actual download endpoint for collections (addresses, buildings, parcels, roads). | ✅ |
| 60 | **OpenStreetMap copyright/licence** | https://www.openstreetmap.org/copyright | ODbL 1.0 + attribution + **share-alike on derived databases**. Critical: any normalization *database* we derive from OSM inherits ODbL. | ⚠️ **ODbL** — license-hostile for closed data products |
| 61 | **OSM wiki: Addresses** | https://wiki.openstreetmap.org/wiki/Addresses | The `addr:*` tagging model (incl. interpolation, `addr:place`, country quirks) — the schema our internal address model should be able to round-trip. | — docs |
| 62 | **OSM wiki: `Key:addr:*`** | https://wiki.openstreetmap.org/wiki/Key:addr:* | Full list of `addr:` subkeys with usage counts. | — docs |
| 63 | **GeoNames (export overview)** | https://www.geonames.org/export/ | 11M+ placenames, admin1/admin2 codes, alternate names — our lookup table for city/region normalization and alias resolution. | ⚠️ **CC-BY 4.0** (attribution required) |
| 64 | **GeoNames postal codes dump** | https://download.geonames.org/export/zip/ | Per-country postcode → place/admin/lat-lon files. The free worldwide postcode dataset. | ⚠️ CC-BY |
| 65 | **GeoNames postal readme (field layout + caveats)** | https://download.geonames.org/export/zip/readme.txt | Documents that CA/NL/GB only ship *partial* codes in the free file — a trap for validation logic. | — docs |
| 66 | **GeoNames Premium postal codes** | https://www.geonames.org/products/premium-postalcodes.html | Paid full-precision codes (incl. full CA/GB). Note if we need complete coverage. | 💰 commercial subscription |
| 67 | **Who's On First** | https://whosonfirst.org/ | Gazetteer of every place with stable WOF ids + concordances to GeoNames/Wikidata/etc. The right *join key* for admin-hierarchy normalization. | ⚠️ mixed; see licence page |
| 68 | **WOF licence page** | https://whosonfirst.org/docs/licenses/ | Per-source licence breakdown (CC-BY, OGL, local terms). Must be enumerated for our inventory. | ⚠️ per-source |
| 69 | **whosonfirst-data** | https://github.com/whosonfirst-data/whosonfirst-data | The actual data repos + SQLite/GeoParquet bundles. | ⚠️ |
| 70 | **WOF Spelunker** | https://spelunker.whosonfirst.org/ | Fast manual lookup/concordance browser — invaluable for debugging a bad region normalization. | — tool |
| 71 | **Overture Maps — Addresses theme** | https://docs.overturemaps.org/guides/addresses/ | 472M+ address points with a stable schema (street, number, unit, `address_levels`, postcode, country) in GeoParquet. Currently Alpha but the most query-friendly bulk address dataset. | ✅ **CDLA-Permissive-2.0** (unless source requires otherwise) |
| 72 | **Overture addresses launch post** | https://overturemaps.org/blog/2024/introducing-overture-maps-address-theme/ | Provenance and country coverage of the theme. | — blog |
| 73 | **Overture on AWS Open Data Registry** | https://registry.opendata.aws/overture/ | S3 paths + monthly cadence + the CDLA-Permissive-2.0 licence statement. | ✅ CDLA-2.0 |
| 74 | **Cosmogony (osm-without-borders)** | https://github.com/osm-without-borders/cosmogony | Extracts a clean worldwide administrative *hierarchy* from OSM with explicit zone types — solves "is this admin2 or admin3 in country X". | ⚠️ derived from OSM (ODbL) |
| 75 | **US National Address Database (NAD)** | https://catalog.data.gov/dataset/national-address-database-nad | USDOT-compiled authoritative US address points from state/local partners; free. Better provenance than OA for the US. | ✅ US Gov open data |
| 76 | **NAD text-file distribution** | https://catalog.data.gov/dataset/national-address-database-nad-text-file | The flat-file release (easier to ingest than the FGDB). | ✅ |
| 77 | **US Census TIGER/Line** | https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html | Street centerlines with **address ranges** — lets us validate/interpolate house numbers and normalize street names to Census spellings. | ✅ public domain |
| 78 | **Natural Earth** | https://www.naturalearthdata.com/ | Public-domain admin-0/1 boundaries at 3 scales; the safe choice when GADM's licence blocks us. | ✅ public domain |
| 79 | **GADM** | https://gadm.org/download_world.html · https://gadm.org/license.html | Very detailed global admin boundaries — but **academic/non-commercial only**. Flag loudly. | 💰 **license-hostile: no commercial use / no redistribution** |
| 80 | **Eurostat NUTS** | https://ec.europa.eu/eurostat/web/nuts | EU territorial statistical units + correspondence tables; needed for EU region normalization and NUTS↔postcode joins. | ✅ Eurostat reuse policy |

## 6. Codes & standards: countries, subdivisions, locations, postcodes

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 81 | **ISO 3166 (official landing)** | https://www.iso.org/iso-3166-country-codes.html | The normative country-code standard; codes browsable free on the ISO OBP, but the *published lists* are paywalled. (Page returns 403 to bots; verified via search + ISO OBP.) | 💰 standard text is paid; codes themselves reusable |
| 82 | **ISO 19160-1:2015 — Addressing, conceptual model** | https://www.iso.org/standard/61710.html | The formal conceptual model for address information (address classes, lifecycle, quality). The right vocabulary for our internal schema design. | 💰 paid standard |
| 83 | **ISO/TC 211 addressing hub** | https://committee.iso.org/sites/tc211/home/standards-in-action/addressing.html | Free companion material and a comparative review of national address standards. | — docs |
| 84 | **pycountry** | https://github.com/pycountry/pycountry | ISO 3166-1/-2/-3, 639-3, 4217, 15924 as a Python API (wraps Debian `iso-codes`) incl. translations. Our country/subdivision canonicalizer. | ⚠️ **LGPL-2.1** — fine as a runtime dependency, note it |
| 85 | **pycountry on PyPI** | https://pypi.org/project/pycountry/ | Install/version. | ⚠️ LGPL-2.1 |
| 86 | **ISO-3166-Countries-with-Regional-Codes** | https://github.com/lukes/ISO-3166-Countries-with-Regional-Codes | ISO 3166-1 joined to UN M.49 regions as ready CSV/JSON/XML — quick static lookup with no LGPL dependency. | ✅ (repo) |
| 87 | **iso3166-2 (amckenna41)** | https://github.com/amckenna41/iso3166-2 | Python package + dataset of ISO 3166-2 subdivisions with local names, flags, coordinates. Good for subdivision alias matching. | ✅ (repo) |
| 88 | **oodavid/iso-3166-2** | https://github.com/oodavid/iso-3166-2 | Static JSON of countries + subdivisions (reverse-geocoded). Useful as a frozen snapshot. | ✅ (repo) |
| 89 | **UN M.49 (UNSD methodology)** | https://unstats.un.org/unsd/methodology/m49/ | Authoritative region/subregion groupings + numeric codes; the neutral way to roll countries up to regions. | ✅ UN |
| 90 | **UN/LOCODE (UNECE portal)** | https://unlocode.unece.org/ | 103k+ trade/transport location codes in 249 countries (`CCLLL`), with coordinates and subdivision codes. Excellent free city-name + subdivision cross-reference, and mandatory if we touch logistics data. Downloads in CSV/Access/HTML. | ✅ free download (UNECE terms) |
| 91 | **CLDR project** | https://cldr.unicode.org/ | Locale data: territory names in every language, territory containment, likely subtags — our source for "Deutschland/Allemagne/독일 → DE". | ✅ Unicode licence |
| 92 | **unicode-org/cldr** | https://github.com/unicode-org/cldr | The XML source incl. `supplementalData.xml` → `territoryContainment`, `subdivisionContainment`, `postalCodeData`. | ✅ Unicode |
| 93 | **cldr-json** | https://github.com/unicode-org/cldr-json | Same data as JSON, npm-published — far easier to consume than the XML. Use this. | ✅ Unicode |
| 94 | **CLDR supplemental charts** | https://www.unicode.org/cldr/charts/latest/supplemental/index.html | Human-readable territory containment / territory info tables for sanity-checking our mappings. | ✅ |
| 95 | **UPU S42 international addressing standard (PDF)** | https://www.upu.int/UPU/media/upu/documents/PostCode/S42_International-Addressing-Standards.pdf | The UPU's generic address element list + per-country templates — the closest thing to a *global postal* standard, and the reference for which countries use which element order. | ✅ free PDF (UPU) |
| 96 | **UPU Addressing Solutions (incl. Universal POST\*CODE® DB + PAS)** | https://www.upu.int/en/Postal-Solutions/Programmes-Services/Addressing-Solutions | Per-country "Postal Addressing Systems" descriptions (free) and the raw postcode database (paid, with NDA + rate card). | Mixed: PAS free, POST\*CODE® 💰 **contract + NDA** |
| 97 | **USPS Publication 28 — Postal Addressing Standards** | https://pe.usps.com/text/pub28/welcome.htm | The normative US standardization rules: abbreviations, suffixes, secondary unit designators, ZIP+4 formatting. Our US canonical-form spec. | ✅ free US Gov publication |
| 98 | **Wikipedia: List of postal codes (by country)** | https://en.wikipedia.org/wiki/List_of_postal_codes | Per-country postcode notation schemes in one table — quick seed for a regex table, then verify each against #22/#33. | ⚠️ CC-BY-SA |

## 7. Postcode & geo-index utilities

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 99 | **pgeocode** | https://github.com/symerio/pgeocode | Offline postcode → (lat, lon, place, admin) for ~80 countries with pandas output + postcode distance. Fast, no network. Our default postcode resolver. | ✅ BSD-3 (data: GeoNames CC-BY) |
| 100 | **pgeocode on PyPI** | https://pypi.org/project/pgeocode/ | Install/version. | ✅ BSD-3 |
| 101 | **uszipcode** | https://github.com/MacHu-GWU/uszipcode-project | Bundled SQLite of US ZIPs with census/geometry attributes and rich search (by city, state, radius). Use for US ZIP enrichment and plausibility checks. | ✅ MIT (per conda-forge metadata) |
| 102 | **uszipcode on PyPI** | https://pypi.org/project/uszipcode/ | Install/version. | ✅ MIT |
| 103 | **Zippopotam.us** | https://zippopotam.us/ | Free keyless postcode→place API for 60+ countries, built on GeoNames. Handy for spot checks; **the site states the API is under ODbL**, so don't bulk-ingest into a closed DB. | ⚠️ ODbL |
| 104 | **Zippopotam.us docs** | https://docs.zippopotam.us/ | Endpoint shapes + the GeoNames provenance note. | ⚠️ |
| 105 | **postcodes.io** | https://postcodes.io/ | Free UK postcode lookup/validation/reverse-geocode/autocomplete API serving ONSPD + OS Open Names. | ✅ MIT code |
| 106 | **postcodes.io source** | https://github.com/ideal-postcodes/postcodes.io | Self-hostable — gives us offline UK postcode truth without PAF. | ✅ MIT |
| 107 | **postcodes.io licences page** | https://postcodes.io/docs/licences | Spells out MIT (code) + OS OpenData (GB) + separate NI terms. Copy into our inventory. | ✅/⚠️ mixed |
| 108 | **ONS Postcode Directory (ONSPD)** | https://www.data.gov.uk/dataset/d416ce0f-8c63-4ab8-9a43-2908242391a3/ons-postcode-directory-may-2026 | Quarterly UK postcode → full geography lookup (LSOA, LA, NUTS, coords). The free UK backbone. | ✅ OGL (check release) |
| 109 | **ONS Open Geography Portal** | https://geoportal.statistics.gov.uk/ | Where ONSPD/NSPL and boundary files actually live, with a stable API. | ✅ OGL |
| 110 | **OS Code-Point Open** | https://data.gov.uk/dataset/c1e0176d-59fb-4a8c-92c9-c8b376a80687/code-point-open | Free GB postcode-unit centroids (updated quarterly from PAF). Use instead of licensing PAF when centroid precision suffices. | ✅ OS OpenData |
| 111 | **Uber H3** | https://github.com/uber/h3 | Hexagonal hierarchical global grid — our blocking/bucketing key for coordinate-based candidate generation (resolution ≈ blocking radius). | ✅ Apache-2.0 |
| 112 | **h3-py** | https://github.com/uber/h3-py | Python bindings (`pip install h3`). | ✅ Apache-2.0 |
| 113 | **h3 on PyPI** | https://pypi.org/project/h3/ | Install/version. | ✅ |
| 114 | **H3 documentation** | https://h3geo.org/ | Resolution table (edge lengths/areas) — needed to pick the blocking resolution deliberately. | — docs |
| 115 | **Geohash (algorithm reference)** | https://en.wikipedia.org/wiki/Geohash | Prefix-based geo index; simpler than H3 and string-prefix-joinable in SQL. Know the meridian/pole discontinuities before using it for blocking. | ⚠️ CC-BY-SA (text) |
| 116 | **pygeohash** | https://pypi.org/project/pygeohash/ | Dependency-free pure-Python geohash encode/decode. Safest geohash dependency. | ✅ MIT |
| 117 | **python-geohash** | https://pypi.org/project/python-geohash/ | Faster native geohash implementation (Rust/PyO3 since 0.9). Use if geohashing is hot-path. | ✅ (per PyPI) |
| 118 | **Placekey technical whitepaper** | https://placekey.io/technical-whitepaper | Free universal place identifier (`what@where`, H3-based) designed exactly for address/POI joins across orgs. Consider emitting a Placekey as an output key. | ✅ free standard; API terms apply |
| 119 | **what3words API** | https://developer.what3words.com/public-api | 3-word grid addressing; occasionally appears in delivery data and must be recognized/expanded rather than parsed as a street. | 💰 commercial API |

## 8. Commercial address-verification services (for the "authoritative check" tier)

All of these are **💰 commercial** and most redistribute government reference files under restrictive terms — none can be embedded in an open license inventory.

| # | Resource | URL | What it gives us |
|---|---|---|---|
| 120 | **Google Address Validation API** | https://developers.google.com/maps/documentation/address-validation | Validate + standardize + geocode an address, with component-level verdicts (`inferred`, `replaced`, `unconfirmed`) and USPS CASS data for the US. The best-documented single API for a verdict-per-component model — worth mirroring in our own output schema. |
| 121 | **…validateAddress reference** | https://developers.google.com/maps/documentation/address-validation/reference/rest/v1/TopLevel/validateAddress | The exact `PostalAddress` in / `AddressComponent` + `Verdict` out contract. |
| 122 | **Smarty US Street API reference** | https://www.smarty.com/docs/apis/us-street-api/reference | CASS-certified US verification with DPV, RDI, ZIP+4, rooftop geocodes; documents the component field names we should map to. |
| 123 | **Smarty International Street API** | https://www.smarty.com/docs/cloud/international-street-api | Global verification + the "which fields are required per country" matrix. |
| 124 | **Loqate (address verification)** | https://www.loqate.com/en-us/address-verification/ | Global capture/verify, strong UK/EU reference data. |
| 125 | **Loqate Address Verify docs** | https://docs.loqate.com/our-services/address-verify/overview | Match-level / AVC (Address Verification Code) semantics — a useful model for confidence grading. |
| 126 | **Melissa Address Verification** | https://melissa.com/address-verification | Global address verification, 240+ countries, with standardization to local format. |
| 127 | **Melissa Global Address Verification reference guide** | https://docs.melissa.com/cloud-api/global-address-verification/global-address-verification-reference-guide.html | Result-code taxonomy (AS/AC/AE codes) — again good prior art for our own status codes. |
| 128 | **Melissa pricing** | https://www.melissa.com/pricing | Credit-based pricing, for cost modelling. |
| 129 | **Experian Address Validation** | https://docs.experianaperture.io/address-validation/experian-address-validation/ | Real-time + bulk validation across 245 countries/territories; Aperture docs are public. |
| 130 | **Experian `/validate` endpoint reference** | https://docs.experianaperture.io/address-validation/experian-address-validation/address-api-reference/validate | Request/response and "suggestions vs final address" model. |

## 9. National postal authority reference data (license-hostile, plan around it)

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 131 | **USPS CASS™ certification** | https://postalpro.usps.com/certifications/cass | What "CASS-certified" actually requires; needed if we ever claim USPS-grade standardization. | 💰 program + licence |
| 132 | **USPS AMS API (Address Matching System)** | https://postalpro.usps.com/address-quality/ams-api | USPS's own matching logic + ZIP+4 assignment as a licensable library. The authoritative US matcher. | 💰 **licence agreement required** |
| 133 | **USPS ZIP+4 Product** | https://postalpro.usps.com/address-quality-solutions/zip-4-product | The ZIP+4 reference file itself (part of AIS). | 💰 paid AIS product |
| 134 | **USPS Address Quality / AIS hub** | https://postalpro.usps.com/address-quality | Index of AIS products (City/State, ZIP+4, DPV, RDI, LACS) and the definition of a "standardized address". | — docs |
| 135 | **CASS (background)** | https://en.wikipedia.org/wiki/Coding_Accuracy_Support_System | Neutral explanation of the certification regime. | ⚠️ CC-BY-SA |
| 136 | **Royal Mail PAF (Powered by PAF)** | https://www.poweredbypaf.com/ | 32M UK delivery points / 1.8M postcodes — the only *complete* UK address file. | 💰 **commercial licence, per-use fees** |
| 137 | **PAF licensing model** | https://www.poweredbypaf.com/about-paf-licencing/ | How PAF licensing is structured (whole file vs postcode areas) — read before quoting UK coverage. | 💰 |
| 138 | **PAF (background)** | https://en.wikipedia.org/wiki/Postcode_Address_File | Neutral summary incl. the open-data controversy. | ⚠️ CC-BY-SA |
| 139 | **OS AddressBase Premium (UPRN)** | https://www.ordnancesurvey.co.uk/products/addressbase-premium | ~40M GB addresses with **UPRN** lifecycle (incl. provisional/historic) — the best UK join key if we can license it. | 💰 commercial |
| 140 | **Royal Mail PAF Public Sector Licence (via OS)** | https://www.ordnancesurvey.co.uk/licensing/paf-licence | The cheaper public-sector route to PAF, if applicable. | 💰 |
| 141 | **Canada Post AddressComplete** | https://www.canadapost-postescanada.ca/ac/ | Authoritative Canadian address capture/validation. | 💰 commercial |
| 142 | **Canada Post AddressComplete API** | https://www.canadapost-postescanada.ca/ac/support/api/ | The API surface for custom integration. | 💰 |
| 143 | **GeoPostcodes** | https://www.geopostcodes.com/postal-zip-code-database | Commercial worldwide postcode + admin-hierarchy database curated from ~1,500 authoritative sources; the usual answer when GeoNames coverage isn't enough. | 💰 commercial |
| 144 | **GeoPostcodes public sample data** | https://github.com/GeoPostcodes/gpc-data | Free sample CSVs (incl. a country-level file) — enough to evaluate schema fit before buying. | ❓ sample terms |

## 10. Papers (parsing, matching, geocoding)

| # | Resource | URL | What it gives us |
|---|---|---|---|
| 145 | **Barrentine — "Statistical NLP on OpenStreetMap"** | https://medium.com/@albarrentine/statistical-nlp-on-openstreetmap-b9d573e6cc86 | libpostal's author on why address parsing is an NLP problem; the original design rationale for normalization + expansion. (Medium 403s bots; verified via search + libpostal README, which links it as the canonical "Original post".) |
| 146 | **Barrentine — Part 2 (CRFs on 1B addresses)** | https://medium.com/@albarrentine/statistical-nlp-on-openstreetmap-part-2-80405b988718 | How the 1.0 parser was trained: feature design, address synthesis from OSM + OpenCage templates, evaluation. The single most useful document for building our own parser. |
| 146b | **Mapzen — "Inside libpostal"** | https://www.mapzen.com/blog/inside-libpostal/ | Shorter architectural tour of the training pipeline. |
| 147 | **Wang et al. — "A Probabilistic Address Parser Using CRFs and Stochastic Regular Grammar" (ICDMW 2016)** | https://research.gold.ac.uk/id/eprint/19514/ | Open-access PDF; CRF + grammar hybrid, explicitly framed for data cleansing / record linkage. Closest academic analogue to what we're building. (IEEE version: https://ieeexplore.ieee.org/document/7836670) |
| 148 | **Yassine et al. — "Leveraging Subword Embeddings for Multinational Address Parsing"** | https://arxiv.org/abs/2006.16152 | The deepparse model: subword embeddings + seq2seq generalizing across 20 countries. |
| 149 | **Beauchemin et al. — "Deepparse: An Extendable, Fine-Tunable … Library"** | https://arxiv.org/abs/2311.11846 | The tool paper; states the **LGPL-3.0** licence explicitly (see also https://aclanthology.org/2023.nlposs-1.3/). |
| 150 | **"Multinational Address Parsing: A Zero-Shot Evaluation"** | https://arxiv.org/abs/2112.04008 | How well address parsers transfer to *unseen* countries — directly relevant to our long-tail country coverage risk. |
| 151 | **Ramani & Borrajo (JPMorgan) — "Methods for Matching English Language Addresses"** | https://arxiv.org/abs/2403.12092 | Systematic comparison of address-matching methods from string distance to deep learning, with precision/recall/accuracy. Good benchmark design to copy. |
| 152 | **"Improving Address Matching Using Siamese Transformer Networks"** | https://arxiv.org/abs/2307.02300 | Siamese transformer for address matching with a retrieval/re-rank setup; practical accuracy/latency numbers. |
| 153 | **"Address Matching Based on Hierarchical Information"** | https://arxiv.org/abs/2305.05874 | Exploits the hierarchical structure of addresses rather than treating them as flat strings — argues for our component-wise matching design. |
| 154 | **"Improvement in Semantic Address Matching using NLP"** | https://arxiv.org/abs/2404.11691 | Semantic (embedding) matching vs classical similarity for addresses. |
| 155 | **"Fighting crime with Transformers: address parsing in payment data"** (NAACL 2024 industry) | https://arxiv.org/abs/2404.05632 | **Noisy, real-world** (payment-message) address parsing, plus an open augmented dataset — the closest published setting to dirty enterprise data. |
| 156 | **StructAM (LREC-COLING 2024)** | https://aclanthology.org/2024.lrec-main.1333/ | Structure-aware semantic address matching; handles misspellings/incompleteness. |
| 157 | **Amazon — "Pretraining and Finetuning LMs on Geospatial Networks for Accurate Address Matching" (EMNLP 2024 industry)** | https://aclanthology.org/2024.emnlp-industry.58/ | Amazon's production approach: pretrain on geospatial graphs, then decide "same physical building?". The industrial reference for address matching at scale. |
| 158 | **Amazon — "Learning Geolocations for Cold-Start and Hard-to-Resolve Addresses via Deep Metric Learning" (EMNLP 2022 industry)** | https://aclanthology.org/2022.emnlp-industry.33/ | Deals with addresses that can't be resolved by lookup at all — our worst-case bucket. |
| 159 | **GeoIndia — seq2seq geocoding for Indian addresses (EMNLP 2024 industry)** | https://aclanthology.org/2024.emnlp-industry.29/ | Loosely structured, multi-script, landmark-based addresses — the failure mode for every Western-trained parser. |
| 160 | **"Is ChatGPT a game changer for geocoding — a benchmark for address parsing"** | https://arxiv.org/abs/2310.14360 | LLM vs CRF/seq2seq on a 239k-record benchmark with 21 injected error types. Use its error taxonomy as our test-corruption generator. |
| 161 | **Geocoding Address Parsing Benchmark (code/data)** | https://github.com/zhengcongyin/Geocoding-Address-Parsing-Benchmark | The artifacts for #160 — a ready-made noisy evaluation set. |
| 162 | **"Toward building next-generation Geocoding systems: a systematic review"** | https://arxiv.org/abs/2503.18888 | 2025 survey of geocoding requirements, components and open problems — the best single orientation doc for the geo half. |
| 163 | **"Clean Me If You Can: A Large Collection of Real-World Addresses for Data Cleaning Benchmarking"** | https://arxiv.org/abs/2606.31983 | Large **dirty postal dataset + ground truth**, purpose-built for data-cleaning benchmarks. Highest-value eval asset found. |
| 164 | **mixed-address-parsing (HF dataset)** | https://huggingface.co/datasets/Josephgflowers/mixed-address-parsing | 100k–1M synthetic/mixed labelled addresses for smoke-testing a parser. Verify licence on the dataset card before use. |

## 11. Engineering write-ups & practitioner knowledge

| # | Resource | URL | What it gives us |
|---|---|---|---|
| 165 | **Michael Tandy — "Falsehoods programmers believe about addresses"** | https://www.mjt.me.uk/posts/falsehoods-programmers-believe-about-addresses/ | The canonical list of address assumptions that break (numberless buildings, leading-zero postcodes, postal ≠ administrative counties, address ≠ recipient location, PO/GPO/locked bags…). Turn each bullet into a unit test. |
| 166 | **Anchor-linked mirror of the above** | https://gist.github.com/almereyda/85fa289bfc668777fe3619298bbf0886 | Deep-linkable version, handy for citing individual falsehoods in tickets. |
| 167 | **kdeldycke/awesome-falsehood** | https://github.com/kdeldycke/awesome-falsehood | The umbrella list (addresses, names, time, geography, phone numbers) — all of which our normalization engine touches. CC0. |
| 168 | **Shopify Engineering — "Handling Addresses from All Around the World"** | https://shopify.engineering/handling-addresses-from-all-around-the-world | Production war story on internationalized address *forms and data model* at Shopify, incl. why they lean on Google's address metadata. |
| 169 | **Stripe — Address Element docs** | https://docs.stripe.com/elements/address-element | How a payments company models addresses across 236 regions (autocomplete, per-country field sets). Useful as a field-schema sanity check. |
| 170 | **geocode.earth — "The exactitude of postcodes"** | https://geocode.earth/blog/2026/exactitude-of-postcodes | Why postcodes don't cleanly attach to streets, and why a "missing" postcode is a modelling mismatch, not a data gap. Directly informs whether we treat postcode as required. |
| 171 | **Senzing — "What is libpostal?"** | https://senzing.com/what-is-libpostal/ | libpostal explained from an **entity-resolution** vantage point (exactly our use case). (Site 403s bots; content verified via extraction.) |

## 12. Matching / entity-resolution machinery (the consumer of normalization)

| # | Resource | URL | What it gives us | Licence |
|---|---|---|---|---|
| 172 | **dedupe** | https://github.com/dedupeio/dedupe | Active-learning fuzzy matching / dedup / ER in Python, with address-aware comparators. | ⚠️ check LICENSE (MIT-family per repo) |
| 173 | **Splink** | https://github.com/moj-analytical-services/splink | Fellegi–Sunter probabilistic linkage that runs **in the warehouse** (DuckDB/Spark/Athena). Best fit for scaling ER over our normalized output. | ✅ MIT |
| 174 | **Python Record Linkage Toolkit** | https://github.com/J535D165/recordlinkage | Modular blocking + comparison + classification; good for quick experiments and baselines. | ✅ BSD-3 |
| 175 | **RapidFuzz** | https://github.com/rapidfuzz/RapidFuzz | Fast string similarity (Levenshtein/JaroWinkler/token-set) in C++; the workhorse for component-level comparison. | ✅ MIT |
| 176 | **jellyfish** | https://github.com/jamesturk/jellyfish | Phonetic algorithms (Soundex/Metaphone/NYSIIS) + edit distances — for street-name phonetic blocking. | ✅ MIT |
| 177 | **microsoft/libpostal-tutorial** | https://github.com/microsoft/libpostal-tutorial | Microsoft's worked tutorial on using libpostal to structure extracted address text (from Form Recognizer). Good onboarding for the team. | ✅ CC-BY-4.0 docs / MIT code |

---

## License inventory: the ones to watch

**Hard blockers / needs legal sign-off**
- **GADM** (#79) — academic & non-commercial only, no redistribution. Use Natural Earth (#78) or OSM-derived boundaries instead.
- **Royal Mail PAF** (#136–138), **OS AddressBase** (#139), **USPS AMS/ZIP+4/AIS** (#132–133), **Canada Post AddressComplete** (#141–142), **UPU Universal POST\*CODE® DB** (#96), **GeoPostcodes** (#143) — all paid, all with redistribution restrictions. Treat as optional external services, never as bundled data.
- **Commercial APIs** (#120–130) — per-call terms usually forbid caching/deriving a database from results. If we cache verdicts, check each contract.

**Copyleft / share-alike — usable, but constrains what we ship**
- **Nominatim** (#35) — GPL-3.0-or-later. Run as a separate service; do not import its code.
- **deepparse** (#6–8) — LGPL-3.0. Safe as a dynamically-linked dependency or sidecar service; avoid vendoring into a proprietary binary.
- **pycountry** (#84) — LGPL-2.1. Same reasoning; or use the static JSON alternatives (#86–88) to sidestep it entirely.
- **Gisgraphy** (#52) — LGPL + commercial dual track.
- **OpenStreetMap / ODbL** (#60) — the big one. Any *database* we derive from OSM (including Nominatim/Photon/Pelias indexes, Cosmogony, and arguably libpostal's model data) carries ODbL share-alike obligations on the derived database. **libpostal's code is MIT but its trained models come from OSM + OpenAddresses** — get this reviewed before shipping the models inside a closed product (see the open discussion at https://github.com/openvenues/libpostal/issues/291).
- **GeoNames** (#63–65) — CC-BY: attribution required, incl. in derived products. pgeocode inherits this.
- **Who's On First** (#67–69), **OpenAddresses** (#56–59) — per-source licences; enumerate them (#58, #68) rather than assuming one blanket licence.
- **Zippopotam.us** (#103) — ODbL.
- **Wikipedia tables** (#98, #115, #135, #138) — CC-BY-SA; fine as research input, do not paste into shipped data files.

**Cleanest picks for a permissive stack**
libpostal code (MIT) + OpenCage address-formatting (MIT) + Google address metadata (CC-BY 4.0) + Overture addresses (CDLA-Permissive-2.0) + Photon (Apache-2.0) + Pelias/Placeholder (MIT) + H3 (Apache-2.0) + Splink/RapidFuzz/jellyfish (MIT) + Natural Earth (public domain) + UN/LOCODE + USPS Pub 28 (government, free).

---

### Notes on verification
- Every URL above returned HTTP 200 when fetched directly, **except** the following, which were verified via search-result metadata and/or inbound citation and are known to block automated clients: `iso.org` (#81, #82), `unece.org/trade/uncefact/unlocode` (use `unlocode.unece.org`, #90, which does resolve), `medium.com/@albarrentine` (#145, #146 — both linked as canonical from libpostal's README), `senzing.com` (#171), `experian.com` marketing page (docs subdomain used instead), `naturalearthdata.com` (#78, content extracted successfully), and `ieeexplore.ieee.org` (#147 — open-access PDF mirror at research.gold.ac.uk used as primary).
- Licences marked ✅/⚠️ were confirmed from a LICENSE file, repo metadata, or an explicit licence statement on the page. Entries marked ❓ had no licence visible where I looked and must be checked before adoption: addressit (#20), Geo::StreetAddress::US (#24), the community libpostal Docker images (#50, #51), deepparse-address-data (#9), GeoPostcodes samples (#144).
- **Security note:** while extracting `wiesmann.codiferes.net` ("Falsehoods programmers believe about geography", often cited alongside #165), the page returned an embedded prompt-injection payload instead of article text. That URL is therefore **excluded** from this list — do not fetch it with an automated agent.
