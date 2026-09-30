# Name & Company Normalization — Verified Resource Map (for a Python normalization engine feeding Splink)

All URLs below were checked in this session (HTTP fetch and/or content extraction). License notes come from PyPI metadata / repo LICENSE where available. Anything I could not confirm is marked **(unverified)**.

**License flags to watch (copyleft / commercial):** `abydos` (GPL-3.0+), `Unidecode` (GPL-2.0+), `text-unidecode` (Artistic/GPL dual), `nameparser` (LGPL), `python-Levenshtein` (GPL-2.0+), `pykakasi` (GPL-3.0+), `gender-guesser` (GPLv3), `gender-detector` (GPL-2), `transliterate` (GPL-2.0/LGPL-2.1), `doublemetaphone` (Artistic). Commercial/paid data: OpenCorporates, D&B DUNS, GLEIF API (free data, ToU), OpenSanctions commercial use terms, ISO standards (paywalled). No AGPL found among the libraries below — notably `dedupe` is MIT (not AGPL, contrary to common belief; its hosted product dedupe.io is the commercial arm).

---

## 1. Person-name parsing

- **nameparser (HumanName)** — https://pypi.org/project/nameparser/ — Rule/list-based splitter for Western personal names into title/first/middle/last/suffix/nickname; the default first stage for person records. **LGPL** — dynamic-link only if you care.
- **python-nameparser repo** — https://github.com/derek73/python-nameparser — Source, configurable title/suffix/prefix lists you will need to extend per corpus.
- **nameparser docs** — https://nameparser.readthedocs.io/en/latest/ — How to customize `CONSTANTS` (titles, conjunctions, suffixes) instead of forking.
- **probablepeople** — https://github.com/datamade/probablepeople — CRF (python-crfsuite) parser that also distinguishes person vs. corporation and labels components probabilistically; MIT. Better than regex on messy, mixed person/company columns.
- **probablepeople on PyPI** — https://pypi.org/project/probablepeople/ — Install/version reference (v0.5.6).
- **probablepeople docs** — https://probablepeople.readthedocs.io/en/latest/ — Tag set and retraining instructions (retrain on your own labeled data for non-US names).
- **libpostal** — https://github.com/openvenues/libpostal — Statistical international address parser/expander; use for the address fields that accompany names in ER blocking. C library, MIT.
- **pypostal** — https://github.com/openvenues/pypostal — Python bindings for libpostal (`expand_address` for normalizing abbreviations).
- **Falsehoods Programmers Believe About Names** — https://www.kalzumeus.com/2010/06/17/falsehoods-programmers-believe-about-names/ — The canonical list of assumptions your schema must not make; read before designing person-name fields.
- **Falsehoods… with examples** — https://shinesolutions.com/2018/01/08/falsehoods-programmers-believe-about-names-with-examples/ — Same list annotated with real counter-examples; useful as a test-case source.

## 2. Company / legal-entity name cleaning

- **cleanco** — https://github.com/psolin/cleanco — MIT. Strips/identifies legal suffixes (GmbH, S.A., Pty Ltd…) and can infer country of incorporation from the suffix; the fastest win for org-name normalization.
- **cleanco on PyPI** — https://pypi.org/project/cleanco/ — v2.3; term lists live in `clean.py` and are easy to extend.
- **fingerprints** — https://pypi.org/project/fingerprints/ — MIT. OpenSanctions library that produces a normalized, sorted, legal-form-collapsed fingerprint of a company name — the single most useful blocking key for org entity resolution.
- **fingerprints repo** — https://github.com/opensanctions/fingerprints — Source; note it now largely delegates to `rigour.names`.
- **rigour** — https://github.com/opensanctions/rigour — MIT. Successor/home of OpenSanctions name cleaning: person vs. organization name handling, prefix removal, org-type normalization, script detection, identifier validation.
- **rigour docs** — https://rigour.followthemoney.tech/ — API reference for `rigour.names`, `rigour.text`, `rigour.ids`.
- **rigour.names module header** — https://github.com/opensanctions/rigour/blob/main/rigour/names/__init__.py — Explicit statement of the three name types (person/org/object) and the different normalizations each needs; good design reference.
- **normality** — https://pypi.org/project/normality/ — MIT. Low-level Unicode/whitespace/ASCII-fold text normalizer underneath fingerprints/rigour; use it so your slugs match theirs.
- **Lost in translation: standardizing our name-cleaning framework** — https://www.opensanctions.org/articles/2026-09-09-name-cleaning/ — OpenSanctions write-up on their current name-cleaning architecture and why naive ASCII-folding fails.
- **corp-names** — https://pypi.org/project/corp-names/ — Small alternative corporate-name cleaner; useful only as a suffix-list donor. Low adoption — vet before depending on it.
- **tidyname** — https://github.com/michellepellon/tidyname — Another company-name cleaning/normalization package (also https://pypi.org/project/tidyname/); treat as a suffix/alias list source rather than a dependency.
- **OpenRefine clustering methods in depth** — https://openrefine.org/docs/technical-reference/clustering-in-depth — Definitive description of fingerprint, n-gram fingerprint, metaphone3 and nearest-neighbour key-collision clustering; the algorithms to reimplement for candidate grouping.

