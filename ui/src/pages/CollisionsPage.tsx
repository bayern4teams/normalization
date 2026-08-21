// Source.txt §92 Collision Dashboard. Accept rule/Reject rule/Whitelist
// collision are real, persisted decisions as of M11
// (POST /runs/{id}/collisions/decision) — wired into this page in M12's
// UI catch-up. "Change configuration" links back to the profile/rules
// pages rather than adding new state of its own (no separate backend
// concept exists for it).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getRunCollisions, listRuns, recordCollisionDecision } from "../api/client";
import type { CollisionDecisionType } from "../api/types";
import { QueryState } from "../components/QueryState";

export function CollisionsPage() {
  const [runId, setRunId] = useState("");
  const [decidedBy, setDecidedBy] = useState("ui-user");
  const queryClient = useQueryClient();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const collisionsQuery = useQuery({
    queryKey: ["run-collisions", runId],
    queryFn: () => getRunCollisions(runId),
    enabled: Boolean(runId),
  });

  const decideMutation = useMutation({
    mutationFn: (vars: { normalizedValue: string; decision: CollisionDecisionType }) =>
      recordCollisionDecision(runId, {
        normalized_value: vars.normalizedValue,
        decision: vars.decision,
        decided_by: decidedBy || "ui-user",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run-collisions", runId] });
    },
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
        <input
          placeholder="Decided by"
          value={decidedBy}
          onChange={(e) => setDecidedBy(e.target.value)}
        />
        {runId && <Link to={`/runs/${runId}`}>View run</Link>}
      </div>
      {decideMutation.isError && (
        <p className="state-message state-message--error">
          Decision failed: {(decideMutation.error as Error).message}
        </p>
      )}

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
                <th>Decision</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {collisionsQuery.data?.map((c) => (
                <tr key={c.normalized_value}>
                  <td>{c.normalized_value}</td>
                  <td>
                    <ul className="plain-list">
                      {c.original_values.map((v) => (
                        <li key={v}>{v}</li>
                      ))}
                    </ul>
                  </td>
                  <td>{c.total_occurrences}</td>
                  <td>
                    {c.decision ? (
                      <span
                        className={`status-pill status-pill--${c.decision.decision.toLowerCase()}`}
                        title={`by ${c.decision.decided_by} at ${c.decision.decided_at}`}
                      >
                        {c.decision.decision}
                      </span>
                    ) : (
                      <span className="hint">not reviewed</span>
                    )}
                  </td>
                  <td className="inline-form">
                    <button
                      type="button"
                      disabled={decideMutation.isPending}
                      onClick={() =>
                        decideMutation.mutate({
                          normalizedValue: c.normalized_value,
                          decision: "ACCEPTED",
                        })
                      }
                    >
                      Accept rule
                    </button>
                    <button
                      type="button"
                      disabled={decideMutation.isPending}
                      onClick={() =>
                        decideMutation.mutate({
                          normalizedValue: c.normalized_value,
                          decision: "REJECTED",
                        })
                      }
                    >
                      Reject rule
                    </button>
                    <button
                      type="button"
                      disabled={decideMutation.isPending}
                      onClick={() =>
                        decideMutation.mutate({
                          normalizedValue: c.normalized_value,
                          decision: "WHITELISTED",
                        })
                      }
                    >
                      Whitelist
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </QueryState>
      )}
    </section>
  );
}
