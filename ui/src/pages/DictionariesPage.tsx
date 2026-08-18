// Source.txt §115 Dictionary Management UI — built-in (read-only) +
// custom (full CRUD/versioning/rollback) dictionaries.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import {
  createDictionary,
  createDictionaryVersion,
  deleteDictionary,
  getDictionary,
  listDictionaries,
  rollbackDictionary,
} from "../api/client";
import { QueryState } from "../components/QueryState";

export function DictionariesPage() {
  const queryClient = useQueryClient();
  const listQuery = useQuery({ queryKey: ["dictionaries"], queryFn: listDictionaries });
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const [newId, setNewId] = useState("");
  const [newEntries, setNewEntries] = useState('{\n  "example-key": "example-value"\n}');
  const [newSource, setNewSource] = useState("ui-user");
  const [newLicense, setNewLicense] = useState("proprietary");
  const [createdBy, setCreatedBy] = useState("ui-user");
  const [createError, setCreateError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => {
      let entries: Record<string, unknown>;
      try {
        entries = JSON.parse(newEntries) as Record<string, unknown>;
      } catch {
        throw new Error("Entries must be valid JSON");
      }
      return createDictionary({
        id: newId,
        entries,
        source: newSource,
        license: newLicense,
        created_by: createdBy,
      });
    },
    onSuccess: () => {
      setNewId("");
      setCreateError(null);
      queryClient.invalidateQueries({ queryKey: ["dictionaries"] });
    },
    onError: (err) => setCreateError((err as Error).message),
  });

  const rollbackMutation = useMutation({
    mutationFn: ({ id, version }: { id: string; version: string }) =>
      rollbackDictionary(id, version, createdBy),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dictionaries"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDictionary(id, createdBy),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dictionaries"] }),
  });

  function exportEntries(id: string, version: string) {
    getDictionary(id, version).then((detail) => {
      const blob = new Blob([JSON.stringify(detail, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}-${version}.json`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  return (
    <section>
      <h1>Dictionaries</h1>

      <h3>Create custom dictionary (import)</h3>
      <form
        className="preview-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (newId.trim()) createMutation.mutate();
        }}
      >
        <div className="preview-form__row">
          <label>
            id
            <input value={newId} onChange={(e) => setNewId(e.target.value)} required />
          </label>
          <label>
            source
            <input value={newSource} onChange={(e) => setNewSource(e.target.value)} />
          </label>
          <label>
            license
            <input value={newLicense} onChange={(e) => setNewLicense(e.target.value)} />
          </label>
          <label>
            created_by
            <input value={createdBy} onChange={(e) => setCreatedBy(e.target.value)} />
          </label>
        </div>
        <label className="preview-form__values">
          entries (JSON)
          <textarea rows={5} value={newEntries} onChange={(e) => setNewEntries(e.target.value)} />
        </label>
        <button type="submit" disabled={createMutation.isPending}>
          Create
        </button>
      </form>
      {createError && <p className="state-message state-message--error">{createError}</p>}

      <h3>All dictionaries</h3>
      <QueryState
        isLoading={listQuery.isPending}
        isError={listQuery.isError}
        error={listQuery.error}
        isEmpty={listQuery.data?.length === 0}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Dictionary</th>
              <th>Version</th>
              <th>Source</th>
              <th>License</th>
              <th>Entries</th>
              <th>Locale</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {listQuery.data?.map((d) => {
              const key = `${d.id}@${d.version}`;
              const status = !d.is_custom
                ? "built-in"
                : d.active_version === d.version
                  ? "active"
                  : "deprecated";
              return (
                <Fragment key={key}>
                  <tr>
                    <td>{d.id}</td>
                    <td>{d.version}</td>
                    <td>{d.source}</td>
                    <td>{d.license}</td>
                    <td>{d.entry_count}</td>
                    <td>{d.locale ?? "—"}</td>
                    <td>
                      <span className={`status-pill status-pill--${status}`}>{status}</span>
                    </td>
                    <td className="action-cell">
                      <button type="button" onClick={() => setExpandedKey(expandedKey === key ? null : key)}>
                        {expandedKey === key ? "Hide" : "View"}
                      </button>
                      <button type="button" onClick={() => exportEntries(d.id, d.version)}>
                        Export
                      </button>
                      {d.is_custom && status !== "active" && (
                        <button
                          type="button"
                          onClick={() => rollbackMutation.mutate({ id: d.id, version: d.version })}
                        >
                          Rollback here
                        </button>
                      )}
                      {d.is_custom && status === "active" && (
                        <button type="button" onClick={() => deleteMutation.mutate(d.id)}>
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedKey === key && (
                    <tr>
                      <td colSpan={8}>
                        <DictionaryEntries id={d.id} version={d.version} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </QueryState>

      <h3>Add a version to a custom dictionary</h3>
      <AddVersionForm createdBy={createdBy} />
    </section>
  );
}

function DictionaryEntries({ id, version }: { id: string; version: string }) {
  const query = useQuery({
    queryKey: ["dictionary", id, version],
    queryFn: () => getDictionary(id, version),
  });
  return (
    <QueryState isLoading={query.isPending} isError={query.isError} error={query.error}>
      <pre className="json-block">{JSON.stringify(query.data?.entries, null, 2)}</pre>
    </QueryState>
  );
}

function AddVersionForm({ createdBy }: { createdBy: string }) {
  const queryClient = useQueryClient();
  const [id, setId] = useState("");
  const [entries, setEntries] = useState('{\n  "key": "value"\n}');
  const [merge, setMerge] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(entries) as Record<string, unknown>;
      } catch {
        throw new Error("Entries must be valid JSON");
      }
      return createDictionaryVersion(id, { entries: parsed, created_by: createdBy, merge });
    },
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["dictionaries"] });
    },
    onError: (err) => setError((err as Error).message),
  });

  return (
    <form
      className="preview-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (id.trim()) mutation.mutate();
      }}
    >
      <div className="preview-form__row">
        <label>
          Dictionary id
          <input value={id} onChange={(e) => setId(e.target.value)} required />
        </label>
        <label>
          <input type="checkbox" checked={merge} onChange={(e) => setMerge(e.target.checked)} />{" "}
          Merge (patch) instead of replace
        </label>
      </div>
      <label className="preview-form__values">
        Entries (JSON) — a key set to null is deleted when merging
        <textarea rows={4} value={entries} onChange={(e) => setEntries(e.target.value)} />
      </label>
      <button type="submit" disabled={mutation.isPending}>
        Add version
      </button>
      {error && <p className="state-message state-message--error">{error}</p>}
    </form>
  );
}
