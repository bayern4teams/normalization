# Adaptive, Bounded-Memory Processing at 1B Rows on One 16 GB Laptop: Verified Resource List

**Scope:** engines, self-adapting resource control, source-side pushdown, bounded-memory dedup and cache, large Postgres queues, and checkpoint/progress. It extends (does not repeat) `_raw-pipeline-engineering.md`. Date of research: 2026-11-07. Free sources only.

**How facts were checked.** "Release" data for GitHub/PyPI/crates.io projects came from their public APIs on 2026-11-07 (marked **[api]**). Doc claims were read through a fetch-and-summarize tool, not raw pages (marked **[doc]**). Anything marked **not checked** was not verified. No benchmark numbers are given unless the source states them. Licence marks: **[BSL]** source-available, **[GPL]** copyleft (needs an owner decision), **[LGPL]**.

**Laptop state measured while researching (`free -g`, `df -h /home`):** 15 GiB total, 8 used, 6 available, 4 buff/cache. `/home` 148 GB, 22 GB free (85% used). So "16 GB" is really about 6 GB available at one moment, with the owner's other programs running. This drives the whole design: the budget must be read at run time, not set once.

**Repo facts used (read, not changed):** `clone_executor.py` uses a `ProcessPoolExecutor` with `_WORKER_COUNT` (fixed) and constants `SOURCE_READ_BATCH_ROWS`, `DESTINATION_INSERT_CHUNK_ROWS` (fixed); checkpoints are per table, committed with the destination chunk (ADR-018). ADR-016 chose single-node Polars+DuckDB+Arrow and rejected Spark/Ray, with the stated trigger "re-evaluated at M8 benchmark gate". FINAL_REPORT §5.6: `migrate_sources` loads the whole queue (1,914,572 rows) at start-up; measured about 113 MB/s growth, OOM-killed at t+27 s under `MemoryMax=3G`; option 1 (SQL pre-filter plus server-side cursor) is the recommended fix, owner decision pending.

---

## 1. Engines for 1B rows on one 16 GB machine

### 1.1 Apache Spark (local mode, PySpark, Spark Connect)
- URL: https://spark.apache.org/docs/latest/spark-connect-overview.html ; https://spark.apache.org/docs/latest/api/python/tutorial/sql/arrow_pandas.html
- Licence: Apache-2.0. Release: Spark v4.3.0 (git tag), pyspark 4.3.0 on PyPI, 2026-10-30 **[api]**. Maintenance: very active (pushed 2026-11-07, 750 open issues in the repo counter), no PyPI advisories listed **[api]**.
- Finding **[doc]**: `SparkSession.builder.remote("local[*]")` starts an in-process Connect server per Python process (startup cost each run); a persistent server is possible but `SPARK_LOCAL_CONNECT_REUSE` is called experimental. The server is JVM-based. Python UDFs: Arrow-optimized UDFs are the default since Spark 4.2, but they are still row-at-a-time functions with Arrow only for transfer; pandas UDFs run per batch; `maxRecordsPerBatch` defaults to 10,000 and the docs say large batches raise JVM memory use. Grouped pandas UDFs load a whole group into memory. The page gives no per-row cost numbers (not checked).
- Relevance: Spark can spill and can read JDBC in parallel, but this project's cost is the Python normalizers and the libpostal call, not the shuffle. Spark would add a JVM (memory floor not measured here, not checked), a second process boundary for every value, and a second runtime to pin for `env_id` (ADR-014). It does not solve the actual bottleneck. Consistent with ADR-016.

### 1.2 Kafka and Redpanda
- URL: https://kafka.apache.org/intro ; https://github.com/apache/kafka ; https://github.com/redpanda-data/redpanda
- Licence: Kafka Apache-2.0. Redpanda Community Edition is BSL 1.1 **[BSL]** (GitHub API returned no licence field; BSL stated by vendor-comparison pages in search results, not checked against the licence file). Release: Redpanda v26.2.2, 2026-08-22 **[api]**. Kafka: the releases API returned nothing, latest tag not determined (not checked). Python clients: kafka-python 3.0.13 (2026-11-06), aiokafka 0.15.0 (2026-10-28) **[api]**.
- Finding **[doc]**: Kafka is an event-streaming platform: publish/subscribe, durable retention, processing as events occur. The intro page describes Kafka Connect for continuous change capture from tables; it says nothing about one-shot batch DB-to-DB copies. A third-party single-node benchmark (4 vCPU, 8 GB; Kafka 4.2.0 about 1.2 GB RSS with default 2 GB heap, Redpanda about 3x or more) appeared in a search summary; I did not open it (not checked).
- Relevance: a log helps when many independent consumers need the same ordered event stream, or for change capture (CDC). This project reads a bounded table once, per key range, with its own checkpoint. A broker adds memory (about 1+ GB), disk (retention of 1B rows), and a second place for state, and the laptop has 22 GB free disk. Verdict: not relevant to the batch path. It may become relevant only if a later CDC/incremental feature is built (then Debezium+Kafka is the standard route; not researched here).

