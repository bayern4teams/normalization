// DB-clone-and-normalize — clone job progress + errors report. Polls via
// react-query's built-in refetchInterval (the one genuinely new UI idiom
// this feature needs) while the job is PENDING_DB_CREATE/SCHEMA_READY/
// RUNNING; stops once it reaches a terminal status. Errors section is the
// same table + QueryState + pagination layout as RunDetailPage's errors
// section (decision #9: a complete, paginated error report).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { getCloneJob, getCloneJobErrors, startCloneJob, verifyCloneJobDatabase } from "../api/client";
import { QueryState } from "../components/QueryState";

const TERMINAL = new Set(["COMPLETED", "FAILED"]);
const ERRORS_PAGE_SIZE = 50;

export function CloneJobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const queryClient = useQueryClient();
  const [errorsOffset, setErrorsOffset] = useState(0);

  const jobQuery = useQuery({
    queryKey: ["clone-job", jobId],
    queryFn: () => getCloneJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data && TERMINAL.has(query.state.data.status) ? false : 2000),
  });

  const errorsQuery = useQuery({
    queryKey: ["clone-job-errors", jobId, errorsOffset],
    queryFn: () => getCloneJobErrors(jobId as string, ERRORS_PAGE_SIZE, errorsOffset),
    enabled: Boolean(jobId),
    // Same polling condition as jobQuery — errors accumulate as the job
    // runs, so a one-shot fetch at mount time (typically PENDING_DB_CREATE,
    // before Phase 2 has produced any) would show a permanently-stale
    // "No errors" even after real errors are recorded.
    refetchInterval: () => (jobQuery.data && TERMINAL.has(jobQuery.data.status) ? false : 2000),
  });

  const verifyMutation = useMutation({
    mutationFn: () => verifyCloneJobDatabase(jobId as string),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["clone-job", jobId] }),
  });
  const startMutation = useMutation({
    mutationFn: () => startCloneJob(jobId as string),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["clone-job", jobId] }),
  });

  if (!jobId) return null;
  const job = jobQuery.data;

  return (
    <section>
      <h1>Clone job</h1>
      <QueryState isLoading={jobQuery.isPending} isError={jobQuery.isError} error={jobQuery.error}>
        {job && (
          <div className="detail-card">
            <p>
              <span className={`status-pill status-pill--${job.status.toLowerCase()}`}>{job.status}</span>
            </p>
            <dl className="kv-list">
              <dt>Source</dt>
              <dd>
                {job.source_connection_id} / {job.source_database}
              </dd>
              <dt>Destination</dt>
              <dd>
                {job.destination_connection_id} / {job.destination_database}
              </dd>
              <dt>Tables</dt>
              <dd>{job.tables.length}</dd>
              <dt>Rows cloned so far</dt>
              <dd>{job.progress.rows_done}</dd>
              <dt>Tables completed</dt>
              <dd>
                {job.progress.tables_completed.length} / {job.tables.length}
              </dd>
              <dt>Current table</dt>
              <dd>{job.progress.current_table ?? "—"}</dd>
            </dl>

            {job.status === "PENDING_DB_CREATE" && (
              <>
                <h3>1. Create the destination database</h3>
                <p className="hint">
                  This app never issues CREATE DATABASE itself. Run this command against the
                  destination server by hand, then click Verify.
                </p>
                <pre className="code-block">CREATE DATABASE {job.destination_database};</pre>
                <button type="button" disabled={verifyMutation.isPending} onClick={() => verifyMutation.mutate()}>
                  Verify database exists + create empty tables
                </button>
                {verifyMutation.isError && (
                  <p className="state-message state-message--error">
                    {(verifyMutation.error as Error).message}
                  </p>
                )}
              </>
            )}

            {job.status === "SCHEMA_READY" && (
              <>
                <h3>2. Start populating</h3>
                <p className="hint">
                  Every table's schema has been created empty. Starting streams, normalizes, and
                  populates every row — a background job you can navigate away from and come back
                  to poll.
                </p>
                <button type="button" disabled={startMutation.isPending} onClick={() => startMutation.mutate()}>
                  Start clone
                </button>
                {startMutation.isError && (
                  <p className="state-message state-message--error">
                    {(startMutation.error as Error).message}
                  </p>
                )}
              </>
            )}

            {job.status === "RUNNING" && (
              <p className="hint">
                Running — this page polls every 2 seconds. If the app restarts mid-run, clicking
                Start again on this job resumes from the last committed row instead of redoing
                already-cloned rows.
              </p>
            )}

            {job.status === "FAILED" && job.error && (
              <p className="state-message state-message--error">Job failed: {job.error}</p>
            )}
          </div>
        )}
      </QueryState>

      <h3>Errors</h3>
      <p className="hint">
        A row/column that failed to normalize keeps its original raw value in the clone (never
        blank, never skipped) — recorded here with full detail.
      </p>
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
              <th>Table.Field</th>
              <th>Row</th>
              <th>Error</th>
              <th>Safe preview</th>
            </tr>
          </thead>
          <tbody>
            {errorsQuery.data?.map((e, i) => (
              <tr key={i}>
                <td>{e.field}</td>
                <td>{e.record_ref}</td>
                <td>{e.error}</td>
                <td>{e.safe_preview}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="inline-form">
          <button
            type="button"
            disabled={errorsOffset === 0}
            onClick={() => setErrorsOffset((o) => Math.max(0, o - ERRORS_PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            type="button"
            disabled={(errorsQuery.data?.length ?? 0) < ERRORS_PAGE_SIZE}
            onClick={() => setErrorsOffset((o) => o + ERRORS_PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </QueryState>
    </section>
  );
}
