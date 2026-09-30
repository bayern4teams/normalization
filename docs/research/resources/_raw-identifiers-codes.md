# Identifiers, Codes & Reference/Authority Data — Verified Resource List

**Scope:** normalization + validation of identifiers (check digits, structural rules, authority lookups) and canonical code lists / taxonomies.
**Verification:** every URL below was fetched (HTTP 200) or content-extracted successfully during compilation. A handful of origins (iso.org, swift.com, bls.gov, sec.gov, unece.org, ssa.gov, spglobal.com) reject raw bot GETs with 403 but returned real content through an extractor — they are marked **(bot-walled)**, meaning the page is real but your crawler needs a browser UA.
**License flags:** 🔴 = paid/restricted redistribution, 🟡 = free but license/attribution/registration required, 🟢 = open.

---

## 1. Multi-format validation libraries (start here)

| # | Resource | URL | Why / when |
|---|---|---|---|
| 1 | **python-stdnum** (project home) | https://arthurdejong.org/python-stdnum/ | 🟢 LGPL-2.1+. The single highest-leverage dependency: 200+ number formats, plus built-in Luhn, Verhoeff and the whole ISO/IEC 7064 family. |
| 2 | python-stdnum — **supported formats index** | https://arthurdejong.org/python-stdnum/formats | Authoritative enumeration of every module (per-country VAT/tax IDs, national IDs, bank accounts, company registers). Scrape this to auto-generate your coverage matrix. |
| 3 | python-stdnum — API docs (2.2) | https://arthurdejong.org/python-stdnum/doc/ | Per-module `validate()`/`compact()`/`format()`/`is_valid()` contract; the `validate()`-raises-typed-exceptions pattern is what you want to wrap for error taxonomies. |
| 4 | python-stdnum — source | https://github.com/arthurdejong/python-stdnum | Read the modules directly when you need the exact check-digit maths (e.g. `stdnum/iso7064/`, `stdnum/luhn.py`, `stdnum/verhoeff.py`). |
| 5 | python-stdnum on PyPI | https://pypi.org/project/python-stdnum/ | Pin here; extras `[VIES]`, `[SOAP]` pull in online-verification deps. |
| 6 | **Cross-cutting coverage note** | https://arthurdejong.org/python-stdnum/formats | stdnum covers VAT (all EU + many non-EU), IBAN, ISBN/ISSN/ISMN, IMEI, LEI, GTIN/EAN/GS1, NPI, US SSN/EIN/ATIN/ITIN, CUSIP, ISIN, SEDOL, FIGI, MEID, VIN-adjacent, BIC, ISIL, GRid, CAS-RN, Damm/Verhoeff/Luhn/ISO 7064 — verify per-module before assuming. |
| 7 | **validators** (Python) | https://pypi.org/project/validators/ | Lightweight fallbacks for email/URL/IP/MAC/slug/card when you don't want stdnum's heft; weaker semantics — don't use it for money-grade IDs. |

## 2. Banking: IBAN, BIC/SWIFT, bank routing

| # | Resource | URL | Why / when |
|---|---|---|---|
| 8 | **schwifty** (docs) | https://schwifty.readthedocs.io/en/latest/ | IBAN + BIC objects with country-aware structure validation, BBAN→IBAN generation and bank-registry lookup — richer than a bare mod-97 check. |
| 9 | schwifty on PyPI / source | https://pypi.org/project/schwifty/ · https://github.com/mdomke/schwifty | Bundles a bank registry per country; check the registry's freshness before trusting bank-name resolution. |
| 10 | **ISO 13616 IBAN Registry** (registration authority) | https://www.iso13616.org/ | 🔴 SWIFT is the RA. The PDF/TXT registry is the only normative source for per-country IBAN length + BBAN layout. Redistribution of the registry file is restricted — derive structures, don't ship the file. |
| 11 | SWIFT IBAN standards page | https://www.swift.com/standards/data-standards/iban-international-bank-account-number **(bot-walled)** | 🔴 Registry download + registration procedures; states ISO designated SWIFT as RA. |
| 12 | ISO 13616-1:2007 (IBAN structure) | https://www.iso.org/standard/41031.html **(bot-walled)** | 🔴 Paywalled standard; cite for the mod-97-10 (ISO 7064) check and the "letters→digits" transliteration rule. |
| 13 | SWIFT BIC (ISO 9362) data standard | https://www.swift.com/standards/data-standards/bic-business-identifier-code **(bot-walled)** | 🔴 BIC8/BIC11 structure, BIC directory licensing. BIC *syntax* is free to implement; the *directory* of live BICs is a paid product. |
| 14 | IBAN structure reference (iban.com) | https://www.iban.com/structure | Convenient human-readable per-country IBAN layout table for sanity-checking your implementation. Commercial site — treat as secondary, not authority. |

## 3. Securities & legal-entity identifiers

