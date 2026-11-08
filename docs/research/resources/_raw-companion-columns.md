# Companion columns in the normalized destination: why add columns, and what if none?

**Scope:** whether the clone should keep adding companion columns (`<col>_currency`, `<col>_code`, `<col>_region`, `<col>__from`/`__to`) and whether it should add `<col>_normalized` for key columns (D32, B8b/B8c). Read-only research, 2026-11-08. All web pages fetched 2026-11-08 unless marked "not checked". Licence column: "not checked" where this research did not open the licence page.

## A. Repo facts (read, not changed)

| # | Fact | Source |
|---|---|---|
| R1 | MONEY: amount typed `NUMERIC(38,4)` / `Decimal(38,4)`; currency in `<col>_currency` (suffix is `_currency`, not `amount_currency` unless the column is called `amount`). Code comment: without it the currency "would otherwise be dropped on the floor". | `packages/normapi/src/normapi/clone_executor.py::_CURRENCY_SUFFIX`, `::_destination_plan` |
| R2 | COUNTRY/LANGUAGE/PHONE: `display` stays in the column, `comparison` (ISO alpha-2, BCP 47, E.164) goes to `<col>_code`. Reason in code: a column named CountryCode held "United States" and joined against nothing. | `clone_executor.py::_CODE_SUFFIX` |
| R3 | PHONE also gets `<col>_region` because "E.164 alone does not re-render or re-parse a number (+1 is US, CA and 22 more)". | `clone_executor.py::_REGION_SUFFIX` (D10) |
| R4 | DATE/DATETIME: TEXT column holds EDTF (partial allowed), plus typed `__from`/`__to` (`Date32` / `DATE`). Typing the one column would give NULL or invent month/day. Rejected alternative: typed DATE plus `__edtf`. | `docs/adr/ADR-020-typed-destination.md` |
| R5 | Key columns get no native type and no companions today. | `clone_executor.py::_destination_plan` docstring |
| R6 | Companions are filled only for answer statuses (NORMALIZED, PARSED, REPAIRED, UNCHANGED, NEEDS_REVIEW); AMBIGUOUS/INVALID get none. | `clone_executor.py::_ANSWER_STATUSES` |
| R7 | The model already holds all views in one object: `original`, `repaired`, `display`, `comparison`, `search`, `ascii`, `structured`, plus status, trace. | `packages/normcore/src/normcore/models.py::NormalizedValue` |
| R8 | ADR-013 (sidecar design, Accepted 2026-08-17) chose ONE struct column per field with all views (`<field>__nrm`) in an Arrow/Parquet sidecar. The clone feature (ADR-017, Postgres/ClickHouse only) later chose in-place values plus companions instead. The in-place mode was removed 2026-10-27 so the origin is never written. | `docs/adr/ADR-013-normalization-storage.md`, `ADR-017-clone-normalize-engine-scope.md` |
| R9 | `ARCHITECTURE.md` documents `<col>__from`/`__to` in the per-type table; its data-contract section does not list `_currency`, `_code`, `_region` (checked by grep, not exhaustively). Doc gap, not a design point. | `ARCHITECTURE.md` "Data contract" |
| R10 | Column lineage already maps every companion to the one source column (`currency_columns`, `code_columns`, `region_columns`, `bounds_columns`), so lineage is fine with companions. Source column is DIRECT/TRANSFORMATION. | `packages/normapi/src/normapi/lineage.py` (`build_table_run`) |
| R11 | Report constraints: Q12 output must carry appropriate types for ER/matching; Q21 destination schema is fully ours to change; Q16 a wrong value is catastrophic; D32 owner answers "b8b. a": a configured key column keeps the source value, normalized value goes to a companion; name `_normalized` waits for the owner (B8c). | `docs/improvement-report.md` rows Q12, Q16, Q21, D32 |

## B. Sources, by research question

### 1. How money is represented

1. **ISO 20022 Amount type**
   URL: https://www.iso20022.org/sites/default/files/media/file/ISO_20022_Generation_of_JSON_Schema_Draft_2020_12_for_ISO_20022_2013_10June2025.pdf (surfaced by search; summary below is from search snippets, the PDF itself was not opened).
   Licence: not checked. Version/date: ISO 20022 JSON-schema guide, June 2025.
   Finding: `ActiveCurrencyAndAmount` is a decimal with a required `Ccy` attribute (ISO 4217). Example `<InstdAmt Ccy="EUR">1.00</InstdAmt>`. Dropping `Ccy` fails schema validation. The JSON mapping makes an object with an amount and `Ccy`. A separate `ImpliedCurrencyAndAmount` type has no currency (used when the currency is fixed by context).
   Relevance: the standard never allows an amount without its currency unless the currency is implied by the message. Two parts, one value. Not "not checked" on the rule itself; the exact facet numbers (5 fraction digits, 18 digits) come from the search summary only.

