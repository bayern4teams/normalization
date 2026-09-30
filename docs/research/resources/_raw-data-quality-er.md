# Data Cleaning / Data Quality / Entity Resolution — Verified Resource Map
**Purpose:** ecosystem + state of the art + benchmarks for a Python *value-normalization engine* that standardizes column values across a whole DB before Splink-based entity resolution.

**Legend:** 🟢 = directly reusable as a library/dependency · 🟡 = reusable with adaptation (vendor/standard/spec/dataset) · 🔵 = idea/design source only (paper, product, survey) · 📊 = benchmark data.

> All 170+ URLs below were HTTP-checked. A handful (`dl.acm.org`, `iso.org`, `sourceforge.net`, `ibm.com/docs`) return 403 to scripted clients — they are bot-walls, not dead links; they open fine in a browser. Where possible an open-access mirror is given instead.

---

## 1. Validation / expectation / profiling frameworks (declarative data-quality gates)

These matter for the normalization engine as the **assertion layer around it**: pre-checks (what is dirty), post-checks (did normalization preserve cardinality/nullability/domain).

| # | Name | URL | What it gives us |
|---|---|---|---|
| 1 | 🟢 Great Expectations | https://github.com/great-expectations/great_expectations | Declarative "Expectations" over pandas/Spark/SQL; the canonical vocabulary of column-level assertions to wrap normalization steps. |
| 2 | 🔵 GX Expectation Gallery | https://docs.greatexpectations.io/docs/reference/glossary_of_expectations | Enumerated catalogue of ~300 checks — a ready-made checklist of *what "normalized" can mean per column*. |
| 3 | 🟢 Soda Core | https://github.com/sodadata/soda-core | YAML/SodaCL checks pushed down to the warehouse; good for whole-DB scans without pulling data into Python. |
| 4 | 🟡 Soda contract language ref | https://docs.soda.io/reference/contract-language-reference | Data-contract grammar — model for expressing "this column must be in canonical form X". |
| 5 | 🟢 Pandera | https://github.com/unionai-oss/pandera | Schema + statistical validation for pandas/polars/pyspark with **coercion hooks** — closest OSS thing to a typed normalization contract. |
| 6 | 🟢 Pandera docs | https://pandera.readthedocs.io/ | `Check`/`Coerce`/`DataFrameModel` API details; parsers can host normalizers directly. |
| 7 | 🟢 Deequ (Scala/Spark) | https://github.com/awslabs/deequ | Constraint suggestion + **automatic constraint inference** and metric repositories at Spark scale. |
| 8 | 🟢 PyDeequ | https://github.com/awslabs/python-deequ | Python API over Deequ — usable directly if the DB is Spark-accessible. |
| 9 | 🔵 Deequ paper (VLDB 2018) | https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf | "Automating Large-Scale Data Quality Verification" — the incremental-metrics/anomaly-detection design we can copy for drift on normalized columns. |
| 10 | 🟢 dbt-core | https://github.com/dbt-labs/dbt-core | If normalization is materialized in SQL, dbt gives lineage + test scaffolding. |
| 11 | 🟢 dbt-expectations | https://github.com/calogica/dbt-expectations | GX-style tests as dbt tests — lets normalization invariants live next to the models. |
| 12 | 🟢 dbt-utils | https://github.com/dbt-labs/dbt-utils | `accepted_values`, `unique_combination_of_columns`, surrogate keys — cheap standardization guards. |
| 13 | 🟡 dbt package hub | https://hub.getdbt.com/ | Index to find further quality/cleaning packages. |
| 14 | 🟢 frictionless-py | https://github.com/frictionlessdata/frictionless-py | Describe/validate/**transform** tabular data; its `steps` pipeline is a working model for a declarative normalization DSL. |
| 15 | 🟡 Table Schema spec | https://datapackage.org/standard/table-schema/ | Portable column-type + constraint + `missingValues` spec — good target format for our per-column normalization config. |
| 16 | 🟡 Frictionless framework docs | https://framework.frictionlessdata.io/ | Pipeline/step reference. |
| 17 | 🟢 datapackage-py | https://github.com/frictionlessdata/datapackage-py | Reference implementation for reading/writing Table Schema descriptors. |
| 18 | 🟢 datatest | https://github.com/shawnbrown/datatest | pytest-style data validation with *difference objects* — useful to diff pre/post normalization. |
| 19 | 🟡 datatest docs | https://datatest.readthedocs.io | API for acceptance/allowance of known deviations. |
| 20 | 🟢 pointblank (R) | https://github.com/rstudio/pointblank | Agent-based validation + auto-generated data-quality reports; the reporting model is worth stealing. |
| 21 | 🟢 pointblank (Python) | https://github.com/posit-dev/pointblank | Python port — directly usable for validation reports on normalized tables. |
| 22 | 🟢 ydata-profiling | https://github.com/ydataai/ydata-profiling | One-call column profiling (types, cardinality, top values, missingness) — the **discovery phase** input for choosing normalizers. |
| 23 | 🟡 ydata-profiling docs | https://docs.profiling.ydata.ai/latest | Config for large tables / minimal mode. |
| 24 | 🟢 sweetviz | https://github.com/fbdesignpro/sweetviz | Fast comparative EDA — compare a column before vs. after normalization visually. |
| 25 | 🟢 DataProfiler (Capital One) | https://github.com/capitalone/DataProfiler | Schema + statistics + **entity/PII labeling** with a pretrained model; closest OSS "what semantic type is this column" utility. |
| 26 | 🟢 Nike spark-expectations | https://github.com/Nike-Inc/spark-expectations | Row-level quarantine of failing records in Spark pipelines — pattern for "unnormalizable" rows. |
| 27 | 🟢 whylogs | https://github.com/whylabs/whylogs | Lightweight statistical profiles/sketches; cheap continuous monitoring of normalized column distributions. |
| 28 | 🟢 Evidently | https://github.com/evidentlyai/evidently | Drift/data-quality reports and test suites — detect when normalization rules stop matching reality. |
| 29 | 🟢 Elementary | https://github.com/elementary-data/elementary | dbt-native anomaly detection + data observability UI. |
| 30 | 🔵 Apache Griffin | https://griffin.apache.org | JVM/Spark data-quality service (accuracy, completeness, timeliness dimensions) — dimension taxonomy reference. |

