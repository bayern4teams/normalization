#!/usr/bin/env bash
# Mirror check: the remotes `origin` (GitLab, default) and `github` must hold the same
# branches and tags at the same commits. `git push` already pushes to both (origin has two push
# URLs); this reports any ref that drifted, for example after a push that failed on one side.
# Usage: bash scripts/check_mirror.sh
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

refs() { git ls-remote --heads --tags "$1" | grep -v '\^{}' | sort -k2; }

if diff <(refs origin) <(refs github); then
  echo "check_mirror: OK — origin and github hold the same $(refs origin | wc -l) refs"
else
  echo "check_mirror: FAIL — refs above differ (< origin, > github)."
  echo "Fix a missing or behind ref with: git push <remote> <branch>  (never --force without a yes, B2)."
  exit 1
fi