| # | Resource | URL | Why / when |
|---|---|---|---|
| 15 | **GLEIF API** (LEI) | https://www.gleif.org/en/lei-data/gleif-api | 🟢 Free REST API over the full LEI registry; `https://api.gleif.org/api/v1/lei-records` is live and unauthenticated — ideal for on-the-fly entity resolution. |
| 16 | **GLEIF Golden Copy & Delta files** | https://www.gleif.org/en/lei-data/gleif-golden-copy · https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy | 🟢 CC0-style open data. Bulk LEI-CDF/RR-CDF/Reporting-Exceptions files, 3×/day + deltas — the right route for a local normalization table. |
| 17 | GLEIF LEI mapping files (ISIN↔LEI, BIC↔LEI, OpenCorporates↔LEI, GEM↔LEI) | https://www.gleif.org/en/lei-data/lei-mapping · https://www.gleif.org/en/lei-data/lei-mapping/download-isin-to-lei-relationship-files | 🟢 The crosswalk layer: turns a security identifier into an issuer entity. Essential for dedupe across financial datasets. |
| 18 | ISO 17442-1:2020 — LEI | https://www.iso.org/standard/78829.html **(bot-walled)** | 🔴 Normative 20-char LEI structure incl. the ISO 7064 MOD 97-10 two-digit checksum. |
| 19 | GLEIF — the LEI / ISO 17442 explainer | https://www.gleif.org/en/organizational-identity/lei-vlei/the-legal-entity-identifier-lei | Free restatement of the code structure when you can't buy the ISO text. |
| 20 | GLEIF blog — LEI for entity identification/matching | https://www.gleif.org/en/newsroom/blog/the-compliance-catalyst-transforming-entity-identification-in-the-digital-age-with-the-lei | Practitioner argument for LEI-anchored entity matching vs. name-matching; useful framing for your resolution strategy. |
| 21 | GLEIF blog index | https://www.gleif.org/en/newsroom/blog | Ongoing posts on mapping, vLEI, data quality reports. |
| 22 | **ISO 20275 Entity Legal Form (ELF) code list** | https://www.gleif.org/en/lei-data/code-lists/iso-20275-entity-legal-forms-code-list | 🟢 The canonical way to normalize "GmbH / Ltd / S.A. / Inc." suffixes — 4-char ELF codes, free download. Massively underused for company-name normalization. |
| 23 | **OpenFIGI API** | https://www.openfigi.com/api/documentation | 🟢 Free (rate-limited, key optional) mapping from ISIN/CUSIP/SEDOL/ticker → FIGI. FIGI itself is openly licensed — the escape hatch from CUSIP/SEDOL licensing. |
| 24 | OpenFIGI home / FIGI allocation rules | https://www.openfigi.com/ · https://www.openfigi.com/assets/local/figi-allocation-rules.pdf | Structure + check-digit (mod-10 double-add-double) and the "no embedded meaning" design rationale. |
| 25 | OMG FIGI specification | https://www.omg.org/spec/FIGI/ | 🟢 The formal open standard behind FIGI; cite when justifying FIGI as the neutral join key. |
| 26 | OpenFIGI API examples | https://github.com/OpenFIGI/api-examples | Batch-mapping request shapes (max 100 jobs/request) — copy the batching + backoff logic. |
| 27 | ISO 6166:2021 — ISIN | https://www.iso.org/standard/78502.html **(bot-walled)** | 🔴 Paywalled; ISIN = 2-char ISO 3166 prefix + 9 NSIN + Luhn check digit. |
| 28 | **ANNA** (Association of National Numbering Agencies) | https://anna-web.org/ | The ISIN registration authority network; per-country NNA list tells you who issues the NSIN you're parsing. |
| 29 | **CUSIP Global Services** | https://www.cusip.com/ · https://www.cusip.com/identifiers.html | 🔴 CUSIP numbers are licensed IP (CGS/S&P). You may compute/validate the mod-10 check digit, but redistributing CUSIP databases requires a licence. Prefer FIGI for public data. |
| 30 | **SEDOL** (LSEG) | https://www.lseg.com/en/data-analytics/market-data/data-analytics-pricing/data-symbology/sedol | 🔴 Licensed. 7-char alphanumeric with weighted (1,3,1,7,3,9,1) mod-10 check digit — algorithm is public, the Masterfile is not. |
| 31 | SEDOL Masterfile Service & Technical Guide (PDF) | https://lseg.com/content/dam/lseg/en_us/documents/sedol/sedol-masterfile-service-and-technical-guide-v8.8.pdf | Exact field layouts and check-digit spec, publicly posted by LSEG. |
| 32 | **ISO 10383 MIC** (market identifier codes) | https://www.iso20022.org/market-identifier-codes | 🟢 Free monthly CSV of operating/segment MICs — needed to normalize exchange references alongside ISIN/FIGI. |

## 4. Tax / VAT / government registries

