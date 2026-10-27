#!/usr/bin/env bash
# Repo script `scripts/cloud_setup.sh`: the supervisor runs it (step 4) when a tool is missing at
# session start, then the project bootstrap. Same installs as cloud_environment_setup.sh, with retries;
# the versions are scripts/refresh_graphs.py::PINS.
set -euo pipefail
export DO_NOT_TRACK=1  # graft's usage ping and version check (owner decision 2026-10-27)
cd "$(dirname "$0")/.."

python3.11 -m venv /opt/graphtools
/opt/graphtools/bin/pip install -q graphifyy==0.9.96 codebase-memory-mcp==0.12.1
# graft's postinstall downloads a tree-sitter binary from GitHub; that download hung once, so retry
# with a short timeout instead of waiting out one long one.
for _ in 1 2 3; do timeout 180 npm install -g @nanonets/graft@0.26.0 && break; done || true
for t in graphify codebase-memory-mcp; do ln -sf "/opt/graphtools/bin/$t" "/usr/local/bin/$t"; done
for t in graphify graft codebase-memory-mcp; do command -v "$t" >/dev/null || { echo "setup: $t not on PATH" >&2; exit 1; }; done

# The project's own bootstrap: system headers for PyICU, uv + Python 3.12, deps, hooks, then the
# loud graph refresh (scripts/refresh_graphs.py exits non-zero and names any missing tool).
SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo"
timeout 600 $SUDO apt-get update -qq && timeout 900 $SUDO apt-get install -y -qq libicu-dev pkg-config \
  || echo "setup: libicu-dev install failed, the PyICU build will fail" >&2
command -v uv >/dev/null || pip install -q uv
uv python install 3.12
uv sync --all-extras
git config core.hooksPath .githooks
uv run python scripts/refresh_graphs.py
