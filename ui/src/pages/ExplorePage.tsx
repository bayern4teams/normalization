// M21 step 2 of 3 — Explore. Browse a real connection's databases and
// tables, see real sample values per column (one batched request per
// table, per the M16 API's own design goal), assign a semantic type to
// whichever columns matter, across as many tables as needed, then start
// one real multi-column run (M17) over everything selected.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createProfile,
  createRun,
  deleteConnection,
  detectType,
  getConnectionTableColumns,
  listConnectionDatabases,
  listConnections,
  listConnectionTables,
  sampleConnectionTable,
  startMultiColumnRun,
  upsertColumnMapping,
} from "../api/client";
import { FIELD_SEMANTIC_TYPES, type FieldSemanticType, type RunColumnSpec, type TypeSuggestion } from "../api/types";
import { QueryState } from "../components/QueryState";

const AUTO_SUGGEST_MIN_CONFIDENCE = 0.5;

// Bare /explore (no connection chosen yet) — pick from real, already
// saved connections, or go make one.
export function ExploreLandingPage() {
  const queryClient = useQueryClient();
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: listConnections });
  const deleteMutation = useMutation({
    mutationFn: deleteConnection,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

  return (
    <section>
      <h1>Explore</h1>
      <p className="hint">Step 2 of 3 — pick a connection to browse.</p>
      <QueryState
        isLoading={connectionsQuery.isPending}
        isError={connectionsQuery.isError}
        error={connectionsQuery.error}
        isEmpty={connectionsQuery.data?.length === 0}
        emptyMessage="No connections saved yet."
      >
        <ul className="plain-list">
          {connectionsQuery.data?.map((c) => (
            <li key={c.id} className="action-cell">
              <Link to={`/explore/${c.id}`}>
                {c.alias} ({c.kind} — {c.host}:{c.port}/{c.database})
              </Link>
              <button
                type="button"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(c.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </QueryState>
      <Link to="/connect">Connect a new database</Link>
      {deleteMutation.isError && (
        <p className="state-message state-message--error">
          Could not delete: {(deleteMutation.error as Error).message}
        </p>
      )}
    </section>
  );
}

interface Selection {
  table: string;
  column: string;
  semanticType: FieldSemanticType;
}

export function ExplorePage() {
  const { connectionId } = useParams<{ connectionId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [database, setDatabase] = useState("");
  const [table, setTable] = useState("");
  // key: "table.column"
  const [selections, setSelections] = useState<Map<string, Selection>>(new Map());
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const databasesQuery = useQuery({
    queryKey: ["connection-databases", connectionId],
    queryFn: () => listConnectionDatabases(connectionId as string),
    enabled: Boolean(connectionId),
  });
  const tablesQuery = useQuery({
    queryKey: ["connection-tables", connectionId, database],
    queryFn: () => listConnectionTables(connectionId as string, database),
    enabled: Boolean(connectionId) && Boolean(database),
  });
  const columnsQuery = useQuery({
    queryKey: ["connection-table-columns", connectionId, database, table],
    queryFn: () => getConnectionTableColumns(connectionId as string, database, table),
    enabled: Boolean(connectionId) && Boolean(database) && Boolean(table),
  });
  const samplesQuery = useQuery({
    queryKey: ["connection-table-samples", connectionId, database, table],
    queryFn: () => sampleConnectionTable(connectionId as string, database, table, 5),
    enabled: Boolean(connectionId) && Boolean(database) && Boolean(table),
  });
  // Deterministic suggestion only (field-name pattern + real sample-value
  // validation, no LLM — see normanalysis.type_detection). Always a
  // suggestion the user can override, never applied silently.
  const suggestionsQuery = useQuery({
    queryKey: ["connection-table-suggestions", connectionId, database, table, samplesQuery.dataUpdatedAt],
    queryFn: async () => {
      const cols = columnsQuery.data?.columns ?? [];
      const samples = samplesQuery.data ?? {};
      const entries = await Promise.all(
        cols.map(async (col) => {
          const suggestions = await detectType(col.name, samples[col.name] ?? [], table);
          return [col.name, suggestions[0]] as const;
        }),
      );
      return Object.fromEntries(entries) as Record<string, TypeSuggestion | undefined>;
    },
    enabled: Boolean(columnsQuery.data) && Boolean(samplesQuery.data),
  });

  // Auto-fill each column's dropdown with its top suggestion once, the
  // first time a table's suggestions arrive — never overwrites a value
  // the user already set (here or on a prior visit to this table).
  const autoFilledTables = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!table || !suggestionsQuery.data) return;
    const tableKey = `${database}.${table}`;
    if (autoFilledTables.current.has(tableKey)) return;
    autoFilledTables.current.add(tableKey);
    setSelections((prev) => {
      const next = new Map(prev);
      for (const col of columnsQuery.data?.columns ?? []) {
        const key = `${table}.${col.name}`;
        if (next.has(key)) continue;
        const suggestion = suggestionsQuery.data?.[col.name];
        if (
          suggestion &&
          suggestion.confidence >= AUTO_SUGGEST_MIN_CONFIDENCE &&
          suggestion.semantic_type !== "FREE_TEXT"
        ) {
          next.set(key, { table, column: col.name, semanticType: suggestion.semantic_type });
        }
      }
      return next;
    });
  }, [table, database, suggestionsQuery.data, columnsQuery.data]);

  const setSelection = (column: string, semanticType: FieldSemanticType | "") => {
    setSelections((prev) => {
      const next = new Map(prev);
      const key = `${table}.${column}`;
      if (semanticType === "") {
        next.delete(key);
      } else {
        next.set(key, { table, column, semanticType });
      }
      return next;
    });
  };

  const mappingMutation = useMutation({
    mutationFn: (selection: Selection) =>
      upsertColumnMapping(connectionId as string, database, selection.table, selection.column, {
        semantic_type: selection.semanticType,
        updated_by: "ui",
      }),
  });

  const startRun = async () => {
    if (!connectionId || selections.size === 0) return;
    setStarting(true);
    setStartError(null);
    try {
      // Save every real mapping first (M16) so it's remembered for next
      // time this same connection/database is explored again.
      for (const selection of selections.values()) {
        await mappingMutation.mutateAsync(selection);
      }
      const profile = await createProfile({
        name: `ui-explore-${new Date().toISOString()}`,
        field_configs: [],
        created_by: "ui",
      });
      const run = await createRun(profile.id, `ui-explore-${connectionId}`);
      const columns: RunColumnSpec[] = Array.from(selections.values()).map((s) => ({
        table: s.table,
        column: s.column,
        semantic_type: s.semanticType,
      }));
      await startMultiColumnRun(run.id, { connection_id: connectionId, database, columns });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/report/${run.id}`);
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "Failed to start run");
    } finally {
      setStarting(false);
    }
  };

  if (!connectionId) return null;

  return (
    <section>
      <h1>Explore</h1>
      <p className="hint">Step 2 of 3 — pick columns and assign what they mean.</p>

      <div className="preview-form__row">
        <label>
          Database
          <select
            value={database}
            onChange={(e) => {
              setDatabase(e.target.value);
              setTable("");
            }}
          >
            <option value="">Select a database…</option>
            {databasesQuery.data?.map((db) => (
              <option key={db} value={db}>
                {db}
              </option>
            ))}
          </select>
        </label>
        {database && (
          <label>
            Table
            <select value={table} onChange={(e) => setTable(e.target.value)}>
              <option value="">Select a table…</option>
              {tablesQuery.data?.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {table && (
        <QueryState
          isLoading={columnsQuery.isPending || samplesQuery.isPending}
          isError={columnsQuery.isError || samplesQuery.isError}
          error={columnsQuery.error ?? samplesQuery.error}
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Sample values</th>
                <th>Semantic type</th>
              </tr>
            </thead>
            <tbody>
              {columnsQuery.data?.columns.map((col) => {
                const key = `${table}.${col.name}`;
                const current = selections.get(key)?.semanticType ?? "";
                return (
                  <tr key={col.name}>
                    <td>
                      {col.name}
                      {col.is_primary_key && <span className="hint"> (key)</span>}
                    </td>
                    <td>{col.type}</td>
                    <td className="sample-row">
                      {(samplesQuery.data?.[col.name] ?? []).join(", ") || "—"}
                    </td>
                    <td>
                      <select
                        value={current}
                        onChange={(e) =>
                          setSelection(col.name, e.target.value as FieldSemanticType | "")
                        }
                      >
                        <option value="">Not mapped</option>
                        {FIELD_SEMANTIC_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                      {current !== "" && suggestionsQuery.data?.[col.name]?.semantic_type === current && (
                        <span className="hint">
                          {" "}
                          suggested ({Math.round((suggestionsQuery.data[col.name]?.confidence ?? 0) * 100)}%)
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </QueryState>
      )}

      <div className="detail-card">
        <h3>Selected columns ({selections.size})</h3>
        {selections.size === 0 ? (
          <p className="hint">Assign a semantic type to at least one column to start a run.</p>
        ) : (
          <ul className="plain-list">
            {Array.from(selections.values()).map((s) => (
              <li key={`${s.table}.${s.column}`}>
                {s.table}.{s.column} → {s.semanticType}
              </li>
            ))}
          </ul>
        )}
        <button type="button" disabled={selections.size === 0 || starting} onClick={startRun}>
          {starting ? "Starting…" : "Start normalization"}
        </button>
        {startError && <p className="state-message state-message--error">{startError}</p>}
      </div>
    </section>
  );
}
