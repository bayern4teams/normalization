# Local run guide — the rest of round 2, on the owner's laptop

The cloud routine built D13, D14, D15 and U1 (Phases 0-4) and stopped before Phase 5. This guide is
for **one agent on the laptop** that finishes round 2: it runs the live checks of
[LOCAL_VERIFY.md](LOCAL_VERIFY.md), measures the real-data runs, diagnoses the API start-up memory
problem, and closes Phase 5. Read [STATUS](STATUS), [HANDOFF.md](HANDOFF.md), this file, and
[the plan](../ROUND2_IMPLEMENTATION_PLAN.md) §2-§9, in that order. AGENTS.md is loaded already.

## 1. Owner decisions for this run (2026-10-29)

Recorded with the owner's own words (F4). Each line answers a question in the chat of 2026-10-29.

| # | Decision | Owner's words |
|---|---|---|
| R1 | The routine stops; `autonomy=off` in STATUS | "1. yes" |
| G1 | One agent, Opus. It cannot start subagents, so it also does the verifier's job itself (§5.8) | "a but only is single agent. it could not be able to create sub agents" |
| G2 | Commit and push to `feat/round2-fixes`; never merge | "a" |
| G3 | A fresh job-records database `norm_app_r2_<run>` on 10.10.9.41 for each large job | "a" |
| G3/G4 | Real-data clones go over HTTP to the API started natively on the laptop (§4), not the Docker API | "Native API (Recommended)" |
| G4 | Drive the clones over HTTP, never the in-process test client | "a" |
| G5 | Diffbot in full, ZoomInfo 100k and 1M samples; diagnose why the API still runs out of memory, report it, research a fix | "b. yes we should diagnose why it still going OOM. and report it and then research about it how to fix it." |
| G6 | Real data with a LANGUAGE column for D13; the agent may load or download benchmark datasets it needs; many already live on the benchmark box | "there is alot of other databases in remote also you could tell in guide that agents go and download proper databases for benchmark that you think need but note that alot of databases live on remote" |
| G6 | The D13 source goes into `bench-pg` as a new database | "bench-pg (Recommended)" |
| G7 | D15: second LAN caller from 10.10.9.41; outside caller through a Docker network on `203.0.113.0/24`; two-address host name by unit test only | "a, a, a" |
| G8 | Walk the UI in a browser with local screenshots kept outside the repo; if no browser is available, Playwright with its traces | "a, and if it not available do b" |
| G9 | Install the pinned Vale and lychee into `.tools/`; run zizmor with the owner's `gh` token | "a" |
| G10 | No code for the open owner decisions; list them in FINAL_REPORT as waiting | "a" |
| G11 | This file is the guide; LOCAL_VERIFY.md stays the checklist it fills in | "a" |
| G12 | Every `norm_*` and `bm_round2_*` database stays until the owner has looked; dropping one needs a yes | "a" |
| W1 | Writes go where the approved 2026-10-28 run put them: Diffbot outputs and `norm_app_*` on `diffbot-pg`, ZoomInfo samples and outputs on `zoominfo-ch` | "Same as 10-28 (Recommended)" |

## 2. Hard rules for this run

On top of AGENTS.md. Each one is a stop line: when it would be crossed, stop and ask the owner.

- **One agent, no subagents.** Never call the Agent tool. Skills (`/ponytail-review`, and so on) are fine.
- **Never change `autonomy`** in STATUS, never merge, never push `main`, never force-push.
- **Sources are only read**: `testdiffbot`, `testzoominfo`, everything under `/home/benchmark/data/`
  and `/home/benchmark/suites/`. Every write goes into a **new** database whose name starts with
  `norm_r2_`, `norm_app_r2_` or `bm_round2_`. Never write into an existing database.
- **Leave alone what is not this project's**: Langfuse on the laptop (ports 3000, 9090 on `0.0.0.0`),
  and the `argilla` and `bench-mongo` stacks on the box. Never `docker compose down -v` on the box.
- **Passwords never reach the repo, a command line, a log or the chat.** Read them into shell variables
  (§3.2) and pass them in request bodies built from the environment (§4.2), never as arguments.
- **Memory**: tests in capped batches (AGENTS.md §4); every API process and every clone runs under
  `systemd-run --user --scope -q -p MemoryMax=3G -p MemorySwapMax=0`. The laptop has 15 GB and about
  5 GB free (measured 2026-10-29). An earlier unbounded start froze it twice.
- **No code changes** except: fixes for a check that fails because of round 2 code (D3: a failing test
  first), and the Phase 5 deletions the plan lists. A test change follows plan §2.9 (`TEST-CHANGE:`).
  The open owner decisions (§7) get no code. The memory problem (§5.6) gets a diagnosis and a
  proposal, not a fix.
