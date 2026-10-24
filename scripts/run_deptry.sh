#!/usr/bin/env bash
# M4/K4: deptry per uv-workspace member (each against its OWN pyproject), then the root
# (tests, scripts; packages/ excluded there). deptry reads one pyproject at a time.
set -euo pipefail
cd "$(dirname "$0")/.."
status=0
for p in packages/*/; do
  echo "== $p"
  (cd "$p" && uv run --project ../.. deptry src) || status=1
done
echo "== root"
uv run deptry . || status=1
exit $status
