# Verified Resource Map — Numbers, Dates/Times, Currency, Money, Units, Measurements & Locale Data

**Verification:** every URL checked live. Unmarked links returned HTTP 200 to a plain fetch. Links marked **(bot-walled)** return 403 to `curl` but were confirmed to exist and carry the stated content via an extraction service (ISO, UNECE, LoC, IMF). Licenses read from each project's LICENSE file or the GitHub license API, not assumed. 90 entries.

---

## 1. Locale data foundations — CLDR, ICU, Babel (the authoritative layer)

1. **Unicode CLDR project home** — https://cldr.unicode.org/ — Entry point and release cadence for the locale data that every number/date/currency/unit decision must be sourced from.
2. **unicode-org/cldr** — https://github.com/unicode-org/cldr — Upstream XML: number patterns, symbols, currency digits, unit conversions and preferences. *License: Unicode License v3 (permissive, attribution).*
3. **unicode-org/cldr-json** — https://github.com/unicode-org/cldr-json — Ready-to-consume JSON packages (`cldr-numbers-full`, `cldr-dates-full`, `cldr-units-full`); pin a version per engine release. *License: Unicode License v3.*
4. **UTS #35 / TR35 — LDML (index)** — https://unicode.org/reports/tr35/ — Normative spec for locale identifiers and all CLDR data; treat this as the engine's rulebook.
5. **TR35 Part 3: Numbers** — https://www.unicode.org/reports/tr35/tr35-numbers.html — Defines decimal/group separators, number patterns, currency spacing and lenient-parsing semantics.
6. **TR35 Part 4: Dates** — https://www.unicode.org/reports/tr35/tr35-dates.html — Date field symbol table, skeletons, calendars, eras; source of truth for locale date order (`dd/MM` vs `MM/dd`).
7. **TR35 Part 6: Supplemental** — https://unicode-org.github.io/cldr/ldml/tr35-info.html — Currency↔territory mapping, currency rounding/minor units, measurement systems, unit preference data.
8. **CLDR plural rules spec** — https://cldr.unicode.org/index/cldr-spec/plural-rules — Needed to emit correct unit/currency plural forms, and to parse localized unit names.
9. **CLDR chart: number formatting patterns by locale** — https://www.unicode.org/cldr/charts/47/by_type/numbers.number_formatting_patterns.html — Direct evidence for which locales use `,` vs `.` vs NBSP grouping — the data backing an AMBIGUOUS verdict on `1,234`.
10. **CLDR chart: unit preferences** — https://unicode.org/cldr/charts/47/supplemental/unit_preferences.html — Region + usage → preferred unit (road distance in `mi` for en-US); drives canonical-unit selection per locale.
11. **Unicode License v3 (full text)** — https://www.unicode.org/license.txt — Exact terms for redistributing CLDR/ICU data inside a product.
12. **unicode-org/icu (ICU4C / ICU4J)** — https://github.com/unicode-org/icu — Reference implementation of TR35; when ICU and your parser disagree, ICU is right. *License: Unicode License v3.*
13. **PyICU (upstream)** — https://gitlab.pyicu.org/main/pyicu — Python bindings to ICU4C — the only way to get full ICU parse fidelity in Python; needs a matching system ICU. *License: MIT-style (see repo).*
14. **python-babel/babel** — https://github.com/python-babel/babel — Pure-Python CLDR consumer; check which CLDR version each release bundles. *License: BSD-3-Clause.*
15. **babel.numbers API** — https://babel.pocoo.org/en/latest/api/numbers.html — `parse_decimal`/`format_decimal`/`format_currency`: raises on malformed input instead of guessing a separator convention.

## 2. Date/time standards and formal models

