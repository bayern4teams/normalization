# Raw research: benchmark findings 2, 7, 8, 9 (2026-11-08)

**Scope:** ClickHouse sort-key cloning (#2), column type autodetect on small tables (#7), passthrough/key column types (#8), `/preview` throughput under concurrency (#9).
**Method:** repo read-only, free web sources. "Fetched" = page text read in this session. "Not checked" = claim not verified here. No numbers invented; repo facts cite `path::symbol`.
**Licence marks:** unmarked = free doc / spec / paper. [Apache] [MIT] given where known from the project, else "not checked".

---

## A. ClickHouse sorting key (#2)

1. system.tables reference — https://clickhouse.com/docs/operations/system-tables/tables — docs, ClickHouse docs (CC BY-NC-SA per site footer, not checked) — fetched 2026-11-08.
   Finding: `sorting_key` = "The sorting key expression specified in the table"; `primary_key` likewise; `create_table_query` = "The query that was used to create the table". No text-format promise; no version note.
   Relevance: `sorting_key` is documented as an expression, not a column list. Our regex `_SORTING_KEY_PART` in `normio/connectors/clickhouse.py` assumes a column list; that is an undocumented assumption.

2. system.columns reference — https://clickhouse.com/docs/operations/system-tables/columns — fetched.
   Finding: `is_in_sorting_key`, `is_in_primary_key`, `is_in_partition_key` are flags; `default_expression` is a string. The flags say which columns appear in the key expression, not in what order, and not the expression itself.
   Relevance: good for "which columns must be NOT Nullable / present"; cannot rebuild `ORDER BY toDate(ts)`.

3. ClickHouse source, `src/Storages/KeyDescription.cpp` — https://github.com/ClickHouse/ClickHouse/blob/master/src/Storages/KeyDescription.cpp — Apache-2.0 — master, fetched 2026-11-08.
   Finding: the key is stored as `expression_list_ast` (ORDER BY elements, with the DESC/ASC wrapper `ASTStorageOrderByElement` removed; direction kept apart in `reverse_flags`). `parse()` wraps text in `( ... )`, parses, then clears the "parenthesized" flag so a single expression does not format as `(x)`.
   Relevance: shows ClickHouse has explicit code to avoid spurious parentheses, so `(id)` in 26.8 would be a formatter change or a different AST shape. Not confirmed. A direction (DESC) is NOT visible in `sorting_key`.

4. ClickHouse source, `src/Storages/System/StorageSystemTables.cpp` — https://github.com/ClickHouse/ClickHouse/blob/master/src/Storages/System/StorageSystemTables.cpp — Apache-2.0 — fetched (summary by fetch tool).
   Finding: `sorting_key` is `format({context, *expression_ptr})` of `getSortingKey().expression_list_ast`; empty when the user may not see columns (`can_show_columns`).
   Relevance: the text is the output of ClickHouse's SQL formatter on an AST. Formatter output can change between releases without a changelog line. A user without column-show rights gets an empty string (our code must handle `""`).

5. Changelog search for a `sorting_key` format change — web search 2026-11-08.
   Finding: NOT FOUND. No official entry says `sorting_key` text changed for `ORDER BY (id)` between 24.x and 26.x. The benchmark's "26.8 gives `(id)`" is **not verified**; our local server is 24.9. Third-party: stokaro/ptah issue #4104 (https://github.com/stokaro/ptah/issues/4104) tested `ORDER BY id` on 26.9.8.3 and 24.10.4.191; it reports a primary-key marking mismatch, not a format difference (from a search summary, issue page not fetched).
   Relevance: do not assert "format changed in 25.x". Say "cannot be excluded; test on both versions".

6. PostHog PR #115813 — https://github.com/PostHog/posthog/pull/115813 — MIT (repo; not checked) — fetched.
   Finding: a project that parsed `sorting_key` text with a regex closed the PR calling it "fragile for expressions"; test key was `(team, toStartOfDay(ts), created_on)`.
   Relevance: independent evidence that regex-splitting this text fails for expressions.

7. `formatQuery`, `formatQuerySingleLine` — https://clickhouse.com/docs/sql-reference/functions/other-functions — since v23.10.0 (OrNull variants v23.11.0) — fetched.
   Finding: server-side function that parses a SQL string and returns formatted SQL; throws on parse error.
   Relevance: `formatQuery('SELECT ' || sorting_key)` or a parser could give a normalized form on 24.9+. It does not split a list into elements; it only normalizes text. `EXPLAIN AST` (not fetched, not checked) prints the tree and could split top-level elements server-side.

8. SHOW CREATE TABLE / `create_table_query` — https://oneuptime.com/blog/post/2026-03-31-clickhouse-show-create-table/view and https://clickhouse.com/docs/reference/statements/create/table — third-party blog (licence not checked) + ClickHouse docs — fetched via search summary only.
   Finding: `create_table_query` equals SHOW CREATE TABLE output: full DDL with engine, ORDER BY, PARTITION BY, TTL, codecs. `CREATE TABLE new AS db.old` copies structure and engine when no engine is given.
   Relevance: `create_table_query` holds the user's own ORDER BY text; this is what backup tools replay.

9. Altinity/clickhouse-backup — https://github.com/Altinity/clickhouse-backup — Apache-2.0 (not checked) — search summary only.
   Finding: stores each table's DDL in a metadata JSON and replays it (with database/table rename mapping). It does not parse the sort key. Issue #297 (https://github.com/AlexAkulov/clickhouse-backup/issues/297): a column named like the table broke replayed DDL.
   Relevance: the industry pattern is "replay DDL text", not "rebuild ORDER BY from a column list". It works only when source and destination column names/types are unchanged. We change types (typed destination), so verbatim replay is not enough.

10. dbt-clickhouse `order_by` — https://docs.getdbt.com/reference/resource-configs/clickhouse-configs and https://clickhouse.com/docs/integrations/dbt/materializations — fetched via search summary.
   Finding: `order_by` is a "tuple of column names or arbitrary expressions", user-supplied string or list, emitted verbatim into `ORDER BY (...)`. Default is `tuple()`.
   Relevance: dbt does not derive the key; the user states it. Confirms expressions are first-class.

11. MergeTree docs, `ORDER BY` — https://clickhouse.com/docs/reference/engines/table-engines/mergetree-family/mergetree — not fetched, search hit only. clickhouse-copier: not checked.

12. Repo facts (read).
   - `normio/connectors/clickhouse.py::get_table_engine_info` returns `(engine, order_by columns)` from `sorting_key` only.
   - `normio/connectors/clickhouse_destination.py` builds `ORDER BY (` + quoted identifiers + `)`, or `tuple()`, and makes key columns non-Nullable (`nullable=col.name not in order_by_set`).
   - So an expression key needs two things: the expression text, and the set of columns it references (for non-Nullable and for the destination type). A normalized column (typed or TEXT) may no longer fit `toDate(ts)` if `ts` becomes String.

### A. Options, recommendation, measure, open questions -> see "Finding 2" at the end.

---

## B. Column semantic type detection (#7)

13. Sherlock, Hulsebos et al., KDD 2019 — https://arxiv.org/abs/1905.10688 — paper — fetched.
   Finding: 78 DBpedia-derived types, about 686,765 columns (VizNet); 1,588 features per column (statistics, character distributions, word and paragraph embeddings); support-weighted F1 0.89.
   Relevance: supervised, trained on whole columns (often many rows); evaluates on single columns without header. Training columns are large; no small-table calibration given in the abstract. Small-table behaviour: not checked.

14. Sato, Zhang et al., VLDB 2020 — https://arxiv.org/abs/1911.06311 — fetched.
   Finding: adds table context (topic model) and structured prediction; support-weighted F1 0.925, macro F1 0.735.
   Relevance: macro F1 well below weighted F1 shows rare types are weak. A per-type validator beats a global threshold for rare types.

15. DoDuo, Suhara et al., SIGMOD 2022 — https://arxiv.org/abs/2104.01785 — fetched.
   Finding: whole-table Transformer, multi-task (types and relations); reaches prior state of the art with 8 tokens per column; gains up to 4.0% (types).
   Relevance: very few values per column can be enough for a pretrained model; we have no such model (and B9: cost). Idea only.

16. Pythagoras, Langenecker et al., LWDA 2023 / EDBT 2024 — https://ceur-ws.org/Vol-3630/LWDA2023-paper13.pdf and https://openproceedings.org/2024/conf/edbt/paper-196.pdf — fetched via search summary only.
   Finding: GNN for numerical columns using table name, neighbour columns, metadata; claims about 22% F1 gain over best prior (EDBT version, not verified by us).
   Relevance: confirms numerical columns are the hard case in the literature: values alone barely identify them; context (name, neighbours) does. Our NUMERIC (name 0.6) is that case.

17. ptype, Ceritli, Williams, Geddes, DMKD 34 (2020) — https://arxiv.org/abs/1911.10081 — fetched via search summary.
   Finding: probabilistic finite-state machines per type; each row is "column type", "missing" or "anomaly"; the type is inferred from all rows; anomalies are flagged, not forced.
   Relevance: the closest to "evidence-based, abstain-capable": missing values (NULL, empty, "n/a") are excluded before counting. We should exclude them from the denominator (we do: `non_null_sample`, `_MIN_VALUE_ONLY_RATIO`).

18. Frictionless Detector — https://framework.frictionlessdata.io/docs/framework/detector.html — MIT (not checked) — fetched.
   Finding: `sample_size` default 100 rows; `field_confidence` default 0.9 (share of values that must match a type, so 9 ints and 1 string = integer); `field_missing_values` default `[""]`; `field_float_numbers` default False.
   Relevance: closest published defaults to ours (0.9 and a sample). The 0.9 there is the match ratio, ours is a combined score. Different meaning; do not compare numbers.

19. Table Schema spec — https://specs.frictionlessdata.io/table-schema/ — fetched.
   Finding: separate types `date` (YYYY-MM-DD), `datetime` (ISO 8601), `time`, `year`, `yearmonth`. Omitted type means string.
   Relevance: the spec has a decision rule by format, not by "all midnight". `year` and `yearmonth` types support precision-preserving partial dates (matches our EDTF rule).

20. Google Sensitive Data Protection likelihood — https://docs.cloud.google.com/sensitive-data-protection/docs/likelihood — fetched.
   Finding: five levels VERY_UNLIKELY to VERY_LIKELY by signal strength: weak signal alone = VERY_UNLIKELY; passing checksum without context = POSSIBLE; strong signals = LIKELY. Default minimum is POSSIBLE.
   Relevance: a published model for "weak evidence is reported with a label, not hidden": the caller sets the floor. Fits "suggest to a human, apply only above a line".

21. Microsoft Presidio — https://presidio.dataprivacystack.org/analyzer/ and /decision_process/ — MIT (not checked) — fetched.
   Finding: each result has a float `score`; pattern recognizers have regex plus validation logic; context words raise a score (example in the docs: phone 0.5 to 0.85 with the word "phone"; credit card 0.3 to 1.0). Page gives no default threshold.
   Relevance: same shape as ours (name 0.55-0.85 plus sample validation). Presidio lets a pattern with a failed checksum be dropped (validation can invalidate). Default `score_threshold`: not checked.

22. AWS Glue classifiers, Google Data Catalog: not checked (no page read).

23. BCP 47 / IANA Language Subtag Registry — https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry — public data — File-Date 2026-09-17, fetched header only.
   Finding: the authoritative list of language, script, region, variant subtags (record format `Type`, `Subtag`, `Description`, `Deprecated`, `Preferred-Value`). RFC 5646 defines well-formed vs valid tags.
   Relevance: an authoritative LANGUAGE validator exists as data: a value validates only if its language subtag is in the registry. Risk: short values (`no`, `it`, `de`, `sv`, `fi`) are also common words/abbreviations, and 2-3 letter codes collide with other columns (country, state). Validity alone is weak evidence for short codes; combined with a name hit it is strong. Whether ISO 639 / CLDR data is already in the repo: not checked.

24. NUMERIC validator — no standard; any numeric string parses. Literature (item 16) treats numeric columns as name/context-driven. A parse test cannot discriminate NUMERIC from IDs, postcodes, years or counts, which is why NUMERIC has no sample validator in `type_detection.py::_SAMPLE_VALIDATORS`. Note NUMERIC drives a typed Decimal column (ADR-020); a wrong guess turns text like `0150` into a number and loses leading zeros. This is a real harm, not only a metric loss.

25. Repo facts (read) — `normanalysis/type_detection.py`: `_SAMPLE_VALIDATORS` lists EMAIL, PHONE, DATE, DATETIME, URL, UUID, COUNTRY, CURRENCY, BOOLEAN, MONEY. No LANGUAGE, NUMERIC. Relaxed (substring) name matches carry factor `_RELAXED_CONFIDENCE_FACTOR = 0.6` and must be confirmed by data. Line ~101: name pattern `date|_at|_on` maps to DATETIME at 0.55 (so a `*_on` column with a date-only sample can be typed DATETIME). Only cleanly parsed values count as evidence (repaired ones do not). The DATE/DATETIME tie rule is at about line 290 (not re-read in full).

### B. Options, recommendation, measure, open questions -> see "Finding 7" at the end.

---

## C. Passthrough and key column types (#8)

26. Repo, ADR-020 — `docs/adr/ADR-020-typed-destination.md` — read.
   Says: NUMERIC, MONEY, BOOLEAN typed; "Everything else, key columns included, stays TEXT/String." "Key columns get no companions" (for DATE bounds). Decision #8: a failed value's original string always lands in the cell; no value a typed column cannot hold may reach INSERT.
   The "key columns" sentence is about the 24 semantic types: a column configured with a semantic type (even if it is a key) is TEXT unless NUMERIC/MONEY/BOOLEAN. It does not clearly speak about UNCONFIGURED columns.

27. Repo, code — `normio/connectors/postgres_destination.py::PostgresDestination.create_table` — read.
   A column in `semantic_types` gets `column_overrides` or `SEMANTIC_TYPE_TO_PG_TYPE` or `PASSTHROUGH_PG_TYPE` (TEXT). A column NOT in `semantic_types` gets `col.native_type`. The docstring says so: "Passthrough (unconfigured) columns keep the origin's own native type string as-is — valid DDL here because source and destination are always the same engine (scope decision at the top of the plan)." Primary key is replicated (ADR-017, decision #11).
   Result: code and ADR-020 wording disagree only if ADR-020 is read as covering unconfigured columns. The code's own docstring and ADR-017's "same engine" scope support native types. ADR-013 and ADR-017: no statement about key column type found by grep (ADR-013 mentions `source_row_key` and reversible key paths; ADR-017 mentions replicating PKs and ORDER BY). `docs/benchmarks/REPORT.md`: passthrough columns are compared by multiset hash against the source (lines ~574, ~676) and reported "equal", which only works if passthrough values round-trip unchanged. That is evidence for native types (a TEXT cast of `bigint` would still hash equal as text, so it is not decisive: not checked).
   Where does "TEXT for everything else" come from? ADR-020 Context: the comments in both destination connectors still said "every value is TEXT/String", "the state before `storage_types`". So the TEXT rule is older than the typed work; the passthrough code path is the later behaviour.

28. Practice references (no single standard found; none fetched):
   - clickhouse-backup / `CREATE TABLE AS` / dbt seeds replay or copy native types (items 8-10). Same-engine copy tools keep native types.
   - Cross-engine tools (pgloader, Airbyte, Fivetran) map types because engines differ; not checked here, and not relevant while source = destination engine.
   - Entity-resolution engines and downstream joins: not checked.

29. Risks (reasoned, not measured):
   - Keep native: joins on keys downstream keep working with the source's own types and PK/ORDER BY semantics stay identical; same-engine DDL is valid; no cast step, no cast failures; cost: the destination is "typed" in an inconsistent way (some columns native, some TEXT), and a native-typed key column that is ALSO configured (e.g. a bigint column configured as NUMERIC) changes type through the typed rules. Failure mode: a native type our code does not know (ClickHouse `LowCardinality(Nullable(String))`, `Array`, enum, Postgres domain/array/composite) is copied verbatim into DDL; ClickHouse non-Nullable key rule in `clickhouse_destination.py` strips `Nullable`.
   - Force TEXT: uniform, predictable, matches ADR-020 text; but a `bigint` PK becomes TEXT: sort order changes (`'10' < '9'`), joins to source-typed tables need a cast, PK index size grows, ClickHouse ORDER BY on a String sorts differently (and makes range pruning on numeric predicates useless); and a lossless back-cast is not guaranteed for exotic types (arrays, timestamps with zones).
   - Rule of "never invent, never lose": native passthrough preserves values exactly by construction; TEXT preserves the string form only.

### C. Options, recommendation, measure, open questions -> see "Finding 8" at the end.

---

## D. Throughput under concurrency (#9)

30. AnyIO threads — https://anyio.readthedocs.io/en/stable/threads.html — MIT (not checked) — fetched.
   Finding: default worker-thread limiter is 40 tokens; `to_thread.current_default_thread_limiter().total_tokens` can change it.
   Relevance: Starlette runs a plain `def` route through this. At 16 users there are at most 16 threads in use: the limit (40) is not the cause.

31. Python free-threading how-to — https://docs.python.org/3/howto/free-threading-python.html — PSF — fetched.
   Finding: since 3.13 a build without the GIL exists; overhead on pyperformance "about 1% on macOS aarch64 to 8% on x86-64 Linux"; C extensions not marked as safe re-enable the GIL (with a warning); `sys._is_gil_enabled()` tells the state.
   Relevance: free-threaded Python would let threads use many cores but needs every compiled dependency to be compatible.

32. PEP 779 (supported free-threaded build) — https://peps.python.org/pep-0779/ — public domain/CC0 (not checked) — fetched.
   Finding: sets phase II (officially supported) for Python 3.14; hard target 15% single-thread overhead and 20% memory; status Final, 2025-06-16.
   Relevance: 3.14t is "supported" but optional; our image is `python:3.12-slim-bookworm` (`packages/normapi/Dockerfile`), so it is not an option without a Python upgrade. Compatibility of our dependencies (pyarrow, pydantic-core, orjson, regex, etc.): not checked.

33. FastAPI server workers — https://fastapi.tiangolo.com/deployment/server-workers/ — MIT — fetched.
   Finding: `--workers N` starts N processes to use multiple cores; on Kubernetes, prefer one process per container and scale by replicas.
   Relevance: our Dockerfile runs ONE uvicorn process: `CMD ["uvicorn", "normapi.main:app", ... "--no-proxy-headers"]`; no `--workers`. Confirmed by reading `packages/normapi/Dockerfile`. (compose.yaml: grep found no uvicorn/workers option; not read in full.)

34. Uvicorn deployment — https://uvicorn.dev/deployment/ — BSD-3 (not checked) — fetched.
   Finding: `--workers` spawns (not forks) worker processes; `--reload` and `--workers` are exclusive; Gunicorn with workers is possible via the separate `uvicorn-worker` package (`uvicorn.workers` is deprecated). Page gives no worker-count formula; examples use 4.
   Relevance: the cheapest scale-out is `--workers`, but note that our process holds in-memory state in `app.state` (dispatcher, caches, clone job store?). Per-process state with N workers may break (a job started in worker A is not visible in worker B): check before using. Not checked in code.

35. GIL behaviour, Beazley "Understanding the Python GIL" — not fetched; do not cite numbers. General statement (from the Python docs, not fetched here): only one thread runs Python bytecode at a time, so CPU-bound threads give no parallel speed-up; with N busy threads they contend for the lock.

36. Repo facts (read) — `normapi/routes.py::preview` is a plain `def` that loops `dispatcher.normalize(...)` over `body.values` with `SCAFFOLD_PROFILE` and returns a `list[NormalizedValue]` (response-model validation by pydantic runs on the event-loop thread after the threadpool returns, in current FastAPI; not checked). `/field-test` does the same for one value. The dispatcher is shared (`app.state.dispatcher`). Whether the dispatcher or normalizers take a lock, hit a cache with a lock, call libpostal over HTTP, or touch a DB: not checked.

37. What could explain 340 -> 74 req/s with p99 about 1 s (hypotheses, none measured):
   a. **GIL plus one core.** One process, CPU-bound: ideal throughput is flat at about the 1-user figure (340), not lower. A drop to about 22% of it means extra loss beyond "no scaling".
   b. **Thread contention overhead.** Many threads fighting for the GIL add switching cost, and the event-loop thread (serialisation, routing, pydantic) competes with the 16 workers for the same lock; the loop thread gets the GIL only at switch intervals, so latency rises. Plausible; magnitude unknown.
   c. **A lock or shared structure** inside the dispatcher/cache/regex machinery (threading.Lock, `functools.lru_cache`, SQLite connection, dictionary reload) serialising or thrashing under load.
   d. **Load generator on the same machine** taking CPU, or a CPU/cgroup limit on the container (CPU quota throttling shows as periodic stalls). Compose CPU limit: not checked.
   e. **Per-request cost proportional to `len(values)`:** if the benchmark's batch size is larger at 16 users, req/s drops (not suspected, check the load script).
   Latency check: Little's law, 16 users / 74 req/s = about 216 ms mean latency, and the 1 s p99 means a long tail, which fits queueing behind the GIL or a lock (arithmetic only).

38. What to measure: (see "Finding 9").

---

# Findings: options, recommendation, measure, open questions

## Finding 2: ClickHouse sort key (parenthesised, tuple, expression)

**Options**
- 2a. **Take the key expression text verbatim from the engine, split by the server's parser.** Use `create_table_query` (or `sorting_key` wrapped in `SELECT`) and let ClickHouse split top-level elements, e.g. via a query that parses `ORDER BY` text (`EXPLAIN AST` / `formatQuery`: not tested). Pros: handles `(id)`, `(a, b)`, `toDate(ts)`, `cityHash64(x)`, `tuple()` by one rule; independent of format changes. Cons: needs a version floor (formatQuery 23.10+); the expression references source columns, so a typed or renamed column can break it. Risk: our DDL becomes code from a stored string (injection is low: source is the user's own DB, but check B-rules on identifier validation).
- 2b. **Keep a column-name list but strip one outer pair of parentheses and split on top-level commas (a small tokenizer that respects backquotes, quotes and nested parentheses).** Pros: no SQL round trip, works for 24.x and 26.x. Cons: for an expression you still do not get column names; you must decide what to do (see 2c). Risk: hand-rolled parser; correct handling of quotes/escapes needs tests.
- 2c. **Decide per element: bare identifier (or quoted) -> copy to ORDER BY as today; anything else (expression) -> do not guess: use `tuple()` and report status "sort key not replicated: expression".** Pros: honours "never guess", no wrong DDL. Cons: destination loses its physical sort order and primary-key skipping for these tables, so reads are slower (not measured), which may matter for `ReplacingMergeTree` dedupe (the ORDER BY is the dedupe key!). That is a data-semantics risk: with `tuple()`, `ReplacingMergeTree` never merges duplicates correctly. So for Replacing/Summing/Collapsing engines 2c alone is unsafe.
- Use `system.columns.is_in_sorting_key` as a cross-check: every column found in the parsed key must exist in the table, and the set should equal the flagged columns when the key has only bare names.

**Recommendation:** 2b + 2c now, 2a later. Parse the text with a top-level-comma tokenizer after removing one wrapping pair of parentheses; a bare or backquoted identifier that is a real column is used; an expression key is replicated verbatim ONLY when every column it references stays at its source type in the destination (checked by identifier scan against `is_in_sorting_key` columns), else fail the table with a clear message (J11) rather than silently use `tuple()`. Never fall back to `tuple()` silently for Replacing/Summing/Collapsing/Aggregating engines. Add a test with the three shapes `(id)`, `(a, b)`, `(toDate(ts), id)` and `tuple()` that fails first (L3). This is general (no list of functions).

**What to measure**
- `SELECT version(), sorting_key FROM system.tables` for tables with `ORDER BY id`, `ORDER BY (id)`, `ORDER BY (a, b)`, `ORDER BY (toDate(ts), id)`, `ORDER BY tuple()`, `ORDER BY a DESC` on 24.9 and on the 26.x image: record the exact strings (this confirms or refutes the "26.8 gives `(id)`" claim and shows whether DESC is shown).
- Compare with `create_table_query`.
- Test `formatQuery` and `EXPLAIN AST` on 24.9 for splitting.
- Check which engine families the benchmark's CH tables use.

**Open questions for the owner**
1. Fail the table, or fall back to `tuple()` with a warning, when the key is an expression we cannot replicate? (Recommend fail for Replacing/Summing/Collapsing; owner may allow `tuple()` for plain MergeTree.)
2. Minimum supported ClickHouse version (decides whether `formatQuery` is allowed)? Recommend 24.x floor as today.
3. Should a typed (changed) column inside an expression be a hard error?
4. DESC keys: `sorting_key` hides direction (item 3); replicate from `create_table_query` or refuse?

## Finding 7: autodetect on small tables

**Options**
- 7a. **Keep the 0.9 apply line; add real validators for LANGUAGE and NUMERIC-like types where an authoritative source exists.** LANGUAGE: validate against the IANA subtag registry (item 23) (or CLDR if already a dependency, not checked); count only values that are well-formed AND in the registry. Pros: general, authoritative, in line with C2. Cons: short codes collide with words/other codes; needs name hit anyway (so it stays "name + data confirms"). NUMERIC: a parse test cannot discriminate, so no validator; and a wrong NUMERIC type damages data (leading zeros, IDs).
- 7b. **Two lines: "suggest" (shown to a human, e.g. >= 0.6) and "apply" (>= 0.9, clone applies automatically).** Pros: this is what Google DLP (default min POSSIBLE, item 20) and Presidio (scores plus caller threshold) do; weak evidence is visible, not applied. Cons: UI/API work; clone must keep ignoring suggestions below the apply line. Already close to current state (suggestion exists; apply line = 0.9). The gap is only that the suggestion list is not rich.
- 7c. **Small-table rule: a minimum number of non-null sample values before value evidence counts, and a Wilson/Bayesian lower bound instead of a raw 60% ratio.** With 3 values, "3 of 3 match" is weak evidence; a lower bound makes the confidence rise with sample size. Pros: principled, fixes both over-typing (one date column typed DATETIME on few rows) and the opposite, with no tuning to one benchmark. Cons: a new statistic to document; the numeric choice of the bound's confidence level is a free parameter (owner decision, not copied from any paper). Published defaults for comparison: Frictionless uses first 100 rows and 0.9 match share (item 18), ptype uses all rows with a probabilistic model (item 17).
- 7d. **DATE vs DATETIME rule:** type DATETIME only if at least one value has a time part that parses cleanly; a column whose values are all date-only (no `T`/time) is DATE (or stays untyped if mixed). Do NOT use "all 00:00:00" as the evidence to downgrade a stated DATETIME: `2020-05-01 00:00:00` states a time; changing it to a date would drop stated precision (against "precision preserved"). Instead choose the type from the SOURCE column's own native type when available (a `date` column is DATE; `timestamp` is DATETIME) and use value format only when the source is text. Frictionless distinguishes by format (item 19). Verify: the DATETIME-for-date case may come from the `_on|_at` name pattern at 0.55 plus relaxed ties (line ~101, ~290).

**Recommendation:** 7d first (source native type is the strongest, authoritative signal and it is cheap), then 7a for LANGUAGE (registry validator, name must also match), 7c for small samples; keep 0.9 as the apply line and never infer FREE_TEXT or NUMERIC from values alone. For NUMERIC leave untyped unless a human configures it: an unconfigured column that is already numeric in the source keeps its native type anyway (see Finding 8), so "untyped" is not a loss. Abstain beats a low-confidence apply: no studied tool applies below its threshold unattended; they expose the weak result to a human (items 20, 21).

**What to measure**
- Per detected type: precision and recall on columns whose source type is known (use native types as ground truth where a text column holds a known type), as a function of sample size N (1, 3, 10, 30, 100, 1000), over all benchmark databases, reported as measured, not tuned.
- Count of columns with name hit but no value evidence by type (the 12 of 19).
- For LANGUAGE: how many values in real LANGUAGE columns are in the registry, and how many non-language short columns (country, state) also pass.
- List every column typed DATETIME whose values are all date-only.

**Open questions for the owner**
1. Is the source's native type (date vs timestamp) allowed as evidence for DATE/DATETIME? (Recommend yes: it is the source's own statement.)
2. Should there be a "suggest" tier visible in the UI below 0.9 (7b)?
3. Minimum non-null sample size before value evidence counts?
4. Language registry or CLDR (whichever the repo already carries)? Accept the collision risk for 2-3 letter codes, only with a name hit?
5. May NUMERIC ever be applied automatically?