- **Do not commit** the uncommitted graft 0.26 edits in `.claude/` (owner: "Keep it local"). Stage
  files by name, never `git add -A`.
- **Downloads** (G6) go to the box under `/home/benchmark/data/public/<category>/<dataset>/`, with a
  `SOURCE.md` (URL, UTC download time, license, sha256) and a line in the right `MANIFEST-*.md`,
  following `/home/benchmark/README.md`. Check the license first: permissive or open-data licenses
  only; anything copyleft or unclear, ask. Never into the repo (B6, H1).
- **Session limits**: commit `WIP local: <step>` before every long step and keep the "In flight"
  section of HANDOFF.md current, so a new session resumes from git, not from memory.

## 3. Machines and access

### 3.1 Where things are (checked 2026-10-29)

| What | Where |
|---|---|
| Laptop (this machine) | `10.10.9.137`, Docker 29.7.1, 31 GB free disk, psql installed, no ClickHouse client |
| Benchmark box | `10.10.9.41`, `ssh template@10.10.9.41` (key, no password). Its own guide: `/home/benchmark/README.md` |
| Box firewall | new inbound connections to container ports are accepted only from 10.10.9.137 |
| Earlier real-data run | `reports/2026-10-28_main_remote/REPORT.md` (git-ignored, on the laptop): method, measurements, rerun steps |

AGENTS.md §4 names `$BENCH_DIR=/home/bayern/Projects/benchmark`; that folder does not exist on the
laptop (checked 2026-10-29). The box is where the benchmark data lives. The HTTP runs of this guide
need no `BENCH_DIR`. Raw outputs of this run go to `reports/2026-10-29_round2_local/` on the laptop
(git-ignored, as on 2026-10-28). Record the stale path as an owner item (§7).

| Server on the box | Engine | Port | Holds | Use in this run |
|---|---|---|---|---|
| `diffbot-pg` | Postgres 16 | 5401 | `testdiffbot` (schema `diffbot`, 13 tables, 52,828 rows) | source; `norm_r2_*` outputs; `norm_app_r2_*` job records |
| `zoominfo-ch` | ClickHouse 26.8 | 8101 HTTP, 9101 native | `testzoominfo` (7 tables, 35.1M rows, ReplacingMergeTree: count with `FINAL`) | source; `norm_r2_src_*` samples and `norm_r2_*` outputs |
| `bench-pg` | Postgres 16 | 5405 | disposable benchmark origins (user `postgres`, no password) | `bm_round2_*` origins for D13 and more (G6) |
| `bench-ch` | ClickHouse 26.8 | 8102 | disposable benchmark origins (user `default`, no password) | only if a ClickHouse origin is needed |

Datasets already on the box: `/home/benchmark/data/public/` (`analytics-large`, `company-registries`,
`entity-matching`, `relational-samples`; each file listed in `MANIFEST-*.md`). For D13,
`entity-matching/raha-movies_1/{dirty,clean}.csv` has `language` and `country` columns. Look there
before downloading anything.

### 3.2 Passwords, read at run time

```bash
export PG_PW=$(ssh template@10.10.9.41 'grep -oP "(?<=POSTGRES_PASSWORD: ).*" /home/benchmark/stacks/diffbot-pg/compose.yaml')
```

```bash
export CH_PW=$(ssh template@10.10.9.41 'grep -oP "(?<=<password>)[^<]+" /home/benchmark/stacks/zoominfo-ch/clickhouse-users.xml')
```

`psql` reads `PGPASSWORD`; set it per command (`PGPASSWORD=$PG_PW psql -h 10.10.9.41 -p 5401 -U postgres ...`).
ClickHouse over HTTP: `curl -s -u "postgres:$CH_PW" http://10.10.9.41:8101/ --data-binary "<SQL>"`.
On the box with no local client: `docker exec diffbot-pg psql -U postgres -d testdiffbot`.

## 4. The two API processes

| | Docker API | Native API |
|---|---|---|
| Used for | D15 port binding and callers, D14 integration suite, the U1 walk | the real-data clones (§5.5, §5.6), the D13 clone |
| Started by | `docker compose up -d --build` | §4.2 |
| Address | `10.10.9.137:8080` (`NORM_BIND_ADDR`) | `10.10.9.137:8090` (check `ss -ltn` first) |
| Job records | the compose Postgres (`127.0.0.1:5535`) | a fresh `norm_app_r2_<run>` on `diffbot-pg` |
| Memory cap | `mem_limit: 4g` in compose.yaml | `MemoryMax=3G` |

