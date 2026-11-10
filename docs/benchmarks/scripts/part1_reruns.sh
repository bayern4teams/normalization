#!/usr/bin/env bash
# PART1 completion reruns (REPORT.md §11): every benchmark that exposed a bug in §6-§10, on the
# combined branches, one at a time, each in its own capped cgroup (run_capped.sh: 6 GB, no swap,
# ulimit -v 16 GB). Run from a checkout of the combined branches; writes $BENCH_DIR/work/part1/bench/.
set -u
: "${BENCH_DIR:?set BENCH_DIR to the benchmark folder, e.g. /home/benchmark on the benchmark machine}"
cd "${1:-.}"
export TMPDIR="$BENCH_DIR/work/spool"
mkdir -p "$TMPDIR" "$BENCH_DIR/work/part1/bench"
O="$BENCH_DIR/work/part1/bench"
R="docs/benchmarks/scripts/run_capped.sh"
run() { name=$1; shift; s=$(date +%s); echo "=== $name start $(date -Is)"; $R "p1-$name" uv run python docs/benchmarks/scripts/clone_bench.py "$@" --out "$O/$name.json" > "$O/$name.log" 2>&1; echo "=== $name exit $? wall $(( $(date +%s)-s ))s"; tail -1 "$O/$name.log"; }
run d1_nul      --engine clickhouse --src-db d1src         --dst-db p1_d1_nul   --field-configs docs/benchmarks/configs/d1_fields.json --no-autodetect
run ch_badutf8  --engine clickhouse --src-db d1src_badutf8 --dst-db p1_badutf8  --field-configs docs/benchmarks/configs/d1_fields.json --no-autodetect
run d5_ch       --engine clickhouse --src-db d5src         --dst-db p1_d5_ch    --field-configs docs/benchmarks/configs/fields_d5.json --no-autodetect --country US --locale en-US
run d5_pg       --engine postgres   --src-db rb_d5src      --dst-db p1_d5_pg    --field-configs docs/benchmarks/configs/fields_d5.json --no-autodetect --country US --locale en-US
run chinook     --engine postgres   --src-db chinook       --dst-db p1_chinook  --country US --locale en-US
run raha        --engine postgres   --src-db raha          --dst-db p1_raha     --country US --locale en-US
run uk          --engine postgres   --src-db uk_price_paid --dst-db p1_uk       --country GB --locale en-GB
run france      --engine postgres   --src-db ref_france    --dst-db p1_france   --no-autodetect --country FR --locale fr-FR
run luxembourg  --engine postgres   --src-db ref_lu        --dst-db p1_lu       --country LU
run pagila      --engine postgres   --src-db pagila --src-port 5438 --dst-db p1_pagila --country US --locale en-US
run norway      --engine postgres   --src-db ref_norway    --dst-db p1_norway   --country NO --locale nb-NO
run gleif       --engine postgres   --src-db ref_gleif     --dst-db p1_gleif
run nyc_taxi    --engine clickhouse --src-db nyc_taxi      --dst-db p1_nyc_taxi
run tpch_sf1    --engine clickhouse --src-db tpch_sf1      --dst-db p1_tpch_sf1
run ontime      --engine clickhouse --src-db ontime        --dst-db p1_ontime   --country US --locale en-US
run tpch_sf10   --engine clickhouse --src-db tpch_sf10     --dst-db p1_tpch_sf10
echo "=== all done $(date -Is)"
