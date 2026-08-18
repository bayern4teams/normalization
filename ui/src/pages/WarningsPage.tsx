// Source.txt §89 Warnings — real per-value warnings for a selected run.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getRunValues, listRuns } from "../api/client";
import { QueryState } from "../components/QueryState";

export function WarningsPage() {
  const [runId, setRunId] = useState("");
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const valuesQuery = useQuery({
    queryKey: ["run-values", runId],
    queryFn: () => getRunValues(runId),
    enabled: Boolean(runId),
  });

  const warningRows = (valuesQuery.data ?? []).flatMap((row, index) =>
    row.result.warnings.map((warning) => ({ index, original: row.original, warning })),
  );

  return (
    <section>
      <h1>Warnings</h1>
      <div className="inline-form">
        <select value={runId} onChange={(e) => setRunId(e.target.value)}>
          <option value="">Select a run…</option>
          {runsQuery.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id.slice(0, 8)} ({r.metrics.warnings} warnings)
            </option>
          ))}
        </select>
      </div>

      {runId && (
        <QueryState
          isLoading={valuesQuery.isPending}
          isError={valuesQuery.isError}
          error={valuesQuery.error}
          isEmpty={warningRows.length === 0}
          emptyMessage="No warnings in this run."
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>Row</th>
                <th>Original</th>
                <th>Warning</th>
              </tr>
            </thead>
            <tbody>
              {warningRows.map((row, i) => (
                <tr key={i}>
                  <td>{row.index}</td>
                  <td>{row.original ?? <em>null</em>}</td>
                  <td>{row.warning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </QueryState>
      )}
    </section>
  );
}