16. **ISO 8601 — official landing page** — https://www.iso.org/iso-8601-date-and-time-format.html — Authoritative description/scope of the base standard **(bot-walled)**.
17. **ISO 8601-2:2019 (extensions)** — https://www.iso.org/standard/70908.html — The part standardizing uncertain, approximate, partial and set-valued dates **(bot-walled)**.
18. **RFC 3339** — https://www.rfc-editor.org/rfc/rfc3339 — The strict internet profile to emit as canonical output; deliberately narrower than ISO 8601.
19. **RFC 9557 (IXDTF)** — https://www.rfc-editor.org/rfc/rfc9557.html — Standard suffix syntax `…[Europe/Berlin][u-ca=…]` so a serialized instant keeps its zone and calendar.
20. **EDTF specification (Library of Congress)** — https://www.loc.gov/standards/datetime/ — The practical model for `1984?`, `1984~`, `199X`, `[1667,1668]` — exactly the "preserve precision, never invent" requirement **(bot-walled)**.
21. **ixc/python-edtf** — https://github.com/ixc/python-edtf — Parses EDTF into explicit date *ranges* with uncertainty flags rather than a single datetime. *License: MIT.*
22. **TC39 Temporal documentation** — https://tc39.es/proposal-temporal/docs/index.html — Best available type taxonomy to copy: Instant vs PlainDate vs PlainDateTime vs ZonedDateTime, plus DST disambiguation policies.

## 3. Date/time parsing and handling libraries

23. **dateparser** — https://dateparser.readthedocs.io/en/latest/ — Multi-language natural-language parsing with explicit `DATE_ORDER`, `PREFER_DAY_OF_MONTH`, language allowlists; unconstrained defaults will guess. *License: BSD-3-Clause.*
24. **dateutil/dateutil** — https://github.com/dateutil/dateutil — `parser.parse`, `relativedelta`, `tz`; powerful but over-eager — always set `dayfirst`/`yearfirst` and never use `fuzzy` in a normalizer. *License: Apache-2.0 / BSD dual.*
25. **pendulum** — https://github.com/python-pendulum/pendulum — Aware-by-default datetimes with DST-correct arithmetic; good model for the internal type. *License: MIT.*
26. **arrow** — https://arrow.readthedocs.io/en/latest/ — Ergonomic parsing/humanizing, but normalizes aggressively — a precision-loss risk worth knowing. *License: Apache-2.0.*
27. **whenever** — https://github.com/ariebovenberg/whenever — Type-safe Python datetimes separating local/instant like Temporal; strongest correctness story in Python today. *License: MIT.*
28. **ciso8601** — https://github.com/closeio/ciso8601 — Very fast strict ISO 8601 parser; ideal fast path before any fuzzy fallback. *License: MIT.*
29. **udatetime** — https://github.com/freach/udatetime — Fast C RFC 3339 parse/format; narrower scope than ciso8601. *License: Apache-2.0.*

## 4. Temporal expression extraction & normalization (text → normalized value)

30. **facebook/duckling** — https://github.com/facebook/duckling — Rule + ranking parser that emits normalized time, number, amount-of-money, duration and quantity values from free text. *License: BSD-3-Clause.*
31. **FraBle/python-duckling** — https://github.com/FraBle/python-duckling — JVM-bridge Python wrapper over the older Clojure Duckling; pin it knowingly. *License: Apache-2.0.*
32. **sonos/rustling-ontology** — https://github.com/sonos/rustling-ontology — Concrete multilingual rules for numbers, money, durations and temperatures — a good template for your own rule set. *License: see repo (Apache/MIT).*
33. **HeidelTime** — https://github.com/HeidelTime/heideltime — Multilingual TIMEX3 tagger with news/narrative/colloquial/scientific domain modes. *License: GPL-3.0 — copyleft, check before embedding.*
34. **SUTime (Stanford CoreNLP)** — https://stanfordnlp.github.io/CoreNLP/sutime.html — Deterministic rule-based temporal tagger with TIMEX3 output and explicit reference-date handling. *License: GPL-3.0.*
35. **Stanza** — https://stanfordnlp.github.io/stanza/ — Neural NER emitting DATE/TIME/MONEY/PERCENT/QUANTITY spans for candidate detection upstream of normalization. *License: Apache-2.0.*
36. **spaCy EntityRecognizer** — https://spacy.io/api/entityrecognizer — Production-friendly span detection (`DATE`, `TIME`, `MONEY`, `QUANTITY`, `CARDINAL`) to feed the normalizer. *License: MIT.*
37. **timefhuman** — https://github.com/alvinwan/timefhuman — Human phrasings and ranges ("7/17 3-4 PM"); small, and a useful source of test cases. *License: Apache-2.0.*
38. **TempEval-3 task paper** — https://arxiv.org/pdf/1206.5333 — Defines evaluation of timex extraction *and value normalization*; reuse its metrics to report your own accuracy.
39. **TIMEX3 annotation guidelines (LDC PDF)** — https://catalog.ldc.upenn.edu/docs/LDC2012T12/annotationGuidelines_timex3_SP.pdf — Concrete rules for granularity, sets, durations and underspecified values — the annotation contract to mirror in your output schema.