## 3. Entity schema, matching frameworks, dedupe engines

- **nomenklatura** — https://github.com/opensanctions/nomenklatura — MIT. Entity deduplication/resolution framework (resolver graph, scoring, xref) built on FollowTheMoney; the closest open analogue to a production ER pipeline.
- **nomenklatura on PyPI** — https://pypi.org/project/nomenklatura/ — v4.x install reference.
- **FollowTheMoney** — https://github.com/opensanctions/followthemoney — MIT. Entity schema (Person, Company, LegalEntity…) with typed `name`/`alias`/`previousName` properties — steal this model instead of inventing one.
- **FollowTheMoney docs** — https://followthemoney.tech/ — Schema browser and Python API for entity/property handling.
- **followthemoney on PyPI** — https://pypi.org/project/followthemoney/ — Install reference.
- **OpenSanctions open-source components** — https://www.opensanctions.org/docs/opensource/ — Map of which library does what (rigour, fingerprints, nomenklatura, yente, zavod).
- **OpenSanctions identifiers & deduplication** — https://www.opensanctions.org/docs/identifiers/ — How they mint canonical entity IDs and manage merge decisions; directly applicable to your resolver store.
- **yente** — https://github.com/opensanctions/yente — The matching API service; reference implementation of name-based screening with configurable algorithms.
- **OpenSanctions matching API** — https://www.opensanctions.org/docs/api/matching/ — Query-by-example matching semantics and candidate ranking.
- **Splink** — https://github.com/moj-analytical-services/splink — Your downstream engine: Fellegi-Sunter probabilistic linkage on SQL backends (DuckDB/Spark/Athena).
- **Splink on PyPI** — https://pypi.org/project/splink/ — v5 install reference.
- **Splink comparison level library (API)** — https://moj-analytical-services.github.io/splink/api_docs/comparison_level_library.html — The exact comparison levels (ExactMatch, JaroWinklerAtThreshold, LevenshteinAtThreshold, ArrayIntersect…) your normalizer must emit fields for.
- **Splink comparison library (API)** — https://moj-analytical-services.github.io/splink/api_docs/comparison_library.html — Prebuilt `NameComparison` / `ForenameSurnameComparison` definitions — design your output columns to feed these.
- **Splink out-of-the-box comparisons** — https://moj-analytical-services.github.io/splink/topic_guides/comparisons/out_of_the_box_comparisons.html — What the name templates assume (term-frequency adjustments, forename/surname transposition).
- **Splink string comparators guide** — https://moj-analytical-services.github.io/splink/topic_guides/comparisons/comparators.html — Which fuzzy metric to pick per field and threshold guidance.
- **Splink phonetic transformations guide** — https://moj-analytical-services.github.io/splink/topic_guides/comparisons/phonetic.html — How Splink expects precomputed Soundex/Metaphone/Double-Metaphone columns — i.e. what your engine should materialize.
- **dedupe** — https://github.com/dedupeio/dedupe — MIT (see https://github.com/dedupeio/dedupe/blob/main/LICENSE). Active-learning dedupe with blocking-rule learning; good baseline to benchmark Splink against.
- **Python Record Linkage Toolkit** — https://recordlinkage.readthedocs.io/en/latest/ — BSD-3. Pandas-native indexing + comparison + classification; convenient for offline evaluation of your normalizer.
- **recordlinkage repo** — https://github.com/J535D165/recordlinkage — Source and comparison-function list.
- **RLTK (USC ISI Record Linkage ToolKit)** — https://github.com/usc-isi-i2/rltk — MIT. Academic ER toolkit with a wide similarity-function catalogue (the Zylon/rltk lineage). PyPI release is an alpha: https://pypi.org/project/rltk/.