### 1.3 Ray
- URL: https://docs.ray.io/en/latest/ray-core/scheduling/ray-oom-prevention.html ; https://github.com/ray-project/ray
- Licence: Apache-2.0. Release: ray 2.60.0, 2026-11-04 **[api]**. Maintenance: very active, 3,731 open issues, no PyPI advisories **[api]**.
- Finding **[doc]**: Ray has a memory monitor in the raylet: kills one task/actor process when node memory use passes `RAY_memory_usage_threshold` (default 0.95), checked every 250 ms; killed tasks retry with backoff capped at 60 s, and retry indefinitely unless `max_retries=0`. With cgroup v2 resource isolation it reserves system memory (default 10% of total, bounded 500 MB to 10 GB).
- Relevance: the idea (watch usage, kill the youngest retriable task, retry) is useful as a pattern. Using Ray itself on one laptop adds a raylet, a GCS and an object store (each uses memory; amounts not measured here). Already rejected in ADR-016 for the same reason as Spark. The 0.95 default is too close to the cap for a laptop that has frozen.

### 1.4 Dask / distributed
- URL: https://distributed.dask.org/en/stable/worker-memory.html ; https://github.com/dask/dask
- Licence: BSD-3-Clause. Release: dask and distributed 2026.8.0, 2026-08-24 **[api]**. Maintenance: active (last push 2026-09-29), no PyPI advisories **[api]**.
- Finding **[doc]**: the clearest published ladder of memory thresholds: target 0.60 (spill managed data), spill 0.70 (by process memory, checked every 200 ms), pause 0.80 (stop starting tasks), terminate 0.95 (the nanny kills and restarts the worker, tasks are rescheduled). Spilling applies only to managed data, not interpreter or allocator memory.
- Relevance: copy the ladder, not the library. Pause-before-kill (at 0.80) is exactly "graceful degradation" and is cheap to write in the project's own pool. Dask's pure-Python scheduler overhead per task makes it a poor fit for a few thousand big batches only if tasks are tiny (not measured, not checked).

### 1.5 Polars (new streaming engine, out-of-core)
- URL: https://pola.rs/posts/release-polars-2/ ; https://github.com/pola-rs/polars
- Licence: MIT. Release: py-2.1.0, 2026-10-25; 2.0 released 2026-10-06 per the release post **[api][doc]**. Maintenance: very active, 2,932 open issues **[api]**.
- Finding **[doc]**: in 2.0, `collect()` on a LazyFrame uses the streaming engine by default; spill to disk is on by default, starting at about 80% of RAM, with a default 64 GB disk budget; spill covers sort, window functions and many expressions. The 2.0 post says joins and group-bys were not yet out-of-core. A search summary says 2.1 adds out-of-core group-by and an env var `POLARS_OOC_MEMORY_BUDGET_MB` (not confirmed on a primary page, not checked). Streaming does not keep row order unless `maintain_order=True`.
- Relevance: two warnings for this laptop. (a) The 64 GB default disk budget is bigger than the 22 GB free disk, so it must be set explicitly. (b) The 80% RAM trigger ignores other programs. Use for column work inside a batch; do not rely on it as the system-level guard. Per-value Python UDFs (`map_elements`) run row by row in Python (general knowledge, not checked in this round); keep the project's `normalize_batch` over distinct arrays instead.

