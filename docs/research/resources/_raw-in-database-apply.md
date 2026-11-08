# In-database apply of a value mapping (direction "H-b") — Research Notes

**Scope:** can ClickHouse (CH) apply a (column, raw value, context key) -> normalized-value mapping to 1B rows itself (`INSERT ... SELECT` + join/dictionary), so rows never leave the database machine? Researched 2026-11-07, free sources only.

**Marks:** *verified* = text was read on the page in this session. *not checked* = not verified here (from memory or a search snippet only). Licence of ClickHouse server and chDB: Apache-2.0 (chDB: confirmed by search result; ClickHouse server: *not checked*, from memory). Docs pages themselves are CC/Apache-licensed docs; licence of docs text *not checked*.

**Method note:** WebFetch summarises pages with a small model; where the summary said "not on this page" the fact is marked *not checked*. Several doc URLs 404 (moved docs layout); I used the URLs that worked.

---

## 1. Applying a mapping at scale

1. **ClickHouse JOINs part 2: hash, parallel_hash, grace_hash** — https://clickhouse.com/blog/clickhouse-fully-supports-joins-hash-joins-part2 — ClickHouse blog, 2023-04-20 (page modified 2026-03-03) — *verified*.
   - `hash`: one in-memory table built from the RIGHT table, single-threaded fill. 100M-row right table: 5.06 s, peak 8.95 GiB (~96 B/row, my arithmetic). 1M-row right table: 0.82 s, 716 MiB.
   - `parallel_hash`: one table per bucket, built in parallel; about 2x faster, but 18.29 GiB peak on a 30-core node (about 2x the memory of `hash`). INNER and LEFT only.
   - `grace_hash`: spills buckets to disk; 4 buckets 13.1 s / 3.72 GiB; 8 buckets 16.4 s / 2.10 GiB.
   - Relevance: the right side is our mapping. Memory scales with mapping rows x row width, and every normalized column needs its own join in one INSERT SELECT, so right sides add up. The blog's tables are not ours; per-key bytes depend on value width.

2. **ClickHouse JOINs part 3: full_sorting_merge and partial_merge** — https://clickhouse.com/blog/clickhouse-fully-supports-joins-full-sort-partial-merge-part3 — 2023-05-24 — *verified*.
   - `full_sorting_merge`: 11.6 s / 4.71 GiB unoptimised; 2 s / 793 MiB with key pre-filtering (`max_rows_in_set_to_optimize_join`, default 100,000 keys); 7 s / 498 MiB when join keys match the physical sort order (no sort needed).
   - `partial_merge`: ~2.2 GiB, 33.8 s (left ordered) / 44.9 s (left random), 5.27 GiB spilled.
   - Relevance: low memory, slower. Useful only as a fallback when a mapping does not fit RAM. Our row table is not sorted by the value column, so the "sorted" best case does not apply.

3. **ClickHouse JOINs part 4: direct join** — https://clickhouse.com/blog/clickhouse-fully-supports-joins-direct-join-part4 — 2023-06-07 — *verified*.
   - Right side must be a key-value engine: Join, EmbeddedRocksDB or Dictionary. Only LEFT ANY supported. The key must match the key attribute of the store.
   - 30-core node, 1M actors x roles: direct join with `flat` dictionary 0.044 s (about 25x faster than `hash`); with `hashed` dictionary 0.113 s. Hash join 1.08-1.13 s, parallel hash 0.69 s.
   - Memory: hashed dictionary ~128 MiB for the 1M-key example (~134 B/key, my arithmetic, single narrow attribute assumed); flat dictionary 1.52 GiB (array sized by the largest key). Query-log memory excludes the dictionary's own memory.
   - Relevance: the best fit for "look up one row per key, mapping already in RAM, shared by all queries". A flat layout needs a UInt64 key; our key (column, value, ctx) is composite, so `COMPLEX_KEY_HASHED`. Whether `direct` works with complex-key dictionaries: *not checked* (the blog shows UInt64 keys only). `dictGet` works with complex keys (dictionary docs overview; *not re-checked*).

