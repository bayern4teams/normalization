# Ponytail debt ledger (Phase 5, 2026-10-06)

Every `# ponytail:` marker in `packages/` and `scripts/`, from
`grep -rnE '(#|//) ?ponytail:' packages scripts`. The 8 hits under `tests/` are planted lines inside the §2.4 grep
self-tests (fixtures, not debt) and are left out. **[D]** marks a marker added by Defects D1-D12;
**no-trigger** marks one that names no upgrade path or trigger.

## Added by D1-D12

- `normalizers/identifier.py:72` [D7], tax-id module found from English stdnum title words ("tax", "vat"). ceiling: a title in another language (CO `nit`) is not found -> unverifiable; personal + VAT ids of one country -> several candidates -> unverifiable. upgrade: an authoritative per-country tax-id choice.
- `normalizers/identifier.py:81` [D7], hand map of the 4 legacy modules (US/GB/DE/FR). ceiling: 4 entries. upgrade: drop once stdnum names "the" tax id per country.
- `normalizers/identifier.py:143` [D7], a narrower single title-matched module still counts as classified; the sibling rule runs every sibling on a rejection. upgrade: an authoritative per-country choice.
- `normalizers/url.py:123` [D9], PSL snapshot pinned with the package. ceiling: newer suffixes unknown (None, never guessed). upgrade: scheduled dependency bump (moves env_id), never a fetch.
- `normalizers/phone.py:96` [D10], regionless `tel:+<cc>` accepted only with an extension (byte-identity with the pre-D10 output). upgrade: accept it always when the change of output is acceptable (escalation f).
- `normalizers/phone.py:115` [D10], one extension per number (`x45 x46` merges). upgrade: reject inputs with two extension markers if they show up.
- `normalizers/name.py:126` / `:135` [D11], no Beider-Morse beyond 255 chars (measured super-linear cost). upgrade: none needed for names; revisit if long legitimate values appear. **no-trigger** on `:126` (points to `:135`).
- `normalizers/_bmpm.py:69` [D11], upstream's bracket-less context quirk kept for faithfulness (4/131 Cyrillic names lose alternatives). upgrade: follow Commons Codec if it fixes it; re-vendor.
- `normio/storage_types.py:64` [D5], ClickHouse `Decimal(38,9)`. upgrade: `Decimal256` (76 digits) if a real column needs it.
- `normio/storage_types.py:84` [D5], PG NUMERIC 131072 integer digits (PG docs 8.1.2). upgrade: column map if Postgres raises it.
- `normio/storage_types.py:87` [D5], PG 16383 fraction digits. **no-trigger** (a documented engine limit).
- `normapi/lineage.py:43` [D3], fixed 5 s per forward POST. upgrade: configurable if a real collector needs more.
- `normapi/clone_executor.py:2137` [D3], START/COMPLETE are two writes. upgrade: one transaction if a run without COMPLETE ever matters.
- `normapi/pg_persistence.py:874` [D1], whole-context verdict load. upgrade: keyed IN-lookup per chunk at millions of verdicts.
- `normanalysis/calibration.py:30` [D2], 5% significance level. **no-trigger** (a convention; every bound derives from it).
- `normanalysis/calibration.py:33` [D2], ten equal-width bins. upgrade: fewer bins when per-type data is small.
- `normanalysis/gold.py:435` [D6], bare-host URL truth is AMBIGUOUS (contested with url.py's https policy, escalation h). upgrade: drop the kind if the policy is ratified.
- `normanalysis/gold.py:453` [D6], seven CLDR locales for country names. upgrade: more locales, no new code.
- `normanalysis/disguised_missing.py:47` [D4], every distinct value validated (DateNormalizer slow path, escalation k). upgrade: validate a sample, or fix the date slow path.
- `normanalysis/disguised_missing.py:51` [D4], no numeric magic numbers (-999). upgrade: `ptype` once it supports pandas 3 / greenery 4.
- `normanalysis/disguised_missing.py:132` [D4], the missing-value table's size bounds the "small set". upgrade: a frequency model (ptype).
- Docstring ceilings (no `#` prefix): `gold.py` module docstring (injector families; BART/Raha only through the CSV loader), `gold.load_cases` (Raha's two-file layout must be merged first), `calibration.py` module docstring (conformal prediction and persisted per-source bins deferred to Part 3: trigger is a labelled corpus large enough per semantic type), `name.py:_phonetic_fields` (no key for Han/Hangul/Devanagari/Thai: polyphonic).

## Pre-existing (before D1-D12)

- `normio/connectors/clickhouse_destination.py:175`, no insert-dedup on resume. upgrade: a dedup key if resumed double-inserts are observed.
- `normio/connectors/postgres_destination.py:158`, tables without a primary key get no dedup guard. upgrade: persist `source_row_key`.
- `normalizers/money.py:69`, short-scale suffixes only, no single letters ("M" is the loti). upgrade: when a source needs them, with a locale.
- `normapi/secrets.py:7`, one key, no rotation. upgrade: key versioning when rotation is required.
- `normapi/clone_executor.py:122`, if/else over two engines, no connector Protocol. upgrade: a Protocol at a third engine.
- `normapi/clone_executor.py:914`, `threading.Thread`, no task queue. upgrade: a queue for several deployments.
- `normapi/clone_executor.py:1937`, resume re-streams and skips. upgrade: pushdown filter on `read_table`.
- `normapi/clone_executor.py:2068`, no cardinality-adaptive cache switch. upgrade: the adaptive version if low-cardinality re-dispatch costs show.
- `normapi/schemas.py:280`, column plan stored in the job's JSON blob. upgrade: own table if consumed elsewhere.
- `normcore/multivalue.py:21`, bracket-delimited multi-values only. upgrade: a Postgres `{a,b}` parser when a source ships them.
- `normexec/cache.py:117`, 512 MB hard-coded. upgrade: an env var if a container needs it.
- `scripts/generate_cldr_names.py:21`, CLDR standard territory names only. upgrade: when Babel exposes variants.

33 markers (22 added by D1-D12, `name.py` counts twice), 3 with no trigger.