### 1.6 DuckDB (out-of-core, spilling)
- URL: https://duckdb.org/docs/2.0/guides/performance/how_to_tune_workloads.html ; https://duckdb.org/2024/07/09/memory-management.html ; https://github.com/duckdb/duckdb
- Licence: MIT. Release: v2.0.0, 2026-10-21 (PyPI duckdb 2.0.0) **[api]**. Maintenance: very active, 1,150 open issues, no PyPI advisories **[api]**.
- Finding **[doc]**: spilling is adaptive: data stays in memory until intermediates pass `memory_limit` (default 80% of physical RAM, per the 2024 post). GROUP BY, JOIN, ORDER BY and window functions can all go larger than memory; limits: several blocking operators in one query can still run out of memory, `string_agg()` cannot offload, sort-based holistic aggregates can fail. `temp_directory` is settable; `preserve_insertion_order=false` lowers memory for big Parquet/CSV import and export. Parallelism is by row group (122,880 rows), so `threads` can be capped. The page gives no GB-per-thread rule. Exact distinct on high-cardinality columns is listed as able to go out-of-core.
- Relevance: the best fit for "distinct values and cache on disk with a hard cap". Set `memory_limit` and `threads` per run from the measured budget (not the 80% default), set `temp_directory` on a disk with known free space, and cap `max_temp_directory_size` (DataFusion documents that setting; the DuckDB page did not, so check it on the DuckDB settings page, not checked).

### 1.7 Apache DataFusion
- URL: https://datafusion.apache.org/user-guide/configs.html ; https://github.com/apache/datafusion
- Licence: Apache-2.0. Release: crate datafusion 55.2.0 (2026-10-07); PyPI `datafusion` 55.0.0 (2026-10-12) **[api]**. Maintenance: very active, 2,441 open issues **[api]**.
- Finding **[doc]**: `datafusion.runtime.memory_limit` (default none), a fair-spill pool that divides memory evenly among partitions, `temp_directory`, `max_temp_directory_size` (default 100G), and the advice to lower `target_partitions` and `batch_size` under tight limits. Python UDF support not covered by that page (not checked).
- Relevance: the memory-pool design (a limit, then fair share per partition, then spill) is the model for a per-column memory budget. As an engine it duplicates DuckDB/Polars (F5: one capability, one implementation). Idea only.

### 1.8 Daft
- URL: https://docs.daft.ai/en/stable/ ; https://github.com/Eventual-Inc/Daft
- Licence: Apache-2.0. Release: v0.7.26, 2026-10-06 (PyPI `daft` 0.7.26; the old name `getdaft` stops at 0.5.0, 2025-08-01) **[api]**. Maintenance: active, 481 open issues **[api]**.
- Finding **[doc]**: Rust engine with a Python API, aimed at multimodal/AI work; docs claim memory management that avoids OOM and local-to-cluster scaling. The home page does not cover spill, runners or batch UDFs (not checked).
- Relevance: no clear gain over Polars+DuckDB for text-normalization UDFs, and one more engine to pin. Skip unless a measurement shows a gap.

### 1.9 Arrow, ADBC, Flight, and plain multiprocessing
- URL: https://github.com/apache/arrow-adbc ; https://arrow.apache.org/docs/format/Columnar.html
- Licence: Apache-2.0. Release: arrow-adbc 25 (2026-10-21), `adbc-driver-postgresql` 1.13.0 (2026-10-26), pyarrow 26.0.1 (2026-11-03) **[api]**.
- Finding: ADBC returns Arrow batches directly from Postgres (and other drivers); useful if the project wants Arrow end to end without row-to-Arrow conversion. Not read in this round (not checked beyond metadata).
- Relevance: the project already uses a `ProcessPoolExecutor`. At this scale the bottleneck is likely the normalizer and libpostal round trips, so keep the pool and make it adaptive (Section 2). Arrow Flight is for network transport between services; both ends here are local libraries, so no gain (reasoning, not measured).

### 1.10 clickhouse-connect streaming
- URL: https://clickhouse.com/docs/integrations/language-clients/python/advanced-querying ; PyPI `clickhouse-connect`.
- Licence: Apache-2.0. Release: 1.12.0, 2026-11-03 **[api]**.
- Finding **[doc]**: `query_arrow_stream`, `query_df_stream` and others return one block at a time inside a context manager; block size follows `max_block_size` and `preferred_block_size_bytes`; if the consumer is slower than the server, raise `http_buffer_size` (default 10 MiB). A dropped connection raises `StreamFailureError`, never a silent partial result.
- Relevance: gives backpressure for free (a slow consumer slows the HTTP read), and the two block-size settings are the knobs for adaptive read size.

---

## 2. Self-adapting resource control

