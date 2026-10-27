# Phase 0 report — baseline and re-verification

Run 2026-10-27, Python 3.12.3, branch `feat/round2-fixes` at the branch point. Plan §8, Phase 0.

## 1. Baseline: the four ci-fast commands

| stage | result | time |
|---|---|---|
| `uv run ruff check .` | pass | 1 s |
| `uv run ruff format --check .` | pass (636 files) | 1 s |
| `uv run mypy packages` | pass (98 files) | 25 s |
| `pytest -m "unit or (golden and not slow)"` (16 GB cap) | 3217 passed, 24 skipped, 76 deselected, 1 xfailed | 299 s |

`gh` is not available in the cloud, so `ci-fast` on the branch was not listed here; the phase-gate run
checks GitHub through the MCP tools.

Setup note: a bare `uv sync` picked Python 3.13 and failed to build `pyarrow`/`pyicu`.
`uv sync --all-extras --python 3.12` works after `scripts/cloud_setup.sh` installed `libicu-dev` and
`pkg-config`. Use `--python 3.12` in the cloud until a `.python-version` file exists (not added: it is
a repo-layout change, M1).

## 2. Re-verification of the report's "Verified state"

| item | claim | verdict |
|---|---|---|
| D15 | API listens on `0.0.0.0` | confirmed: `normapi/main.py` (`NORM_API_HOST` default), `packages/normapi/Dockerfile` CMD. The report says "the Dockerfile"; it is `packages/normapi/Dockerfile` (differs: path) |
| D15 | no caller or `Host` check; CORS wide on methods and headers | confirmed: `app.py::create_app` has `CORSMiddleware` with `allow_methods=["*"]`, `allow_headers=["*"]`; no `TrustedHost` |
| D15 | compose ports have no host address | confirmed: api 8080, libpostal 8081, postgres 5535, demo 5434, 3307, 27018, 8124 |
| D15 | f-string DSN | confirmed: `clone_executor.py::build_source_connector` |
| D15 | committed `NORM_SECRET_KEY` | confirmed in `compose.yaml` |
| D15 | `is_private` unsafe | confirmed: `2001:db8::1` and `198.18.0.1` are `True` on 3.12 here |
| D15 | clickhouse-connect pinning | clickhouse-connect 0.15.1 `get_client` has no `hostaddr`. It has `server_host_name` (TLS name check), so connecting to the checked IP with `host=<ip>, server_host_name=<name>` is possible. Not tested against a real server: live item |
| D14 | `in_place` field, `staging_name`, `swap_table` on both destinations | confirmed (`schemas.py`, `clone_executor.py`, `routes.py`, both `*_destination.py`) |
| D14 | tests that set `in_place` | the report's list plus one more: `tests/unit/test_run_recorder.py` matches only `test_historical_run_never_mutated_in_place`, a different meaning (no change needed). Files with the field: `test_in_place_clone.py`, `test_clone_routes.py`, `test_followups.py`, `test_robustness.py`, `test_adjudication_acceptance.py`, `test_lineage_d3_acceptance.py`, `test_typed_destination_d5_acceptance.py`, `integration/test_clone_pipeline.py`, `integration/test_followups_live.py` |
| D14 | docs | `README.md` and `ARCHITECTURE.md` mention it; `GLOSSARY.md` has no match for `in_place` (differs: check the word "in place" by hand in Phase 2) |
| D14 | `writable_user` login | `01-init.sql` defines `writable_user` with `CREATEDB`; whether other tests use it is for Phase 2 to check |
| D13 | `_resolve_language`, `_split_language_tag`, `_country_from_*` | confirmed at the cited names |
| D13 | 384 hyphenated names | confirmed (384) |
| D13 | `gaa` is named `Ga` in CLDR English | confirmed: Babel 2.18.0 `Locale("en").languages["gaa"] == "Ga"`; `mnw` has no English entry in CLDR (pycountry: `Mon`) |
| D13 | CLDR territory to language | Babel 2.18.0 `get_global("territory_languages")`: 258 territories. `MM` lists `mnw`; `TH` lists `mnw`. Row evidence works for the `Mon` case |
| U1 | 18 page files, no review page | confirmed: 18 files in `ui/src/pages`, none for the queue |
| U1 | `detail` masked | not proven: the `AdjudicationQueueEntry` docstring says masked; the code that fills `detail` was not traced. Phase 4 traces it before the raw-value route |
| U1 | Playwright specs | `ui/e2e`: `dictionaries`, `preview`, `profiles-and-runs`, `smoke`, `type-detection`. Dropped-page specs: `dictionaries`, `preview` (and the dropped parts of `profiles-and-runs`) |

Playwright installs in the cloud (dry-run tick: exit 0, 22 s).

## 3. Open questions

None. Drift found is small and recorded above.