## Finding 8: unconfigured and key columns, native type or TEXT

**Options**
- 8a. **Native type for unconfigured columns (keys included); fix ADR-020's wording.** Pros: matches code, ADR-017 (same engine) and the docstring, keeps DDL valid on the same engine, joins and sorting identical to the source, PK/ORDER BY semantics preserved, no cast failures. Cons: destination columns are not uniformly TEXT; any exotic native type is copied verbatim (needs a test for each engine's unusual types).
- 8b. **Force TEXT/String for everything except the typed set (code follows the ADR).** Pros: uniform; matches ADR-020 literally. Cons: changes behaviour that benchmark comparisons rely on; key sort order and joins change (`'10' < '9'`); PK/ORDER BY on strings; casting back is lossy for arrays and some timestamp types; large work in `create_table` for both engines and in the insert path (values must be converted to text); breaks the "multiset hash over passthrough columns equals source" check only if hash is typed (not checked).
- 8c. **Native for keys (PK, ORDER BY) and for unconfigured columns; TEXT only for columns that carry a semantic type.** This IS the current behaviour, stated as a rule. Pros: no code change; one clear sentence. Cons: same as 8a. It is 8a with the rule written down.

**Recommendation:** 8a/8c (change the ADR, not the code). Reason: the code and its docstring give a reason (same-engine scope, ADR-017) and the verified benchmark rows use it; forcing TEXT adds risk with no data-quality gain, since an unconfigured column is not normalized at all. An exception to record: a key column that IS configured with a semantic type becomes TEXT (or NUMERIC/MONEY/BOOLEAN) per ADR-020, and then the replicated PRIMARY KEY/ORDER BY points at a changed type; say so in the ADR (decision for the owner). Record the decision with the owner's words (F4).