## 2. Cleaning / wrangling / transformation libraries (the normalization toolbox itself)

| # | Name | URL | What it gives us |
|---|---|---|---|
| 31 | 🟢 OpenRefine | https://github.com/OpenRefine/OpenRefine | The reference implementation of value normalization: clustering, mass-edit, GREL transforms, reconciliation. |
| 32 | 🔵 OpenRefine clustering in depth | https://openrefine.org/docs/technical-reference/clustering-in-depth | **Most directly relevant single document**: key-collision (fingerprint, n-gram fingerprint, metaphone3, cologne) + nearest-neighbour (levenshtein, PPM) algorithms — port these as canonical-form generators. |
| 33 | 🔵 OpenRefine GREL functions | https://openrefine.org/docs/manual/grelfunctions | Complete catalogue of string/date/number transforms practitioners actually need — a feature checklist for our DSL. |
| 34 | 🟡 OpenRefine Reconciliation API | https://openrefine.org/docs/technical-reference/reconciliation-api | Standard protocol for mapping dirty values to a controlled vocabulary/authority — a normalization backend interface we can implement. |
| 35 | 🟡 OpenRefine ↔ Wikibase reconciling | https://openrefine.org/docs/manual/wikibase/reconciling | Worked example of reconciling free text to canonical entity IDs. |
| 36 | 🟢 refinr (R) | https://github.com/ChrisMuir/refinr | Standalone port of OpenRefine's key-collision + n-gram merge algorithms — compact reference implementation. |
| 37 | 🟢 refinr on CRAN | https://cran.r-project.org/package=refinr | Documented algorithm behaviour/params. |
| 38 | 🟢 openclean-core | https://github.com/VIDA-NYU/openclean-core | NYU's Python data-cleaning framework: profiling + **repair/standardization operators** + provenance. The closest existing project to what we're building. |
| 39 | 🟡 openclean docs | https://openclean.readthedocs.io/ | Operator model (`eval` functions, mappers, cluster-based standardization). |
| 40 | 🟢 PyJanitor | https://github.com/pyjanitor-devs/pyjanitor | Chainable cleaning verbs (clean_names, coalesce, currency conversion, fuzzy joins) — a lot of "boring" normalization for free. |
| 41 | 🟢 DataPrep (SFU) | https://github.com/sfu-db/dataprep | `dataprep.clean` has **40+ ready column normalizers** (country, phone, email, IP, lat/long, IBAN, dates, address) — highest-value direct dependency in this list. |
| 42 | 🟢 AutoClean | https://github.com/elisemercury/AutoClean | Opinionated automated preprocessing pipeline (imputation, outliers, encoding) — good default-policy reference. |
| 43 | 🟢 Cleanlab | https://github.com/cleanlab/cleanlab | Confident-learning label/data error detection; useful to flag improbable values post-normalization. |
| 44 | 🟢 Cleanlab Datalab | https://docs.cleanlab.ai/stable/cleanlab/datalab/datalab.html | One-call issue scan (outliers, near-duplicates, nulls) over a dataset. |
| 45 | 🟢 csvkit | https://github.com/wireservice/csvkit | CLI type inference/`csvclean`/`csvstat` — quick triage on raw extracts. |
| 46 | 🟢 VisiData | https://github.com/saulpw/visidata | Terminal explorer with frequency tables — fastest way for a human to eyeball a column's value distribution. |
| 47 | 🔵 Dora | https://github.com/NathanEpstein/Dora | Small EDA/cleaning helper (mostly historical; ideas only, low maintenance). |

## 3. Domain-specific value normalizers (drop-in building blocks)

This is where most real normalization power comes from — **prefer these over hand-rolled regex.**