### 4.1 Setup, once

```bash
git checkout feat/round2-fixes && git pull --ff-only
git config core.hooksPath .githooks
uv sync --all-extras
scripts/install_tools.sh
( cd ui && npm ci && npm run build )
```

`.env` does not exist yet. Create it from `.env.example`; set `NORM_BIND_ADDR=10.10.9.137` and a new
key: `NORM_SECRET_KEY=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')`.
`.env` is git-ignored; check with `git check-ignore .env` before writing it.

### 4.2 Native API, one per large job

```bash
RUN=diffbot   # one name per job: diffbot, zi100k, zi1m, lang
PGPASSWORD=$PG_PW psql -h 10.10.9.41 -p 5401 -U postgres -c "CREATE DATABASE norm_app_r2_$RUN"
export NORM_PG_DSN="postgresql://postgres:${PG_PW}@10.10.9.41:5401/norm_app_r2_$RUN"
export NORM_BIND_ADDR=10.10.9.137 NORM_LIBPOSTAL_URL=http://127.0.0.1:8081 MALLOC_ARENA_MAX=2
set -a; . ./.env; set +a; export NORM_PG_DSN   # .env supplies NORM_SECRET_KEY; keep the run's DSN
systemd-run --user --scope -q -p MemoryMax=3G -p MemorySwapMax=0 \
  uv run uvicorn normapi.main:app --host 10.10.9.137 --port 8090 --no-proxy-headers
```

Run it in the background and log to `reports/2026-10-29_round2_local/api_$RUN.log`. Check that
`.env` does not override `NORM_PG_DSN` back to localhost (`grep NORM_PG_DSN .env`), and that libpostal
from the compose stack answers on `127.0.0.1:8081`.

Drive it the way `docs/benchmarks/scripts/clone_bench.py::main` does (read it for the call order:
connections, plan, the `CREATE DATABASE` step, verify, start, poll, quality, lineage), but over HTTP
with `curl` or `httpx`. Build bodies that carry a password from the environment, never on the
command line:

```bash
jq -n --arg pw "$PG_PW" '{name:"diffbot-src", engine:"postgres", host:"10.10.9.41", port:5401,
  username:"postgres", password:$pw}' \
| curl -s -H 'Content-Type: application/json' --data @- http://10.10.9.137:8090/normalization/connections
```

Field names come from `normapi/schemas.py`; read them, do not copy them from this example.

## 5. The work, in order

Order (plan §8, owner Q4 "i agree"): the live checks first, then Phase 5, so the final report carries
their results. Fill in each "Result (filled in locally):" line of LOCAL_VERIFY.md with what was
measured, the command, and the date. A check that cannot run is written as "not checked", with the reason.

### 5.1 The CI run, before any live check

Plan §8 "The CI run": read `ci-fast.yml`, `stub-check.yml`, `docs-note.yml`, `guards.yml`,
`dep-check.yml`, `docs.yml` and run the `run:` steps of every job, base `main`. Tests in capped
batches. Vale and lychee: download the exact versions and checksums `docs.yml` names into `.tools/`
(no `sudo install`). zizmor: `GH_TOKEN=$(gh auth token) uv run zizmor .github/workflows`. Then
`gh run list --branch feat/round2-fixes --limit 5`: a run that started and failed blocks; a run that
ends in about 2 s with no steps is the known billing refusal, recorded, not a block. Record every
job's result in HANDOFF.md. The known `test_groups_cost_is_linear_in_pairs` failure under load is
recorded, never edited (L1).

### 5.2 Docker stack and the integration suite (D14)

```bash
docker compose build && docker compose up -d
docker compose ps    # every service with a healthcheck must be healthy
( ulimit -v 16777216; uv run pytest -m integration -q )
```

Then the D14 entry of LOCAL_VERIFY.md: `grep -rn in_place packages ui/src` is empty; a
`POST /normalization/clone-jobs` with `in_place` answers 422; after a clone, `SELECT count(*)` of every
origin table is unchanged and no origin table name ends in `__normalizing`.

### 5.3 D15 on the real network

Follow the D15 entry of LOCAL_VERIFY.md, with these callers (G7):

- **This host**: `ss -ltnp` shows this project's ports only as `10.10.9.137:8080` and `127.0.0.1:*`.
  Langfuse's `0.0.0.0` ports are not this project's; list them separately and leave them.