### 2.1 cgroup v2 memory controls
- URL: https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html
- Licence: kernel docs (GPL-2.0 kernel). Maintenance: kernel documentation, current.
- Finding **[doc]**: `memory.high` is a throttle: processes over it are slowed and heavily reclaimed, and "going over the high limit never invokes the OOM killer". `memory.max` is the hard limit: the OOM killer runs inside the cgroup. `memory.events` counts `high`, `max`, `oom`, `oom_kill`. A process may write `memory.high` or `memory.max` (opened with O_NONBLOCK) to change limits at run time. A non-root user can use a cgroup subtree only if the cgroup is delegated to them (write access to the directory and its `cgroup.procs`).
- Relevance: the right shape is two limits: `memory.high` at the budget (the kernel slows the app gently), `memory.max` a little above (last defence). The app can read `memory.current` and `memory.events` (`high` counter rising means "I am over budget, shrink"). This is a measured signal, not a guess.

### 2.2 Pressure Stall Information (PSI)
- URL: https://www.kernel.org/doc/html/latest/accounting/psi.html
- Finding **[doc]**: `/proc/pressure/{cpu,memory,io}` and per-cgroup `memory.pressure` give `some` and `full` lines with avg10/avg60/avg300 and cumulative `total` in microseconds. `full` means all non-idle tasks stalled, the thrashing signal. A trigger is created by writing `<some|full> <stall us> <window us>` and waiting for POLLPRI; windows must be 500 ms to 10 s, and unprivileged users must use a window that is a multiple of 2 s. Kernel needs PSI enabled (Kubernetes docs say 4.20 or newer; the PSI page did not state a minimum).
- Relevance: PSI is the best "is the machine in trouble now" signal because it counts the whole machine, including the browser and IDE. `some` memory avg10 and system-wide `io` pressure are the inputs for a controller. This laptop kernel is Linux 7.1 so PSI should exist; confirm `/proc/pressure/memory` exists on the box (not checked).

### 2.3 systemd resource control, systemd-run, systemd-oomd
- URL: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html ; https://www.freedesktop.org/software/systemd/man/latest/systemd-oomd.service.html ; https://github.com/systemd/systemd
- Licence: systemd is GPL-2.0 (run as a system tool, not a dependency). Release: v262.2, 2026-11-05 **[api]**.
- Finding **[doc]**: `MemoryHigh=` is the primary control and `MemoryMax=` the last line (the page says so). `CPUWeight=` and `IOWeight=` (1 to 10000, default 100) share time between siblings, so the app can run at low weight and the browser keeps priority. `ManagedOOMMemoryPressure=kill` makes a unit a candidate for systemd-oomd, which polls PSI and sends SIGKILL to the cgroup. oomd docs warn: run work under the user manager first, otherwise one hungry task can get the whole session scope killed; swap is strongly recommended. The resource-control page does not document `systemd-run --user --scope` (not checked); the per-user manager needs `Delegate=` for controllers to be available.
- Relevance: a committed unit or wrapper script (B10) that starts the API/worker with `MemoryHigh`, `MemoryMax`, low `CPUWeight`/`IOWeight`, is the outer safety net that cannot be bypassed by an app bug. The app's own controller then works inside that envelope. Do not turn on `ManagedOOMMemoryPressure` for the user slice without the owner (it can kill the browser session, per the oomd page).

### 2.4 earlyoom
- URL: https://github.com/rfjakob/earlyoom
- Licence: MIT. Release: v1.9.0, 2025-09-16 **[doc]**. Maintenance: 599 commits, 22 open issues, last release about 14 months before this research; the page did not say it uses PSI.
- Finding **[doc]**: user-space daemon, polls available memory and free swap up to 10 times a second, sends SIGTERM then SIGKILL under thresholds (default below 10% of both), picks the highest `oom_score` unless `--sort-by-rss`.
- Relevance: a kill-the-biggest tool does not know which process is the app. Prefer cgroup limits so the app is the thing that is limited, and set `oom_score_adj` so the app is chosen before the browser (the Linux feature exists; setting it was not checked here).

### 2.5 AIMD, Vegas, Gradient: adaptive concurrency from TCP
- URL: https://www.cse.wustl.edu/~jain/papers/cong_av.htm (Chiu and Jain, Computer Networks and ISDN 17(1), 1989); https://github.com/Netflix/concurrency-limits
- Licence: paper free; Netflix library Apache-2.0. Release: v0.5.4, 2025-12-08, last push 2026-10-21, 54 open issues **[api]** (the page showed no releases list, API shows tags).
- Finding **[doc]**: Chiu and Jain show additive increase with multiplicative decrease converges to an efficient and fair state from any start. Netflix's library applies TCP ideas to concurrency: Vegas estimates queue length from min RTT versus sample RTT and moves the limit by 1 per window; Gradient2 compares a short and a long exponential average of latency to see a queueing trend and cuts hard on it; AIMD reacts only to failures. README advice: delay-based on servers, loss-based (AIMD) or loss+delay on clients. Java only. Netflix's own blog post could not be fetched (HTTP 403, not checked).
- Relevance: the project is a client of two remote services (source DB, libpostal). The client advice applies: AIMD on in-flight requests, with latency gradient as an extra "slow down" signal. Algorithm is about 30 lines; no need to depend on the Java library.