| # | Resource | URL | Why / when |
|---|---|---|---|
| 33 | **EU VIES** VAT validation | https://ec.europa.eu/taxation_customs/vies/ | 🟢 Free existence-check of EU VAT numbers. Structural validation ≠ registration: always do stdnum-syntax first, VIES second. |
| 34 | VIES SOAP WSDL (machine endpoint) | https://ec.europa.eu/taxation_customs/vies/services/checkVatService.wsdl | Verified live WSDL. Expect per-member-state downtime (`MS_UNAVAILABLE`) — design for tri-state results: valid / invalid / unknown. |
| 35 | **HMRC "Check a UK VAT number" API** v2.0 | https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-registered-companies-api/2.0 | 🟡 Free, requires HMRC developer registration. Post-Brexit UK VAT is no longer in VIES — you need this as a separate route. |
| 36 | HMRC Developer Hub (API catalogue) | https://developer.service.hmrc.gov.uk/api-documentation/docs/api | Other UK tax-identifier APIs + the sandbox for tests. |
| 37 | **IRS — Valid EINs / prefix assignment** | https://www.irs.gov/businesses/small-businesses-self-employed/valid-eins | 🟢 Authoritative list of valid EIN campus prefixes — the only real structural validation available for EIN (no check digit). |
| 38 | IRS — ITIN | https://www.irs.gov/tin/itin/individual-taxpayer-identification-number-itin | ITIN range rules (9xx-{70–88,90–92,94–99}-nnnn) for distinguishing ITIN from SSN. |
| 39 | **SSA — SSN randomization** | https://www.ssa.gov/employer/randomization.html **(bot-walled)** | 🟢 Critical: since 2011-06-25 SSNs are randomized, so area-number→state inference and "high group" lists are **invalid**. Only the 000/666/900-999 area, 00 group, 0000 serial exclusions remain. |
| 40 | **Companies House Developer Hub** (UK) | https://developer.company-information.service.gov.uk/ | 🟡 Free with API key; canonical UK company numbers + officer data for entity normalization. |
| 41 | **OpenCorporates API** | https://api.opencorporates.com/ | 🔴/🟡 Cross-jurisdiction company identifiers; open-data tier for public-benefit use, commercial licence otherwise. Read the API terms before bulk use. |
| 42 | **NPPES NPI Registry API** (US healthcare) | https://npiregistry.cms.hhs.gov/api-page | 🟢 Free API; NPI is 10 digits with a Luhn check over the 80840-prefixed value — a classic gotcha. |
| 43 | NPPES bulk data files | https://download.cms.gov/nppes/NPI_Files.html | 🟢 Monthly full + weekly incremental dumps for offline NPI normalization. |

## 5. Phone numbers

| # | Resource | URL | Why / when |
|---|---|---|---|
| 44 | **google/libphonenumber** | https://github.com/google/libphonenumber | 🟢 Apache-2.0. The reference metadata + parsing/validation/formatting semantics; everything else is a port. |
| 45 | libphonenumber **FALSEHOODS.md** | https://github.com/google/libphonenumber/blob/master/FALSEHOODS.md | Read before designing your phone column: numbers are not stable, not unique per person, not always dialable, length/validity changes over time. |
| 46 | libphonenumber **FAQ.md** | https://github.com/google/libphonenumber/blob/master/FAQ.md | Explains `isValidNumber` vs `isPossibleNumber`, why to store **E.164 + region**, and metadata release cadence. |
| 47 | **phonenumbers** (Python port) | https://pypi.org/project/phonenumbers/ | The library to actually call; tracks upstream metadata versions closely. |
| 48 | python-phonenumbers source | https://github.com/daviddrysdale/python-phonenumbers | Port notes, metadata regeneration process, and the `phonenumberslite` variant. |
| 49 | phonenumberslite | https://pypi.org/project/phonenumberslite/ | Same validation without geocoder/carrier/timezone metadata — big install-size win if you only normalize. |
| 50 | **RFC 3966** — the `tel:` URI | https://www.rfc-editor.org/rfc/rfc3966.html | Canonical serialization when you must store phone numbers as URIs (incl. `phone-context` for local numbers). |
| 51 | ITU-T numbering resources (E.164) | https://www.itu.int/en/ITU-T/inr/Pages/default.aspx | Authoritative country-calling-code assignments; use to sanity-check libphonenumber metadata drift. |

## 6. Email addresses

| # | Resource | URL | Why / when |
|---|---|---|---|
| 52 | **email-validator** (Python) | https://pypi.org/project/email-validator/ · https://github.com/JoshData/python-email-validator | 🟢 Syntax + normalization (Unicode NFC, IDNA A-label) + optional DNS deliverability. The pragmatic default; returns a normalized form, which is what you actually want. |
| 53 | **RFC 5321** — SMTP | https://www.rfc-editor.org/rfc/rfc5321.html | The *authoritative* mailbox grammar and the 64-octet local-part / 255-octet domain / 254-char path limits. |
| 54 | **RFC 5322** — Internet Message Format | https://www.rfc-editor.org/rfc/rfc5322.html | Header address grammar (display names, groups, comments). Do **not** implement the full grammar for validation — cite it to justify why you don't. |
| 55 | **RFC 6531** — SMTPUTF8 | https://www.rfc-editor.org/rfc/rfc6531.html | EAI: UTF-8 local parts. Decide explicitly whether your pipeline accepts them; most downstream systems won't. |
| 56 | **RFC 6532** — Internationalized email headers | https://www.rfc-editor.org/rfc/rfc6532.html | The header-side counterpart to 6531; needed for correct EAI normalization. |
| 57 | **RFC 5890** — IDNA 2008 definitions | https://www.rfc-editor.org/rfc/rfc5890.html | A-label/U-label terminology; the basis for domain-part canonicalization. |
| 58 | **UTS #46** — IDNA Compatibility Processing | https://www.unicode.org/reports/tr46/ | Reconciles IDNA2003/2008 divergence (ß, ς, ZWJ). Choose transitional vs non-transitional *once*, document it. |
| 59 | **idna** (Python) | https://pypi.org/project/idna/ | IDNA 2008 + UTS 46 encoder; `encode(..., uts46=True)`. Python's stdlib `'idna'` codec is IDNA 2003 — a real bug source. |
| 60 | **dnspython** | https://www.dnspython.org/ | MX/A/AAAA checks for deliverability tiering; remember implicit-MX fallback to A records. |
| 61 | **RFC 7208** — SPF | https://www.rfc-editor.org/rfc/rfc7208.html | When your "valid email" check needs sending-domain policy signals, not just resolvability. |
| 62 | **disposable-email-domains** list | https://github.com/disposable-email-domains/disposable-email-domains | 🟢 The most maintained blocklist; pip-installable. Treat as a *signal*, never as validity — false positives are routine. |
| 63 | "Falsehoods programmers believe about email" | https://beesbuzz.biz/code/439-Falsehoods-programmers-believe-about-email | Corrects the regex-driven instincts: plus-addressing isn't universal, case sensitivity in local parts, non-unique mailboxes. |
| 64 | "Falsehoods programmers believe about names" | https://www.kalzumeus.com/2010/06/17/falsehoods-programmers-believe-about-names/ | The genre's origin; directly relevant to any person/org name normalization you bolt onto identifiers. |

