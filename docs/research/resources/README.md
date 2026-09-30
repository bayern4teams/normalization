# Resource sweep — master index

**1,130 unique verified URLs across 9 domain tracks.** Every URL in these
files was fetched during compilation; entries that could not be confirmed
are marked `(unverified)` or `(bot-walled)` in place. Compiled 2026-09-30.

Read this page to find the right file. Read the file to find the resource.

| Track | File | URLs | Answers the question |
|---|---|---|---|
| Address & geo | [`_raw-address-geo.md`](_raw-address-geo.md) | 183 | How do I parse, validate and render a postal address anywhere on earth? |
| Identifiers & code lists | [`_raw-identifiers-codes.md`](_raw-identifiers-codes.md) | 201 | Which authority owns this code, and how do I check its check digit? |
| Data quality & ER | [`_raw-data-quality-er.md`](_raw-data-quality-er.md) | 204 | What does the field already build, and what do I benchmark against? |
| Names & companies | [`_raw-names-companies.md`](_raw-names-companies.md) | 150 | How do I clean a person or legal-entity name for matching? |
| Pipeline engineering | [`_raw-pipeline-engineering.md`](_raw-pipeline-engineering.md) | 110 | How do I make it resumable, provenance-tracked, fast and tested? |
| Ambiguity & abstention | [`_raw-ambiguity-abstention.md`](_raw-ambiguity-abstention.md) | 106 | When should the engine refuse to answer, and how do I prove it was right to? |
| Unicode & text | [`_raw-unicode-text.md`](_raw-unicode-text.md) | 91 | What is the normative rule for this text operation? |
| Dates, money, units, locale | [`_raw-dates-money-units-locale.md`](_raw-dates-money-units-locale.md) | 90 | Where does CLDR say what `1,234` means in this locale? |
| Schema normal forms | [`_raw-schema-normal-forms.md`](_raw-schema-normal-forms.md) | 87 | 1NF–6NF, FD/UCC/IND discovery — the *other* meaning of "normalize a database" |

Domain concentration of the 1,130 URLs: github.com 265, pypi.org 73,
arxiv.org 73, unicode.org 28, rfc-editor.org 20, iso.org 14, vldb.org 14,
gleif.org 13.

**Independent spot-check (not a self-report).** A random 60-URL sample was
re-fetched with a browser user-agent after compilation: 56 returned 2xx.
The 4 non-2xx were all 403 from `dl.acm.org` (×2), `iso.org` and
`unece.org` — precisely the bot-walled origins the tracks flag inline, not
dead links. Reproduce with:

```bash
grep -ohE 'https?://[^ )"]+' docs/research/resources/_raw-*.md \
  | sed 's/[.,;)]*$//' | sort -u | shuf -n 60 \
  | xargs -P 20 -I{} curl -sS -o /dev/null -w '%{http_code} {}\n' -L --max-time 20 \
      -A 'Mozilla/5.0' {}
```

---

## The vocabulary problem, first

"Normalize a database" names three unrelated activities. This repo does
exactly one of them. Before using any resource below, know which you mean.

| Sense | What it does | Covered by | This repo |
|---|---|---|---|
| **A. Value normalization** | dirty value → canonical value (`"Jan 3 2020"` → `2020-01-03`) | 8 of the 9 files here | **This is the engine.** |
| **B. Schema normalization** | 1NF→BCNF decomposition driven by discovered functional dependencies | `_raw-schema-normal-forms.md` Part A | **Absent.** Nothing in `packages/` discovers an FD. |
| **C. Feature scaling** | z-score / min-max for ML input | `_raw-schema-normal-forms.md` Part B | Out of scope, correctly. |

Sense B is the genuine hole. `desbordante` (FD/UCC/IND discovery, Apache-2.0,
`pip install desbordante`) and Papenbrock & Naumann's *Data-driven Schema
Normalization* (EDBT 2017) are the entry points — both in the schema file.

---

## Mapping: audit gap → the resources that close it

The gaps come from [`../../improvement-audit-notes.md`](../../improvement-audit-notes.md),
each verified by reading the named source file. Numbers match that document.