**What to measure**
- `grep` every place where `native_type` flows into DDL (both destinations) and list the types in the benchmark sources (distinct `native_type` values) to see how exotic they are.
- Run a clone of a table with a configured key column (configured as text type) and check the PK/ORDER BY in the destination (`\d` / `SHOW CREATE TABLE`).
- Confirm with the owner's ER/downstream users whether they join on keys as integers.

**Open questions for the owner**
1. Is "unconfigured columns keep their native type" the intended rule (then amend ADR-020), or should the code force TEXT (then it is a larger change)?
2. What should happen when a configured column is also the PK or in the ORDER BY: allowed (changes key type), blocked, or keep native?
3. Do downstream consumers (ER engine, joins) expect typed keys?

## Finding 9: `/preview` throughput falls from 340 to 74 req/s at 16 users

**Options**
- 9a. **Measure first, no code change.** py-spy and per-request CPU time (below). Pros: cheap, finds the real cause (lock vs GIL vs host). Cons: delays a fix.
- 9b. **Multiple processes: `uvicorn --workers N` (N <= cores) or one container replica per core behind a proxy.** Pros: the standard answer for CPU-bound Python (FastAPI docs, item 33; Uvicorn, item 34): scales near-linearly in cores for stateless endpoints. Cons: per-process memory (the engine loads dictionaries; N copies); `app.state` is per process, so clone jobs, stores and caches must not rely on shared memory (not checked); on Kubernetes the docs prefer replicas to workers.
- 9c. **Offload to a `ProcessPoolExecutor`.** Pros: parallel in one container, keeps the API process single. Cons: pickle cost per call, a pool of workers each loading the dispatcher (the clone executor already has one: `clone_executor._WORKER_COUNT`, default 3, capped by CPU count); for `/preview` (tiny CPU per request) pickling may cost more than it saves. Not measured.
- 9d. **Batch.** `/preview` already takes `values: list`; a client sending many values per request amortises the per-request overhead. Pros: no server change. Cons: client change; does not fix single-value `/field-test`.
- 9e. **Free-threaded CPython 3.14t.** Supported status since 3.14 (PEP 779) with about 10% overhead and an unmeasured effect here; the image is 3.12 and C-extension compatibility is not checked. Not recommended now.
- 9f. **Raise the anyio limiter above 40.** Useless at 16 users (item 30).