## 7. URLs, domains, and opaque IDs

| # | Resource | URL | Why / when |
|---|---|---|---|
| 65 | **WHATWG URL Standard** | https://url.spec.whatwg.org/ | The living spec browsers implement, including the normative *serialization* algorithm — this is what "normalized URL" should mean today. |
| 66 | **RFC 3986** — URI generic syntax | https://www.rfc-editor.org/rfc/rfc3986.html | Still the reference for percent-encoding, dot-segment removal, and scheme-based normalization; differs from WHATWG in real ways — pick one. |
| 67 | **url-normalize** (Python) | https://pypi.org/project/url-normalize/ | Ready-made RFC-3986-style canonicalization (case, default ports, dot segments, IDNA). |
| 68 | **w3lib.url** | https://w3lib.readthedocs.io/en/latest/w3lib.html · https://github.com/scrapy/w3lib | `canonicalize_url()` from Scrapy: query-param sorting and encoding handling — the battle-tested dedupe canonicalizer. |
| 69 | **Public Suffix List** | https://publicsuffix.org/list/ · https://github.com/publicsuffix/list | 🟡 MPL-2.0. The only correct way to find a registrable domain; never split on the last two labels. |
| 70 | **tldextract** | https://pypi.org/project/tldextract/ · https://github.com/john-kurkowski/tldextract | PSL-backed subdomain/domain/suffix split with a cached local snapshot — pin the snapshot for reproducibility. |
| 71 | **RFC 9562** — UUIDs (obsoletes 4122) | https://www.rfc-editor.org/rfc/rfc9562.html | Current UUID spec incl. v6/v7/v8; v7 is the one to use for new time-ordered IDs. |
| 72 | RFC 4122 (historic) | https://www.rfc-editor.org/rfc/rfc4122.html | Cite only for legacy v1/v3/v4/v5 semantics you must keep parsing. |
| 73 | **ULID spec** | https://github.com/ulid/spec | Crockford base32, 26 chars, lexicographically sortable; note the spec's own monotonicity caveats. |
| 74 | python-ulid | https://pypi.org/project/python-ulid/ | Maintained ULID implementation with UUID interop. |
| 75 | Snowflake ID format | https://en.wikipedia.org/wiki/Snowflake_ID | Timestamp/worker/sequence bit layout — needed to *parse* (and detect string-vs-int64 precision loss in JSON). |

## 8. Trade, product, logistics & physical-asset identifiers

