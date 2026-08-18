// Source.txt §92 Collision Dashboard. Collisions are computed live per
// run (no stored accept/reject/whitelist state exists server-side yet —
// disclosed in the M7 verification pack rather than faked here), so
// "Inspect" is the one real interactive affordance; Accept/Reject/
// Whitelist would need a persistence layer this milestone doesn't add.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getRunCollisions, listRuns } from "../api/client";
import { QueryState } from "../components/QueryState";

export function CollisionsPage() {
  const [runId, setRunId] = useState("");
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const collisionsQuery = useQuery({
    queryKey: ["run-collisions", runId],
    queryFn: () => getRunCollisions(runId),
    enabled: Boolean(runId),
  });

  return (
    <section>
      <h1>Collision Dashboard</h1>
      <p className="hint">
        New collisions created by normalization — distinct original values that now compare equal.
      </p>

      <div className="inline-form">
        <select value={runId} onChange={(e) => setRunId(e.target.value)}>
          <option value="">Select a run…</option>
          {runsQuery.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id.slice(0, 8)} ({r.profile_version}, {r.status})
            </option>
          ))}
        </select>
        {runId && <Link to={`/runs/${runId}`}>View run</Link>}
      </div>

      {runId && (
        <QueryState
          isLoading={collisionsQuery.isPending}
          isError={collisionsQuery.isError}
          error={collisionsQuery.error}
          isEmpty={collisionsQuery.data?.length === 0}
          emptyMessage="No collisions in this run."
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>Normalized value</th>
                <th>Original values</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {collisionsQuery.data?.map((c, i) => (
                <tr key={i}>
                  <td>{c.normalized_value}</td>
                  <td>
                    <ul className="plain-list">
                      {c.original_values.map((v) => (
                        <li key={v}>{v}</li>
                      ))}
                    </ul>
                  </td>
                  <td>{c.total_occurrences}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </QueryState>
      )}
    </section>
  );
}