- **Second LAN caller**: `ssh template@10.10.9.41 "curl -s -o /dev/null -w '%{http_code}\n' http://10.10.9.137:8080/health"` must print 200.
- **Caller outside the private ranges**: `203.0.113.0/24` is TEST-NET-3 (RFC 5737), never routed, and not in
  the allowed set. The API container joins a temporary network in that range; a curl container on the
  same network calls the API's container address with an allowed `Host`, so only the peer check can refuse:

  ```bash
  docker network create --subnet 203.0.113.0/24 r2-outside
  docker network connect --ip 203.0.113.2 r2-outside "$(docker compose ps -q api)"
  docker run --rm --network r2-outside curlimages/curl:8.17.0 -s -o /dev/null -w '%{http_code}\n' \
    -H 'Host: 10.10.9.137:8080' http://203.0.113.2:8080/health    # expected 403
  docker network disconnect r2-outside "$(docker compose ps -q api)"
  ```

  Removing the network afterwards (`docker network rm r2-outside`) needs the owner's yes (H2). Pull
  the curl image only after checking its tag exists; record the image digest.
- **Bad Host**: `curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://10.10.9.137:8080/health` gives 400.
- **Database targets**: save a connection to `8.8.8.8` (422). The host name with two addresses, one
  public, is covered by `tests/unit/test_address_policy*.py` only (G7): write "not checked live".
- **libpq `hostaddr`**: during a native-API clone from `diffbot-pg`, check on the box with
  `docker exec diffbot-pg psql -U postgres -Atc "select client_addr from pg_stat_activity where datname='testdiffbot'"`
  that the client is 10.10.9.137. For ClickHouse, `system.query_log` on `zoominfo-ch` shows the client
  address and the queries of the clone.
- **Native start address**: `normapi/main.py` and `.env.example` default `NORM_API_HOST` to `0.0.0.0`
  for `python -m normapi.main`. Check whether ADR-022 covers that path; if it does not, it is an owner
  item (§7), not a fix.

### 5.4 D13 on real data with a LANGUAGE column

1. Load `raha-movies_1/dirty.csv` and `clean.csv` from the box into a new `bm_round2_movies` database on
   `bench-pg` (one table each, every column `text`, row counts checked against `wc -l` minus the
   header). Load it with `psql \copy` on the box, or with
   `/home/benchmark/playbook/merge-engine/tools/load_origins.py` if it fits (read it first).
2. Other datasets with a LANGUAGE column may be added the same way (G6). Search the box first; download
   only what the D13 checks need, under §2's download rule.
3. Clone it through the native API (§4.2, `RUN=lang`), field types detected automatically, then once
   with `language` set to LANGUAGE and `country` to COUNTRY.
4. Check the D13 entry of LOCAL_VERIFY.md on the output: values that are both a code and a name are
   `AMBIGUOUS` unless the row's country or the column settles them; a 2-letter column stays codes;
   feeding the output back changes nothing; `env_id` moved with the new `language.py` (ADR-014); a
   resumed job keeps `column_language_form`. Expected outcomes come from the report's D13 table and
   the plan §9, never from the output.
5. The report's DB-free probe (feeding `display` and `comparison` back over all pycountry
   languages: 440 of 7,910 and 0 before): run it again and record both numbers after.

### 5.5 Real-data runs: Diffbot, ZoomInfo 100k, ZoomInfo 1M

Repeat `reports/2026-10-28_main_remote/REPORT.md` §6 on this branch, through the native API, each run
with its own `norm_app_r2_<run>` and new output names (`norm_r2_out_diffbot`, `norm_r2_src_zi100k`,
`norm_r2_out_zi100k`, `norm_r2_src_zi1m`, `norm_r2_out_zi1m`). Make the samples with
`reports/2026-10-28_main_remote/scripts/make_sample.sh` (it runs on the box). Measure as that report
did (wall and CPU time, peak memory, server load, network); `scripts/measure.py` there drives the
in-process client and needs adapting to HTTP, outside the repo. Compare every number with the
2026-10-28 table and explain each difference. Check row counts directly (ClickHouse with `FINAL`).

### 5.6 The API start-up memory problem (G5)

Known cause on `main` (2026-10-28 report, finding 1): `normapi/adjudication.py::migrate_sources`,
called by `normapi/app.py::create_app`, loads the whole review queue with
`list_queue(..., limit=2**31)`. It is unchanged on this branch (checked 2026-10-29).

1. **Reproduce, capped**: after the 1M run, stop the native API and start it again on the same
   `norm_app_r2_zi1m`, under `MemoryMax=3G`. Record the peak memory over time (`systemd-cgtop` or
   `/sys/fs/cgroup/.../memory.peak`), the start-up time, and whether the cap killed it.