## 4. String similarity & phonetics

- **jellyfish** — https://jamesturk.github.io/jellyfish/ — MIT. Rust-backed Jaro, Jaro-Winkler, Levenshtein, Damerau, plus Soundex/Metaphone/NYSIIS/Match-Rating; the safest default phonetics dependency.
- **jellyfish repo** — https://github.com/jamesturk/jellyfish — Source and per-function docs.
- **RapidFuzz** — https://github.com/rapidfuzz/RapidFuzz — MIT. Fastest practical fuzzy matching (`token_set_ratio`, `partial_ratio`, `process.cdist`) for candidate generation at scale.
- **RapidFuzz docs** — https://rapidfuzz.github.io/RapidFuzz/ — Scorer semantics; read before choosing a ratio variant for company names.
- **Levenshtein (rapidfuzz fork)** — https://github.com/rapidfuzz/Levenshtein — The maintained, permissively licensed drop-in for the old `python-Levenshtein` API.
- **python-Levenshtein** — https://pypi.org/project/python-Levenshtein/ — **GPL-2.0-or-later** — avoid in a proprietary engine; use `Levenshtein`/RapidFuzz instead.
- **textdistance** — https://github.com/life4/textdistance — MIT. 30+ distances (Jaccard, Sorensen, MLIPNS, editex, Monge-Elkan) for offline metric selection experiments.
- **abydos** — https://github.com/chrislit/abydos — **GPL-3.0+** — by far the widest phonetic coverage (Beider-Morse, Daitch-Mokotoff, Caverphone, Phonex, Eudex, ~40 algorithms) but the license likely blocks bundling; use it to generate reference outputs, not in the shipped engine.
- **abydos.phonetic API list** — https://abydos.readthedocs.io/en/latest/abydos.phonetic.html — Catalogue of every phonetic encoder with citations — the best single index of the field.
- **phonetics** — https://pypi.org/project/phonetics/ — MIT. Small, clean Soundex/Metaphone/DMetaphone/NYSIIS/RefinedSoundex implementation; a license-safe abydos substitute.
- **pyphonetics** — https://pypi.org/project/pyphonetics/ — MIT. Another lightweight phonetic-algorithm set with distance helpers.
- **Metaphone (python)** — https://pypi.org/project/Metaphone/ — BSD. Reference Double Metaphone port.
- **doublemetaphone** — https://pypi.org/project/doublemetaphone/ — **Artistic License** — faster C implementation; check license fit.
- **Beider-Morse Phonetic Matching (Steve Morse)** — https://stevemorse.org/phonetics/bmpm.htm — Authoritative description of BMPM: language-aware, multi-token phonetic encodings for Jewish/European surnames — the right tool for transliterated surnames.
- **Apache Commons Codec BeiderMorseEncoder** — https://commons.apache.org/proper/commons-codec/apidocs/org/apache/commons/codec/language/bm/BeiderMorseEncoder.html — Production BMPM implementation and rule files (JVM); the source Elasticsearch uses.
- **Apache Commons Codec repo** — https://github.com/apache/commons-codec — Apache-2.0 BMPM/Soundex/Metaphone rule data you can port.
- **Elasticsearch phonetic token filter** — https://www.elastic.co/docs/reference/text-analysis/analysis-phonetic-tokenfilter — How to do phonetic blocking in the search tier (beider_morse, daitch_mokotoff, metaphone).
- **pg_trgm** — https://www.postgresql.org/docs/current/pgtrgm.html — Trigram similarity + GIN/GiST indexes for in-database fuzzy candidate retrieval; the pragmatic blocking layer if your store is Postgres.
- **fuzzystrmatch (Postgres)** — https://www.postgresql.org/docs/current/fuzzystrmatch.html — In-DB Soundex, Metaphone, Double Metaphone, Levenshtein, Daitch-Mokotoff.
- **Soundex (overview)** — https://en.wikipedia.org/wiki/Soundex — Algorithm definition and its known failure modes on non-Anglo names.
- **Metaphone / Double Metaphone** — https://en.wikipedia.org/wiki/Metaphone — Lawrence Philips' algorithms, including Double Metaphone's primary/alternate keys.
- **Double Metaphone** — https://en.wikipedia.org/wiki/Double_Metaphone — Redirects to the Metaphone article; primary/alternate key semantics matter for indexing two keys per name.
- **NYSIIS** — https://en.wikipedia.org/wiki/New_York_State_Identification_and_Intelligence_System — Surname-oriented phonetic code, generally stronger than Soundex for US surnames.
- **Beider-Morse algorithm (overview)** — https://en.wikipedia.org/wiki/Beider%E2%80%93Morse_Phonetic_Name_Matching_Algorithm — Short summary of language detection + rule-based phonetic generation.
- **Jaro-Winkler distance** — https://en.wikipedia.org/wiki/Jaro%E2%80%93Winkler_distance — Definition and the prefix-weighting caveat that biases it toward matching name prefixes.
- **hmni** — https://github.com/Christopher-Thornton/hmni — MIT. Siamese-network fuzzy name matcher; interesting as a learned-similarity baseline, but unmaintained-looking — benchmark before trusting.
- **fuzzychinese** — https://github.com/znwang25/fuzzychinese — BSD. Stroke/radical/char n-gram TF-IDF matching for Chinese company names — handles cases where romanization loses information.

