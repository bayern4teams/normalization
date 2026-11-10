# Local verification checklist — what the cloud could not prove

Everything here is **implemented, unverified** until the owner runs it locally. Confirm each entry
with an independent check (a direct query, `ss -ltnp`, a curl from another machine), never the
application's own success message. The local agent's steps for this list are in [LOCAL_RUN.md](LOCAL_RUN.md).

## Restore the environment first

```bash
git checkout feat/round2-fixes && git pull --ff-only
uv sync --all-extras                       # Python 3.12; PyICU needs libicu-dev + pkg-config
cp .env.example .env                       # then set NORM_SECRET_KEY (D15 removed it from compose.yaml)
docker version --format '{{.Server.Version}}'   # must be 28.3.3 or newer (report D15)
docker compose up -d postgres libpostal    # metadata and destination Postgres on host port 5535
( ulimit -v 16777216; uv run pytest -m integration -q )
( cd ui && npm ci && npx playwright install chromium && npm run test:e2e )
```

Use a copy of a real database; the sources are read-only (ADR-013, unconditional after D14).

## The report's "before" values (the owner must see these change)

| item | before (from the report) | where |
|---|---|---|
| D15 | the API listens on `0.0.0.0`; every compose port has no host address; any database host is accepted; the Postgres DSN is an f-string; `NORM_SECRET_KEY` is committed in `compose.yaml` | report D15, "Verified state" |
| D14 | `in_place` drops the original table after the swap on Postgres and ClickHouse | report D14, "Verified state" |
| D13 | feeding `display` back changes 440 of 7,910 pycountry languages (208 to another language, 232 to INVALID); feeding `comparison` back changes 0 | report D13, "Measured" |
| U1 | no page shows the review queue; 18 page files, 13 navigation items | report U1, "Verified state" |

## Per-item entries (added by the lead when it accepts an item)

```text
### <id> — <title>
- Why the cloud could not verify: <no Docker / no LAN / no database / no running stack>
- Command: <exact command>
- Independent check: <query / ss / curl from another host / file to compare>
- Expected evidence: <from the report, or "any value > X because ...">
- Result (filled in locally):
```

### D15 — local network only

- Why the cloud could not verify: no Docker, no LAN, no real Postgres or ClickHouse.
- Command: set `NORM_BIND_ADDR` (LAN address) and `NORM_SECRET_KEY` in `.env`; `docker compose up -d`; then
  `ss -ltnp` on the host; `curl http://$NORM_BIND_ADDR:8080/health` from a second LAN machine; the same
  from a machine outside the private ranges (or with a public `Host`) must be refused; save a connection to
  a public host (must answer 422); save one to a host name with two addresses, one public (must answer 422).
- Independent check: `ss -ltnp` shows only `$NORM_BIND_ADDR:8080` and `127.0.0.1:*` for every other port;
  `docker version` server >= 28.3.3; the Postgres log shows the connection came from the checked address
  (libpq `hostaddr`); for ClickHouse, `system.query_log` shows the client connected (the driver was given the
  IP with `server_host_name`; never tried against a real server).
- Expected evidence: no port on `0.0.0.0`; LAN caller answered; outside caller refused with 403; bad Host 400.
- Also: `Host: localhost:80@evil.com` is accepted (the allowlist reads the part before the first `:`); an
  IPv6 `Host` (`[::1]`) is not allowed.
