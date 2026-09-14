// DB-clone-and-normalize — new clone job: connection -> database -> (every
// table, listed) -> per-table column config -> submit. Every table in the
// chosen origin database is cloned automatically (decision #3); this page
// only decides, per column, a semantic type or passthrough. No stepper
// component — plain local state + conditional sections, matching the
// codebase's existing page idiom (PreviewPage/RunsPage).
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCloneJob, listColumns, listConnections, listDatabases, listTables } from "../api/client";
import { FIELD_SEMANTIC_TYPES, type FieldSemanticType } from "../api/types";
import { QueryState } from "../components/QueryState";

type FieldConfigs = Record<string, Record<string, FieldSemanticType | null>>;

function TableColumnConfig({
  connectionId,
  database,
  table,
  config,
  onChange,
}: {
  connectionId: string;
  database: string;
  table: string;
  config: Record<string, FieldSemanticType | null>;
  onChange: (table: string, column: string, value: FieldSemanticType | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const columnsQuery = useQuery({
    queryKey: ["clone-columns", connectionId, database, table],
    queryFn: () => listColumns(connectionId, database, table),
    enabled: expanded,
  });
  const configuredCount = Object.values(config).filter((v) => v).length;

  return (
    <div className="detail-card">
      <button type="button" onClick={() => setExpanded((v) => !v)}>
        {expanded ? "Hide" : "Configure"} {table} {configuredCount > 0 && `(${configuredCount} configured)`}
      </button>
      {expanded && (
        <QueryState
          isLoading={columnsQuery.isPending}
          isError={columnsQuery.isError}
          error={columnsQuery.error}
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>Column</th>
                <th>Native type</th>
                <th>Semantic type (or passthrough)</th>
              </tr>
            </thead>
            <tbody>
              {columnsQuery.data?.map((col) => (
                <tr key={col.name}>
                  <td>{col.name}</td>
                  <td>{col.native_type}</td>
                  <td>
                    <select
                      value={config[col.name] ?? ""}
                      onChange={(e) =>
                        onChange(table, col.name, (e.target.value || null) as FieldSemanticType | null)
                      }
                    >
                      <option value="">passthrough (don't normalize)</option>
                      {FIELD_SEMANTIC_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </QueryState>
      )}
    </div>
  );
}

export function CloneJobNewPage() {
  const navigate = useNavigate();
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: listConnections });

  const [sourceConnectionId, setSourceConnectionId] = useState("");
  const [sourceDatabase, setSourceDatabase] = useState("");
  const [destConnectionId, setDestConnectionId] = useState("");
  const [destDatabase, setDestDatabase] = useState("");
  const [fieldConfigs, setFieldConfigs] = useState<FieldConfigs>({});

  const sourceDatabasesQuery = useQuery({
    queryKey: ["clone-databases", sourceConnectionId],
    queryFn: () => listDatabases(sourceConnectionId),
    enabled: Boolean(sourceConnectionId),
  });
  const tablesQuery = useQuery({
    queryKey: ["clone-tables", sourceConnectionId, sourceDatabase],
    queryFn: () => listTables(sourceConnectionId, sourceDatabase),
    enabled: Boolean(sourceConnectionId) && Boolean(sourceDatabase),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createCloneJob({
        source_connection_id: sourceConnectionId,
        source_database: sourceDatabase,
        destination_connection_id: destConnectionId,
        destination_database: destDatabase,
        field_configs: fieldConfigs,
      }),
    onSuccess: (job) => navigate(`/clone/${job.job_id}`),
  });

  function setColumnConfig(table: string, column: string, value: FieldSemanticType | null) {
    setFieldConfigs((prev) => ({
      ...prev,
      [table]: { ...prev[table], [column]: value },
    }));
  }

  const ready = Boolean(sourceConnectionId && sourceDatabase && destConnectionId && destDatabase);

  return (
    <section>
      <h1>New clone job</h1>
      <p className="hint">
        Every table in the chosen origin database is cloned automatically. Pick, per column,
        whether it gets normalized (and to what semantic type) or copied through untouched
        (passthrough). The origin is read strictly read-only and is never modified — Phase 1
        creates the destination's tables completely empty, Phase 2 streams, normalizes, and
        populates them.
      </p>

      {connectionsQuery.data?.length === 0 && (
        <p className="hint">No saved connections yet — create one on the Connections page first.</p>
      )}

      <div className="preview-form__row">
        <label>
          Source (origin, read-only) connection
          <select
            value={sourceConnectionId}
            onChange={(e) => {
              setSourceConnectionId(e.target.value);
              setSourceDatabase("");
              setFieldConfigs({});
            }}
          >
            <option value="">Select…</option>
            {connectionsQuery.data?.map((c) => (
              <option key={c.connection_id} value={c.connection_id}>
                {c.engine} {c.host}:{c.port} ({c.username})
              </option>
            ))}
          </select>
        </label>
        <label>
          Source database
          <select
            value={sourceDatabase}
            onChange={(e) => {
              setSourceDatabase(e.target.value);
              setFieldConfigs({});
            }}
            disabled={!sourceConnectionId}
          >
            <option value="">Select…</option>
            {sourceDatabasesQuery.data?.map((db) => (
              <option key={db} value={db}>
                {db}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="preview-form__row">
        <label>
          Destination (write-capable, same server) connection
          <select value={destConnectionId} onChange={(e) => setDestConnectionId(e.target.value)}>
            <option value="">Select…</option>
            {connectionsQuery.data?.map((c) => (
              <option key={c.connection_id} value={c.connection_id}>
                {c.engine} {c.host}:{c.port} ({c.username})
              </option>
            ))}
          </select>
        </label>
        <label>
          Destination database (new name — you'll create it by hand)
          <input value={destDatabase} onChange={(e) => setDestDatabase(e.target.value)} placeholder="orders_clone" />
        </label>
      </div>

      {tablesQuery.isPending && sourceDatabase && <p className="state-message">Loading tables…</p>}
      {tablesQuery.data && (
        <>
          <h3>Tables ({tablesQuery.data.length})</h3>
          {tablesQuery.data.map((table) => (
            <TableColumnConfig
              key={table}
              connectionId={sourceConnectionId}
              database={sourceDatabase}
              table={table}
              config={fieldConfigs[table] ?? {}}
              onChange={setColumnConfig}
            />
          ))}
        </>
      )}

      <button type="button" disabled={!ready || createMutation.isPending} onClick={() => createMutation.mutate()}>
        Create clone job
      </button>
      {createMutation.isError && (
        <p className="state-message state-message--error">
          Create failed: {(createMutation.error as Error).message}
        </p>
      )}
    </section>
  );
}