## 5. Legal-form and company reference data / authorities

- **GLEIF — ISO 20275 Entity Legal Forms code list** — https://www.gleif.org/en/lei-data/code-lists/iso-20275-entity-legal-forms-code-list — THE authority for legal-form normalization: ELF codes with per-jurisdiction local-language names, abbreviations and transliterations. Free download.
- **ELF code list v1.6 CSV (direct)** — https://www.gleif.org/lei-data/code-lists/iso-20275-entity-legal-forms-code-list/2026-02-19-elf-code-list-v1.6.csv — Machine-readable ELF file; load this as your suffix/legal-form dictionary instead of hand-rolling one.
- **ELF code list v1.5 PDF** — https://www.gleif.org/media/pages/about-lei/code-lists/iso-20275-entity-legal-forms-code-list/5bca1b3e6f-1745410236/2023-09-28-elf-code-list-v1.5.pdf — Human-readable prior version for diffing.
- **GLEIF code lists index** — https://www.gleif.org/en/lei-data/code-lists — Also hosts registration-authority and reporting-exception lists you need for jurisdiction mapping.
- **ISO 20275:2017** — https://www.iso.org/standard/67462.html — The standard itself (**paywalled/commercial**); the GLEIF code list is the free operational artifact.
- **GLEIF Golden Copy downloads** — https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy — Full LEI file (legal name, other names, legal form, HQ/legal address, relationships) — a free, high-quality org-name + alias corpus.
- **GLEIF LEI Level-1 data reference** — https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-1-data-who-is-who — Field-by-field description of what Level-1 records contain.
- **GLEIF API** — https://www.gleif.org/en/lei-data/gleif-api — REST access for lookups/enrichment (docs land at a Postman collection).
- **GLEIF search** — https://search.gleif.org/ — Manual spot-checking of normalization decisions against authoritative legal names.
- **OpenCorporates API reference** — https://api.opencorporates.com/documentation/API-Reference — Widest cross-jurisdiction company register coverage with previous names/aliases. **Commercial licensing** — see https://opencorporates.com/pricing/.
- **OpenCorporates API walkthrough** — https://knowledge.opencorporates.com/knowledge-base/api-walkthrough/ — Search vs. fetch semantics and the jurisdiction_code scheme.
- **SEC EDGAR — accessing data** — https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data — Official bulk/JSON access rules (User-Agent required) for CIK ↔ company-name mapping; free public-domain data.
- **EDGAR full-text search** — https://www.sec.gov/edgar/search — UI/endpoint for confirming US registrant names and former names.
- **Companies House REST API** — https://developer.company-information.service.gov.uk/overview — UK register: company names, previous names, officers; free with API key.
- **Companies House public search** — https://find-and-update.company-information.service.gov.uk/ — Manual verification of UK entity names.
- **EU BRIS — find a company** — https://e-justice.europa.eu/topics/registers-business-insolvency-land/business-registers-search-company-eu/general-information-find-company_en — Federated EU business-register search; useful for cross-border legal-form ground truth.
- **BRIS search endpoint** — https://webgate.ec.europa.eu/e-justice/searchBris.do — The actual query interface behind BRIS. **(unverified — not fetched in this session)**
- **VIES VAT validation** — https://ec.europa.eu/taxation_customs/vies/ — Validates EU VAT IDs and returns the registered trading name — a strong deterministic key alongside normalized names.
- **VIES programme page** — https://taxation-customs.ec.europa.eu/vies-vat-information-exchange-system_en — Scope, SOAP/REST service description and usage limits.
- **D&B D-U-N-S lookup** — https://www.dnb.com/en-us/smb/duns/duns-lookup.html — DUNS is the de-facto corporate-family key in procurement data. **Commercial-only** for bulk/API use.
- **OpenFIGI API** — https://www.openfigi.com/api/documentation — Free mapping of tickers/ISINs to FIGIs with issuer names; good for financial-instrument-linked org names.
- **Research Organization Registry (ROR)** — https://ror.org/ — CC0 registry of research organizations with rich alias/label/acronym arrays; excellent free alias training data.
- **ROR REST API** — https://ror.readme.io/docs/rest-api — Query interface for names, aliases, acronyms, labels per language.
- **Handling name metadata in ROR** — https://ror.org/blog/2022-08-31-name-metadata-in-ror — Practical discussion of alias vs. label vs. acronym modeling — directly transferable to your schema.
- **GRID** — https://www.grid.ac/ — ROR's predecessor dataset; still a source of historical org aliases.

