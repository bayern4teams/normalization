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
