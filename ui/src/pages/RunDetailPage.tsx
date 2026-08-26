// Source.txt §94 Run detail + §119 Change Impact UI.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getImpact, getRun, getRunCollisions, getRunErrors, listRuns } from "../api/client";
import { QueryState } from "../components/QueryState";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [compareTarget, setCompareTarget] = useState("");

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId as string),
    enabled: Boolean(runId),
    // M11: run execution is asynchronous — poll while this run is still
    // PENDING/RUNNING so the page catches its real COMPLETED/FAILED
    // transition (and Change Impact becoming available) without a
    // manual refresh.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "PENDING" || status === "RUNNING" ? 1500 : false;
    },
    // M21 finding, applied here too: TanStack Query's default pauses
    // interval refetching while the tab is backgrounded/hidden — this
    // run can finish while the user is on another tab, and this page
    // should still catch it without a manual reload.
    refetchIntervalInBackground: true,
  });
  const impactQuery = useQuery({
    queryKey: ["impact", runId],
    queryFn: () => getImpact(runId as string),
    enabled: Boolean(runId) && runQuery.data?.status === "COMPLETED",
    retry: false,
  });
  const errorsQuery = useQuery({
    queryKey: ["run-errors", runId],
    queryFn: () => getRunErrors(runId as string),
    enabled: Boolean(runId),
  });
  const collisionsQuery = useQuery({
    queryKey: ["run-collisions", runId],
    queryFn: () => getRunCollisions(runId as string),
    enabled: Boolean(runId),
  });
  const otherRunsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });

  if (!runId) return null;

  return (
    <section>
      <h1>Run detail</h1>
      <QueryState isLoading={runQuery.isPending} isError={runQuery.isError} error={runQuery.error}>
        {runQuery.data && (
          <div className="detail-card">
            <p>
              Profile <Link to={`/profiles/${runQuery.data.profile_id}`}>{runQuery.data.profile_id}</Link>{" "}
              @ <strong>{runQuery.data.profile_version}</strong> —{" "}
              <span className={`status-pill status-pill--${runQuery.data.status.toLowerCase()}`}>
                {runQuery.data.status}
              </span>
            </p>
            <dl className="kv-list">
              <dt>Source snapshot</dt>
              <dd>{runQuery.data.source_snapshot}</dd>
              <dt>Started</dt>
              <dd>{runQuery.data.started_at}</dd>
              <dt>Finished</dt>
              <dd>{runQuery.data.finished_at ?? "—"}</dd>
              <dt>Rows processed</dt>
              <dd>{runQuery.data.metrics.records_processed}</dd>
              <dt>Changed / unchanged</dt>
              <dd>
                {runQuery.data.metrics.changed_values} / {runQuery.data.metrics.unchanged_values}
              </dd>
              <dt>Warnings / errors</dt>
              <dd>
                {runQuery.data.metrics.warnings} / {runQuery.data.metrics.errors}
              </dd>
              <dt>env_id</dt>
              <dd>{runQuery.data.env_id}</dd>
            </dl>
            {runQuery.data.status === "FAILED" && runQuery.data.failure_reason && (
              <p className="state-message state-message--error">
                Failed: {runQuery.data.failure_reason}
              </p>
            )}
            <p className="hint">
              Per-run library version listing is not wired up yet (env_id is a real hash, but its
              human-readable expansion isn't exposed via this API at this milestone).
            </p>
          </div>
        )}
      </QueryState>

      {runQuery.data?.status === "COMPLETED" && (
        <>
          <h3>Change impact (§119)</h3>
          <QueryState
            isLoading={impactQuery.isPending}
            isError={impactQuery.isError}
            error={impactQuery.error}
          >
            {impactQuery.data && (
              <div className="card-grid">
                <div className="card">
                  <div className="card__value">{impactQuery.data.total_values}</div>
                  <div className="card__label">Rows affected</div>
                </div>
                <div className="card">
                  <div className="card__value">
                    {impactQuery.data.unique_before} → {impactQuery.data.unique_after}
                  </div>
                  <div className="card__label">Unique values</div>
                </div>
                <div className="card">
                  <div className="card__value">{impactQuery.data.new_collisions}</div>
                  <div className="card__label">New collisions</div>
                </div>
                <div className="card">
                  <div className="card__value">{impactQuery.data.lossy_count}</div>
                  <div className="card__label">Lossy operations</div>
                </div>
                <div className="card">
                  <div className="card__value">
                    {impactQuery.data.avg_length_before.toFixed(1)} →{" "}
                    {impactQuery.data.avg_length_after.toFixed(1)}
                  </div>
                  <div className="card__label">Avg length</div>
                </div>
              </div>
            )}
            {impactQuery.data && impactQuery.data.warnings.length > 0 && (
              <ul className="warning-list">
                {impactQuery.data.warnings.map((w, i) => (
                  <li key={i}>⚠ {w}</li>
                ))}
              </ul>
            )}
          </QueryState>
        </>
      )}

      <h3>Errors</h3>
      <QueryState
        isLoading={errorsQuery.isPending}
        isError={errorsQuery.isError}
        error={errorsQuery.error}
        isEmpty={errorsQuery.data?.length === 0}
        emptyMessage="No errors."
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Record</th>
              <th>Error</th>
              <th>Severity</th>
              <th>Safe preview</th>
            </tr>
          </thead>
          <tbody>
            {errorsQuery.data?.map((e, i) => (
              <tr key={i}>
                <td>{e.record_ref}</td>
                <td>{e.error}</td>
                <td>{e.severity}</td>
                <td>{e.safe_preview}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>

      <h3>
        Collisions {collisionsQuery.data && collisionsQuery.data.length > 0 && (
          <Link to="/collisions" className="hint">
            (review in Collision Dashboard)
          </Link>
        )}
      </h3>
      <QueryState
        isLoading={collisionsQuery.isPending}
        isError={collisionsQuery.isError}
        error={collisionsQuery.error}
        isEmpty={collisionsQuery.data?.length === 0}
        emptyMessage="No collisions detected."
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Normalized value</th>
              <th>Original values</th>
              <th>Occurrences</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {collisionsQuery.data?.map((c) => (
              <tr key={c.normalized_value}>
                <td>{c.normalized_value}</td>
                <td>{c.original_values.join(", ")}</td>
                <td>{c.total_occurrences}</td>
                <td>
                  {c.decision ? (
                    <span
                      className={`status-pill status-pill--${c.decision.decision.toLowerCase()}`}
                    >
                      {c.decision.decision}
                    </span>
                  ) : (
                    <span className="hint">not reviewed</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>

      <h3>Compare with another run</h3>
      <div className="inline-form">
        <select value={compareTarget} onChange={(e) => setCompareTarget(e.target.value)}>
          <option value="">Select a run…</option>
          {otherRunsQuery.data
            ?.filter((r) => r.id !== runId)
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.id.slice(0, 8)} ({r.profile_version})
              </option>
            ))}
        </select>
        <button
          type="button"
          disabled={!compareTarget}
          onClick={() => navigate(`/compare?a=${runId}&b=${compareTarget}`)}
        >
          Compare
        </button>
      </div>
    </section>
  );
}
