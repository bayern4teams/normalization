#!/usr/bin/env bash
# Run one benchmark job in its own cgroup with a hard RSS cap (kernel-enforced, unlike ulimit -v).
# usage: run_capped.sh <name> <command...>   -> systemd user scope "bench-<name>", MemoryMax 6G, no swap
set -u
name=$1; shift
exec systemd-run --user --scope --unit="bench-$name-$(date +%s)" -q \
  -p MemoryMax=6G -p MemorySwapMax=0 -p MemoryHigh=5G \
  bash -c 'ulimit -v 16777216; export MALLOC_ARENA_MAX=2 NORM_SECRET_KEY=$(cat "$BENCH_DIR/work/bench/secret.key"); exec "$@"' _ "$@"
