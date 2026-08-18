// Source.txt §96/§121 — Normalization Comparison Workspace (A/B).
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { compareRuns, getRunValues, listRuns } from "../api/client";
import { QueryState } from "../components/QueryState";

function reasonFor(
  a: { display: string | null; normalization_status: string },
  b: { display: string | null; normalization_status: string } | undefined,
): string {
  if (!b) return "no matching original value in run B's sample";
  if (a.normalization_status !== b.normalization_status) {
    return `status differs: A=${a.normalization_status} vs B=${b.normalization_status}`;
  }
  if (a.display !== b.display) return "display value differs";
  return "no difference";
}

export function ComparisonPage() {
  const [searchParams] = useSearchParams();
  const [runIdA, setRunIdA] = useState(searchParams.get("a") ?? "");
  const [runIdB, setRunIdB] = useState(searchParams.get("b") ?? "");

  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const summaryQuery = useQuery({
    queryKey: ["compare-summary", runIdA, runIdB],
    queryFn: () => compareRuns(runIdA, runIdB),
    enabled: Boolean(runIdA) && Boolean(runIdB) && runIdA !== runIdB,
    retry: false,
  });
  const valuesAQuery = useQuery({
    queryKey: ["run-values", runIdA],
    queryFn: () => getRunValues(runIdA),
    enabled: Boolean(runIdA),
  });
  const valuesBQuery = useQuery({
    queryKey: ["run-values", runIdB],
    queryFn: () => getRunValues(runIdB),
    enabled: Boolean(runIdB),
  });

  const bByOriginal = new Map((valuesBQuery.data ?? []).map((row) => [row.original, row.result]));

  return (
    <section>
      <h1>Comparison Workspace</h1>
      <div className="preview-form__row">
        <label>
          Run A (v1)
          <select value={runIdA} onChange={(e) => setRunIdA(e.target.value)}>
            <option value="">Select…</option>
            {runsQuery.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id.slice(0, 8)} ({r.profile_version})
              </option>
            ))}
          </select>
        </label>
        <label>
          Run B (v2)
          <select value={runIdB} onChange={(e) => setRunIdB(e.target.value)}>
            <option value="">Select…</option>
            {runsQuery.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id.slice(0, 8)} ({r.profile_version})
              </option>
            ))}
          </select>
        </label>
      </div>

      {runIdA && runIdB && runIdA !== runIdB && (
        <>
          <h3>Aggregate metrics (§96)</h3>
          <QueryState
            isLoading={summaryQuery.isPending}
            isError={summaryQuery.isError}
            error={summaryQuery.error}
          >
            {summaryQuery.data && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>A ({summaryQuery.data.a.profile_version})</th>
                    <th>B ({summaryQuery.data.b.profile_version})</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Unique values</td>
                    <td>{summaryQuery.data.a.unique_values}</td>
                    <td>{summaryQuery.data.b.unique_values}</td>
                  </tr>
                  <tr>
                    <td>Unique ratio</td>
                    <td>{summaryQuery.data.a.unique_ratio.toFixed(3)}</td>
                    <td>{summaryQuery.data.b.unique_ratio.toFixed(3)}</td>
                  </tr>
                  <tr>
                    <td>Invalid rate</td>
                    <td>{summaryQuery.data.a.invalid_rate.toFixed(3)}</td>
                    <td>{summaryQuery.data.b.invalid_rate.toFixed(3)}</td>
                  </tr>
                  <tr>
                    <td>Changed between A and B</td>
                    <td colSpan={2}>
                      {summaryQuery.data.changed_between_a_and_b} (
                      {(summaryQuery.data.changed_between_a_and_b_pct * 100).toFixed(1)}%)
                    </td>
                  </tr>
                  <tr>
                    <td>Collision rate delta (B − A)</td>
                    <td colSpan={2}>{summaryQuery.data.collision_rate_delta.toFixed(3)}</td>
                  </tr>
                </tbody>
              </table>
            )}
          </QueryState>

          <h3>Value-by-value (§121)</h3>
          <QueryState
            isLoading={valuesAQuery.isPending}
            isError={valuesAQuery.isError}
            error={valuesAQuery.error}
            isEmpty={valuesAQuery.data?.length === 0}
          >
            <table className="data-table">
              <thead>
                <tr>
                  <th>Value</th>
                  <th>v1 (A)</th>
                  <th>v2 (B)</th>
                  <th>Difference</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {valuesAQuery.data?.map((row, i) => {
                  const bResult = row.original !== null ? bByOriginal.get(row.original) : undefined;
                  const differs = bResult ? row.result.display !== bResult.display : true;
                  return (
                    <tr key={i}>
                      <td>{row.original ?? <em>null</em>}</td>
                      <td>{row.result.display ?? <em>null</em>}</td>
                      <td>{bResult?.display ?? <em>—</em>}</td>
                      <td>{differs ? "yes" : "no"}</td>
                      <td>{reasonFor(row.result, bResult)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </QueryState>
        </>
      )}
    </section>
  );
}
