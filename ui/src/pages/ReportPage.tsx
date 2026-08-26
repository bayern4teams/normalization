// M21 step 3 of 3 — Report. Polls a run (M11's async execution) to
// completion, then renders each mapped column's real profile/collisions
// (M18's per-column report routes) — a browser Notification fires once,
// the moment the run first reaches a terminal status.
import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { getRun, getRunCollisions, getRunProfile } from "../api/client";
import { QueryState } from "../components/QueryState";

const ACTIVE_STATUSES = new Set(["PENDING", "RUNNING"]);

function notifyOnce(status: string) {
  if (typeof Notification === "undefined") return;
  const body = status === "COMPLETED" ? "Your normalization run finished." : `Run ended: ${status}`;
  if (Notification.permission === "granted") {
    new Notification("Normalization run complete", { body });
  }
}

export function ReportPage() {
  const { runId } = useParams<{ runId: string }>();
  const notified = useRef(false);

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ACTIVE_STATUSES.has(status) ? 1000 : false;
    },
    // A real, live-verified gap (not present in this project until this
    // milestone's own testing surfaced it): TanStack Query's default
    // pauses interval-based refetching while `document.visibilityState`
    // is "hidden" — a genuinely common real case for a page whose whole
    // point is watching a background job while the user does something
    // else in another tab. Without this, a run that finishes while the
    // tab isn't focused is never detected, and the completion
    // Notification below never fires.
    refetchIntervalInBackground: true,
  });

  const status = runQuery.data?.status;
  const columns = runQuery.data?.columns ?? [];

  useEffect(() => {
    if (typeof Notification === "undefined") return;
    if (Notification.permission === "default") {
      void Notification.requestPermission();
    }
  }, []);

  useEffect(() => {
    if (status && !ACTIVE_STATUSES.has(status) && !notified.current) {
      notified.current = true;
      notifyOnce(status);
    }
  }, [status]);

  const profileQueries = useQueries({
    queries: columns.map((c) => ({
      queryKey: ["run-profile", runId, c.table, c.column],
      queryFn: () => getRunProfile(runId as string, { table: c.table, column: c.column }),
      enabled: Boolean(runId) && status === "COMPLETED",
    })),
  });
  const collisionQueries = useQueries({
    queries: columns.map((c) => ({
      queryKey: ["run-collisions", runId, c.table, c.column],
      queryFn: () => getRunCollisions(runId as string, { table: c.table, column: c.column }),
      enabled: Boolean(runId) && status === "COMPLETED",
    })),
  });

  if (!runId) return null;

  return (
    <section>
      <h1>Report</h1>
      <p className="hint">Step 3 of 3 — real results for this run.</p>

      <QueryState isLoading={runQuery.isPending} isError={runQuery.isError} error={runQuery.error}>
        {runQuery.data && (
          <div className="detail-card">
            <p>
              <span className={`status-pill status-pill--${runQuery.data.status.toLowerCase()}`}>
                {runQuery.data.status}
              </span>{" "}
              <Link to={`/runs/${runId}`} className="hint">
                (advanced run detail)
              </Link>
            </p>
            {runQuery.data.progress && (
              <dl className="kv-list">
                <dt>Rows processed</dt>
                <dd>
                  {runQuery.data.progress.rows_done}
                  {runQuery.data.progress.total_rows_estimate
                    ? ` / ~${runQuery.data.progress.total_rows_estimate}`
                    : ""}
                </dd>
                <dt>Chunks committed</dt>
                <dd>{runQuery.data.progress.chunks_done}</dd>
                {ACTIVE_STATUSES.has(runQuery.data.status) && (
                  <>
                    <dt>Currently normalizing</dt>
                    <dd>
                      {runQuery.data.progress.current_table ?? "—"}.
                      {runQuery.data.progress.current_column ?? "—"}
                    </dd>
                  </>
                )}
                {runQuery.data.progress.rows_skipped_null_watermark > 0 && (
                  <>
                    <dt>Skipped (NULL created_at)</dt>
                    <dd>{runQuery.data.progress.rows_skipped_null_watermark}</dd>
                  </>
                )}
              </dl>
            )}
            {runQuery.data.status === "FAILED" && runQuery.data.failure_reason && (
              <p className="state-message state-message--error">
                Failed: {runQuery.data.failure_reason}
              </p>
            )}
          </div>
        )}
      </QueryState>

      {status === "COMPLETED" && columns.length > 0 && (
        <div className="card-grid">
          {columns.map((col, i) => {
            const profile = profileQueries[i];
            const collisions = collisionQueries[i];
            return (
              <div className="card" key={`${col.table}.${col.column}`}>
                <div className="card__label">
                  {col.table}.{col.column} ({col.semantic_type})
                </div>
                {profile.data && (
                  <dl className="kv-list">
                    <dt>Rows</dt>
                    <dd>{profile.data.rows}</dd>
                    <dt>Changed / unchanged</dt>
                    <dd>
                      {profile.data.changed} / {profile.data.unchanged}
                    </dd>
                    <dt>Warnings / errors</dt>
                    <dd>
                      {profile.data.warnings} / {profile.data.errors}
                    </dd>
                    <dt>Potentially lossy</dt>
                    <dd>{profile.data.potentially_lossy}</dd>
                    <dt>Collisions</dt>
                    <dd>{collisions.data?.length ?? 0}</dd>
                  </dl>
                )}
                <Link to={`/runs/${runId}?table=${col.table}&column=${col.column}`} className="hint">
                  Drill down (advanced view)
                </Link>
              </div>
            );
          })}
        </div>
      )}

      {status === "COMPLETED" && columns.length === 0 && (
        <p className="hint">
          This run has no per-column breakdown — see the{" "}
          <Link to={`/runs/${runId}`}>advanced run detail</Link> instead.
        </p>
      )}
    </section>
  );
}