| # | Verified gap | Where to look | Highest-leverage item |
|---|---|---|---|
| 1 | `TAX_ID` + `CODE` share one curated stdnum subset | identifiers §1, §4 | python-stdnum's *formats index* — scrape it to auto-generate a coverage matrix instead of curating by hand |
| 2 | `name.py` lacks Double Metaphone / Beider-Morse | names §4 | Apache Commons Codec BMPM rule files (Apache-2.0); `phonetics` or `Metaphone` on PyPI — **not** `abydos` (GPL-3.0) |
| 3 | `company.py` ignores GLEIF ELF codes at runtime | names §5, identifiers §3 | ISO 20275 ELF code list CSV — free, authoritative, per-jurisdiction legal forms |
| 4 | `url.py` has no PSL, no WHATWG canonicalization | identifiers §7 | Public Suffix List + `tldextract` (pin the snapshot); WHATWG URL Standard for the serialization algorithm |
| 5 | `phone.py` cannot round-trip extensions | identifiers §5 | RFC 3966 `tel:` URI; libphonenumber `FALSEHOODS.md` before any schema decision |
| 6 | `country_codes.py` skips historic countries | address §6, identifiers §9 | `pycountry.historic_countries`; CLDR supplemental territory aliases |
| 7 | No cross-field / multi-pass reconciliation | pipeline §1–2, ambiguity §4 | Rules-engine designs + possible-worlds semantics for holding two candidate readings |
| 8 | `NEEDS_REVIEW` exists; nothing consumes it | ambiguity §7 | Human-in-the-loop / weak-supervision patterns; OpenRefine's reconciliation UI as the interaction model |
| 9 | `confidence` is hand-set, never calibrated | ambiguity §5–6 | Chow's rule for the threshold, conformal prediction for the guarantee, risk–coverage curves as the report format |
| 10 | `type_detection.py` is keyword tables + sniffing | dates §9, data-quality §7 | **ptype** — models disguised missing data explicitly rather than failing the column; Sato for table-context typing |
| 11 | Provenance stops at the process boundary | pipeline §5 | OpenLineage column-lineage facet; W3C PROV-O |
| 12 | Destination columns collapse to TEXT | pipeline §3, §6 | Arrow columnar format + data-contract/schema-registry patterns |

---

## If you read only ten things

1. **UAX #15** (Unicode normalization forms) — the floor under every text op.
2. **TR35 / CLDR** — the only defensible source for "what does `1,234` mean here".
3. **libpostal + `FALSEHOODS.md`s** (names, addresses, time, email) — negative-test generators.
4. **python-stdnum formats index** — your identifier coverage matrix, free.
5. **GLEIF ELF code list** — legal-form normalization, solved and authoritative.
6. **ptype** (arXiv 1911.10081) — disguised missing data as a first-class model.
7. **Papenbrock & Naumann, Data-driven Schema Normalization** — the missing half of the project.
8. **Chow's rule + conformal prediction** — turns `AMBIGUOUS` from a vibe into a guarantee.
9. **OpenLineage column-lineage facet** — provenance that survives the process boundary.
10. **Splink comparison-level docs** — your output schema must feed these; design backwards from them.

---

## Licence hazards worth knowing before you `pip install`

Collected from the per-file licence sections. These are the ones that bite.

- **ODbL contamination (OSM).** Any *database* derived from OSM inherits
  share-alike — including Nominatim/Photon/Pelias indexes, and arguably
  libpostal's trained models. libpostal's *code* is MIT; its *models* come
  from OSM + OpenAddresses. See openvenues/libpostal#291.
- **GPL in the phonetics/transliteration layer.** `abydos` (GPL-3.0),
  `Unidecode` (GPL-2.0+), `python-Levenshtein` (GPL-2.0+), `pykakasi`,
  HeidelTime, SUTime, Nominatim's Python. Permissive substitutes exist for
  every one: `phonetics`, `anyascii`, `Levenshtein` (rapidfuzz fork), Photon.
- **LGPL — sidecar, don't vendor.** `deepparse`, `pycountry`, `nameparser`,
  `python-stdnum`, Gisgraphy.
- **Licensed identifier databases.** CUSIP, SEDOL, SWIFT BIC directory,
  GICS, SNOMED CT, UNSPSC, OCLC. The check-digit *algorithms* are public;
  the *databases* are not. Open substitutes: FIGI for CUSIP/SEDOL, ISIC/NACE
  for GICS, ROR for proprietary org IDs.
- **Attribution-required data.** GeoNames (CC-BY), QUDT (CC BY 4.0), Google
  address metadata (CC-BY 4.0), Public Suffix List (MPL-2.0).
- **Paywalled standards with free operational substitutes.** ISO 8601 → RFC
  3339 + EDTF; ISO 4217 → SIX's XML lists; ISO 3166 → Debian `iso-codes`;
  ISO/IEC 7064 → `stdnum.iso7064`.

---

## One security note carried up from the sweep

While extracting *"Falsehoods programmers believe about geography"* at
`wiesmann.codiferes.net`, the page returned an embedded **prompt-injection
payload** instead of article text. That URL is excluded from these files.
Do not fetch it with an automated agent.