2. **Confirm the cause** with a measurement, not by reading: for example `tracemalloc` or `py-spy dump`
   during start-up, and the queue size (`select count(*), pg_size_pretty(sum(pg_column_size(t.*)))`
   on the queue table). Look for every other start-up path that reads a whole table
   (`graft callers create_app --direction out --depth 2`, then read each).
3. **Research a fix (F7)**: this codebase first (paged `list_queue` callers already exist in
   `normapi/routes.py`), then installed libraries (psycopg server-side cursors), then public projects.
   Report a short table: approach, link, license, maintenance, how it would be used, and a
   recommendation.
4. **Report** in FINAL_REPORT.md, section "API start-up memory": measured numbers, the cause with its
   evidence, the options, the recommendation. **No code change**; the fix waits for the owner.

### 5.7 U1 against the running stack (G8)

Walk the five screens on `http://10.10.9.137:8080/` as LOCAL_VERIFY.md's U1 entry lists, with data
from a real job (the Diffbot run's queue). Use the built-in browser; keep screenshots in
`reports/2026-10-29_round2_local/ui/`, never in the repo. Measure the review key response (< 0.1 s)
and page load (< 1 s with 250 distinct values) from the browser's own timing (Performance API), and
check the network log shows no request to another origin. If no browser is available, run
`( cd ui && npm run test:e2e )` and take timings from Playwright traces, and write that the live walk
was not done. Check `docker compose exec api ls /app/ui/dist`.

### 5.8 The agent's own adversarial re-check (instead of a verifier)

The plan's verifier was a second agent; here one agent does both jobs, so it re-checks in a fresh
state. In a clean worktree (`git worktree add --detach ../norm-r2-check HEAD`), re-run each
pass/fail command of §5.2-§5.7 and compare with what was recorded; read every accepted item's diff
against the plan §9 acceptance list and the report's text, looking for what the cloud lead explained
away. Re-attack D13, which the cloud never re-attacked after its fixes (HANDOFF.md). Every mismatch is
fixed (D3) or written up. The worktree is removed only with the owner's yes.

### 5.9 Phase 5 close

Exactly plan §8 "Phase 5, close", with the CI run of §5.1 repeated on the final commit:

- `/ponytail-review` over `git diff main...HEAD`, `/ponytail-audit`, `/ponytail-debt`, `/ponytail-gain`.
- Delete the unused exports in `ui/src/api/{client,types}.ts` the Phase 4 review found (graphs and
  `graft grep` first, F6), then `npm run build && npm run lint` and Playwright.
- Every HANDOFF.md row has a verdict; LOCAL_VERIFY.md has every Result line filled in.
- Write `docs/plans/round2/FINAL_REPORT.md`: per item what was built, how it was verified (cloud and
  local), measured results against the report's "before" values, §5.6, the open owner items (§7), and
  every check not run with its reason. Fold `.handoff/` into it (link nothing that will be purged),
  then remove `.handoff/` in a commit; show the file list first and wait for the owner's yes (B3).
- Add one round 2 status line to `docs/improvement-report.md` (add, do not rewrite).
- Docs decision per J13 in each commit message. Commit `[ROUND2 COMPLETE]`, push, stop. STATUS:
  `next=complete lock=none`, autonomy untouched.

## 6. When to stop and ask

Stop, write the question under Notifications in HANDOFF.md, commit, push, and ask the owner in the
chat when: a source would be written; a database would be dropped or a file deleted; a check fails and
the fix would change behaviour the plan or the report does not describe; memory nears the cap outside
the measured start-up case; a dataset's license is unclear; a password would have to be typed or
printed; or anything in this guide disagrees with the plan or AGENTS.md.

## 7. Open owner items (no code in this run, G10)

Carry these into FINAL_REPORT.md as waiting for the owner, with any new evidence from the live run:

- R23 gaps: unmasked sample values in clone-job error text; raw `disguised_missing[].value` (D4 needs
  it); `/preview`, `/field-test`, `/runs/{id}/values` echo raw values.
- `/docs` and `/redoc` off; whether to add `swagger-ui-dist`.
- The cloud lead's review-key decisions (number keys, skip, undo before send).
- The old `NORM_SECRET_KEY` in `main`'s history: rotate; `.gitleaksignore` or not.
- `test_groups_cost_is_linear_in_pairs` fails under load.
- `Host: localhost:80@evil.com` accepted.
- The API start-up memory fix (§5.6).
- `$BENCH_DIR` in AGENTS.md §4 points to a folder that no longer exists on the laptop.
- `NORM_API_HOST=0.0.0.0` for the native start, if §5.3 finds ADR-022 does not cover it.
