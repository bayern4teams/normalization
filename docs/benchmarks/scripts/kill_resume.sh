#!/usr/bin/env bash
# Kill a clone job mid-run the way an OOM kill does (SIGKILL to its whole
# cgroup scope: the API process and its worker pool), then resume it through
# the API. usage: kill_resume.sh <name> <kill_after_rows> <clone_bench args...>
# Destination row counts are polled from the destination itself.
set -u
cd /home/bayern/Projects/normalization
name=$1; kill_after=$2; shift 2
O=.tmp/followups/bench
engine=$(echo "$@" | sed -n 's/.*--engine \([a-z]*\).*/\1/p')
dst=$(echo "$@" | sed -n 's/.*--dst-db \([A-Za-z0-9_]*\).*/\1/p')
rows() {
  if [ "$engine" = clickhouse ]; then
    curl -s 'http://localhost:8124/?user=readonly_user&password=readonly_pass' --data-binary "SELECT ifNull(sum(rows),0) FROM system.parts WHERE database='$dst' AND active"
  else
    PGPASSWORD=normalization psql -h localhost -p 5535 -U normalization -d "$dst" -Atc "select coalesce(sum(n_live_tup),0) from pg_stat_user_tables" 2>/dev/null || echo 0
  fi
}
s=$(date +%s)
.tmp/bench/run_capped.sh "$name" uv run python docs/benchmarks/scripts/clone_bench.py "$@" --out "$O/$name.json" > "$O/$name.log" 2>&1 &
until [ "$(rows)" -ge "$kill_after" ] 2>/dev/null; do sleep 2; done
scope=$(systemctl --user list-units "bench-$name-*" --plain --no-legend | awk '{print $1}' | head -1)
systemctl --user kill --signal=SIGKILL "$scope"
echo "killed $scope at $(date -Is) after $(( $(date +%s)-s ))s with $(rows) destination rows"
wait
job=$(PGPASSWORD=normalization psql -h localhost -p 5535 -U normalization -d normalization -Atc \
  "select job_id from normalization_clone_jobs where data::jsonb->>'destination_database' = '$dst' limit 1")
echo "job $job status $(PGPASSWORD=normalization psql -h localhost -p 5535 -U normalization -d normalization -Atc "select data::jsonb->>'status' from normalization_clone_jobs where job_id='$job'")"
r=$(date +%s)
.tmp/bench/run_capped.sh "$name-resume" uv run python docs/benchmarks/scripts/clone_bench.py "$@" --resume-job "$job" --out "$O/$name-resume.json" > "$O/$name-resume.log" 2>&1
echo "resume exit $? wall $(( $(date +%s)-r ))s"; tail -1 "$O/$name-resume.log"