- Result (filled in locally): PASS 2026-11-01 (re-run 2026-11-01 in a clean worktree, §5.8). `ss -ltnp`
  shows this project's ports only as `10.10.9.137:8080` (api), `127.0.0.1:5535` (postgres),
  `127.0.0.1:8081` (libpostal) — nothing on `0.0.0.0`; no Langfuse ports touched. `docker version`
  server 29.7.1 ≥ 28.3.3. Second LAN caller (10.10.9.41): `curl http://10.10.9.137:8080/health` → 200.
  Outside caller (curl container on the `203.0.113.0/24` TEST-NET network, 203.0.113.2, allowed
  `Host`) → 403, re-checked 2026-11-01. Bad `Host: evil.example`
  → 400. `Host: localhost:80@evil.com` → 200 (known limit, listed above). Saving a connection to
  8.8.8.8 → 422. libpq `hostaddr` live: during the native-API clone from diffbot-pg the box's
  `pg_stat_activity` client_addr for the clone sessions is 10.10.9.137; ClickHouse `system.query_log`
  shows `initial_address = ::ffff:10.10.9.137` for the ZoomInfo clone queries. Two-address host name:
  NOT checked live (unit tests only, per owner G7). The `r2-outside` network still exists on this
  host (removing it needs the owner's yes, H2).

### D14 — remove in-place mode

- Why the cloud could not verify: no Postgres or ClickHouse.
- Command: `( ulimit -v 16777216; uv run pytest -m integration -q )` against the compose stack; `grep -rn in_place packages ui/src`.
- Independent check: after a clone, `SELECT count(*)` of the origin tables is unchanged and its tables carry no `__normalizing` suffix.
- Expected evidence: integration suite green; a `POST /normalization/clone-jobs` with `in_place` answers 422.
- Limit: two saved connections to one server under different host names (`localhost` and `127.0.0.1`) are not guessed to be one origin; the guard compares engine, host and port as saved.
- Note: a job stored before this change with `in_place: true` is not migrated; delete such rows from the metadata database if any exist.
- Result (filled in locally): PASS 2026-11-01 (and re-run 2026-11-01 in a clean worktree, §5.8).
  `( ulimit -v 16777216; uv run pytest -m integration -q )` against the compose stack: 33 passed
  (67 s). `grep -rn in_place packages ui/src` returns nothing. `POST /normalization/clone-jobs`
  with `in_place: true` → 422. After the §5.5 clones: every origin table count unchanged
  (testdiffbot 13 tables, sum 52,828, re-counted after the runs; testzoominfo never opened for
  write — only `norm_r2_src_*` sample DBs were created), and no origin or output table name ends
  in `__normalizing` (checked on testdiffbot, norm_r2_out_diffbot and norm_r2_resume_diffbot).

## Test changes to review

Plan §2.9: every test change outside the pre-approved list, each its own `TEST-CHANGE:` commit.
Review the diff of each and confirm the test still checks the same behaviour.

| file | commit | reason |
|---|---|---|

| `tests/conftest.py` (new) | WIP D15 commit "TEST-CHANGE: loopback peer and localhost host for every TestClient" | Starlette's default peer `testclient` and host `testserver` are refused by ADR-022 |
| `tests/unit/test_connector_schema.py` | WIP D15 commit "TEST-CHANGE: use a literal local address as the connection host" | host `h` does not resolve; assertions unchanged |
| `tests/unit/test_address_policy.py` | WIP D15 commit "lint-clean the moved address-policy test" | formatting and a top-level import only |
| `tests/unit/test_u1_serving.py` (new this round) | `bb162ca`, `57d8cbc` (WIP commits, not in `TEST-CHANGE:` form; recorded 2026-11-10, D24) | C5: `JS_NOT_FETCHED` widened by `reactrouter.com`, `mantine.dev`, `localhost`, `github.com` (message text in the bundle, none fetched); the `/docs`-served-locally test was removed from the file and parked in `.handoff/U1.test_docs_local.md` (needs `swagger-ui-dist`, outside plan 2.10). Owner approval: none, escalated in HANDOFF.md; owner 2026-11-07 "2. a" ruled `/docs` out (FINAL_REPORT §7). Review 2027-01-27. |
| `tests/integration/test_followups_live.py` | WIP local: D14 integration fix (source_identity) | Added `source_database` to fixture `_job_with_error_rows()` so resume tests survive the `source_identity` migration in `_normalize_table` |

### D13 — LANGUAGE code is the contract

- Why the cloud could not verify: no real source database. Check: a clone of a table with a LANGUAGE column, a COUNTRY column
  (`Mon` with `MM` gives `mnw`, with no evidence stays AMBIGUOUS) and a column of only 2-letter codes (`Ga` gives `ga`).
- Check that `env_id` moves with the new `language.py` (ADR-014) and that a resumed job keeps `column_language_form`.
- Known limit: a registered BCP 47 variant with no CLDR locale (for example `sl-rozaj`) is read as a name, not split.
- Result (filled in locally): PASS 2026-11-01 (§5.4 + §5.8 re-attack in a clean worktree). Real
  clone: `bm_round2_movies` (raha-movies_1, 7,390 rows, 502 distinct languages) on bench-pg cloned
  through the native API with `language`→LANGUAGE and `country`→COUNTRY: output gained
  `language_code`/`country_code`; 5,763 single-language rows → `en`; 1,627 multi-language cells
  (e.g. `English,French`) → NULL (AMBIGUOUS, kept unchanged — never a guessed pick); feeding the
  output codes back changes 0. Acceptance cases: `Mon` with no evidence → AMBIGUOUS; `Mon` with
  row country `MM` → `mnw`; `Ga` in a 2-letter-code column → `ga`; `Mon-Khmer` not split as a BCP
  47 variant (INVALID, original kept); `en` → `en`. DB-free probe over all 7,910 pycountry
  languages: feeding `comparison` back changes **0** (the "before" 0 holds); feeding `display` back
  changes **142, all to AMBIGUOUS holds, 0 silent rewrites** — the "before" 440 (208 to another
  language, 232 to INVALID) is gone: a display value is never re-interpreted into a different
  answer, it is held for review instead. `env_id` moved with the new `language.py`: the ADR-014
  source-hash input (blake3 over every `normalizers/*.py`) changed main `4b43f2eb…` → HEAD
  `1fa6736e…`; stored-verdict movement not checked (verdict table empty). A resumed job keeps
  `column_language_form`: a diffbot job killed mid-Phase-2 and resumed after an API restart
  completed with its stored configs intact and full counts (52,828/52,828), and the check was
  repeated with an explicit LANGUAGE/COUNTRY job (movies, killed at 2,000 rows, resumed →
  COMPLETED 14,780 rows, `language_code` distribution identical to the full run: en 5,763, NULL
  1,627; `_column_evidence` runs per table inside every Phase-2 pass, so the resumed pass applies
  it too).

### U1 — the new UI

- Why the cloud could not verify: no Docker, no running stack, no real API shapes.
- Command: `docker compose up -d --build`; open `http://$NORM_BIND_ADDR:8080/`; walk Connections (save a public host: refused at the field),
  New clone, Jobs (reload keeps filter and detail), Review (keys 1-9, o, k, u), Quality. `( cd ui && npm run test:e2e )`.
- Independent check: browser dev-tools network tab shows no request to another origin; the Review key press updates the page in under 0.1 s
  and each page loads in under 1 s with 250 distinct values; `docker run` image has `/app/ui/dist`.
- Also: `/docs` is off (Swagger needs `swagger-ui-dist`); R23 gaps listed in HANDOFF.md Open escalations.
- Result (filled in locally): PASS 2026-11-01 (§5.7, live browser walk + Playwright). Docker stack
  up (`docker compose exec api ls /app/ui/dist` shows the built UI in the image; the image was
  built 2026-10-29, after the last UI/API change 2026-10-28, so it is current; not rebuilt this
  session); walked all five screens at
  `http://10.10.9.137:8080/` against a real job (`bm_round2_ui_out`, COMPLETED, 14,780 rows).
  Connections: saving a public host is refused before it can be stored — "Test connection" shows
  "address '8.8.8.8' is outside the allowed local network" and Save stays disabled. New clone,
  Jobs (list + detail; detail and URL survive a reload), Review (12 entries from real job data;
  keys o/k/u present; a key press updates the page in **14 ms**, budget 100 ms), Quality (per-job
  column table renders for the real job). Network: every resource the pages load comes from the
  API's own origin (`performance` resource entries → single origin `http://10.10.9.137:8080`).
  Route content render 102-105 ms per screen; the strict "page load < 1 s with 250 distinct
  values" budget was NOT measured as a controlled 250-value page (this stack's queue holds 12
  distinct entries) — recorded as not checked. `( cd ui && npm run test:e2e )`: 48 passed.
  Screenshots kept outside the repo in `reports/2026-10-29_round2_local/ui/`.
  2026-11-07 (owner "4. a"): measured with **300** distinct values (1,203 rows of day/month-ambiguous
  dates cloned from `norm_r2_src_ui300` on the compose Postgres; native API on `10.10.9.137:8090`
  under `MemoryMax=3G`, job records in `norm_app_r2_ui300`). Playwright, headless Chromium, a new page
  per run: navigation to the first review value on screen **130-160 ms** (5 runs; budget 1 s); the
  `/adjudication/review` request 9-14 ms. Key `k` to the next value: **3-16 ms** (10 presses; budget
  0.1 s). PASS.