2. **HL7 FHIR R5 Money**
   URL: https://hl7.org/fhir/datatypes.html#Money. Licence: not checked (FHIR publishes under its own licence page). Version: R5 v5.0.0.
   Finding: `value` (decimal, precision implicit and significant) and `currency` (ISO 4217 code, required binding). Both 0..1.
   Relevance: same two-part shape. Note the precision-is-significant wording matches "precision is preserved".

3. **Kimball, "Multiple currency facts"**
   URL: https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/multiple-currencies/. Licence: not checked (copyright text). Date: not shown.
   Finding: each money measure is a pair of columns: amount in the original currency, and amount converted to one reference currency (done in ETL under a stated policy); a currency dimension names the original currency.
   Relevance: relational practice is columns beside each other, not a packed value. It also warns that conversion belongs to a policy; this project does not convert (and must not).

4. **PostgreSQL wiki, "Don't Do This"**
   URL: https://wiki.postgresql.org/wiki/Don%27t_Do_This. Licence: not checked. Date: current page.
   Finding: do not use `money`: it stores no currency (uses the `lc_monetary` locale setting, so changing the setting changes meaning) and cannot hold fractions of a cent. Use `numeric`; "if you need to track currency, store it in an adjacent column".
   Relevance: the Postgres community's own answer is exactly today's design (numeric amount plus adjacent currency column). A currency-less amount is the discouraged case.

5. **PostgreSQL composite types**
   URL: https://www.postgresql.org/docs/current/rowtypes.html. Licence: PostgreSQL licence (not checked on page). Version: current docs.
   Finding: constraints on a table's columns do not travel with the composite type (a domain with CHECK is the workaround); field access needs `(col).field`; updates of a field need special syntax; literals are quoting-prone. My own note, not on the page: foreign keys and ordinary indexes on a field are harder than on a plain column (not checked).
   Relevance: a composite `(amount, currency)` column is possible but costs query ergonomics and ER tool compatibility.

6. **ClickHouse Tuple**
   URL: https://clickhouse.com/docs/sql-reference/data-types/tuple. Licence: Apache-2.0 for the repo (not checked on page). Version: current docs.
   Finding: elements are read by name or index (`t.1`), compared left to right, and `Nullable(Tuple(...))` differs from `Tuple(Nullable(...))`. The page does not say whether a Tuple may be a key, or how a join on a field behaves (not checked).
   Relevance: a Tuple is a valid single column, but whether it fits the sort key and joins is unverified.

7. **ClickHouse sorting key and Nullable**
   URL: https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree. Finding: Nullable in `ORDER BY`/`PRIMARY KEY` needs `allow_nullable_key` and is "strongly discouraged". Matches the repo rule that keys get no native type.

8. **ClickHouse LowCardinality**
   URL: https://clickhouse.com/docs/sql-reference/data-types/lowcardinality. Finding: helps under about 10,000 distinct values, can be worse over about 100,000. A currency or country-code column has fewer than 300 distinct values, so a companion's per-row cost can be small on ClickHouse (not measured here; the repo uses `text_type`, see R1 call site, whether it is LowCardinality was not checked).

9. **Arrow canonical extension types**
   URL: https://arrow.apache.org/docs/format/CanonicalExtensions.html. Licence: Apache-2.0 (not checked on page). Finding: the list (tensors, JSON, UUID, opaque, bool8, Parquet Variant, timestamp with offset) has no money or currency type. Arrow/Parquet have decimal, struct and extension mechanisms, so a struct is possible but not standardized.
   Relevance: no standard "money" column type exists to adopt.

10. **dbt, staging layer**
    URL: https://docs.getdbt.com/best-practices/how-we-structure/2-staging. Licence: not checked. Finding: staging does renaming and type casting, and keeps the raw value beside the clean one (`subtotal_cents` and a converted `subtotal`) because staging must not change grain or lose source data. No rule on money currency.
    Relevance: the common practice is "clean column plus the raw one kept", i.e. adding columns, not packing.

**Answer to "is one column ever recommended?"** Not found in any source above. Every source keeps amount and currency as two parts. A packed text such as "5.00 USD" is untyped and not summable; a currency-less amount is explicitly discouraged (Postgres wiki) or allowed only when the currency is implied by context (ISO 20022 implied type). A composite/tuple is a legitimate encoding of the same two parts, with ergonomics cost. No source found recommends a tuple for an analytic table (not found, not proof of absence).

