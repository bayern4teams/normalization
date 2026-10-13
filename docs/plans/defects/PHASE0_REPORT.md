# Phase 0 report — baseline and ownership

Session: supervisor tick 2026-10-05 (branch point `4003af0`, kit only).

## 1. Baseline (plan §8 Phase 0 step 1)

| stage | result | wall time | expected (§2.8) |
|---|---|---|---|
| `uv run ruff check .` | pass | 0.9 s | |
| `uv run ruff format --check .` | pass (464 files) | 0.5 s | lint+format+mypy 6.5 s |
| `uv run mypy packages` | pass (92 files) | 23.8 s (cold cache) | |
| `pytest -m "unit or (golden and not slow)"` | **1290 passed**, 12 skipped, 140 deselected | 98 s | 1288 passed, 46 s |

Findings:
- **+2 passing tests** vs the plan's 1288: the kit commits added tests (not a regression).
- Wall time ~2x the local figure: cloud CPU, not a code change.
- `ci-fast` on GitHub: green on every `feat/defects-fixes` push (runs 48-55, latest `715ddb8`).
- **Environment trap:** a `.venv` first created by `uv sync` before `scripts/cloud_setup.sh` ran picked
  `/usr/bin/python3.13`; under 3.13 `pyarrow==17.0.0` has no wheel and its sdist build fails
  (`pkg_resources`). Fix used: `rm -rf .venv && UV_PYTHON=3.12 uv sync --all-extras`. `cloud_setup.sh`
  installs libicu-dev/pkg-config and cpython 3.12 but does not pin the venv's interpreter; a
  `.python-version` file (`3.12`) would remove the trap. Recorded, not changed (outside D1-D12).
- **Tool trap:** `graft` was on PATH at session start but its npm package was gone after a second
  `cloud_setup.sh` run (dangling `/opt/node22/bin/graft`); `npm install -g @nanonets/graft@0.19.0` restored it.

## 2. Re-verification per item (plan §8 Phase 0 step 2)

Read against the source on 2026-10-05 (two read-only sweeps, lead spot-checked `dispatch.py:303-314`,
`routes.py:1105-1114`, `identifier.py:113-145`). Paths under `packages/<pkg>/src/<pkg>/`.