## 6. Aliases, person-name datasets, demographics

- **Wikidata Help:Aliases** — https://www.wikidata.org/wiki/Help:Aliases — How aliases are modeled per language; the semantics you inherit when ingesting them.
- **Wikidata Query Service** — https://query.wikidata.org/ — SPARQL endpoint to bulk-extract `skos:altLabel` aliases for people and companies (CC0 data).
- **Wikidata SPARQL service portal** — https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service — Query examples, limits, and federation notes.
- **Wikidata data access** — https://www.wikidata.org/wiki/Wikidata:Data_access — Dumps vs. API vs. WDQS; pick dumps for building an alias table.
- **DBpedia SPARQL** — https://www.dbpedia.org/resources/sparql/ — Wikipedia-derived redirects/labels — a complementary alias source (redirects are especially good name-variant signal).
- **SSA Popular Baby Names — beyond the top 1000** — https://www.ssa.gov/oact/babynames/limits.html — Free national/state given-name frequency files; use for given-name gazetteers, term-frequency weights and gender priors.
- **SSA baby names on data.gov** — https://catalog.data.gov/dataset/baby-names-from-social-security-card-applications-national-data — Stable mirror/metadata for the same dataset.
- **names-dataset** — https://pypi.org/project/names-dataset/ — MIT package, large multi-country first/last-name lists with country and gender distributions (derived from a Facebook leak — check your own compliance stance).
- **name-dataset repo** — https://github.com/philipperemy/name-dataset — Source and data-provenance notes.
- **gender-guesser** — https://github.com/lead-ratings/gender-guesser — **GPLv3** — offline gender inference from given names (Jörg Michael's dictionary); good for a person-name feature, watch the license.
- **gender-guesser on PyPI** — https://pypi.org/project/gender-guesser/ — Install/version reference.
- **gender-detector** — https://github.com/malev/gender-detector — **GPL-2** — country-aware gender inference off open name registries; alternative to gender-guesser.
- **gender-detector on PyPI** — https://pypi.org/project/gender-detector/ — Install reference (old, v0.1.0).
- **ethnicolr** — https://github.com/appeler/ethnicolr — Name → race/ethnicity probability models (census/Florida voter/Wikipedia-trained). Useful as a *name-origin* prior for choosing transliteration rules; strongly consider fairness/legal review before using ethnicity output in matching decisions.
- **ethnicolr on PyPI** — https://pypi.org/project/ethnicolr/ — v2.0.0 install reference.