| # | Resource | URL | Why / when |
|---|---|---|---|
| 76 | **GS1 General Specifications** | https://www.gs1.org/standards/barcodes-epcrfid-id-keys/gs1-general-specifications | 🟡 Free PDF, GS1 IP. The normative source for GTIN-8/12/13/14, GLN, SSCC, GRAI, GIAI structures and AI syntax. |
| 77 | GS1 ID Keys overview | https://www.gs1.org/standards/id-keys · https://www.gs1.org/standards/id-keys/gtin · https://www.gs1.org/standards/id-keys/gln | Which key to use for products (GTIN), locations/parties (GLN), logistic units (SSCC). |
| 78 | GS1 check-digit calculator + manual method | https://www.gs1.org/services/check-digit-calculator · https://www.gs1.org/services/how-calculate-check-digit-manually | Ground-truth test vectors for the mod-10 (3,1) weighting used across GTIN/GLN/SSCC. |
| 79 | **International ISBN Agency — Range Message** | https://www.isbn-international.org/range_file_generation | 🟡 Free XML of all registration-group and registrant ranges — required to *hyphenate* ISBNs correctly and to reject structurally impossible ones. |
| 80 | **ISO 6346:2022** — freight containers | https://www.iso.org/standard/83558.html **(bot-walled)** | 🔴 Paywalled. Owner code + category + serial + mod-11 check digit (the letter→value table is the tricky part; note excluded values 11,22,33…). |
| 81 | **BIC — Bureau International des Containers** | https://www.bic-code.org/ · https://www.bic-code.org/bic-codes/ | The registration authority for ISO 6346 owner prefixes; lookup tool validates that a prefix is actually allocated. |
| 82 | **NHTSA vPIC VIN API** | https://vpic.nhtsa.dot.gov/api/ · https://vpic.nhtsa.dot.gov/api/home/index/faq | 🟢 Free, no key. Decodes VINs and exposes WMI tables; the FAQ documents the ISO 3779 position-9 check-digit rule (North America only). |
| 83 | **IMO Identification Number Schemes** | https://www.imo.org/en/ourwork/iiis/pages/imo-identification-number-schemes.aspx | Ship (7-digit, weighted 7..2 mod-10) and company/registered-owner IMO numbers; the resolution PDFs give the normative algorithm. |
| 84 | **GSMA device services / IMEI database** | https://www.gsmaservices.com/device-services/ | 🔴 TAC allocation authority. IMEI's Luhn check is trivial; verifying the TAC prefix is real requires the licensed TAC database. |
| 85 | **UN/LOCODE** | https://unece.org/trade/uncefact/unlocode **(bot-walled)** | 🟢 5-char place codes for ports/locations; the single best key for normalizing shipping locations. |
| 86 | UN/LOCODE downloads (CSV/TXT/MDB) | https://unece.org/trade/cefact/UNLOCODE-Download **(bot-walled)** | Current release files plus ISO 3166/4217 companion lists and the Rec-20 unit-of-measure codes. |
| 87 | UN/LOCODE as a data package | https://github.com/datasets/un-locode | 🟢 Git-versioned CSV mirror — far easier to diff release-over-release than the official zips. |
| 88 | **UN/CEFACT Code List Recommendations** (incl. Rec 20 units of measure) | https://unece.org/trade/uncefact/cl-recommendations **(bot-walled)** | 🟢 Rec 20/21 unit codes (KGM, MTR, C62…) — the normalization target for any quantity field in trade/EDI data. |
| 89 | **X12 External Code Lists** | https://x12.org/codes | 🔴 X12 content is licensed; membership/licence needed for full code sets. Check the terms page before embedding. |
| 90 | **ISO 20022 external code sets** | https://www.iso20022.org/catalogue-messages/additional-content-messages/external-code-sets | 🟢 Free, machine-readable, quarterly-updated (purpose codes, status reasons, etc.) — externalized precisely so you can update them without re-versioning messages. |

## 9. Country / currency / language / script code lists

| # | Resource | URL | Why / when |
|---|---|---|---|
| 91 | **pycountry** | https://pypi.org/project/pycountry/ | 🟢 ISO 3166-1/-2/-3, 4217, 639-3, 15924 shipped from the Debian `iso-codes` database — the least-effort correct source in Python, **including 3166-3 withdrawn/successor codes**. |
| 92 | **Debian `iso-codes`** | https://packages.debian.org/sid/iso-codes | 🟢 LGPL. Upstream of pycountry: JSON code lists + translations for 639/639-3/639-5, 4217, 3166/3166-2, 15924. Use it if you want language-neutral labels. |
| 93 | ISO 3166 (official landing) | https://www.iso.org/iso-3166-country-codes.html **(bot-walled)** | 🔴 Code list itself is browsable free on OBP but bulk/official files are paid. Note: ISO 3166-1 alpha-2 is **reassignable** — never treat it as an eternal key. |
| 94 | ISO 3166-3 (former countries) | https://en.wikipedia.org/wiki/ISO_3166-3 | Practical reference for deprecated→successor mapping (CS→RS/ME, AN→CW/SX/BQ, YU, DD…). Cross-check against pycountry's `historic_countries`. |
| 95 | **UN M49** standard area codes | https://unstats.un.org/unsd/methodology/m49/ · https://unstats.un.org/unsd/methodology/m49/overview/ | 🟢 Numeric region/subregion hierarchy that ISO 3166 numeric aligns with; the correct way to roll countries up to regions. |
| 96 | **ISO 4217 / SIX** (currency RA) | https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html | 🟢 SIX is the ISO 4217 maintenance agency; free current + historic currency XML/CSV incl. minor-unit exponents (JPY=0, TND=3 — do not hardcode 2). |
| 97 | ISO 4217 (ISO landing) | https://www.iso.org/iso-4217-currency-codes.html **(bot-walled)** | 🔴 Standard text paywalled; the code list itself is free from SIX. |
| 98 | **IANA Language Subtag Registry** | https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry | 🟢 The single normative file for BCP 47 subtags incl. `Deprecated`/`Preferred-Value` fields — this is how you canonicalize `iw`→`he`, `in`→`id`. |
| 99 | **RFC 5646 / BCP 47** | https://www.rfc-editor.org/rfc/rfc5646.html | Tag grammar + canonicalization + matching rules; read §4.5 on canonical form before writing your own. |
| 100 | **langcodes** | https://pypi.org/project/langcodes/ · https://github.com/rspeer/langcodes | 🟢 Best-in-class BCP 47 parsing, standardization, likely-subtag filling and *distance* scoring (for fuzzy matching locales). |
| 101 | language_data | https://pypi.org/project/language-data/ | Companion dataset giving langcodes human-readable names; separate install to keep the core light. |
| 102 | **ISO 639-3 (SIL) code tables** | https://iso639-3.sil.org/code_tables/download_tables · https://iso639-3.sil.org/ | 🟢 The registration authority's own downloads, including retirement/change-request tables — needed for deprecated language codes. |
| 103 | **ISO 15924 script codes** | https://www.unicode.org/iso15924/codelists.html · https://www.unicode.org/iso15924/iso15924-codes.html | 🟢 Unicode Consortium is the RA; free authoritative alpha-4 + numeric script list. |
| 104 | **CLDR** / cldr-json | https://cldr.unicode.org/ · https://github.com/unicode-org/cldr-json | 🟢 Locale display names, territory containment, currency formatting/rounding, likely subtags — the data layer under langcodes. |
| 105 | **country-converter (coco)** | https://pypi.org/project/country-converter/ · https://github.com/IndEcol/country_converter | 🟢 Regex-based matching of messy country *names* → ISO codes, plus conversion between 40+ classification schemes (EU, OECD, UN, EXIO, continent). The pragmatic tool for dirty input. |
| 106 | pycountry-convert | https://pypi.org/project/pycountry-convert/ | Country↔continent and alpha2/alpha3/numeric conversions layered on pycountry; lighter than coco, less fuzzy tolerance. |
| 107 | iso3166 (Python) | https://pypi.org/project/iso3166/ | Minimal zero-dependency alpha2/alpha3/numeric lookup when you can't take pycountry's data weight. |
| 108 | **REST Countries API** | https://restcountries.com/ | 🟢 Free JSON with codes, names, currencies, calling codes, TLDs. Good for enrichment/demos; snapshot it rather than depending on it at runtime. |
| 109 | **DataHub core: country-codes** | https://datahub.io/core/country-codes | 🟢 Frictionless data package joining ISO 3166-1, M49, ITU dialing, FIPS, currency and more in one CSV — the fastest way to bootstrap a crosswalk table. |
| 110 | DataHub core: language-codes / currency-codes | https://github.com/datasets/language-codes · https://github.com/datasets/currency-codes | 🟢 Git-versioned CSVs of ISO 639 and ISO 4217 — diffable, CI-friendly. |
| 111 | DataHub reference-data collection | https://datahub.io/collections/reference-data | Index of the other core reference packages (country-list, continent codes, airport codes…). |
| 112 | **Frictionless Data Package spec** | https://specs.frictionlessdata.io/data-package/ · https://frictionlessdata.io/ | 🟢 The packaging/schema convention those datasets use; worth adopting for your own emitted reference tables. |