### 2.6 Python libraries that implement adaptive concurrency or batch size
- `adaptive-concurrency` 0.1.1: https://pypi.org/project/adaptive-concurrency/ . Apache-2.0, released 2026-09-25 (0.1.0 same day), Alpha, one maintainer **[doc]**. Adjusts concurrent batches and items per batch from per-item latency and failures; zero runtime dependencies; thread or asyncio; has a rate limiter, circuit breaker, bisection of failed batches. Author reports slow convergence under noisy latency (median 19 batches at low noise, 126 at high noise, author's benchmark). Relevance: closest existing match for the libpostal and source-read side, but it is 6 weeks old and Alpha, so per D-rule "new dependency needs a yes and a pinned version"; use as a design reference or vendor the idea. Memory is not one of its signals.
- `aiolimiter` 1.3.0 (2026-09-07, MIT) **[api]**: a fixed leaky-bucket rate limiter, not adaptive. Only useful as a hard ceiling.
- `psutil` 7.2.2 (2026-01-28, BSD-3-Clause, no advisories) **[api]**: `virtual_memory().available`, process RSS, `cpu_percent`. Linux only features such as PSI are not in psutil; read the files directly (not checked whether psutil exposes PSI).
- `cgroupspy` 0.2.3 (2024-03-19) **[api]**: stale; reading `/sys/fs/cgroup/.../memory.current` with plain file reads is simpler.
- Search found no mature Python port of Netflix's limits (searched PyPI/GitHub via web search only).

### 2.7 Bounded queues and backpressure as the first line
- No external source needed for the principle (a bounded `queue.Queue(maxsize=n)` blocks producers); here the source is the API behaviour already read: `clickhouse-connect` streams one block at a time and slows the HTTP read when the consumer is slow (1.10), and psycopg server cursors send only requested rows (3.2). Relevance: make every stage hand-off a bounded queue sized in bytes (Arrow `nbytes`), not rows; this alone caps memory regardless of speed.

---

## 3. Using the remote DB machine's power

### 3.1 ClickHouse: pushdown of DISTINCT/GROUP BY, limits that protect the server
- URL: https://clickhouse.com/docs/operations/settings/query-complexity ; https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniq
- Licence: ClickHouse Apache-2.0. Release: v26.10.2.103-stable, 2026-10-24; 8,838 open issues **[api]**.
- Finding **[doc]**: per-query guardrails exist: `max_memory_usage`, `max_rows_to_read`, `max_rows_to_group_by` with `group_by_overflow_mode` (`throw` default, `break` returns a partial result, `any` stops adding keys), `max_execution_time`; limits are checked after each data part, so can be exceeded briefly. A web search summary says `max_bytes_before_external_group_by` should be set below `max_memory_usage` (commonly half) and spills GROUP BY to disk; the official settings page fetched did not list it (not checked on a primary page); the defaults differ between sources, so read `system.settings` on the real server. `uniq` uses adaptive sampling (up to 65,536 hash values); the docs say about 1% error at hundreds of billions with 64-bit hashing and that servers older than 26.8 returned wrong estimates at that scale; `uniqExact`/`uniqHLL12`/`uniqCombined` pages were not read.
- Relevance: `SELECT col, count() FROM t GROUP BY col` run on the source returns only distinct values (the exact set is needed, so use plain GROUP BY, not `uniq`). `uniq` is for the plan (how many distinct values) before choosing a strategy. Pushing a distinct query is not a "parser-driven" pushdown, so ADR-016's "provably safe only" rule is not touched, but the owner should confirm that reading. Cap the load on the shared source with `max_threads`, `max_memory_usage`, `priority`-type settings per query (setting names from search results; `max_threads` and `priority` definitions were not fetched, not checked).