### 2. Code plus display

11. **OpenRefine reconciliation**
    URL: https://openrefine.org/docs/manual/reconciling. Licence: BSD-3 (not checked on page). Version: current manual.
    Finding: a match does not add a column; the cell stores both the original text and the matched entity link. A new column appears only on "Add entity identifiers column", user-triggered, user-named.
    Relevance: the tool keeps text and key together in one cell (a structured cell), and offers a column as an explicit, opt-in export.

12. **Splink (record linkage)**
    URL: https://moj-analytical-services.github.io/splink/topic_guides/data_preparation/feature_engineering.html. Licence: MIT (not checked on page).
    Finding: comparisons are defined per named column; derived features (postcode parts, Double Metaphone `first_name_dm`, `full_name`) are added as new columns before linking; the page's advice is to supply good features.
    Relevance: an ER engine expects separate, flat, standardized columns. A struct/JSON field would need unpacking first (not stated on the page; inference).

13. **Senzing entity specification**
    URL: https://www.senzing.com/docs/entity_specification/index.html. Licence: not checked (commercial product; spec text). 
    Finding: prefers parsed components (parsed names, addresses), asks for standardized labels (identifier types, record types), canonical IDs for social handles; no general pre-cleansing step is requested; never says Senzing standardizes for you.
    Relevance: wants flat feature attributes with standard codes; says nothing about carrying a display and a key together.

14. **Zingg, dedupe.io**
    URLs tried: https://docs.zingg.ai/... (field definition page returned 404). Not checked. dedupe (https://github.com/dedupeio/dedupe) not checked.

15. **FHIR CodeableConcept (code plus display)**: not checked in this research (only Money and dates were read). The agent should not cite it until opened: https://hl7.org/fhir/datatypes.html#CodeableConcept.
    GeoNames: not checked.

**Answer:** the only ER sources opened (Splink, Senzing) take flat, per-attribute columns with standard codes. Separate columns are what they consume. No opened source recommends storing only the human name when a code exists.

### 3. Partial dates

16. **EDTF (Library of Congress)**
    URL: https://www.loc.gov/standards/datetime/. Licence: not checked (US government publication). Version: current spec page (EDTF 2019 draft lineage, not confirmed on page).
    Finding: Level 0 allows year only (`1985`) and year-month (`1985-04`) as reduced precision, and intervals `1964/2008` (when endpoint precision differs, interval precision is undefined). Level 1 adds open ends (`1985-04-12/..`, null string = unknown). Levels 1 and 2 are ISO 8601-2 features; implementations must state their level.
    Relevance: confirms EDTF TEXT is the right lossless carrier. Caveat from the page: an interval with mixed precision has undefined precision, so a typed bound pair is the safe way to query.

17. **FHIR date / dateTime**
    URL: https://hl7.org/fhir/datatypes.html (R5 5.0.0). Finding: `date` may be year only, year-month or full; stored as a string with partial forms allowed.
    Relevance: the closest standard practice is the same as ours: keep the partial string. FHIR does not define typed bounds on the type (not seen on the page).

18. **Wikidata time datatype**
    URL: https://www.wikidata.org/wiki/Special:ListDatatypes. Licence: CC0 for data (not checked on page). Finding: a time has a separate `precision` value (9 = year, 10 = month, 11 = day, and so on).
    Relevance: a third known pattern: one point value plus a precision code (still two fields). OpenRefine partial dates: not checked.

**Answer:** each standard that handles partial dates either keeps a string (FHIR, EDTF) or adds a precision field (Wikidata). None puts a partial date into a single typed DATE without loss. Postgres `daterange` (one typed column holding both bounds) exists; not checked on its docs here, and ClickHouse has no range type (not checked).

### 4. Key columns

19. **ClickHouse ReplacingMergeTree**
    URL: https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree. Finding: duplicates are rows with the same `ORDER BY` values (not `PRIMARY KEY`); the last inserted (or highest `ver`) wins; dedupe happens only at background merge time; `FINAL` dedupes at query time.
    Relevance: if a key were normalized in place, `A@B.com` and `a@b.com` become equal `ORDER BY` values and one row can be dropped later, silently. This only applies when the destination table uses this engine; the clone's destination engine choice was not checked here. In Postgres the same collision is a loud primary-key violation that aborts the chunk (ADR-020 decision 8 text about chunk transactions).
    Not found: a data-cleaning source stating "never modify keys". General practice (keep source key, add a standardized key column) is from experience, not checked. dbt surrogate keys: not checked.