## 10. Industry, product & occupation taxonomies

| # | Resource | URL | Why / when |
|---|---|---|---|
| 113 | **NACE** (Eurostat) | https://ec.europa.eu/eurostat/web/nace | 🟢 EU activity classification; NACE Rev. 2.1 is in force — plan for the Rev.2→2.1 migration, the correspondence tables are not 1:1. |
| 114 | Eurostat classifications hub / ShowVoc | https://ec.europa.eu/eurostat/web/metadata/classifications · https://showvoc.op.europa.eu/ | 🟢 Machine-readable (SKOS/linked-data) NACE, CPA, PRODCOM and correspondence tables — replaced the old RAMON interface. |
| 115 | **NAICS** (US Census) | https://www.census.gov/naics/ | 🟢 Public domain. 2022 revision current; the site serves crosswalks to prior vintages and to SIC. |
| 116 | **SIC** — SEC EDGAR code list | https://www.sec.gov/corpfin/division-of-corporation-finance-standard-industrial-classification-sic-code-list **(bot-walled)** | 🟢 The SIC variant actually used in EDGAR filings — if you're parsing SEC data, use *this* list, not the 1987 OSHA manual. |
| 117 | **ISIC Rev. 4** (UNSD) | https://unstats.un.org/unsd/classifications/Econ/isic · https://unstats.un.org/unsd/classifications/Family/Detail/27 | 🟢 The UN parent classification that NACE/NAICS map to; use as the pivot when crosswalking between national schemes. |
| 118 | ISIC Rev. 4 publication (PDF) | https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_4_publication_English.pdf | Full structure + explanatory notes for classification-boundary decisions. |
| 119 | UNSD classification structures/downloads | https://unstats.un.org/unsd/classifications/Econ/Structure | 🟢 Downloadable structures for ISIC, CPC, SITC and the official correspondence tables. |
| 120 | **SITC Rev. 4** | https://unstats.un.org/unsd/trade/sitcrev4.htm | 🟢 Trade-statistics commodity classification; still required for long historical trade series. |
| 121 | **WCO Harmonized System** | https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs-nomenclature-2022-edition/hs-nomenclature-2022-edition.aspx | 🔴/🟡 HS 6-digit nomenclature is WCO IP; the edition pages are free to browse but bulk reuse is restricted. Note national codes extend to 8–10 digits. |
| 122 | WCO Trade Tools (HS browser) | https://www.wcotradetools.org/en/harmonized-system | Browse/search HS 2022 incl. the alphabetical index — useful for building a lookup UI, not for bulk export. |
| 123 | **UNSPSC** (UNDP, owner) | https://www.undp.org/unspsc | 🔴/🟡 UNSPSC is owned by UNDP; browsing is free, the full codeset requires a subscription for commercial use. ⚠️ The historical `unspsc.org` domain currently serves unrelated spam content — do **not** link or fetch it. |
| 124 | UNSPSC via UNGM | https://www.ungm.org/public/unspsc | 🟢 Free public browser/export of UNSPSC segments–families–classes–commodities for UN procurement use. |
| 125 | **ECLASS** | https://eclass.eu/en · https://eclass.eu/en/eclass-standard | 🔴 Membership/licence required for the full release (14.x). Strong in industrial/technical product properties where UNSPSC is too coarse. |
| 126 | ECLASS release notes (14.0 example) | https://eclass.eu/en/news/news/eclass-release-140-now-available-for-download | Shows release cadence and AAS/Digital-Product-Passport submodels — relevant if you're normalizing manufacturing data. |
| 127 | **GICS** (MSCI) | https://www.msci.com/indexes/index-resources/gics | 🔴 Jointly owned MSCI + S&P Dow Jones; **licensed** — you may not redistribute GICS classifications. Methodology PDF is free to read. |
| 128 | GICS (S&P Dow Jones side) | https://www.spglobal.com/spdji/en/landing/topic/gics/ **(bot-walled)** | 🔴 Sector/industry-group definitions; use for mapping logic, licence for the assignments themselves. |
| 129 | **SOC** (US BLS) | https://www.bls.gov/soc/ **(bot-walled)** | 🟢 Public domain 2018 SOC structure + crosswalks; the US occupation normalization target. |
| 130 | **ISCO-08** (ILO) | https://isco.ilo.org/en/ · https://www.ilo.org/publications/international-standard-classification-occupations-isco-08 | 🟢 The international occupation classification and its correspondence tables to national schemes (incl. SOC). |