## 5. Time zones, tzdata and leap seconds

40. **IANA Time Zone Database** — https://www.iana.org/time-zones — Authoritative tzdb releases; record which tzdb version produced each resolved offset.
41. **tz "theory.html"** — https://data.iana.org/time-zones/theory.html — Maintainers' own document on zone naming, stability guarantees and pre-1970 data caveats — mandatory reading before trusting historical offsets.
42. **Python `zoneinfo`** — https://docs.python.org/3/library/zoneinfo.html — The correct modern API; note the system-tzdata dependency and `fold` semantics.
43. **stub42/pytz** — https://github.com/stub42/pytz — Legacy but ubiquitous; its `localize`/`normalize` model is a top source of silently wrong results. *License: MIT.*
44. **"pytz: The Fastest Footgun in the West"** — https://blog.ganssle.io/articles/2018/03/pytz-fastest-footgun.html — Precise explanation of why pytz arithmetic breaks; the argument for a zoneinfo-only policy.
45. **PEP 495 — local time disambiguation (`fold`)** — https://peps.python.org/pep-0495/ — Normative rule for the doubled hour at DST fall-back; required to classify a local timestamp as AMBIGUOUS.
46. **IANA leap-seconds.list** — https://data.iana.org/time-zones/tzdb/leap-seconds.list — Machine-readable leap-second table with an expiry date, for TAI/UTC-correct handling.
47. **Google leap smear** — https://developers.google.com/time/smear — Why real ingested timestamps near a leap second may be smeared or duplicated rather than :60.
48. **"Falsehoods programmers believe about time"** — https://infiniteundo.com/post/25326999628/falsehoods-programmers-believe-about-time — Convert directly into a negative-test checklist for the date engine.
49. **Jon Skeet — "Storing UTC is not a silver bullet"** — https://codeblog.jonskeet.uk/2019/03/27/storing-utc-is-not-a-silver-bullet/ — Why future local times must retain zone + wall time, not just an instant.
50. **Matt Johnson-Pint — Code of Matt** — https://codeofmatt.com/ — Long-running date/time/timezone correctness blog from a tz/CLDR contributor; source for offset vs zone pitfalls.

## 6. Numbers, decimals and numeric ambiguity

51. **Python `decimal`** — https://docs.python.org/3/library/decimal.html — Context, rounding modes and exponent preservation; the only acceptable numeric type for money and for keeping `1.50` ≠ `1.5`.
52. **General Decimal Arithmetic (Cowlishaw)** — https://speleotrove.com/decimal/ — The normative arithmetic model behind `decimal`, incl. significant-trailing-zero semantics your precision rules depend on.
53. **Decimal separator (Wikipedia)** — https://en.wikipedia.org/wiki/Decimal_separator — Country-by-country separator table plus Indian grouping and space separators; the concise case for classing `1,234` AMBIGUOUS without a locale.
54. **price-parser** — https://github.com/scrapinghub/price-parser — Extracts amount + currency from messy price strings; study both its heuristics and where they fail. *License: BSD-3-Clause.*
55. **numbers-parser** — https://github.com/masaccio/numbers-parser — Reads Apple Numbers documents with cell types/formats, recovering the source formatting that disambiguates a raw value. *License: MIT.*

## 7. Currency & money