**Recommendation:** 9a first, because 340 -> 74 is worse than GIL theory predicts (pure GIL contention should flatten near 340, not fall 4.6x) and the cause could be a lock, CPU throttling or the load generator, which no scale-out fixes. If py-spy shows CPU in pure Python with no lock: 9b with 2-4 workers. Do not add workers before checking that nothing in `app.state` must be shared (clone job manager, stores).

**What to measure**
- `py-spy dump` (several samples) and `py-spy record --gil` during the 16-user run: shows who holds the GIL, which frames wait on locks.
- Per-request CPU time (`time.process_time()` or `resource.getrusage` delta) inside the handler, and wall time: wall >> CPU means waiting (lock/queue), wall ~ CPU means pure compute.
- Container limits: `docker stats`, cgroup `cpu.stat` (`nr_throttled`), `nproc` inside the container.
- Event-loop lag (a 10 ms ticking task) to see whether the loop thread is starved.
- Same test with `--workers 2` and `--workers 4` (temporary, hand-run outside the repo files, but B10 says a committed file for any environment change) and with load generator on another host.
- Throughput vs `len(values)` at 1 and 16 users.
- Check that the 1-user figure of 340 req/s used the same payload as 74.

**Open questions for the owner**
1. Is the load generator on the same host as the API? What was the container CPU limit?
2. Is `/preview` expected to serve many concurrent users in production, or is this a diagnostic tool (decides if 9b is worth the state-sharing risk)?
3. Are multiple API processes allowed (clone jobs and stores live in `app.state`?), or must scale come from replicas?
4. Target numbers (req/s, p99) to design against?