## 11. Health & life-science terminologies

| # | Resource | URL | Why / when |
|---|---|---|---|
| 131 | **ICD-10** browser (WHO) | https://icd.who.int/browse10/2019/en | 🟡 Free to browse/use with WHO terms; the 2019 release is the final ICD-10 version. |
| 132 | ICD-11 / WHO classifications hub | https://icd.who.int/browse/2025-01/mms/en · https://www.who.int/standards/classifications/classification-of-diseases | 🟡 ICD-11 has a proper API and stable URIs — prefer it for new work; note ICD-10↔11 mapping is lossy. |
| 133 | **SNOMED CT licensing** | https://www.snomed.org/licensing | 🔴 **Hard restriction.** Free only inside Member countries or for qualifying research; otherwise annual per-system fees. Never ship SNOMED content in a general-purpose package. |
| 134 | SNOMED CT via NLM (US) | https://www.nlm.nih.gov/healthit/snomedct/index.html · https://www.nlm.nih.gov/healthit/snomedct/snomed_licensing.html | 🟡 US users get SNOMED free via a UMLS licence — but still a licence, and still not redistributable. |
| 135 | **LOINC** | https://loinc.org/ · https://loinc.org/kb/license | 🟡 Free, but requires accepting the LOINC licence and preserving attribution/notices. Lab/observation code normalization. |
| 136 | **HL7 FHIR terminology module** | https://www.hl7.org/fhir/terminology-module.html | 🟢 CodeSystem/ValueSet/ConceptMap model — the best general *framework* for representing any code list with versions and mappings, even outside health. |
| 137 | FHIR "Using Codes / known code systems" | https://www.hl7.org/fhir/terminologies-systems.html · https://build.fhir.org/terminologies-systems.html | 🟢 Canonical URI registry for external code systems (ICD, LOINC, SNOMED, ISO 3166…) — steal these URIs as your system identifiers. |
| 138 | terminology.hl7.org (THO) | https://terminology.hl7.org/ · https://terminology.hl7.org/codesystems.html | 🟢 Published, versioned HL7 code systems and value sets with stable canonical URLs. |

## 12. Research, bibliographic & authority identifiers

| # | Resource | URL | Why / when |
|---|---|---|---|
| 139 | **ORCID documentation** | https://info.orcid.org/documentation/ | 🟢 Public API (free) for researcher identifiers. |
| 140 | ORCID iD structure & checksum | https://support.orcid.org/hc/en-us/articles/360006897674-Structure-of-the-ORCID-Identifier | The ISNI-compatible MOD 11-2 check character (can be `X`) and the 0000-0001-5000-0007 → 0000-0003-5000-0001 valid range. |
| 141 | ORCID Public API (live example) | https://pub.orcid.org/v3.0/0000-0002-1825-0097 | Verified live endpoint — use for existence checks after structural validation. |
| 142 | **Crossref REST API** | https://api.crossref.org/ · https://www.crossref.org/documentation/retrieve-metadata/rest-api/ | 🟢 Free DOI resolution/metadata; the polite-pool `mailto` parameter matters for rate limits. |
| 143 | **DOI Handbook** | https://www.doi.org/the-identifier/resources/handbook/ · https://www.doi.org/doi-handbook/HTML/index.html | Normative DOI syntax (prefix/suffix, case-insensitivity, no check digit) and the `https://doi.org/` display rule. |
| 144 | **ROR** (Research Organization Registry) | https://ror.org/ | 🟢 CC0 open registry of research organizations — the open alternative to proprietary org IDs; IDs carry an ISO 7064 mod-97 check. |
| 145 | ROR REST API | https://ror.readme.io/docs/rest-api | 🟢 Free, no key; affiliation-string matching endpoint is genuinely good for messy institution names. |
| 146 | ROR data dumps | https://ror.readme.io/docs/data-dump · https://github.com/ror-community/ror-data | 🟢 Versioned full dumps (CC0) for offline normalization. |
| 147 | **ISNI** | https://isni.org/ · https://isni.org/page/technical-documentation/ | 🟡 ISO 27729. 16-digit with MOD 11-2 check; bulk access and assignment run through registration agencies/OCLC. |
| 148 | **VIAF** | https://viaf.org/ · https://viaf.org/en/viaf/data | 🟡 OCLC-operated name-authority clustering across national libraries; data dumps available under OCLC's terms (ODC-BY-ish, check current notice). |
| 149 | VIAF at OCLC Research | https://www.oclc.org/en/viaf.html | Background on the clustering algorithm — important because VIAF clusters split/merge, so VIAF IDs are *not* permanently stable. |
| 150 | **OCLC APIs / WorldCat Search** | https://www.oclc.org/developer/api/oclc-apis.en.html · https://www.oclc.org/developer/api/oclc-apis/worldcat-search-api.en.html | 🔴 Requires an OCLC subscription/WSKey. OCLC numbers are the join key for library holdings. |
| 151 | **Wikidata Query Service** | https://query.wikidata.org/ | 🟢 CC0. SPARQL over thousands of external-identifier properties — the universal crosswalk of last resort (LEI↔ISIN↔VIAF↔ORCID↔GRID↔ROR…). Quality varies; treat as hints. |
| 152 | Wikidata database downloads | https://www.wikidata.org/wiki/Wikidata:Database_download | 🟢 Full JSON dumps when the query service times out on large crosswalk extractions. |