### 5. Designs with no extra columns

20. **ClickHouse column kinds** (same MergeTree page as 7): `ALIAS` columns are computed at read time and not written to any part. `MATERIALIZED` columns are stored. Relevance: a computed view over stored data costs no storage, but normalization needs Python/ICU/libphonenumber, so the computed value cannot be an SQL expression; only a reshaping (struct from companions) can.

21. **OpenLineage column lineage facet**
    URL: https://openlineage.io/docs/spec/facets/dataset-facets/column_lineage_facet/. Licence: Apache-2.0 (not checked on page).
    Finding: each output field lists `inputFields` with `transformations` (`type` DIRECT/INDIRECT, `subtype`, `description`, `masking`). One input can feed several outputs (the page's example does it).
    Relevance: no design hurts lineage. A side table or struct would need its own dataset or field-path entry. The repo's `lineage.py` maps each companion to its source column today (R10).

## C. Today's companions: what is lost if removed

| Companion | What it holds | What is lost if removed (and not rebuilt elsewhere) | Can it be re-derived from what stays? |
|---|---|---|---|
| `<amount>_currency` | ISO 4217 code | The unit of the amount. Sums across rows mix currencies; a USD and a JPY value look comparable. The original string (with `$`/`USD`) is not in the clone (R8: in-place removed, origin only), so the loss is permanent for the destination copy. | No. Source text is not kept in the destination column. |
| `<col>_code` (COUNTRY) | alpha-2 | The join key. Display "United States" cannot join a table keyed `US`. | Display to code works only through a name lookup that can be ambiguous (D28 `Congo`, `Korea`). Not safe. |
| `<col>_code` (LANGUAGE) | BCP 47 | Same. Display "German" to `de` needs a lookup; ambiguity possible. | Not safely. |
| `<col>_code` (PHONE) | E.164 | The comparison key. Display "+1 650-253-0000" can be re-parsed only with the right region. | Only with the region. |
| `<col>_region` | libphonenumber region | Ability to re-render or re-parse a national-format number; +1 is shared by 23 regions per the code comment. Whether the region can be derived back from E.164 with libphonenumber was not checked. | Not checked. |
| `<col>__from`, `__to` | typed period bounds | SQL filtering and sorting on dates. Without them: TEXT only (not queryable as dates), or a typed DATE that is NULL or invented for partial values (ADR-020). | Yes, by a function over the EDTF text, but not in plain SQL on 1B rows without a computed column. |
| `<key>_normalized` (proposed) | normalized key value | Nothing is lost by removing it, because the key keeps the source value. What is lost is the normalized form for ER on that column. | Not applicable (derivable only by re-running the normalizer). |

## D. Designs

**Design 1: companions as today, plus `<key>_normalized` for configured keys.**
- Pros: flat typed columns (what Splink and Senzing consume, items 12-13); each companion has a typed join/filter; matches Postgres practice (item 4) and dbt practice of keeping both (item 10); already built and tested; lineage already handled (R10).
- Cons: schema differs from the source (extra columns); naming convention is mixed (`_code`, `_currency`, `_region`, `__from`, `_normalized`); a column per view; name clashes with an existing source column are possible (not checked in code).
- Risk of wrong or lost value: lowest of the four, since every fact has its own typed cell and AMBIGUOUS/INVALID leave companions NULL (R6).

**Design 2: no new columns at all; one view per configured column, in place.**
- Pros: schema identical to the source; nothing to name; smallest storage.
- Cons: MONEY loses its currency (breaks Q16: sums over mixed currency are wrong, and no source recommends it, items 1-5); COUNTRY must choose display or code, losing the other; DATE must choose TEXT (not queryable, no typing, against Q12) or typed (invents or NULLs); keys cannot be normalized without collisions (item 19).
- Risk: highest. A wrong or lost value is silent. Not recommended for MONEY, DATE, keys. Possible only for COUNTRY/LANGUAGE (see section E) if the owner picks code-in-place.

**Design 3: a side table per destination table, keyed by the row key (normalized values and companions there).**
- Pros: destination table has the source's exact columns; companions grow without touching it; closest to ADR-013's sidecar spirit (R8).
- Cons: every ER or analytic query needs a join; needs a unique row key, and a table with no primary key (or a ClickHouse table whose `ORDER BY` is not unique) has none, so the sidecar would need a generated row id that the destination table lacks (reasoning, not checked against code); doubles the key storage at 1B rows (not measured); two writes per chunk with one transaction boundary per engine (ClickHouse has no multi-table transaction; not checked); key columns that were normalized would still collide in the side table if used as its key.
- Risk: medium, mostly a mis-join (orphaned or duplicated side rows).

**Design 4: one struct column replacing the original (Postgres composite type / ClickHouse Tuple / JSON).**
- Pros: no extra columns; the whole value travels together (like ISO 20022 and FHIR Money, items 1-2, and ADR-013's `__nrm` struct, R8); one column per configured field.
- Cons: the column's name now holds a struct, so every consumer of the clone breaks (R2 comment); Postgres composites lose constraints and have awkward syntax (item 5); ClickHouse Tuple use as a key or in joins was not verified (item 6); ER tools want flat columns (items 12-13); an index on a field needs a function or a generated column; a Decimal inside a struct is still typed but the struct itself is not a "typed amount".
- Risk: low for the value, high for the consumer (a query that reads the column as text gets a struct string, silently wrong).

**Design 5 (an add-on, not an alternative): a SQL VIEW layered on the clone.**
- Pros: a view can present companions as a struct or hide them; costs no storage; the base tables stay flat.
- Cons: a view cannot create a normalized value (normalization runs in Python), so it solves presentation only; the companions must still exist underneath. ClickHouse `ALIAS` columns are the same idea per column (item 20).
- Risk: none for values; no gain for the owner's question.

## E. Recommendation per type

| Type | Recommendation | Why |
|---|---|---|
| MONEY | Keep `_currency`. Do not remove it. | Every standard and Postgres/dbt/Kimball practice keeps currency with the amount (items 1-4, 10). Removing it is the loss Q16 calls catastrophic, and the original text is not in the clone. If the owner wants fewer columns, the only safe cut is "skip the companion when the source table already has a currency column for that amount": needs a config field, not checked. Consider `LowCardinality` on ClickHouse (item 8, not measured). |
| COUNTRY / LANGUAGE codes | Keep `_code` by default. Owner can choose "code in place" as a per-type setting. | Flat code column is what ER and joins need (items 12-13). The only no-column variant that is not lossy is code-in-place with display re-derived from CLDR by locale, which changes what existing columns hold (R2 comment says that breaks consumers). A column named CountryCode would then be right. Decision for the owner. |
| PHONE `_code` | Keep. | E.164 is the comparison key. |
| PHONE `_region` | Keep until it is checked whether libphonenumber derives the same region from E.164 alone. | The code comment says E.164 is not enough to re-render; that claim was not re-tested here. |
| DATE/DATETIME bounds | Keep `__from`/`__to`. | Standards keep the partial string (FHIR, EDTF) or add a precision field (Wikidata); none types a partial date into one DATE (items 16-18). Bounds invent nothing and are queryable. A Postgres `daterange` would be one column, but not on ClickHouse (not checked). |
| Key columns | Keep the source value in place; add `<col>_normalized` (owner's b8b). Never normalize a key in place. | `ORDER BY` equals duplicate under ReplacingMergeTree (item 19); Postgres would abort the chunk. Fewest-column alternative: do not normalize a configured key and say so with a fix hint (no companion, but the user loses the normalized key for ER). The owner chose the companion in b8b. |

Overall answer to "why add columns at all": a normalized value has views that cannot be rebuilt from each other (display from code is fine; code from display is not; currency from amount is not; a partial date from a typed DATE is not). A flat column per view is what typed joins, ER tools and Postgres practice use. The columns are not decoration; each one stops one specific loss.

## F. Open questions for the owner

1. MONEY: keep `_currency` always (recommended), or skip it when the source table already has a currency column for that amount? (A config field is needed; not built.)
2. COUNTRY/LANGUAGE: keep display in the column plus `_code` (today, recommended), or switch to code in place and drop `_code` (fewer columns, breaks existing consumers)? Per type or global?
3. PHONE: should `_region` stay? Needs a check of whether libphonenumber's region for a number equals the stored region in all cases.
4. Key columns: companion name. `_normalized` is proposed; today's suffixes are `_currency`, `_code`, `_region`, `__from`/`__to`. One convention, or leave as is?
5. A source column may already be named `<col>_code` or `<col>_normalized`: fail the job, or pick another name? (Whether the code checks this was not verified.)
6. Should the original string of a MONEY/COUNTRY value be kept anywhere in the clone? Today it is not (the origin has it), which is why the companions cannot be dropped safely.
7. ClickHouse: should text companions use `LowCardinality(String)`? Not measured; needs a 1B-row estimate.
8. Does the owner want the ADR-013 struct view (`__nrm`) offered as an optional extra output, as a SQL view or a Parquet export, for consumers that want everything in one cell? (Design 5 would give this at no storage cost.)