### 3.2 Postgres: server-side cursors, snapshots, keyset paging
- URLs: https://www.psycopg.org/psycopg3/docs/advanced/cursors.html ; https://www.postgresql.org/docs/current/sql-set-transaction.html ; https://www.postgresql.org/docs/current/functions-admin.html ; https://use-the-index-luke.com/no-offset
- Licence: psycopg 3.3.8 (2026-11-04) is LGPL-3.0 **[LGPL][api]** (already used; FINAL_REPORT notes the licence check). PostgreSQL licence: PostgreSQL Licence (permissive; not checked in this round).
- Finding **[doc]**: psycopg `ServerCursor` uses DECLARE/FETCH; the client holds only the requested rows, and the server keeps the partial result (more server memory, more round trips for small queries). `pg_export_snapshot()` plus `SET TRANSACTION SNAPSHOT` in `REPEATABLE READ` lets several sessions read one consistent snapshot; the exporting transaction must stay open until importers start; import must be the first statement. Keyset ("seek") paging avoids OFFSET cost and drifting pages, but needs a unique ordered key and no jumping to arbitrary pages; the article did not discuss indexes.
- Relevance: parallel reads by key range can share one snapshot (consistent clone across workers), and a range read plus keyset resume point is the natural checkpoint. A long-open snapshot transaction holds back VACUUM on a source database (general Postgres behaviour, not in the pages read, not checked): limit its life and tell the owner.

### 3.3 DuckDB as reader of the sources (Postgres scanner)
- URL: https://duckdb.org/2022/09/30/postgres-scanner.html (already in prior research, entry 21). Not re-read. Relevance: another way to read in parallel; skip unless ADBC/psycopg proves slower.

### 3.4 COPY and native formats
- Not researched beyond the clickhouse-connect streaming in 1.10; Postgres `COPY ... TO STDOUT (FORMAT binary)` and `pgcopy` 1.6.2 (MIT, 2025-11-23 **[api]**) exist; whether either beats ADBC/psycopg here was not measured. Not checked.

---

## 4. Dedup and caches at 1B scale with bounded memory

### 4.1 HyperLogLog and HLL++ for planning
- URL: https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/40671.pdf (the EDBT 2013 paper "HyperLogLog in Practice", Heule, Nunkesser and Hall; title and authors are from memory because the fetch returned binary, not checked); implementations: `datasketches` 5.2.0 (Apache-2.0, 2025-03-01, repo pushed 2026-10-11) **[api]**; `axiomhq/hyperloglog` (Go, not Python).
- Finding: an HLL estimate answers "how many distinct values will this column have" in a few KB of memory. It cannot list the values, so it is only a planner input (choose in-memory set versus on-disk path). Both ClickHouse (`uniq`) and DuckDB (`approx_count_distinct`, page was a redirect, not read, not checked) provide it server-side, so the estimate can come from the source without moving data.
- Relevance: use only to choose the strategy and to size progress estimates. Never use an estimate to decide a value's normalization (precision-preserved rule).

### 4.2 External / partitioned hashing and spilling aggregation
- DuckDB (entry 1.6) and ClickHouse (entry 3.1) already do it: DuckDB's hash aggregate spills adaptively past `memory_limit`; ClickHouse spills with `max_bytes_before_external_group_by` (see caveat). Relevance: let the engines do external distinct (`SELECT DISTINCT` / `GROUP BY`) instead of a hand-written partitioned hash in Python (F5).