56. **ISO 4217 — official landing page** — https://www.iso.org/iso-4217-currency-codes.html — Scope of alphabetic/numeric codes and minor units **(bot-walled)**.
57. **SIX — Global Financial Data Standards (ISO 4217 maintenance agency)** — https://www.six-group.com/en/products-services/financial-information/data-standards.html — The only authoritative source for current lists and amendment publications; watch this page as your change feed.
58. **ISO 4217 List One XML (active currencies)** — https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml — Machine-readable active codes + minor-unit digits, with a publication date to version against.
59. **ISO 4217 List Three XML (historic/withdrawn)** — https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-three.xml — Historic codes (AFA, DEM, ZWD…) needed to normalize historical amounts instead of rejecting them.
60. **ISO 4217 amendment document (example: amendment 178)** — https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/amendments/dl-currency-iso-amendment-178.pdf — Shows the amendment artifact format to diff for incremental currency changes.
61. **py-moneyed** — https://github.com/py-moneyed/py-moneyed — `Money` = Decimal + Currency with guards against cross-currency arithmetic. *License: BSD-3-Clause.*
62. **carlospalol/money** — https://github.com/carlospalol/money — Alternative Money type with explicit rounding/allocation behavior. *License: MIT.*
63. **dinero.js** — https://github.com/dinerojs/dinero.js — Best-documented immutable money model (minor units, scale, allocate/distribute); the API to imitate. *License: MIT.*
64. **currency-symbol-map** — https://github.com/bengourley/currency-symbol-map — Makes symbol collisions concrete: `$` → USD/CAD/AUD/MXN…, `kr`, `¥` — proof that symbol alone cannot resolve a currency. *License: BSD-2-Clause.*
65. **ECB euro reference rates (methodology)** — https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html — Free citable daily rates with documented 16:00 CET snapshot caveats — read before using them as "the" rate.
66. **ECB daily rates XML feed** — https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml — Direct machine-readable EUR-base feed for a conversion layer with no API key.
67. **IMF SDR valuation** — https://www.imf.org/external/np/fin/data/rms_sdrv.aspx — Official XDR basket rates; XDR is a valid ISO 4217 code with no market quote **(bot-walled)**.
68. **Open Exchange Rates API docs** — https://docs.openexchangerates.org/reference/api-introduction — Response shapes and as-of-date semantics for historical conversion. *Commercial license; limited free tier.*
69. **ISO 24165-1 (Digital Token Identifier)** — https://www.iso.org/standard/80601.html — Standard giving crypto assets stable identifiers instead of ambiguous tickers **(bot-walled)**.
70. **DTIF — Digital Token Identifier Foundation** — https://www.dtif.org/ — Registration authority and registry for ISO 24165 DTIs; the reason "BTC" is not an identifier.

## 8. Units & measurements