## 7. Transliteration & romanization

- **ICU General Transforms** — https://unicode-org.github.io/icu/userguide/transforms/general/ — The industrial standard: `Any-Latin; NFD; [:Nonspacing Mark:] Remove; NFC` and script-specific transforms; prefer this over ad-hoc tables.
- **ICU transform rule tutorial** — https://unicode-org.github.io/icu/userguide/transforms/general/rules.html — How to author custom rules (e.g. jurisdiction-specific legal-form romanization).
- **PyICU** — https://pypi.org/project/PyICU/ — MIT bindings exposing `icu.Transliterator` to Python; the license-clean way to romanize at scale.
- **Unidecode** — https://pypi.org/project/Unidecode/ — **GPL-2.0+** — ubiquitous ASCII folding, but the license is a real constraint for proprietary distribution.
- **text-unidecode** — https://pypi.org/project/text-unidecode/ — **Artistic License / GPL dual** — pure-Python Unidecode clone chosen mainly to dodge the GPL; read the license text yourself.
- **anyascii** — https://github.com/anyascii/anyascii — **ISC** — the permissively licensed, broad-coverage Unicode→ASCII transliterator; the right default for a commercial engine.
- **uroman** — https://github.com/isi-nlp/uroman — Apache-2.0. Universal romanizer covering nearly every script; strongest general fallback for exotic scripts (also https://pypi.org/project/uroman/).
- **pypinyin** — https://github.com/mozillazg/python-pinyin — MIT. Hanzi→Pinyin with tone handling and surname-aware readings; essential for Chinese person/company names.
- **pypinyin on PyPI** — https://pypi.org/project/pypinyin/ — Install reference.
- **pykakasi** — https://github.com/miurahr/pykakasi — **GPL-3.0+** — Japanese kana/kanji→romaji; license flag for bundling.
- **pykakasi on PyPI** — https://pypi.org/project/pykakasi/ — Install/version reference.
- **CAMeL Tools** — https://github.com/CAMeL-Lab/camel_tools — MIT. Arabic NLP suite (dediacritization, normalization, transliteration) — needed because Arabic name matching is mostly a normalization problem.
- **Arabic ALA-LC romanization (CAMeL Lab)** — https://github.com/CAMeL-Lab/Arabic_ALA-LC_Romanization — Rule implementation for library-standard Arabic romanization.
- **transliterate** — https://pypi.org/project/transliterate/ — **GPL-2.0/LGPL-2.1** — bidirectional Cyrillic/Greek/Georgian/Armenian transliteration packs.
- **iuliia** — https://pypi.org/project/iuliia/ — MIT. Implements ~20 named Russian→Latin schemes (GOST, ICAO, ALA-LC, BGN/PCGN, Wikipedia) — the best way to generate *all* plausible Cyrillic name variants.
- **ISO 9 (Cyrillic transliteration)** — https://en.wikipedia.org/wiki/ISO_9 — Explains the strict 1:1 reversible mapping and how it differs from BGN/PCGN — matters when deciding which variant is canonical.
- **ISO/DIS 9 at ISO** — https://www.iso.org/standard/89763.html — Official (revision) record; **paywalled**. **(unverified — ISO blocked automated fetch; page exists per search results)**
- **BGN/PCGN Romanization systems (GOV.UK)** — https://www.gov.uk/government/publications/romanization-systems — Official BGN/PCGN romanization tables per language; the system most Western government name lists use.
- **ALA-LC Romanization Tables (LoC)** — https://www.loc.gov/catdir/cpso/roman.html — Library-standard tables for ~70 scripts; authoritative source for bibliographic-style name variants.
- **UNGEGN Working Group on Romanization Systems** — https://arhiiv.eki.ee/wgrs/ — UN-recommended romanization systems per script, with status of each (original https://eki.ee/wgrs/ redirects here).
- **UNGEGN WG5 (UN Statistics)** — https://unstats.un.org/unsd/ungegn/working_groups/wg5.cshtml — Official UN landing page and report archive for romanization decisions.
- **Romanization of Arabic (overview)** — https://en.wikipedia.org/wiki/Romanization_of_Arabic — Side-by-side comparison of competing Arabic schemes; explains why one Arabic name yields dozens of Latin spellings.