### 4.3 On-disk caches
- **DuckDB table or Parquet cache** (already ADR-016's choice): good for bulk lookups by join; weak at single-key point lookups from Python (general knowledge, not measured).
- **SQLite**: https://www.sqlite.org/limits.html **[doc]**: max database about 17.5 TB at the default 4 KB page, up to 281 TB at 64 KB pages (the page says the larger figure is untested and the filesystem limit is lower); 2^64 rows theoretical; billions of rows is within range. Public domain, in the standard library. Good point-lookup cache keyed by `(type, value-hash, version)` with `WITHOUT ROWID`; single writer, so batch writes.
- **LMDB (py-lmdb)**: https://github.com/jnwatson/py-lmdb ; PyPI `lmdb` 3.0.0, 2026-10-02, licence OLDAP-2.8 (OpenLDAP public licence, permissive, check with owner) **[api]**; repo shows 2 open issues, active. Fast reads, one writer, needs a fixed `map_size`; the page did not cover this (not checked). The 0.9 and 1.x on-disk formats are mutually unreadable per the page.
- **RocksDB**: https://github.com/facebook/rocksdb tag v11.13.2 **[api]**; Python bindings not evaluated (`rocksdict` not found on PyPI by name, not checked). Skip: heavier than needed.
- **diskcache** 5.6.3 (2023-08-31) and **sqlitedict** 2.1.0 (2022-12-03) both show 2 PyPI vulnerability entries **[api]** (IDs not retrieved, not checked) and no release in 2+ years: avoid.
- Relevance: SQLite is the smallest choice that meets "bounded memory, on disk, billions of keys, no new dependency". Hash the key (already in ADR-016: blake3 of raw value, never raw value in a key).

### 4.4 Cache keyed by (type, value, version)
- Already decided in ADR-016. Addition from this research: cap the cache by bytes, drop entries oldest-version-first, and size it from free disk at start (22 GB free now, disk is also needed for spill).

---

## 5. Large queues and metadata in Postgres without loading into RAM (the §5.6 problem)

### 5.1 Server-side cursor, SQL pre-filter, keyset paging
- Sources: psycopg cursor page (3.2), use-the-index-luke (3.2), FINAL_REPORT §5.6.
- Finding: the root cause is a whole-table load at start-up; all tools to fix it were already read: named cursor with `fetchmany`, a SQL `WHERE` that returns only rows still needing migration, or keyset batches by primary key. FINAL_REPORT already measured 0 of 1,914,572 rows need migration.
- Relevance: general rule for every queue read in the API: no unbounded `SELECT`, every list endpoint pages by keyset on an indexed key, and the count shown in the UI comes from a bounded or approximate count. Add a test that fails if any query path loads more than N rows into memory (K4: a machine check). Partitioning the queue table (Postgres declarative partitioning, docs not fetched, not checked) helps pruning and cheap deletes of finished jobs, but does not remove the need to page.

---

## 6. Checkpointing/resume at scale, and progress estimation

### 6.1 Checkpoint design
- Source: the repo's ADR-018 as read in `clone_executor.py` (checkpoint committed in the same transaction as the destination chunk; ClickHouse resume re-reads from the last block boundary, `_resume_point`). No new external source reviewed for this in this round (not checked).
- Relevance: at 1B rows the checkpoint must be per key range (not one per table), small, and independent of the number of workers, so the worker count can change between runs. Keyset paging (3.2) gives the resume key. The snapshot caveat applies: a resumed run after a crash cannot import the old exported snapshot (it ended with the transaction), so resume either accepts a new snapshot (document the semantics) or reads the source as of the checkpoint key only. This is an owner decision.

### 6.2 Progress and ETA
- Source: `adaptive-concurrency` reports per-item latency (2.6) but there is no source read here on ETA algorithms (not checked).
- Relevance: with the HLL/`count()` estimate of rows per table (3.1) and a smoothed throughput (exponential average), ETA is rows left divided by recent rate. Show it as a range, never a single number, because rate changes whenever the controller slows down.

---

## Candidate options for this project

**Option A: Keep the single node; add a resource governor (recommended).**
Outer envelope: a committed systemd unit or wrapper (B10) with `MemoryHigh` at the budget, `MemoryMax` slightly above, low `CPUWeight`/`IOWeight`. Inner control loop in the app: read `memory.current`, `memory.events` (`high` counter), PSI `memory some avg10`, `io some avg10`, and `psutil` available memory; AIMD on worker count and on batch bytes (increase by one step when calm for N seconds, halve on any pressure signal, pause new batches at about 0.80 of budget as in the Dask ladder, never go below one worker). Bounded byte-sized queues between stages. DuckDB/Polars given explicit `memory_limit`/`threads`/spill path/disk cap. Source pushdown of `GROUP BY` for distinct values (3.1). SQLite/DuckDB cache capped by bytes. Fix §5.6 with SQL pre-filter plus server cursor.
- Pros: no new runtime, no new service; consistent with ADR-016 and ADR-017; each piece is small and testable; protects the laptop even if the app has a bug (outer limit).
- Cons: you write and tune a controller; PSI and cgroup access need a delegated user cgroup or a systemd unit; more states to test.
- Risks: oscillation if the increase step is too fast; PSI is system-wide, so a browser spike slows the app (acceptable, that is the goal); cgroup files differ if the box is not cgroup v2 (check `stat -fc %T /sys/fs/cgroup`, not checked).
- Measure: peak RSS and `memory.events high` count over a 50M-row run; throughput versus worker count curve; time to recover after a forced 4 GB memory hog; behaviour with libpostal latency raised artificially.

**Option B: Option A plus push distinct-extraction fully to the source.**
First pass: `GROUP BY` (value, count) per column on ClickHouse/Postgres with per-query limits; normalize only distinct values; second pass streams rows only to join back and write.
- Pros: moves the heaviest dedup to the remote machine; local memory depends on distinct count, not rows; lower LAN traffic for repeated values.
- Cons: Postgres `GROUP BY` on very large tables can use a lot of temp space on the source (not measured); the second pass still reads all 1B rows; two passes mean a second snapshot problem.
- Risks: extra load on a shared source; high-cardinality columns (IDs, free text) gain nothing; the owner must accept that distinct queries are in scope of "pushdown only when provably safe".
- Measure: distinct-ratio per column (`uniq`) across real tables; source CPU, temp-file use and query time under `max_threads` caps.

**Option C: Add Polars 2.x streaming for the column stage.**
Replace ad-hoc per-batch Python steps with LazyFrame plans that stream and spill.
- Pros: less hand-written batching; spill is on by default.
- Cons: Polars 2.0 is 1 month old; joins and group-by spill was new in 2.1 (2.0 had none); default 64 GB disk budget and 80% RAM trigger must be overridden.
- Risks: row-order changes by default; behaviour changes between 2.x releases; the Python normalizers still run per distinct value outside Polars.
- Measure: peak memory on joins back of distinct results with 100M rows; spill volume versus free disk.

**Option D: Spark local mode or Ray.**
- Pros: mature spill, shuffle and scheduling; Spark has JDBC parallel reads and Arrow UDFs.
- Cons: JVM/raylet memory on a 6 GB-available laptop; UDF boundary costs; second runtime in `env_id`; conflicts with ADR-016; does not address libpostal or remote-DB limits.
- Risks: heavier freezes, not lighter; weeks of work for no measured gain.
- Measure (only if the owner still wants it): a 10M-row slice on both engines with the same normalizer, recording peak RSS and rows per second.

**Option E: Kafka or Redpanda between read and normalize.**
- Pros: decouples stages; durable replay.
- Cons: broker memory and disk (22 GB free disk is not enough to hold 1B rows of retention without care); no benefit for a one-shot bounded read.
- Risks: a second durable state to keep consistent with the checkpoint.
- Measure: not recommended to measure now; revisit only if CDC (continuous sync) is added.

## Open questions for the owner

1. What is the real memory budget? Fixed cap (for example 6 GB), or "a share of what is free, never below X"? Recommend: budget = min(fixed cap, 60% of available memory at start), re-read every few seconds.
2. May the app run under a committed systemd user unit (or wrapper) with `MemoryHigh`/`MemoryMax`? Needed for Option A's safety net. Recommend yes.
3. May the app read `/proc/pressure/*` and cgroup files (Linux only)? What happens on a non-Linux machine: fall back to `psutil` only? Recommend Linux-first with `psutil` fallback.
4. Is a distinct-value `GROUP BY` on the source acceptable under ADR-016 ("pushdown only when provably safe")? Recommend yes, with per-query limits, since it changes no value.
5. How much load may the app put on the shared source and libpostal machines (cores, concurrent queries)? Can a ClickHouse settings profile or Postgres role with `statement_timeout` be created for the app?
6. Snapshot semantics for resume: one consistent snapshot per run (long transaction on source), or per-range reads with key-based resume and accepted drift?
7. Is the 1B-row source a single Postgres, a single ClickHouse, or both? Rough row width and distinct ratio of the biggest columns? (Not known; all sizing here depends on it.)
8. Disk: how much of the 22 GB may spill and cache use, and on which disk? Polars' default 64 GB budget would exceed it.
9. Is a new dependency acceptable (for example pinning `adaptive-concurrency` 0.1.1 Alpha), or write the AIMD loop in-house (about 30 lines)? Recommend in-house.
10. Is CDC/incremental sync a future requirement? Only then does Kafka become relevant.

## Not verified (summary)
Netflix blog (403); DuckDB `max_temp_directory_size`, `approx_count_distinct` and `memory_limit` page text beyond the 2024 post; ClickHouse `max_threads`/`priority`/`max_bytes_before_external_group_by` on primary pages; Kafka latest release; Redpanda licence file; Polars 2.1 out-of-core group-by and the `POLARS_OOC_MEMORY_BUDGET_MB` variable (search summary only); HLL++ paper text; psutil PSI support; Python UDF cost per engine; `systemd-run --user --scope` docs; presence of PSI and cgroup v2 on the laptop; Postgres partitioning docs; Spark/JVM memory floor.
