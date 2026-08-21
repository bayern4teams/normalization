// Source.txt §89/§94 — Runs list + create-and-execute a run against a
// real profile with real values through the live Dispatcher. Values can
// be pasted (M6) or read from a real connected source (M10 backend,
// wired into this page in M12's UI catch-up).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { createRun, listProfiles, listRuns, listSourceTables, listSources } from "../api/client";
import { FIELD_SEMANTIC_TYPES, type FieldSemanticType } from "../api/types";
import { QueryState } from "../components/QueryState";

const ACTIVE_STATUSES = new Set(["PENDING", "RUNNING"]);

export function RunsPage() {
  const queryClient = useQueryClient();
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    // M11: run execution is asynchronous — a run created just now can
    // still be PENDING/RUNNING here. Poll while any run is non-terminal
    // so the page catches its real COMPLETED/FAILED transition without
    // requiring a manual navigation away and back.
    refetchInterval: (query) => {
      const runs = query.state.data;
      const hasActiveRun = runs?.some((run) => ACTIVE_STATUSES.has(run.status));
      return hasActiveRun ? 1500 : false;
    },
  });
  const profilesQuery = useQuery({ queryKey: ["profiles"], queryFn: listProfiles });
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: listSources });

  const [profileId, setProfileId] = useState("");
  const [sourceSnapshot, setSourceSnapshot] = useState("manual-ui-run");
  const [fieldName, setFieldName] = useState("example_field");
  const [semanticType, setSemanticType] = useState<FieldSemanticType>("PERSON_NAME");
  const [rawValues, setRawValues] = useState("José García\nJose Garcia\nJOSÉ GARCÍA");

  const [valuesMode, setValuesMode] = useState<"paste" | "source">("paste");
  const [sourceId, setSourceId] = useState("");
  const [sourceTable, setSourceTable] = useState("");
  const [sourceColumn, setSourceColumn] = useState("");
  const tablesQuery = useQuery({
    queryKey: ["source-tables", sourceId],
    queryFn: () => listSourceTables(sourceId),
    enabled: Boolean(sourceId),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      if (valuesMode === "source") {
        return createRun(profileId, sourceSnapshot, {
          field_name: fieldName,
          semantic_type: semanticType,
          source: { source_id: sourceId, table: sourceTable, column: sourceColumn },
        });
      }
      const values = rawValues
        .split("\n")
        .map((v) => v.trim())
        .filter((v) => v.length > 0);
      return createRun(profileId, sourceSnapshot, {
        field_name: fieldName,
        semantic_type: semanticType,
        values,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["quality"] });
    },
  });

  const canSubmit =
    Boolean(profileId) &&
    (valuesMode === "paste" || (Boolean(sourceId) && Boolean(sourceTable) && Boolean(sourceColumn)));

  return (
    <section>
      <h1>Runs</h1>

      <form
        className="preview-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) createMutation.mutate();
        }}
      >
        <div className="preview-form__row">
          <label>
            Profile
            <select value={profileId} onChange={(e) => setProfileId(e.target.value)} required>
              <option value="">Select a profile…</option>
              {profilesQuery.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.version})
                </option>
              ))}
            </select>
          </label>
          <label>
            Source snapshot
            <input value={sourceSnapshot} onChange={(e) => setSourceSnapshot(e.target.value)} />
          </label>
          <label>
            Field name
            <input value={fieldName} onChange={(e) => setFieldName(e.target.value)} />
          </label>
          <label>
            Semantic type
            <select
              value={semanticType}
              onChange={(e) => setSemanticType(e.target.value as FieldSemanticType)}
            >
              {FIELD_SEMANTIC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="preview-form__row">
          <label>
            Values from
            <select
              value={valuesMode}
              onChange={(e) => setValuesMode(e.target.value as "paste" | "source")}
            >
              <option value="paste">Pasted values</option>
              <option value="source">Connected source (§105)</option>
            </select>
          </label>
        </div>

        {valuesMode === "paste" ? (
          <label className="preview-form__values">
            Values (one per line)
            <textarea rows={4} value={rawValues} onChange={(e) => setRawValues(e.target.value)} />
          </label>
        ) : (
          <div className="preview-form__row">
            <label>
              Source
              <select
                value={sourceId}
                onChange={(e) => {
                  setSourceId(e.target.value);
                  setSourceTable("");
                }}
              >
                <option value="">Select a source…</option>
                {sourcesQuery.data?.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Table
              <select
                value={sourceTable}
                onChange={(e) => setSourceTable(e.target.value)}
                disabled={!sourceId}
              >
                <option value="">Select a table…</option>
                {tablesQuery.data?.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Column
              <input
                value={sourceColumn}
                onChange={(e) => setSourceColumn(e.target.value)}
                placeholder="column name"
              />
            </label>
          </div>
        )}
        {valuesMode === "source" && sourcesQuery.data?.length === 0 && (
          <p className="hint">
            No sources configured on this server (NORM_SOURCES_CONFIG_PATH unset).
          </p>
        )}

        <button type="submit" disabled={createMutation.isPending || !canSubmit}>
          Create + execute run
        </button>
      </form>
      {createMutation.isError && (
        <p className="state-message state-message--error">
          Run failed: {(createMutation.error as Error).message}
        </p>
      )}
      {profilesQuery.data?.length === 0 && (
        <p className="hint">No profiles yet — create one on the Profiles page first.</p>
      )}

      <QueryState
        isLoading={runsQuery.isPending}
        isError={runsQuery.isError}
        error={runsQuery.error}
        isEmpty={runsQuery.data?.length === 0}
        emptyMessage="No runs yet."
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Profile version</th>
              <th>Status</th>
              <th>Rows</th>
              <th>Changed</th>
              <th>Warnings</th>
              <th>Errors</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runsQuery.data?.map((run) => (
              <tr key={run.id}>
                <td>
                  <Link to={`/runs/${run.id}`}>{run.id.slice(0, 8)}</Link>
                </td>
                <td>{run.profile_version}</td>
                <td>
                  <span
                    className={`status-pill status-pill--${run.status.toLowerCase()}`}
                    title={run.failure_reason ?? undefined}
                  >
                    {run.status}
                  </span>
                </td>
                <td>{run.metrics.records_processed}</td>
                <td>{run.metrics.changed_values}</td>
                <td>{run.metrics.warnings}</td>
                <td>{run.metrics.errors}</td>
                <td>{run.started_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>
    </section>
  );
}