| # | Name | URL | What it gives us |
|---|---|---|---|
| 48 | 🟢 libpostal | https://github.com/openvenues/libpostal | Statistical international address parsing + **expansion/normalization** (abbreviations, transliteration) trained on OSM — gold standard for address columns. |
| 49 | 🟢 pypostal | https://github.com/openvenues/pypostal | Python bindings to libpostal. |
| 50 | 🟢 lieu | https://github.com/openvenues/lieu | libpostal-based address/venue dedupe — reference for address-aware blocking keys. |
| 51 | 🟢 usaddress | https://github.com/datamade/usaddress | CRF-based US address tagging into components. |
| 52 | 🟢 probablepeople | https://github.com/datamade/probablepeople | CRF parser for person/company name strings (splits given/surname/corp suffix). |
| 53 | 🟢 python-nameparser | https://github.com/derek73/python-nameparser | Rule-based human-name parsing (titles, suffixes, nicknames) — cheap and deterministic. |
| 54 | 🟢 python-phonenumbers | https://github.com/daviddrysdale/python-phonenumbers | Port of Google libphonenumber: parse + **E.164 canonical output** + region validation. Definitive phone normalizer. |
| 55 | 🟢 python-stdnum | https://github.com/arthurdejong/python-stdnum | Validation/compact/format for 250+ national & international numbers (VAT, ISBN, IBAN, tax IDs, LEI) — instant ID-column normalization. |
| 56 | 🟢 schwifty | https://github.com/mdomke/schwifty | IBAN/BIC parsing, validation and canonical formatting. |
| 57 | 🟢 python-email-validator | https://github.com/JoshData/python-email-validator | Syntax + deliverability check and **normalized** email form (IDNA, case). |
| 58 | 🟢 pycountry | https://github.com/pycountry/pycountry | ISO 3166 / 3166-2 / 4217 / 639 / 15924 lookup tables — country, currency, language canonicalization. |
| 59 | 🟢 Babel | https://github.com/python-babel/babel | CLDR-backed locale-aware parsing/formatting of numbers, currencies, dates. |
| 60 | 🟢 python-dateutil | https://github.com/dateutil/dateutil | Flexible date parsing + tz handling; baseline for date column normalization. |
| 61 | 🟢 dateparser | https://github.com/scrapinghub/dateparser | Human/multilingual date strings ("2 days ago", non-English months) → datetime. |
| 62 | 🟢 Pint | https://github.com/hgrecco/pint | Physical units parsing + conversion — normalize measurement columns to a canonical unit. |
| 63 | 🟢 price-parser | https://github.com/scrapinghub/price-parser | Extract amount + currency from messy price strings. |
| 64 | 🟢 ftfy | https://github.com/rspeer/python-ftfy | Fixes mojibake/double-encoding — **run before anything else** in the pipeline. |
| 65 | 🟢 Unidecode | https://github.com/avian2/unidecode | ASCII transliteration of Unicode; basis of fingerprint keys. |
| 66 | 🟢 RapidFuzz | https://github.com/rapidfuzz/RapidFuzz | Fast Levenshtein/Jaro-Winkler/token-set ratios — clustering of near-identical values at scale. |
| 67 | 🟢 jellyfish | https://github.com/jamesturk/jellyfish | Phonetic encoders (Soundex, Metaphone, NYSIIS, Match Rating) + string distances — canonical-key generators. |
| 68 | 🟢 string_grouper | https://github.com/Bergvca/string_grouper | TF-IDF n-gram + sparse cosine matching; groups millions of strings fast — practical value-clustering engine. |
| 69 | 🟢 scrubadub | https://github.com/LeapBeyond/scrubadub | PII removal/replacement from free text. |
| 70 | 🟡 scrubadub docs | https://scrubadub.readthedocs.io/en/stable/index.html | Detector/post-processor architecture. |
| 71 | 🟢 Microsoft Presidio | https://github.com/microsoft/presidio | Production PII detection + **anonymization/pseudonymization** with pluggable recognizers; also usable as a semantic-type detector for columns. |
| 72 | 🟡 Presidio docs | https://microsoft.github.io/presidio/ | Recognizer registry + custom entity design. |

## 4. Reference data / standards (canonical target vocabularies)

| # | Name | URL | What it gives us |
|---|---|---|---|
| 73 | 🟡 Unicode UAX #15 (Normalization Forms) | https://unicode.org/reports/tr15/ | NFC/NFD/NFKC/NFKD — the formal basis for string canonicalization; decide and document one form. |
| 74 | 🟡 Unicode CLDR | https://cldr.unicode.org/ | Locale data: collation, number/date patterns, country/currency display names, transliterations. |
| 75 | 🟡 USPS Publication 28 | https://pe.usps.com/text/pub28/welcome.htm | Official US postal addressing standard incl. street-suffix/state/secondary-unit abbreviation tables — direct source for an address abbreviation map. |
| 76 | 🟡 UN M49 area codes | https://unstats.un.org/unsd/methodology/m49/ | Country/region code authority (ISO 3166 alignment) without the iso.org paywall. |
| 77 | 🟡 ISO 3166 country codes | https://www.iso.org/iso-3166-country-codes.html | Authoritative country code standard (site 403s to scripts; loads in browser). |
| 78 | 🟡 GeoNames dumps | https://www.geonames.org/export/ | Free gazetteer (place names, alternate names, admin hierarchy) — build a place-name canonicalization dictionary. |
| 79 | 🟡 OpenAddresses | https://github.com/openaddresses/openaddresses | Global open address point data — validation/ground truth for address normalization. |
| 80 | 🟢 FollowTheMoney | https://github.com/alephdata/followthemoney | Ontology + **property-level type system with normalizers** (names, addresses, identifiers, countries, phones) used in real investigative pipelines. Excellent architectural template for "typed, normalizable properties". |
| 81 | 🟢 nomenklatura | https://github.com/opensanctions/nomenklatura | FtM-based entity dedupe/matching with canonicalization, cross-referencing and a resolver store. |
| 82 | 🔵 nomenklatura docs | https://nomenklatura.followthemoney.tech/ | Matching algorithm + resolver design. |
| 83 | 🔵 Aleph | https://github.com/alephdata/aleph | Full ingest/search/cross-reference platform built on FtM — end-to-end reference architecture. |
| 84 | 📊 OpenSanctions | https://github.com/opensanctions/opensanctions | Real, continuously updated dirty multi-source entity data (names in many scripts) — excellent stress test. |

