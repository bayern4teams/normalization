// Source.txt §91 Field Detail UI.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { getImpact, getRunCollisions, getRunProfile, getRunValues, listFields, listRuns } from "../api/client";
import { ExplanationPanel } from "../components/ExplanationPanel";
import { QueryState } from "../components/QueryState";

export function FieldDetailPage() {
  const { fieldRef } = useParams<{ fieldRef: string }>();
  const decodedFieldRef = fieldRef ? decodeURIComponent(fieldRef) : "";
  const [runId, setRunId] = useState("");

  const fieldsQuery = useQuery({ queryKey: ["fields"], queryFn: listFields });
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const field = fieldsQuery.data?.find((f) => f.field_ref === decodedFieldRef);

  const profileQuery = useQuery({
    queryKey: ["run-profile", runId],
    queryFn: () => getRunProfile(runId),
    enabled: Boolean(runId),
    retry: false,
  });
  const impactQuery = useQuery({
    queryKey: ["impact", runId],
    queryFn: () => getImpact(runId),
    enabled: Boolean(runId),
    retry: false,
  });
  const collisionsQuery = useQuery({
    queryKey: ["run-collisions", runId],
    queryFn: () => getRunCollisions(runId),
    enabled: Boolean(runId),
  });
  const valuesQuery = useQuery({
    queryKey: ["run-values", runId],
    queryFn: () => getRunValues(runId),
    enabled: Boolean(runId),
  });

  return (
    <section>
      <h1>Field detail</h1>
      <h2>{decodedFieldRef}</h2>
      {field && (
        <p>
          Detected semantic type: <strong>{field.semantic_type}</strong> — referenced by{" "}
          {field.profile_ids.length} profile(s).
        </p>
      )}

      <p className="hint">
        Pick a run to inspect this field's actual observed behavior (completeness, distributions,
        collisions, trace) — the field's semantic type above is static profile configuration; the
        numbers below come from a real executed run.
      </p>
      <div className="inline-form">
        <select value={runId} onChange={(e) => setRunId(e.target.value)}>
          <option value="">Select a run…</option>
          {runsQuery.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id.slice(0, 8)} ({r.status})
            </option>
          ))}
        </select>
      </div>

      {runId && (
        <>
          <h3>Completeness / distribution</h3>
          <QueryState
            isLoading={profileQuery.isPending}
            isError={profileQuery.isError}
            error={profileQuery.error}
          >
            {profileQuery.data && (
              <dl className="kv-list">
                <dt>Rows</dt>
                <dd>{profileQuery.data.rows}</dd>
                <dt>Changed / unchanged</dt>
                <dd>
                  {profileQuery.data.changed} / {profileQuery.data.unchanged}
                </dd>
                <dt>Warnings / errors</dt>
                <dd>
                  {profileQuery.data.warnings} / {profileQuery.data.errors}
                </dd>
                <dt>Potentially lossy</dt>
                <dd>{profileQuery.data.potentially_lossy}</dd>
              </dl>
            )}
          </QueryState>

          <h3>Before / after (unique ratio)</h3>
          <QueryState isLoading={impactQuery.isPending} isError={impactQuery.isError} error={impactQuery.error}>
            {impactQuery.data && (
              <dl className="kv-list">
                <dt>Unique before / after</dt>
                <dd>
                  {impactQuery.data.unique_before} / {impactQuery.data.unique_after} (
                  {impactQuery.data.total_values > 0
                    ? ((impactQuery.data.unique_after / impactQuery.data.total_values) * 100).toFixed(1)
                    : "0"}
                  % unique after)
                </dd>
                <dt>New collisions</dt>
                <dd>{impactQuery.data.new_collisions}</dd>
                <dt>Null before / after</dt>
                <dd>
                  {impactQuery.data.null_before} / {impactQuery.data.null_after}
                </dd>
              </dl>
            )}
          </QueryState>

          <h3>Collision impact</h3>
          <QueryState
            isLoading={collisionsQuery.isPending}
            isError={collisionsQuery.isError}
            error={collisionsQuery.error}
            isEmpty={collisionsQuery.data?.length === 0}
            emptyMessage="No collisions."
          >
            <ul className="plain-list">
              {collisionsQuery.data?.map((c, i) => (
                <li key={i}>
                  "{c.normalized_value}" ← {c.original_values.join(", ")} ({c.total_occurrences})
                </li>
              ))}
            </ul>
          </QueryState>

          <h3>Sample values + rule trace</h3>
          <QueryState
            isLoading={valuesQuery.isPending}
            isError={valuesQuery.isError}
            error={valuesQuery.error}
            isEmpty={valuesQuery.data?.length === 0}
          >
            <table className="data-table">
              <tbody>
                {valuesQuery.data?.slice(0, 10).map((row, i) => (
                  <tr key={i}>
                    <td>
                      <div className="sample-row">
                        <span>{row.original ?? <em>null</em>}</span>
                        <span>→ {row.result.display ?? <em>null</em>}</span>
                      </div>
                      <ExplanationPanel result={row.result} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </QueryState>
        </>
      )}
    </section>
  );
}