## 8. Papers, surveys and practitioner write-ups

- **Cohen, Ravikumar & Fienberg — A Comparison of String Distance Metrics for Name-Matching Tasks** — https://www.cs.cmu.edu/~wcohen/postscript/ijcai-ws-2003.pdf — The reference empirical comparison (TF-IDF/SoftTFIDF beating pure edit distance on names); use it to justify metric choices.
- **Cohen et al. — A Comparison of String Metrics for Matching Names and Records** — https://www.cs.cmu.edu/~wcohen/postscript/kdd-2003-match-ws.pdf — KDD-workshop companion with the hybrid SoftTFIDF results.
- **Winkler (1990) — String Comparator Metrics and Enhanced Decision Rules in the Fellegi-Sunter Model** — https://www.stat.cmu.edu/NCRN/PUBLIC/RLClassFiles/HW/Winkler1990.pdf — Origin of Jaro-Winkler and of the F-S scoring Splink implements; read before tuning comparison levels.
- **Christen — Data Matching (Springer)** — https://link.springer.com/book/10.1007/978-3-642-31164-2 — The standard textbook on record linkage (blocking, comparison, classification, evaluation). **Commercial/paywalled book.**
- **Name Matching in Sanctions Screening (OpenSanctions)** — https://www.opensanctions.org/articles/2025-06-24-name-matching/ — Practitioner account of what actually works for cross-script person/company name matching and where fuzzy scores mislead.
- **Improving the way we score matching results** — https://www.opensanctions.org/articles/2022-04-11-scoring/ — How they combine name, identifier and attribute evidence into a score.
- **Improving screening results with logic-v2** — https://www.opensanctions.org/articles/2025-09-11-logic-v2/ — Current matching algorithm design and its named-feature weights.
- **Tuning the matching algorithm** — https://www.opensanctions.org/docs/api/tuning/ — Concrete per-feature weights/thresholds you can mirror as a baseline.
- **Terrorizer: consolidating company names in patent assignees** — https://arxiv.org/abs/2403.12083 — Recent company-name harmonization algorithm (rules + embeddings) with evaluation on assignee data.
- **Disambiguation of Company Names via Deep Recurrent Networks** — https://arxiv.org/abs/2303.05391 — Learned company-name matching baseline; useful for deciding whether to add an ML re-ranker.
- **Corporate-Family Resolution Is Not a String-Matching Problem** — https://arxiv.org/abs/2609.04269 — Public benchmark showing where pure name matching fails for corporate families (subsidiaries/brands); motivates keeping identifiers in the pipeline.
- **Isaac Bloomberg Meets Michael Bloomberg: Better Entity Disambiguation for the News** — https://dl.acm.org/doi/10.1145/2740908.2741711 — Bloomberg's own paper on person/company name disambiguation in news text. **(unverified — ACM blocked automated fetch; DOI/title confirmed via search)**
- **ICE-ID historical census name-matching benchmark** — https://arxiv.org/abs/2506.13792 — Recent benchmark comparing classical name-matching against ML/LLM approaches on noisy historical names.