## 13. Check-digit algorithms & semantic-web vocabularies

| # | Resource | URL | Why / when |
|---|---|---|---|
| 153 | **Luhn algorithm** | https://en.wikipedia.org/wiki/Luhn_algorithm | Mod-10 double-add-double; used by IMEI, NPI, CUSIP, ISIN, credit cards. Catches all single-digit errors, misses 09↔90 transpositions. |
| 154 | **Verhoeff algorithm** | https://en.wikipedia.org/wiki/Verhoeff_algorithm | Dihedral-group check catching *all* single-digit and all adjacent-transposition errors (e.g. Aadhaar). Cite when you need a stronger-than-Luhn scheme. |
| 155 | **Damm algorithm** | https://en.wikipedia.org/wiki/Damm_algorithm | Same error-detection strength as Verhoeff with a single quasigroup table and no permutation — simpler to implement correctly. |
| 156 | **ISO/IEC 7064:2003** — check character systems | https://www.iso.org/standard/31531.html **(bot-walled)** | 🔴 Paywalled but foundational: MOD 11-2 (ISNI/ORCID), MOD 37-2, MOD 97-10 (IBAN/LEI), MOD 11,10, MOD 27,26. `stdnum.iso7064` implements these — use it instead of rolling your own. |
| 157 | UNECE note on the Luhn algorithm (PDF) | https://www.unece.org/fileadmin/DAM/trans/doc/2020/sc2/ECE-TRANS-SC.2-EG_PIRRS-2020-4e_01.pdf | A citable, non-wiki description of Luhn with worked examples for spec documents. |
| 158 | **schema.org** | https://schema.org/ · https://schema.org/docs/schemas.html | 🟢 `identifier`/`PropertyValue` pattern for emitting typed identifiers in structured data; also `leiCode`, `duns`, `taxID`, `isbn` properties. |
| 159 | **DCMI Metadata Terms** | https://www.dublincore.org/specifications/dublin-core/dcmi-terms/ | 🟢 `dcterms:identifier` and the encoding-scheme pattern; the minimal vocabulary for describing reference datasets you publish. |
| 160 | **FIBO** (EDM Council) | https://spec.edmcouncil.org/fibo/ · https://github.com/edmcouncil/fibo | 🟢 MIT-licensed financial ontology with formal models of LEI, ISIN, MIC, currency and legal entities — useful as a conceptual schema for a finance-domain normalization engine. |
| 161 | **BIPM — the SI** | https://www.bipm.org/en/measurement-units | 🟢 Authoritative unit definitions to pair with UN/CEFACT Rec-20 unit *codes* when normalizing quantities. |

---

## Practical notes worth encoding as engine rules

1. **Structure ≠ existence.** Validate syntax/check digit locally (stdnum), then optionally confirm against an authority (VIES, GLEIF, NPPES, vPIC). Model three states: `valid`, `invalid`, `unverifiable` — never collapse a registry outage into "invalid".
2. **Codes are mutable.** ISO 3166 alpha-2 can be reassigned; ISO 639 has deprecated tags with `Preferred-Value`; NACE Rev.2→2.1 and NAICS vintages break 1:1 assumptions; VIAF clusters merge. Store the *code plus the code-list version* you validated against.
3. **Licence contamination risk.** SNOMED CT, GICS, CUSIP, SEDOL, X12, ECLASS, UNSPSC (full codeset), HS bulk, SWIFT IBAN/BIC registries and OCLC data all carry redistribution limits. Keep them in optional, separately-installed data plugins — never vendored into the core package. Open substitutes exist for several: FIGI (for CUSIP/SEDOL), ISIC/NACE (for GICS), LOINC (for parts of SNOMED), ROR (for proprietary org IDs).
4. **Prefer official machine-readable feeds over scraped pages**: GLEIF Golden Copy, IANA subtag registry, SIX ISO 4217 XML, ISO 20022 external code sets, ISBN Range Message, Debian `iso-codes`, ROR dumps, UN/LOCODE CSV.
5. **Canonicalize, then compare.** E.164+region for phones, NFC + IDNA A-label for emails, WHATWG serialization (or RFC 3986 + PSL) for URLs, upper-case compact form for most alphanumeric IDs — and always keep the raw input alongside the canonical form.