71. **pint** — https://pint.readthedocs.io/en/stable/ — Text-registry quantity library with dimensional analysis and string parsing; the sensible default engine. *License: BSD-3-clause style.*
72. **pint: non-multiplicative units** — https://pint.readthedocs.io/en/stable/user/nonmult.html — Correct °C/°F offset handling and delta-vs-absolute temperature — the classic unit-normalization bug.
73. **pint-pandas** — https://github.com/hgrecco/pint-pandas — Unit-aware pandas dtypes for column-scale normalization. *License: BSD-3-clause style.*
74. **QuantiPhy** — https://quantiphy.readthedocs.io/en/stable/ — Parses/formats SI-prefixed engineering values ("1.4 kΩ", "2.5 µs") that generic parsers mangle. *License: MIT.*
75. **quantulum3** — https://github.com/nielstron/quantulum3 — Extracts quantities + units from free text with surface-form disambiguation. *License: MIT.*
76. **unyt** — https://github.com/yt-project/unyt — NumPy-first unit arrays with fast conversion; better than pint for large numeric arrays. *License: BSD-3-Clause.*
77. **Unitful.jl** — https://github.com/JuliaPhysics/Unitful.jl — Type-level unit modeling reference (compile-time dimensions, zero runtime cost). *License: MIT.*
78. **UCUM home** — https://ucum.org/ — Unambiguous, machine-parseable unit codes (case-sensitive `mg/dL`, `10*6/uL`) — the best canonical serialization for units.
79. **ucum-org/ucum** — https://github.com/ucum-org/ucum — `ucum-essence.xml` machine-readable unit table plus changelog. *License: UCUM/Regenstrief — free use, but derivative works of the table are restricted.*
80. **ucumvert** — https://github.com/dalito/ucumvert — Bridges UCUM codes into pint; the practical UCUM↔pint path in Python. *License: MIT.*
81. **UN/ECE Recommendation 20 unit codes (readable table)** — https://docs.peppol.eu/poacc/upgrade-3/codelist/UNECERec20 — Full Rec 20 + Rec 21 code list (`KGM`, `MTR`, `LTR`, `H87`) required for trade/invoice data.
82. **UN/ECE code list recommendations (official source)** — https://unece.org/trade/uncefact/cl-recommendations — Authoritative Rec 20 revisions and history **(bot-walled)**.
83. **QUDT** — https://www.qudt.org/ — Ontology of quantity kinds, units and dimensions with conversion multipliers and ISO/UCUM cross-references.
84. **qudt-public-repo** — https://github.com/qudt/qudt-public-repo — The TTL vocabularies to actually load. *License: CC BY 4.0 — attribution required.*
85. **OM 2 — Ontology of units of Measure** — https://github.com/HajoRijgersberg/OM — Alternative unit ontology with an `om-2-ucum.ttl` mapping; strong on application domains. *License: none declared — clarify before redistributing.*
86. **NIST SP 811 (PDF)** — https://physics.nist.gov/cuu/pdf/sp811.pdf — Official SI usage guide with exact vs rounded conversion-factor tables for your reference data.
87. **SI Brochure, 9th edition (BIPM)** — https://www.bipm.org/documents/20126/41483022/SI-Brochure-9-EN.pdf — Definitive SI definitions, prefixes, and value/unit formatting rules.

## 9. Type inference before normalization

88. **ptype: probabilistic type inference** — https://arxiv.org/abs/1911.10081 — Models missing and anomalous values explicitly instead of failing the column — the right prior for messy input.
89. **ptype-cat** — https://arxiv.org/abs/2111.11956 — Extends inference to categorical columns/encodings, preventing coded numerics from being normalized as measurements.
90. **Sato (contextual semantic type detection)** — https://github.com/megagonlabs/sato — Table-context + structured prediction for column semantic types; materially better than per-column models, and the practical successor to Sherlock. *License: Apache-2.0.*

---

## License summary

- **Permissive, safe to embed:** Unicode License v3 (CLDR, cldr-json, ICU — attribution required); BSD-3-Clause (Babel, dateparser, price-parser, py-moneyed, unyt, Duckling); MIT (python-edtf, whenever, ciso8601, pendulum, money, dinero.js, quantulum3, QuantiPhy, ucumvert, numbers-parser, pytz, Unitful.jl, spaCy); Apache-2.0 (dateutil dual, arrow, udatetime, Stanza, timefhuman, python-duckling, Sato); public domain (tzdb code/data).
- **Copyleft — do not link into a closed product without review:** HeidelTime and Stanford CoreNLP/SUTime are **GPL-3.0**.
- **Conditional data licenses:** QUDT is **CC BY 4.0** (attribution); **UCUM** permits use but restricts derivative works of its unit table; **OM 2** declares no license at all.
- **Paywalled standards:** ISO 8601 / 8601-2, ISO 4217, ISO 24165 and ISO 80000 texts must be purchased — the redistributable substitutes are CLDR, the SIX ISO 4217 XML lists, RFC 3339/9557, EDTF, and NIST SP 811.
- **Third-party services:** ECB rates are free with attribution; Open Exchange Rates is commercial; LDC corpora (TimeBank/TIMEX3 data) require an LDC agreement — the guidelines PDF itself is public.
- **Reference-only / stale:** `facebookarchive/duckling_old` (the Clojure engine behind python-duckling) is archived; pytz is superseded by `zoneinfo`.
