#!/usr/bin/env bash
# Every 10 s: ClickHouse resident memory, its MemoryTracking metric, and the
# destination database's active parts and running merges. TSV on stdout.
# usage: ch_sampler.sh <dst_db>   (normbench ClickHouse on :8124 only)
set -u
q() { curl -s 'http://localhost:8124/?user=readonly_user&password=readonly_pass' --data-binary "$1"; }
echo -e "ts\tresident_bytes\tmemory_tracking\tactive_parts\tmerges\tmerge_mem_bytes\tdst_rows"
while true; do
  r=$(q "SELECT (SELECT value FROM system.asynchronous_metrics WHERE metric='MemoryResident'), (SELECT value FROM system.metrics WHERE metric='MemoryTracking'), (SELECT count() FROM system.parts WHERE database='$1' AND active), (SELECT count() FROM system.merges WHERE database='$1'), (SELECT ifNull(sum(memory_usage),0) FROM system.merges WHERE database='$1'), (SELECT ifNull(sum(rows),0) FROM system.parts WHERE database='$1' AND active) FORMAT TSV")
  echo -e "$(date -Is)\t$r"
  sleep 10
done