4. **Dictionary layouts (hashed family)** — https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/hashed — *verified* by fetch (page dated: not shown).
   - `HASHED` has `SHARDS` (>1 loads in parallel, "huge amount of elements"), `SHARD_LOAD_QUEUE_BACKLOG` (10000 = "good balance between memory and speed"), `MAX_LOAD_FACTOR` (0.5-0.99, default 0.5; higher = less memory, slower reads).
   - `SPARSE_HASHED`: less memory, more CPU. `COMPLEX_KEY_*` variants take the same options. No per-element memory figure on the page; "tens of millions of items" is the only scale hint.
   - Search snippet (ClickHouse blog "Using Dictionaries to Accelerate Queries", https://clickhouse.com/blog/faster-queries-dictionaries-clickhouse, *snippet only, not fetched*): sparse variants rarely recommended, efficient only with a single attribute. Memory is observable in `system.dictionaries.bytes_allocated`.
   - Dictionary overview page https://clickhouse.com/docs/sql-reference/dictionaries — *verified*: source can be a ClickHouse table; docs advise a dedicated user with `SELECT` on the source table; `LIFETIME` sets refresh. Relevance: the mapping table lives in the destination DB; the dictionary reads it with a user that has SELECT only there. A dictionary reload (LIFETIME / `SYSTEM RELOAD DICTIONARY`) must be explicit after the app has finished writing the mapping, else half a mapping is applied (design constraint below).

5. **Join table engine** — https://clickhouse.com/docs/engines/table-engines/special/join — *verified*. Always in RAM; written to disk for restart (`persistent`, default 1). `joinGet` for key lookup. Must match JOIN strictness/type or "can return incorrect data" without error. Row policy makes JOIN fail with ACCESS_DENIED. Relevance: an alternative to a dictionary; no composite-key advantage found; loading means INSERT into it, so no "reload after finish" race but data is visible while half loaded.

6. **`transform()`** — *not checked* (function docs not fetched). Takes array-literal maps; fine only for tiny maps in query text. Not suitable for millions of keys.

7. **Settings** — max_insert_threads, max_threads, min_insert_block_size_*: https://raw.githubusercontent.com/ClickHouse/ClickHouse/master/src/Core/Settings.cpp (master, read 2026-11-07, part of the file only) — *verified* for these four: `max_insert_threads` default 0 = auto from cores, "before version 26.8 the default was 1"; `max_threads` default 0 = core count; `min_insert_block_size_rows` default `DEFAULT_INSERT_BLOCK_SIZE` (literal not shown); bytes = that x 256. `join_algorithm`, `max_memory_usage`, `max_bytes_in_join`, `optimize_on_insert`, `parallel_distributed_insert_select`: *not checked* in this fetch. `parallel_distributed_insert_select` concerns Distributed/cluster tables; on a single server it is not relevant (reasoning, *not checked*).
   - Join algorithm doc page https://clickhouse.com/docs/sql-reference/statements/select/join — *verified in part*: `ie_join` joins the default list from 26.8; `ANY` joins keep one right row per key; `join_use_nulls=1` makes unmatched cells NULL and columns Nullable, `0` fills type defaults. Default list and `direct` requirements: *not checked* on that page.
   - Relevance of `join_use_nulls`/default-fill: an unmatched key must NOT silently become a default value; use `LEFT ANY JOIN` and treat "no match" as a hard error (count check), see constraints.

**Verdict for item 1 (reasoned, not measured):** best first candidate = `COMPLEX_KEY_HASHED` dictionary (sharded) read through `dictGet`/`direct` join; second = `parallel_hash` `LEFT ANY JOIN`; fallback for oversize mappings = `grace_hash`. Memory per key: only two published data points (hash join ~96 B/row at 100M rows; hashed dictionary ~134 B/key at 1M keys), both for narrow example tables. Planning figure must be measured with our value widths.

## 2. INSERT SELECT throughput

8. **Supercharging your large ClickHouse data loads, part 2** — https://clickhouse.com/blog/supercharge-your-clickhouse-data-loads-part2 — Tom Schreiber, 2023-10-18 (modified 2026-03-03) — *verified*.
   - Measures: ClickHouse Cloud, 59 cores / 236 GiB per server; `INSERT INTO SELECT` from object storage (`s3Cluster`, GCS bucket), 65.33B rows, ~14 TiB raw, ~1.2 TiB compressed (~235 B/row raw, my arithmetic). Single server ~4M rows/s, ~240 min total.
   - Tuning: `max_insert_threads` 4 -> 32, `min_insert_block_size_rows` ~1M -> 10M gave almost 3x. 1M-row blocks gave ~65,000 parts (~20 MiB each); 10M-row blocks ~6,500 parts. 59 insert threads with 10M blocks did not fit in RAM; 5M worked. Peak 7 GiB per server at defaults. Formula in the blog: bytes setting = peak memory / (~3 x insert threads).
   - Does NOT measure: reading from a local MergeTree, a join, a wide table, or a 24-core machine. Schema is not on the page (external gist).
   - Relevance: the only vendor figure at billion scale. It shows ClickHouse can write at million-rows/s per server for narrow ~235 B rows when the source is cheap; it says nothing about joins.

9. **"Effective Use of ClickHouse" talk, 2017** — https://presentations.clickhouse.com/2017-highload/ — 2017 — *snippet from search only, not fetched*: 1,000,000-row batches into a MergeTree with 105 columns, ~718 B/row: 506,650 rows/s; single-row inserts 59 rows/s. Old hardware and client-driven inserts. Relevance: a floor-level data point for wide rows; not comparable to today's CPUs.

10. **ClickBench** — https://github.com/ClickHouse/ClickBench — *not checked* (not fetched). From memory it measures 43 analytical SELECT queries on a ~100M-row table, not INSERT. I do not use it for the write rate.

11. **`optimize_on_insert`, merges** — *not checked*. Concern from item 8: many small parts slow merges; keep blocks big (millions of rows) and let the 24 cores overlap insert and merge.

**Verdict for item 2:** 280k rows/s is far below the vendor's 4M rows/s on a 59-core node for ~235 B rows (different hardware, source, and no join), and below the 2017 wide-row figure. So the CH write side is not the obvious bottleneck. Wide tables with many joined columns are unmeasured: must be measured (see "What to measure first").

## 3. Distinct extraction

12. **GROUP BY, GROUPING SETS, external group by** — https://clickhouse.com/docs/sql-reference/statements/select/group-by — *verified*.
   - `max_bytes_before_external_group_by` default 0 (off); `max_bytes_ratio_before_external_group_by` alternative. Docs recommend `max_memory_usage` about twice the spill threshold (or ratio 0.5), because the merge stage may need as much as the first stage. Spill costs: no flush = full speed; flush = "roughly three times longer".
   - `GROUPING SETS` runs aggregation per set and combines results; whether it is a single table scan: *not checked*. ROLLUP/CUBE final merge is single-threaded.
   - Relevance: at 1B rows with high-cardinality columns (names, addresses) the aggregation state can be of the order of the row count; spill or a bigger limit is needed. The 64 GB machine is shared with the destination writes.

13. **`uniq` family** — https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniq — *verified*. `uniq` = adaptive sampling over 64-bit hashes, sample up to 65536; about 1% error for hundreds of billions of values; servers before 26.8 gave wrong results above ~2 billion distinct (bug, fixed 26.8). Docs recommend `uniq` over variants in almost all cases. `uniqExact` memory growth, `uniqCombined`/HLL error: *not checked*.
   - Relevance: use `uniq(value)` and `uniq((value, ctx))` per column in one cheap pre-pass for size estimates (each is one scan, memory-bounded). The pair-to-value ratio is the number that decides the mapping size (item 22).

14. **Several columns in one scan** — approaches: one query per column; `UNION ALL`; `arrayJoin([(col_id, toString(a), ctx), ...])`; `GROUPING SETS`. Published cost comparison: *not found / not checked*. Reasoning only: per-column queries re-read the shared columns (ctx) but read only the needed value column (columnar); an `arrayJoin` multiplies rows by the number of columns and holds all columns' keys in one hash table at once. Measure (plan below).

15. **Read-only users** — https://clickhouse.com/docs/operations/settings/permissions-for-queries — *verified*. `readonly=1`: reads and session-context queries only. `readonly=2`: also `SET`, `CREATE TEMPORARY TABLE`, `RESTORE` (note: `RESTORE` can load data). Temporary tables are exempt from readonly and allow_ddl. Settings under readonly: from the search results (not the page): under `readonly=1` no setting can be changed unless the profile marks it `changeable_in_readonly` within min/max (PR #40631, https://github.com/ClickHouse/ClickHouse/pull/40631); under `readonly=2` unconstrained settings can be changed, `readonly` itself cannot; PR #121488 warns against making `readonly` changeable_in_readonly (https://github.com/ClickHouse/ClickHouse/pull/121488). The doc page does not list changeable settings.
   - **Important consequence (reasoning, *not checked in docs*):** `readonly` is per user/session, not per database. One user cannot be read-only on the source database and writable on the destination database through `readonly`. Use SQL grants instead: `GRANT SELECT ON src.*` and `GRANT CREATE/INSERT/ALTER/DROP ON dst.*` (grant syntax *not checked*), and keep `readonly=0`. Alternatively use two users: a `readonly=1/2` user for distinct extraction, a write user restricted to `dst.*` for the apply. "The app never writes the source" is then enforced by grants, and by using no INSERT/DDL on `src.*` in the SQL the app builds.

16. **Load limits on the source server** — settings profile (https://clickhouse.com/docs/operations/settings/settings-profiles, *verified* that profiles are named setting collections assignable to users; constraints and quotas not on the page). `max_concurrent_queries_for_user`, `priority`, quotas, `max_threads`, `max_memory_usage`, `os_thread_priority`: the existence and meaning of `priority` (lower value = higher priority) is *not checked* in official docs (only a blog, https://oneuptime.com/blog/post/2026-01-21-clickhouse-too-many-simultaneous-queries/view, and a search snippet saying `os_thread_priority` is the Linux nice value). Practical rule: cap `max_threads` and `max_memory_usage` in a dedicated profile for the app user; verify against the real server what happens to other users' queries during a scan.

## 4. Typed destination inside CH

17. **Cast functions** — https://clickhouse.com/docs/sql-reference/functions/type-conversion-functions — partly *verified* (first 100k chars): `accurateCastOrNull` returns NULL if the conversion cannot be done accurately (`TRY_CAST(x AS T)` is the same). `accurateCastOrDefault` returns a default (e.g. `0`), which would hide a failure. Not read: `toDecimal*OrNull`, `parseDateTimeBestEffortOrNull`, `toBoolOrNull`, and whether excess fraction digits are truncated silently.
   - Repo fact (`docs/benchmarks/REPORT.md` §11 table, bug "D5 ClickHouse truncates ... excess fraction digit silently"; ADR-020): CH truncated silently before the D5 gate. So a pure-SQL cast of a string number into `Decimal(38,9)` must not be trusted to flag precision loss; the typed value should be produced and range-checked by `normio/storage_types.py::coerce` in Python (the existing gate), carried in the mapping as a canonical string already at the target scale, and SQL only does a lossless `accurateCastOrNull` that must never produce NULL for an "OK" mapping row.
   - Date parsing in SQL (`parseDateTimeBestEffortOrNull`) must not be used: it would be a second date normalizer disagreeing with `normalizers/date.py` (F5; precision rule "a year stays a year").

## 5. Resume / checkpoint for INSERT SELECT

18. **Deduplication of INSERT SELECT** — https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries — *verified*.
   - `insert_deduplication_token`: the token alone identifies the insert; same token = dropped even if the data differs.
   - Plain non-replicated `MergeTree`: `non_replicated_deduplication_window` default 0 = **no deduplication** until set > 0. Since 26.2 `deduplicate_insert` defaults to `enable` (legacy `insert_deduplicate=0` no longer turns it off alone).
   - INSERT SELECT is "stable" only with a literal `ORDER BY ALL` and a single-stream pipeline; `deduplicate_insert_select` default `enable_when_possible` skips dedup if not stable and no token. Block size settings affect block IDs.
   - Relevance: a token per (job, table, range) makes a retry a no-op *only if* the engine has a dedup window and the previous insert of that range finished. A half-done range (some blocks inserted) with the same token: blocks are keyed per block, so partial retry semantics are subtle: *not checked*. Do not rely on dedup for correctness; use item 19.

19. **Partition manipulation** — https://clickhouse.com/docs/sql-reference/statements/alter/partition — *verified*. `REPLACE PARTITION ... FROM` is atomic, needs same structure, partition key, ORDER BY, primary key, storage policy. `DROP PARTITION` deletes data roughly within 10 minutes. The page does not describe retry semantics.
   - Pattern (reasoning): one range = one unit. Insert into a staging table with the same DDL, verify `count()` equals the source range count, then `REPLACE PARTITION` (atomic) or `ATTACH PARTITION FROM` (needs partition alignment). If the destination's partition key is not aligned with the range, use staging + verify + `INSERT INTO dst SELECT * FROM staging` and `DROP` staging; a crash between those two steps needs the token or a per-range ledger row.
   - ReplacingMergeTree for destination: would change the destination's engine/DDL that users see and dedupe only at merge time (counts wrong until `FINAL`); *not recommended*, reasoning only.

20. **Range choice** — use source partitions / part boundaries (`system.parts`, *not checked*) or primary-key ranges. A hash bucket `cityHash64(pk) % N` re-reads the whole table per bucket (reasoning) — avoid.

## 6. Provenance and errors when the DB writes

21. **OpenLineage and ClickHouse** — https://openlineage.io/docs/spec/facets/dataset-facets/column_lineage_facet/ ; search results (not each page fetched): no standalone ClickHouse integration; ClickHouse appears via Spark V2 catalog (#4878), Flink JDBC extractor (#4495), dbt adapter list. No server-side or query_log emitter found. `columnLineage` dataset facet exists.
   - Relevance: the app, not CH, must emit OpenLineage run events (START/COMPLETE/FAIL per job and per table, input = source table, output = destination table, `columnLineage` facet from the mapping spec). Row counts come from CH queries (`count()`, `system.query_log` / `written_rows`: *not checked*). Per-row lineage: the destination row's identity = source primary key, kept as it is today (same key columns, ADR-013 mapping, *not re-read*).
   - Error samples: errors live in the mapping (status != OK per distinct (value, ctx)), so per-row samples are produced after the insert by `SELECT pk, col, raw ... FROM src JOIN mapping WHERE status != OK LIMIT n BY (col, status)` run by the app, plus `count()` per (col, status). The app writes `normalization_clone_job_errors` and the ADR-018 queue from that. Whether "all error rows" (today every error is a row) or "n samples + exact counts" is acceptable is an owner decision (open question 3). A full error list at 1B rows could itself be hundreds of millions of rows.
   - ADR-018 key = `blake3(semantic_type, content_hash(original), context_hash, profile_version)` is computed by the app per distinct (value, ctx) when it builds the mapping; the mapping row stores it, so the review queue works unchanged. CH has a `BLAKE3` function? *not checked*; not needed if the app computes it.

## 7. Context keys

22. **Composite dictionary keys** — `COMPLEX_KEY_HASHED` (item 4, *verified*) and `dictGet('d', 'attr', tuple(col_id, value, ctx))` (*not re-checked*). Key for the mapping: (column_id, raw value as String, ctx_key String). ctx_key = canonical string of the exact context fields (country alpha-2 and the "country came from where" flag that `_group_by_country` returns today as a (country, bool) pair; the bool is part of the answer, so it is part of the key).
   - Cost: mapping rows = distinct (value, ctx) pairs, not distinct values. For columns where ctx is a function of the value (a postcode and its country) the pair count is close to the value count; for a free-text value repeated across many countries it can multiply by up to the number of countries in which it occurs. The ratio `uniq((value, ctx)) / uniq(value)` per column is measured in the pre-pass (item 13); if the ratio is large, check whether the normalizer really depends on ctx for that semantic type (today's `context_hash` includes the whole context; ADR-018 text "country, locale, field, table, source" are in it): a type that ignores country should use a ctx_key without it. The current cache key includes `context_hash`, so same behaviour; narrowing it is a decision with a correctness risk (owner decision).
   - **Cross-table entity country** (`clone_executor.py::_build_entity_country_map`: precedence own COUNTRY column, entity map, job country; contradictions fall through): the row's ctx is not a column of that row. In SQL it is a join or `dictGet` on the entity key into a table built from the other tables. That map has about as many keys as the entity table has rows (millions to hundreds of millions), so it must also live in CH, not on the laptop. Encoding the precedence rule in SQL creates a second implementation of `_group_by_country` (F5). Options in open question 2.

## 8. Alternatives if H-b is not enough

23. **Executable UDFs / executable table function** — https://clickhouse.com/docs/sql-reference/functions/udf — from a search result (page not fetched) — *not verified on the page*: `type executable` (one process) / `executable_pool` (`pool_size`), `command` run from `user_scripts_path` (default `/var/lib/clickhouse/user_scripts`) with `execute_direct`; constant parameters need `execute_direct`; timeouts `command_termination_timeout`, `command_read_timeout`, `command_write_timeout`; `check_exit_code`.
   - Risks (reasoning, not checked): the Python process and libpostal run on the DB server as the `clickhouse` OS user, outside `max_memory_usage` accounting (accounting of child processes: *not checked*), a crash or leak hits the machine that holds the 1B rows, `env_id` (ADR-014) must be the DB host's Python environment, and "runs in the DB server's process tree" is contrary to the owner's constraint. Per-row calls would also bypass distinct-first (a UDF call per row), unless used only inside the distinct-only step.
24. **chDB** — https://github.com/chdb-io/chdb — Apache-2.0 (search results); latest Python version unclear (sources say 4.2.0 dated 2026-07-02, 4.4.0, and a `chdb-core` 26.7.0): check PyPI. Python UDF via `chdb_udf` decorator (args arrive as strings). In-process engine on whichever host runs Python; it cannot write into the remote server's tables except through the normal client protocol. Relevance: could run the normalizers next to data only if that host reads/writes parquet or uses the table functions to the real CH — it does not remove the network hop to the real server. Low value for this goal.
25. **Normalizer workers on the DB machine, reading only distinct rows** — same H-b, with compute on the 24-core machine: raises normalization throughput if the laptop (i5-13600K: 14 cores, 6 GB free; core count from the owner brief only, *not checked*) is the bottleneck. This breaks "app only on laptop", but a worker container can talk to CH over localhost, and the 64 GB / 24-core box can run workers beside CH with `cgroup` limits. Owner decision.

---

## Feasibility of the 1-hour target

Target: 1,000,000,000 rows / 3600 s = **277,778 rows/s** (arithmetic).

| step | assumption | source | status |
|---|---|---|---|
| A. Distinct extraction scans every normalized column once | scan cost per column at 1B rows | none found | **not checked: must measure** |
| B. Normalization of distinct pairs on the laptop | number of distinct (value, ctx) pairs D; normalizer speed | the only measured speed is the old pipeline, 9-13k rows/s with many normalized columns (REPORT.md §6), which includes row transport and writes; the distinct-only speed is not measured | **not checked**. Example formula: laptop time = D / speed. At 10k distinct/s, 36M distincts take 1 hour; 3.6M take 6 min. libpostal (address) speed not measured here. |
| C. Mapping upload and dictionary load | rows D x ~100-150 B/key | items 1/3 (96 B/row hash join; ~134 B/key hashed dictionary; narrow examples) | planning only: 100M keys x ~134 B ~ 13 GB RAM (arithmetic from one narrow data point) |
| D. INSERT SELECT with joins to dst | rows/s on 24 cores | vendor 4M rows/s, 59 cores, ~235 B/row, from object storage, no join (item 8); 506k rows/s, 105 cols, 2017 (item 9) | the target is 14x lower than the vendor figure. Join cost per normalized column: **not checked**. |
| E. Merges, disk | 2 TB disk holds source + destination; destination same size or larger | owner brief | disk write rate of the machine: not checked |

**Verdict (reasoned, not measured):** Steps D and E look feasible by published figures with a wide margin (target is about 7% of the vendor's single-server figure, or about 15% if scaled linearly to 24 cores, `4M x 24/59 = 1.6M rows/s`, arithmetic under an assumption of linear scaling that I did not verify). The decisive unknown is step B: if the number of distinct (value, ctx) pairs across all normalized columns is of the order of the row count (free text, ids, addresses), the laptop normalizing them in under an hour is not feasible at today's measured per-value speeds, and no ClickHouse tuning changes that. If distinct pairs are 1-5% of the rows, the target is plausible. A number from the real database (`uniq((value, ctx))` per column) is needed before any promise. A realistic split: H-b fixes the data movement; whether it fixes the hour depends on the distinct ratio and the normalizer speed.

## Design constraints for H-b

1. **Read-only source by grants**, not by `readonly` (item 15): app user has SELECT on `src.*`, DDL/INSERT only on `dst.*`; mapping tables and staging tables live in `dst` (or a third `norm_work` database). A test must show an INSERT into `src` fails.
2. **Mapping key = (column_id, raw value, ctx_key)**; ctx_key is the exact `context_hash` input in canonical form, including the country-origin flag. One implementation of the context rule (F5): either the app emits SQL from the same rule definition, or both sides read one machine-readable rule table.
3. **No silent default**: use `LEFT ANY JOIN` / `dictGet` without default; before commit, per range, `count() WHERE mapping key not found` must be 0. Never `join_use_nulls=0` default-fill, never `accurateCastOrDefault`.
4. **Cast gate**: typed value comes from `storage_types.coerce` on the app side, stored in the mapping as a string at the column's scale, plus status. SQL: `accurateCastOrNull` only for rows with status OK. Gate check per range: `countIf(mapping_status='OK' AND cast IS NULL) = 0`. Failed values: NULL in a typed column, original string preserved as today (decision #8 in ADR-020: "a failed value's ORIGINAL string always lands in the cell" — for a typed column that is a conflict today solved by NULL plus error row; same here).
5. **Snapshot consistency**: the distinct step and the apply step must see the same source. Source is "read-only", but is it static during a run? If other writers insert during the hour, new distinct values appear after the mapping was built: the "no match" check (3) catches it. Define: fail the range, extend the mapping, retry.
6. **Mapping versioning**: mapping tables are keyed by (job_id, profile_version, env_id); `env_id` of the laptop environment is stored (ADR-014); the dictionary is created per job and dropped after the job (drop only with a yes, B2/B3).
7. **Dictionary/Join load is explicit**: the app finishes the mapping INSERT, verifies `count()`, then `SYSTEM RELOAD DICTIONARY` (command *not checked*), then verifies `system.dictionaries.element_count` equals the mapping count, before the first apply query.
8. **Resume**: unit = (table, range). A ledger table (in `dst` or the app's Postgres) records per range: source count, dest count, status, token. Redo = drop staging, rebuild, verify, swap in (item 19). Never rely on dedup alone (item 18).
9. **Row counts per range** compared from the source and the destination by direct SQL (D1), plus per-table totals.
10. **Errors**: per-(column, status) exact counts always; per-row error rows or n samples, see open question 3. ADR-018 queue rows built from the mapping, not from rows.
11. **Provenance**: app emits OpenLineage per job/table (item 21); the lineage facet is built from the job's column spec, not read from CH.
12. **Resource caps on the shared box**: dedicated settings profile for the app user (`max_threads`, `max_memory_usage`, spill thresholds with `max_memory_usage` ~2x the threshold, items 12/16); the apply step runs with `max_insert_threads` and block sizes sized from the blog's formula (item 8) and leave cores for merges.
13. **Laptop memory (6 GB free)**: the app streams distinct rows in pages and writes mapping rows in batches; no full-column set in RAM. Cache key (ADR-016) stays value + profile_version + semantic_type + context_hash + env_id.

## What to measure first

On the benchmark machine, with a 10M-row, ~20-column table that resembles the real data (a table from the existing benchmark databases or a generated copy, outputs outside the repo, `$BENCH_DIR`). Run one change at a time, record each result as measured, cap memory, run queries in batches.

1. **Baseline copy**: `INSERT INTO dst SELECT * FROM src` (same DDL). Record rows/s, peak memory (`system.query_log`), parts count; repeat with `max_insert_threads` = 1, 8, 24 and `min_insert_block_size_rows` = 1M, 10M. Result = the CH ceiling on this host.
2. **Distinct pre-pass**: `uniq(col)` and `uniq((col, ctx))` for every normalized column; report the pair/value ratio per column and the total pairs. This number decides feasibility.
3. **Distinct extraction**: per-column `GROUP BY (col, ctx)` vs one `GROUPING SETS` vs `arrayJoin`; with and without `max_bytes_before_external_group_by`; record time, peak memory, spill.
4. **Mapping apply, 1 column**: mapping with D = 1k, 100k, 5M synthetic keys; compare `parallel_hash` LEFT ANY JOIN, `grace_hash`, `COMPLEX_KEY_HASHED` dictionary (with and without `SHARDS`) via `dictGet`, and Join engine; record rows/s, peak memory, dictionary `bytes_allocated`, load time. Gives bytes per key at our value widths.
5. **Mapping apply, N columns**: 1, 4, 8, 16 normalized columns in one INSERT SELECT; rows/s vs N, memory vs N.
6. **Cast gate**: mapping with typed strings (decimals with excess digits, overflows, bad strings); check that the "OK and NULL" count is 0 and compare the SQL result with `coerce` on the same values; check silent truncation of excess fraction digits (D5).
7. **Resume**: kill the INSERT SELECT mid-range (container kill), then redo by (a) token only, (b) staging + replace; verify counts and that no duplicate rows exist.
8. **Real normalizer speed on distinct values only** (laptop container, libpostal on the benchmark box): values/s per semantic type, with the real cache; gives step B of the feasibility table.
9. **Source load**: while step 3 runs, run a light query as another user; record its latency with and without the settings profile.
10. **Equivalence**: for the 10M rows compare destination from the H-b path vs the current app path (value by value, direct SQL). They must be equal for all rows (or every difference explained).

## Open questions for the owner

1. **Distinct ratio**: is there a table on the real database machine (or a copy) where `uniq((value, ctx))` can be read, so the distinct count is known before building? Recommendation: yes, a one-off read-only query per column.
2. **Entity-country propagation** (`_build_entity_country_map`): (a) compute the country map in CH by SQL from a rule table the app writes (recommended), (b) keep it in the app and upload `entity -> country` (millions of keys to the laptop and back), (c) drop cross-table propagation in H-b mode. Which?
3. **Error output at 1B rows**: keep one error row per bad cell (can be hundreds of millions) or exact counts + n samples per (column, status) + the review queue per distinct value? Recommendation: counts + samples.
4. **User and grants**: may the app use one CH user with grants (SELECT on source, write on dst) and no `readonly` flag, or must the source be reached by a separate `readonly` user? Does a CH admin exist to create profiles/quotas?
5. **Destination DDL**: can the destination be partitioned (by what) to allow `REPLACE PARTITION`? What engine and sort key does the real destination use today (plain MergeTree)?
6. **Static source**: is the source frozen for the run, or written to meanwhile?
7. **Compute placement**: if the distinct count is large, is putting normalizer workers (and libpostal) on the database machine (cgroup-limited, localhost to CH) acceptable? Or is the 1-hour target negotiable for text-heavy columns?
8. **CH version on the real server**: several defaults change at 26.2 and 26.8 (dedup, `max_insert_threads`, `uniq` correctness above 2B distinct). Which version runs there?
9. **Context narrowing**: may a semantic type that does not depend on country use a ctx_key without it (smaller mapping)? That needs a per-type rule; risk = wrong reuse.

## Unverified claims (summary)

Not fetched or not on the fetched page: `join_algorithm` default and `direct` with complex keys; `transform()`; `priority`/`max_concurrent_queries_for_user`/quotas semantics; ClickBench's contents; `optimize_on_insert`; `parallel_distributed_insert_select` on a single node; `toDecimal*OrNull`, `parseDateTimeBestEffortOrNull` behaviour; GROUPING SETS single-scan behaviour; UDF page details (search result only); child-process memory accounting for executable UDFs; chDB current version; ClickHouse server licence; BLAKE3 function; 24-core count and laptop core count (from the brief); all per-key memory figures come from narrow blog examples, not from our data. The linear-scaling figure (1.6M rows/s) is an assumption.
