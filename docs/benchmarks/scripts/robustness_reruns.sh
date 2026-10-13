#!/usr/bin/env bash
# fix/robustness benchmark reruns (REPORT.md §9). Needs .tmp/robustness/fields_d5.json = {"vals": {"qty": "NUMERIC", "amount": "MONEY"}} and the rb_d5src twin of d5src on :5436.
# fix/robustness benchmark reruns, one at a time, each in its own capped cgroup.
# Spool for the ClickHouse source goes to .tmp/spool (/tmp is a 436 MB partition).
set -u
cd /home/bayern/Projects/normalization
export TMPDIR=/home/bayern/Projects/normalization/.tmp/spool
O=.tmp/robustness/bench
R=".tmp/bench/run_capped.sh"
run() { name=$1; shift; s=$(date +%s); echo "=== $name start $(date -Is)"; $R "$name" uv run python docs/benchmarks/scripts/clone_bench.py "$@" --out "$O/$name.json" > "$O/$name.log" 2>&1; echo "=== $name exit $? wall $(( $(date +%s)-s ))s"; tail -1 "$O/$name.log"; }
run d1_nul      --engine clickhouse --src-db d1src         --dst-db rb_d1_nul    --field-configs .tmp/bench/d1_fields.json --no-autodetect
run ch_badutf8  --engine clickhouse --src-db d1src_badutf8 --dst-db rb_badutf8   --field-configs .tmp/bench/d1_fields.json --no-autodetect
run d5_ch       --engine clickhouse --src-db d5src         --dst-db rb_d5_ch     --field-configs .tmp/robustness/fields_d5.json --no-autodetect --country US --locale en-US
run d5_pg       --engine postgres   --src-db rb_d5src      --dst-db rb_d5_pg     --field-configs .tmp/robustness/fields_d5.json --no-autodetect --country US --locale en-US
run france_default --engine postgres --src-db ref_france   --dst-db rb_france    --no-autodetect --country FR --locale fr-FR
run pagila      --engine postgres   --src-db pagila --src-port 5438 --dst-db rb_pagila --country US --locale en-US
run tpch_sf1    --engine clickhouse --src-db tpch_sf1      --dst-db rb_tpch_sf1
run norway      --engine postgres   --src-db ref_norway    --dst-db rb_norway    --country NO --locale nb-NO
run ontime      --engine clickhouse --src-db ontime        --dst-db rb_ontime    --country US --locale en-US
run gleif       --engine postgres   --src-db ref_gleif     --dst-db rb_gleif
echo "=== all done $(date -Is)"