## 5. Entity resolution / record linkage frameworks

| # | Name | URL | What it gives us |
|---|---|---|---|
| 85 | 🟢 Splink | https://github.com/moj-analytical-services/splink | Our target ER engine: Fellegi-Sunter EM over DuckDB/Spark/Athena. Its comparison-level library defines exactly what normalization must feed it. |
| 86 | 🟡 Splink docs | https://moj-analytical-services.github.io/splink/getting_started.html | Comparison templates (name, DOB, postcode) — read these to align our canonical forms with its comparators. |
| 87 | 🔵 Splink (MoJ writeup) | https://www.gov.uk/government/publications/joined-up-data-in-government-the-future-of-data-linking-methods/splink-mojs-open-source-library-for-probabilistic-record-linkage-at-scale | Government-scale deployment context and method rationale. |
| 88 | 🟢 Python Record Linkage Toolkit | https://github.com/J535D165/recordlinkage | Indexing + comparison + classification API; its `preprocessing.clean()`/`phonetic()` helpers are a mini normalization library. |
| 89 | 🟡 recordlinkage docs | https://recordlinkage.readthedocs.io/ | Includes standardisation utilities and FEBRL sample datasets. |
| 90 | 🟢 dedupe | https://github.com/dedupeio/dedupe | Active-learning dedupe with **typed variables** (Name, Address, Price, LatLong) — each type encodes a normalization+comparison assumption worth mirroring. |
| 91 | 🟡 dedupe docs | https://docs.dedupe.io/en/latest/ | Variable-type catalogue and blocking/predicate learning. |
| 92 | 🟢 pandas-dedupe | https://github.com/Lyonk71/pandas-dedupe | Thin pandas wrapper; quick baselines. |
| 93 | 🔵 Dedupe.io (SaaS) | https://dedupe.io | Commercial face of dedupe — UI/workflow ideas for human review of clusters. |
| 94 | 🟢 Zingg | https://github.com/zinggAI/zingg | Spark-scale ML identity resolution with active learning; supports fuzzy match on standardized fields. |
| 95 | 🟡 Zingg docs | https://docs.zingg.ai | Field-type configuration (`FUZZY`, `EXACT`, `EMAIL`, `TEXT`) — a compact normalization-type taxonomy. |
| 96 | 🟡 Zingg site | https://zingg.ai/ | Positioning/capabilities overview. |
| 97 | 🟢 JedAI Toolkit (Java) | https://github.com/scify/JedAIToolkit | Full end-to-end ER workbench: schema-agnostic blocking, block cleaning, meta-blocking, matching, clustering. |
| 98 | 🟢 pyJedAI | https://github.com/AI-team-UoA/pyJedAI | Python rewrite — usable to benchmark blocking strategies against Splink's. |
| 99 | 🟢 py_entitymatching (Magellan) | https://github.com/anhaidgroup/py_entitymatching | The academic reference EM pipeline (sampling, labeling, feature generation, debugging matchers). |
| 100 | 🟢 DeepMatcher | https://github.com/anhaidgroup/deepmatcher | Neural EM baselines (SIF/RNN/Attention/Hybrid); still the standard comparison point. |
| 101 | 🟢 Sparkly | https://github.com/anhaidgroup/sparkly | Spark + Lucene TF-IDF **top-k blocking** — scalable candidate generation. |
| 102 | 🟢 Delex | https://github.com/anhaidgroup/delex | Recent anhaidgroup Spark EM/blocking package. |
| 103 | 🟢 DeepBlocker | https://github.com/saravanan-thirumuruganathan/DeepBlocker | Self-supervised deep blocking — design-space exploration of learned blockers. |
| 104 | 🟢 Ditto | https://github.com/megagonlabs/ditto | Transformer EM (serialize pairs → BERT). **Its data-augmentation/serialization preprocessing is effectively normalization-by-injection.** |
| 105 | 🔵 Ditto paper | https://arxiv.org/abs/2004.00584 | Documents the "domain knowledge injection" tricks (span typing, number normalization) directly relevant to us. |
| 106 | 🟢 HierGAT | https://github.com/CGCL-codes/HierGAT | Hierarchical graph attention ER — attribute/token-level attention across records. |
| 107 | 🔵 HierGAT paper (SIGMOD'22) | https://dl.acm.org/doi/10.1145/3514221.3517872 | Method detail (ACM 403s to scripts; opens in browser). |
| 108 | 🟢 Rotom | https://github.com/megagonlabs/rotom | Meta-learned data augmentation for EM/classification — generate normalization-perturbation training data. |
| 109 | 🟢 Sudowoodo | https://github.com/megagonlabs/sudowoodo | Contrastive self-supervised framework covering EM, **data cleaning and column matching** in one model. |

## 6. Research: foundations, surveys, systems

| # | Name | URL | What it gives us |
|---|---|---|---|
| 110 | 🔵 Ilyas & Chu, *Data Cleaning* (book) | https://dl.acm.org/doi/10.1145/3310205 | The canonical textbook: outlier/dedup/rule-based/ML-based cleaning taxonomy. Start here for engine architecture vocabulary. |
| 111 | 🔵 *Trends in Cleaning Relational Data* | https://nowpublishers.com/article/Details/DBS-045 | Survey of consistency + deduplication techniques (FDs, CFDs, DCs, repair algorithms). |
| 112 | 🔵 Chu Data Lab — Data Cleaning for ML | https://chu-data-lab.cc.gatech.edu/data-cleaning-for-ml | Curated research portal with code links for the above line of work. |
| 113 | 🔵 HoloClean (VLDB'17) | https://www.vldb.org/pvldb/vol10/p1190-rekatsinas.pdf | Unified probabilistic repair combining integrity constraints, external dicts and statistics — the strongest "principled repair" framing. |
| 114 | 🔵 HoloClean (arXiv) | https://arxiv.org/abs/1702.00820 | Same, open access. |
| 115 | 🟢 HoloClean code | https://github.com/HoloClean/holoclean | Runnable implementation (dated deps, but the factor-graph design is reusable). |
| 116 | 🟢 Raha / Baran code | https://github.com/BigDaMa/raha | Configuration-free **error detection (Raha)** + **error correction (Baran)** with the six standard dirty datasets bundled. |
| 117 | 📊 Raha datasets folder | https://github.com/BigDaMa/raha/tree/master/datasets | Hospital, Flights, Beers, Rayyan, Movies, Tax with clean/dirty pairs — our regression corpus. |
| 118 | 🔵 Raha paper (SIGMOD'19, PDF) | https://m-mahdavi.github.io/assets/pdfs/mahdavi2019raha.pdf | Ensemble-of-detectors + clustering + minimal labeling; the "no-config" idea we want for rule proposal. |
| 119 | 🔵 Baran paper (VLDB'20, PDF) | http://www.vldb.org/pvldb/vol13/p1948-mahdavi.pdf | Unified context representation (value/vicinity/domain) for correction + transfer learning. **Most directly on-point paper for value normalization.** |
| 120 | 🟢 FasterRaha | https://github.com/LUH-DBS/FasterRaha | Performance-oriented reimplementation. |
| 121 | 🟢 Example-Driven Error Detection | https://github.com/BigDaMa/ExampleDrivenErrorDetection | Active-learning error detection from few examples. |
| 122 | 🔵 NADEEF (SIGMOD'13) | https://dl.acm.org/doi/abs/10.1145/2463676.2465327 | Generic, extensible cleaning system: user-defined rules as (detect, repair) pairs — a clean plugin API to imitate. |
| 123 | 🔵 Data Civilizer (MIT) | https://dsail.csail.mit.edu/index.php/data-civilizer | End-to-end data prep over enterprise data lakes: discovery → linkage → cleaning. |
| 124 | 🔵 Data Civilizer 2.0 (VLDB'19) | http://www.vldb.org/pvldb/vol12/p1954-rezig.pdf | Holistic prep+analytics loop with iterative cleaning feedback. |
| 125 | 🔵 Data Civilizer CIDR'17 slides | https://www.cidrdb.org/cidr2017/slides/p44-deng-cidr17-slides.pdf | Concise system-architecture overview. |
| 126 | 🔵 Conditional Functional Dependencies (ICDE'07) | https://homepages.inf.ed.ac.uk/wenfei/papers/icde07.pdf | Fan et al. — CFDs formalize "in country=US, state must be a 2-letter code"; exactly the shape of normalization rules. |
| 127 | 🔵 Denial Constraints / holistic cleaning (VLDB'13-14) | https://cs.uwaterloo.ca/~ilyas/papers/ChuVLDB2014.pdf | DC discovery (FASTDC) — auto-mine cross-column consistency rules from data. |
| 128 | 🔵 Wang & Strong, *Beyond Accuracy* (1996) | https://web.mit.edu/tdqm/www/tdqmpub/beyondaccuracy_files/beyondaccuracy.html | The 15-dimension data-quality framework (intrinsic/contextual/representational/accessibility) — how to *report* normalization impact. |
| 129 | 🔵 Wang & Strong (JMIS record) | https://www.jmis-web.org/articles/1002 | Citable publication record. |
| 130 | 🔵 Pipino, Lee & Wang, *Data Quality Assessment* (CACM'02) | https://web.mit.edu/tdqm/www/tdqmpub/PipinoLeeWangCACMApr02.pdf | Concrete formulas for quantifying DQ dimensions — turn "cleanliness" into metrics. |
| 131 | 🔵 Potter's Wheel (VLDB'01) | https://www.vldb.org/conf/2001/P381.pdf | Interactive cleaning with **discrepancy detection via structure/domain inference** and a transform algebra — the intellectual ancestor of our engine. |
| 132 | 🔵 Wrangler (CHI'11) | http://vis.stanford.edu/papers/wrangler | Predictive transform suggestion from user gestures; formal transformation language. |
| 133 | 🔵 Wrangler PDF | https://dsf.berkeley.edu/papers/chi11-wrangler.pdf | Full paper text (Berkeley mirror). |
| 134 | 🔵 Stanford HCI Wrangler record | https://hci.stanford.edu/publications/paper.php?id=164 | Publication metadata/related work. |
| 135 | 🔵 Foofah (SIGMOD'17) | https://github.com/umich-dbgroup/foofah | Program synthesis of layout/table transformations from input-output examples. |
| 136 | 🔵 Transform-Data-by-Example (MSR) | https://www.microsoft.com/en-us/research/project/transform-data-by-example | Search engine over harvested code/functions to synthesize a transform from a few examples — the most ambitious "auto-normalize" system. |
| 137 | 🔵 TDE paper page | https://www.microsoft.com/en-us/research/publication/transform-data-by-example-an-extensible-search-engine-for-data-transformations/ | Method + evaluation. |
| 138 | 🟡 Microsoft PROSE SDK | https://github.com/microsoft/prose | Production programming-by-example framework (FlashFill lineage) — could synthesize per-column transforms from labeled examples. |
| 139 | 🔵 PROSE project page | https://www.microsoft.com/en-us/research/project/prose-framework | DSL authoring model, ranking, and witness functions. |
| 140 | 🔵 Auto-Type (SIGMOD'18) | https://www.microsoft.com/en-us/research/publication/synthesizing-type-detection-logic-rich-semantic-data-types-using-open-source-code/ | Synthesizes **type-detection logic for rich semantic types** by mining open-source validators — a way to bootstrap our semantic-type registry. |
| 141 | 🔵 Auto-Type PDF | https://www.microsoft.com/en-us/research/wp-content/uploads/2018/04/Auto-Type.pdf | Full algorithm. |
| 142 | 🟢 AutoType code | https://github.com/congy/AutoType | Reference implementation. |
| 143 | 🔵 SmartDataLake (EU project) | https://smartdatalake.eu/ | Extreme-scale data-lake analytics incl. entity resolution/similarity search components. |
| 144 | 🟢 Smart Data Lake Builder | https://github.com/smart-data-lake/smart-data-lake | Config-driven declarative data pipeline framework (separate project, same name family) — DSL design reference. |

## 7. Semantic column type detection (choose the right normalizer automatically)

This is the piece that turns a per-column manual config into an automatic engine.

| # | Name | URL | What it gives us |
|---|---|---|---|
| 145 | 🟢 Sherlock | https://github.com/mitmedialab/sherlock-project | DL model predicting 78 semantic types from column values + trained weights and features. |
| 146 | 🔵 Sherlock paper | https://arxiv.org/abs/1905.10688 | Feature design (character distributions, word embeddings, paragraph vectors) — reusable even without the model. |
| 147 | 🔵 Sherlock @ KDD'19 | https://www.kdd.org/kdd2019/accepted-papers/view/sherlock-a-deep-learning-approach-to-semantic-data-type-detection | Official paper record. |
| 148 | 🟢 Sato | https://github.com/megagonlabs/sato | Adds **table context + CRF over columns** to Sherlock — better on ambiguous columns. |
| 149 | 🔵 Sato paper (VLDB'20) | https://www.vldb.org/pvldb/vol13/p1835-zhang.pdf | Topic-model table context + structured prediction. |
| 150 | 🟢 ptype | https://github.com/alan-turing-institute/ptype | Probabilistic type inference robust to **missing values and anomalies** — tells us which cells are non-conforming per column, not just the type. Very directly reusable. |
| 151 | 🟢 Doduo | https://github.com/megagonlabs/doduo | Column annotation with pretrained LMs (types + inter-column relations). |
| 152 | 🔵 Doduo paper | https://arxiv.org/abs/2104.01785 | Multi-task table-serialization approach. |
| 153 | 📊 SemTab challenge | https://sem-tab-challenge.github.io/2024/ | Annual tabular-data→KG matching benchmark (CTA/CEA/CPA tasks) with public gold standards for column typing. |

## 8. LLM / foundation-model era (newest state of the art)

| # | Name | URL | What it gives us |
|---|---|---|---|
| 154 | 🔵 Can Foundation Models Wrangle Your Data? (VLDB'23) | https://arxiv.org/abs/2205.09911 | Shows few-shot LLMs match/beat SOTA on **data imputation, error detection and entity matching** — baseline to beat/justify rule-based engine. |
| 155 | 🔵 Jellyfish: LLM for data preprocessing | https://arxiv.org/abs/2312.01678 | Instruction-tuned open models specialized for EM/imputation/error detection; local-model option. |
| 156 | 🔵 Table-GPT (Microsoft) | https://arxiv.org/abs/2310.09263 | Table-tuning for table tasks incl. transformations — relevant if we add an LLM fallback path. |
| 157 | 🔵 CleanAgent | https://arxiv.org/abs/2403.08291 | **LLM agents for data standardization** built on a typed cleaning library — nearly our exact problem statement. |
| 158 | 🔵 Data Cleaning Using LLMs | https://arxiv.org/abs/2410.15547 | Evaluates LLM cleaning on the Raha/Baran benchmark suite — gives comparable numbers. |
| 159 | 🔵 AutoPrep (multi-agent data prep) | https://github.com/ruc-datalab/AutoPrep | Question-aware automated data preparation pipeline with agent decomposition. |
| 160 | 🔵 AutoPrep paper | https://arxiv.org/abs/2412.10422 | Architecture + evaluation. |

## 9. Surveys, books and evaluation methodology for ER

| # | Name | URL | What it gives us |
|---|---|---|---|
| 161 | 🔵 Blocking & Filtering Survey (arXiv) | https://arxiv.org/abs/1905.06167 | Papadakis et al. — exhaustive taxonomy of blocking; informs which normalized keys to emit for Splink. |
| 162 | 🔵 Same survey (ACM CSUR) | https://dl.acm.org/doi/10.1145/3377455 | Published version (ACM 403s scripts). |
| 163 | 🔵 Neural Networks for Entity Matching: A Survey | https://arxiv.org/abs/2010.11075 | Barlaug & Gulla — maps the deep-EM design space. |
| 164 | 🔵 Duplicate Record Detection: A Survey (TKDE'07) | https://www.cs.purdue.edu/homes/ake/pub/survey2.pdf | Elmagarmid et al. — classic; **its data-preparation/standardization section is a direct feature checklist** for our engine. |
| 165 | 🔵 Christen, *Data Matching* (Springer) | https://link.springer.com/book/10.1007/978-3-642-31164-2 | Book with a whole chapter on data pre-processing/standardization for linkage. |
| 166 | 🔵 *The Four Generations of Entity Resolution* | https://link.springer.com/book/10.1007/978-3-031-01878-7 | Papadakis/Ioannou/Thanos/Palpanas — modern synthesis through deep learning. |
| 167 | 🔵 A Critical Re-evaluation of EM Benchmarks | http://arxiv.org/abs/2307.01231 | Shows classic benchmarks are too easy/leaky — **read before trusting any EM benchmark number**. |
| 168 | 🔵 Entity-centric ER evaluation framework | https://arxiv.org/abs/2404.05622 | How to evaluate ER systems properly (cluster-level, sampling-based estimates). |
| 169 | 🔵 Bipartite graph matching for clean-clean ER | https://arxiv.org/abs/2112.14030 | Empirical evaluation of matching/clustering algorithms. |
| 170 | 🔵 Magellan (VLDB'16) | https://www.vldb.org/pvldb/vol9/p1197-pkonda.pdf | "Toward building EM management systems" — argues for tooling around the whole EM workflow, incl. cleaning stages. |

## 10. Benchmark datasets 📊

| # | Name | URL | What it gives us |
|---|---|---|---|
| 171 | 📊 Raha/Baran six datasets | https://github.com/BigDaMa/raha/tree/master/datasets | **Hospital, Flights, Beers, Rayyan, Movies, Tax** — dirty/clean pairs, the de-facto standard cleaning benchmark. Use as our primary regression suite. |
| 172 | 📊 CleanML | https://github.com/chu-data-lab/CleanML | 13 real datasets × 5 error types with a protocol for measuring cleaning's downstream ML impact. |
| 173 | 📊 CleanML paper | https://arxiv.org/abs/1904.09483 | Methodology for "did cleaning actually help?" — adapt to "did normalization improve Splink F1?". |
| 174 | 📊 BART error generator | https://github.com/dbunibas/BART | Controlled, constraint-aware **synthetic error injection** — generate dirty variants of our own DB with known ground truth. Highest-leverage item for internal benchmarking. |
| 175 | 📊 BART project page | https://db.unibas.it/projects/bart/ | Detectability/repairability theory behind the generator. |
| 176 | 📊 BART paper (VLDB'16) | https://www.vldb.org/pvldb/vol9/p36-arocena.pdf | Error-generation semantics. |
| 177 | 📊 Magellan Data Repository | https://sites.google.com/site/anhaidgroup/useful-stuff/the-magellan-data-repository | 800+ EM datasets incl. the standard structured/dirty/textual splits. |
| 178 | 📊 Magellan 839-dataset index | https://sites.google.com/site/anhaidgroup/useful-stuff/the-magellan-data-repository/the-839-data-sets | Per-dataset descriptions and download links. |
| 179 | 📊 Leipzig ER benchmarks | https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution | **Abt-Buy, Amazon-GoogleProducts, DBLP-ACM, DBLP-Scholar** with perfect mappings — the classic four. |
| 180 | 📊 WDC Products | https://webdatacommons.org/largescaleproductcorpus/wdc-products | Multi-dimensional EM benchmark: controlled corner-case amount, unseen entities, training size. |
| 181 | 📊 WDC Products paper | https://arxiv.org/abs/2301.09521 | Benchmark design rationale. |
| 182 | 📊 WDC LSPM corpus v2 | https://webdatacommons.org/largescaleproductcorpus/v2 | 26M product offers + gold standards across 4 categories; extremely dirty real-world attribute values. |
| 183 | 📊 CompERBench | https://madata.bib.uni-mannheim.de/348 | 21 *complete* EM benchmark tasks (full candidate sets, not just pre-blocked pairs). |
| 184 | 📊 CompERBench download | https://data.dws.informatik.uni-mannheim.de/benchmarkmatchingtasks/ | Direct data access. |
| 185 | 📊 EMBench++ | https://db.disi.unitn.eu/pages/EMBench/index.html | Configurable EM benchmark generator with controlled transformations (abbreviations, typos, token swaps) — **directly mirrors normalization failure modes**. |
| 186 | 📊 EMBench++ paper | https://dl.acm.org/doi/10.3233/SW-180331 | Generator semantics (ACM 403s scripts). |
| 187 | 📊 FEBRL | https://sourceforge.net/projects/febrl/ | Classic record-linkage system + **synthetic person datasets with configurable corruption** (name/date/address). Bot-walled to scripts; browser OK. |
| 188 | 📊 FEBRL documentation | https://users.cecs.anu.edu.au/~Peter.Christen/Febrl/febrl-0.2.2/febrldoc-0.2.2.pdf | Data generator + its standardization modules (HMM-based name/address parsing). |
| 189 | 📊 FEBRL paper | https://users.cecs.anu.edu.au/~Peter.Christen/publications/hdkm2008febrl.pdf | System overview incl. standardization pipeline. |
| 190 | 📊 NC voter registration (NCSBE) | https://www.ncsbe.gov/results-data/voter-registration-data | Public NCVR snapshots — the standard large real-world person-linkage dataset (millions of records, temporal snapshots). |
| 191 | 📊 NCSBE bulk data server | https://dl.ncsbe.gov/ | Direct file downloads incl. historical snapshots for building matched pairs. |
| 192 | 📊 ERBench org | https://github.com/erbench | Benchmarking-of-entity-resolution code/data collections. |
| 193 | 📊 recordlinkage sample data | https://recordlinkage.readthedocs.io/ | Ships FEBRL datasets + `krebsregister` — zero-setup smoke tests. |

## 11. Commercial / industrial (feature checklist, not dependencies) 🔵

Read these for **what capabilities buyers expect from a standardization engine** — they converge on the same list: parsing, standardization, address/name/phone/email verification, reference-data lookup, enrichment, fuzzy matching/survivorship, rule management, profiling, monitoring.

| # | Name | URL | What it gives us |
|---|---|---|---|
| 194 | 🔵 Alteryx Designer Cloud (ex-Trifacta) | https://alteryx.com/products/designer-cloud | Predictive transform suggestion UI + transform-by-example — the commercial descendant of Wrangler. |
| 195 | 🔵 Trifacta "how it works" | https://www.trifacta.com/products/how-it-works | Explicit breakdown of profiling → suggest → transform → validate loop. |
| 196 | 🔵 Talend Data Quality | https://www.talend.com/products/data-quality | Semantic discovery, standardization rules/dictionaries, address validation, matching & survivorship. |
| 197 | 🔵 Informatica Data Quality | https://www.informatica.com/products/data-quality.html | Reference tables, parsing/standardization transforms, exception management workflow — strong rule-lifecycle model. |
| 198 | 🔵 Ataccama ONE Data Quality | https://www.ataccama.com/platform/data-quality | AI-assisted DQ rule suggestion + domain detection; good source for rule-authoring UX ideas. |
| 199 | 🔵 SAP Data Services | https://help.sap.com/docs/SAP_DATA_SERVICES | Data Cleanse transform with person/firm/address dictionaries and parsing rules; documentation names the exact standardization primitives. |
| 200 | 🔵 IBM InfoSphere QualityStage | https://www.ibm.com/products/infosphere-qualitystage | Investigate → Standardize (rule sets) → Match → Survive. The **Standardize stage rule-set model is the most explicit industrial analogue to our engine.** |
| 201 | 🔵 Experian Aperture Data Studio | https://www.experian.co.uk/business/platforms/aperture-data-studio | Profiling + validation + global address/email/phone verification in one workflow tool. |
| 202 | 🔵 Experian Data Quality | https://www.experian.com/data-quality | Verification-service capability list. |
| 203 | 🔵 Melissa address verification | https://www.melissa.com/address-verification | Global address parse/correct/standardize/geocode as a service. |
| 204 | 🔵 Melissa Global Address API ref | https://docs.melissa.com/cloud-api/global-address-verification/global-address-verification-reference-guide.html | **Detailed result/status-code taxonomy** (what was corrected, what was ambiguous) — excellent model for our normalization result objects. |
| 205 | 🔵 Anomalo | https://www.anomalo.com/ | Unsupervised DQ monitoring — framing for "detect when values drift out of canonical form". |
| 206 | 🔵 Monte Carlo | https://www.montecarlodata.com/ | Data-observability incident model (freshness/volume/schema/quality). |

---

## Recommended shortlist for the engine

**Build on directly (🟢, ranked by leverage):**
1. `dataprep.clean` (#41) — 40+ ready normalizers; hardest-to-rewrite value.
2. `libpostal`/`pypostal` (#48-49) + `usaddress` (#51) — addresses.
3. `phonenumbers` (#54), `python-stdnum` (#55), `schwifty` (#56), `email-validator` (#57) — deterministic ID/contact canonicalization.
4. `ftfy` (#64) → Unicode NFC (#73) → `Unidecode` (#65) as a fixed pre-stage.
5. `RapidFuzz` (#66) + `jellyfish` (#67) + `string_grouper` (#68) for value clustering; port OpenRefine's key-collision recipes (#32/#36).
6. `ptype` (#150) + `DataProfiler` (#25) for automatic per-column type/anomaly detection.
7. `Pandera` (#5) as the contract layer; `openclean` (#38) and `FollowTheMoney` (#80) as architectural templates for typed, normalizable properties.

**Read before designing (🔵):** Baran (#119), OpenRefine clustering (#32), Potter's Wheel (#131), Auto-Type (#140), Elmagarmid survey §pre-processing (#164), IBM QualityStage Standardize model (#200), Melissa result-code taxonomy (#204).

**Benchmark with (📊):** Raha's six datasets (#171) as regression, BART (#174) to inject controlled errors into our own DB, Leipzig four (#179) + WDC Products (#180) for end-to-end Splink impact, NCVR (#190) for scale. Temper all EM numbers with #167.