| item | verdict | evidence / drift |
|---|---|---|
| D1 | confirmed | AMBIGUOUS producers `phone.py:205-209`, `date.py:572-575`, `money.py:180-183`. Errors only via GET `routes.py:399`, `:1082`. No queue/verdict store. Resume skip `clone_executor.py:1881-1888`; daemon thread `:910-911`; `job_errors` DDL `pg_persistence.py:125-132` (`job_id,row_index,table_name,field,original TEXT NULL,error`); `make_cache_key` `normexec/cache.py:30` |
| D1 PII | pinned | **write stores `original` raw** (`clone_executor.py:1146-1152` → `pg_persistence.py:688-713`); **read masks `original` only** via `normcore/pii.py:68-78` `safe_preview` (default `masked`: `hash=<blake3[:16]> mask=[<char classes>]`) at `routes.py:1111`/`:415`; `error` text returned unmasked and the column-report finding embeds `repr()` samples. Rule for D1: queue rows store `original` exactly as `job_errors` does (raw at rest), the queue API returns `safe_preview(original)` like `routes.py:1111`, never the raw string; candidates/trace go through the trace masking already used for traces (`test_pii_masking.py::TestTraceMasksOnARealNormalizer`). ADR-013/014 hold no PII text; ADR-016:51-55 forbids raw values in keys (D1 key uses `content_hash`) |
| D12 | confirmed (F5) | `enums.py:23`, `dispatch.py:309`; only other mention is a docstring at `normalizers/date.py:18` (report missed it) |
| D2 | differs (count scope) | `ast`: **normalizers 61 sites: literal 1.0×28, 0.0×14, 0.5×3, other×2 (0.9, 0.3), expressions 14** — report exact. All `packages/`: 70 sites (normcore 3, normanalysis 5, normapi 1), literal 1.0×29. Plain grep `confidence=1.0`: 32 lines (F4 said 31). Report cites the `min(1.0 if idn_ok …)` expression in `email.py`; it is `url.py:235`. 0 calibration code |
| D3 | confirmed | `TraceStep` `normcore/trace.py:18`; 0 lineage hits |
| D4 | confirmed | `MissingKind` `enums.py:26`; negative controls `type_detection.py:66` and `:81` (report's 58-68 covers only the first). `ptype` 0.2.12 is MIT, installable, but pulls pandas, matplotlib, scipy, greenery, joblib (feasibility gate in phase 3 weighs this) |
| D5 | over-claims (F1) | `storage_types.py:36-41` types NUMERIC/MONEY/BOOLEAN (CH: Decimal(38,9)/(38,4)/Bool), `coerce` :93, used `clone_executor.py:1196`; default true `clone_executor.py:399/623/706`, `schemas.py:255`. Stale text: `connectors/postgres_destination.py:20-43`, `connectors/clickhouse_destination.py:21-35`, `clone_executor.py:173-175`, `docs/verification/clone-normalize-verification-pack.md:236-243`, `docs/improvement-audit-notes.md:59-61`. README has none. **25** semantic types, not 24 |
| D6 | confirmed (+2 drift) | 877 test functions (report 875), 46 golden in 7 files, 0 corpus files; `tests/golden/expectations/` absent (F7) |
| D7 | confirmed | `_STDNUM_REGISTRY` `identifier.py:68-73` (US/GB/DE/FR); stdnum 1.20 has `get_cc_module`. Unknown country / no country → `validation_status="VALID"` (`:143`); `except Exception` → INVALID (`:121`) — a "could not check" collapsed into "wrong" too. Licence: stdnum is LGPL, dynamic import only — runtime discovery OK, vendoring its data is not. `_VALIDATION_SEVERITY` already has `UNKNOWN` (`dispatch.py:314`), so no new status is needed |
| D8 | confirmed (nuance) | `identifier.py:92-94`; cleaning identical for all three; check digit only for `TAX_ID`+country (`:115`). Registration `normapi/app.py:162` |
| D9 | confirmed | `url.py:36,39`; structured keys `:223-232`; neither `tldextract` nor `publicsuffixlist` installed |
| D10 | differs (F2) | extension kept in `structured["extension"]` (`phone.py:107`) and `display` (INTERNATIONAL); lost in `comparison`/`search` (`:125-126`) and `structured["e164"]`; no RFC 3966. phonenumbers 8.13.55 |
| D11 | confirmed (report under-lists) | `name.py:100-122` emits soundex, nysiis, metaphone **and match_rating_codex** on `anyascii` output (`text_ops.py:287-292`); jellyfish 1.2.1, no Double Metaphone/BMPM installed |
| coverage | **plan cites a test that does not exist** | no "24 of 25" test: the live registry maps 24 of 25 types to a real normalizer (UNKNOWN → passthrough). D8 adds that assertion as a new test instead of "still passes" |

## 3. Ownership
Locked in `HANDOFF.md` ("Locked file-ownership table").

## 4. Synthetic fixtures and BEFORE numbers (plan §8 Phase 0 step 4)

Built by two `defects-verifier` runs (P0-A, P0-B) under `tests/defects/`: the shared scorer
(`scorer.py`, five outcomes, proven both ways by `test_scorer.py`, 29 tests, `unit`), planted fixtures
(`fixtures_phase1.py`, `fixtures_phase23.py`) and two measure scripts (not collected by pytest). Truth comes
from stdnum check-digit functions, libphonenumber example numbers, CLDR via Babel, the PSL, ICU BGN/PCGN and
pycountry, never from `tests/`. Full numbers: `uv run python tests/defects/measure_phase1_before.py --rev e6fa923`
and `uv run python tests/defects/measure_phase23_before.py`.

| item | BEFORE (current code) |
|---|---|
| D1 | 16/16 planted ambiguous values abstain (correct-abstain), 0/16 reach any queue; wrong-confident 0 |
| D7 | 4 of 85 stdnum country packages reachable; 0/6 one-digit invalid twins caught (6 wrong-confident); unlisted (AE) and no-country come back VALID |
| D8 | TAX_ID vs CODE identical `validation_status` in 2 of 3 pairs |
| D9 | 0/10 PSL cases answered (no key); a naive last-two-labels rule is exposed by `a.co.uk`, `b.a.co.uk`, `x.github.io`, IPv4, `foo.notatld` |
| D10 | base, `x45` and `x46` share one `comparison` in 10/10 regions; `rfc3966` absent 40/40 |
| D11 | same-name pairs sharing a key: Soundex 22/31, **any of the four old keys 25/31** (cross-script 13/18); different-name collisions 0/10; non-Latin inputs carrying all four keys 17/17 |
| D5 | `coerce` never raises; overflow (`1e999`, ±10**40 on CH Decimal(38,9)/(38,4) and PG NUMERIC(38,4); `1e1000000` on PG NUMERIC) passes the gate (modelled, unverified-live) |
| D4 | no cell-level report; but the dispatcher already maps `N/A`, `-`, `unknown` to missing per cell, and maps `NA` in a COUNTRY column to NOT_APPLICABLE (40/40 Namibia rows) |
| D12 | `NEEDS_REVIEW`: 0 producers |

### Lead decisions taken from the fixtures
- **D11 baseline** is the *any old key* count (25/31, cross-script 13/18), not Soundex alone: the plan's
  Soundex bar is already met on `main` and would accept a no-op. Must-fix pairs: Мухаммед vs
  Muhammad/Mohammed/Mohammad/محمد, Елена vs Yelena.
- **D11 Latin with diacritics** (`Müller`): Latin script, so it keeps today's keys byte-identical; "not
  applicable" is decided by script, not by the fact that `anyascii` folded a diacritic.
- **D10** acceptance uses base ≠ `x45` ≠ `x46` in `comparison`; "four spellings agree" passes trivially today.
- **D5** includes a precision/scale check in `coerce`: an overflowing value is a value "a typed column cannot
  hold" (decision #8), so it must become `(None, error)`, not reach the INSERT.
- Findings outside D1-D12 are listed under "Open escalations" in `HANDOFF.md`, not fixed here.
