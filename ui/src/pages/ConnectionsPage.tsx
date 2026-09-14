// DB-clone-and-normalize — saved (server-level) connections (decisions
// #2, #12, #13). List/create/delete, same local-useState-fields +
// useMutation idiom as PreviewPage/RunsPage.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { createConnection, deleteConnection, listConnections } from "../api/client";
import type { ConnectionEngine } from "../api/types";
import { QueryState } from "../components/QueryState";

export function ConnectionsPage() {
  const queryClient = useQueryClient();
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: listConnections });

  const [engine, setEngine] = useState<ConnectionEngine>("postgres");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState(5432);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const createMutation = useMutation({
    mutationFn: () => createConnection({ engine, host, port, username, password }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setUsername("");
      setPassword("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (connectionId: string) => deleteConnection(connectionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

  return (
    <section>
      <h1>Connections</h1>
      <p className="hint">
        Server-level (host + port + username + password + engine) credentials — the database is
        picked fresh each time you start a clone job, never baked into the saved connection. Read
        this credential for the origin, or a second, write-capable credential for the destination
        (same server) — never the same credential for both. Passwords are encrypted at rest and
        decrypted only in memory when connecting.
      </p>

      <form
        className="preview-form"
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate();
        }}
      >
        <div className="preview-form__row">
          <label>
            Engine
            <select value={engine} onChange={(e) => setEngine(e.target.value as ConnectionEngine)}>
              <option value="postgres">postgres</option>
              <option value="clickhouse">clickhouse</option>
            </select>
          </label>
          <label>
            Host
            <input value={host} onChange={(e) => setHost(e.target.value)} required />
          </label>
          <label>
            Port
            <input
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              required
            />
          </label>
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} required />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
        </div>
        <button type="submit" disabled={createMutation.isPending}>
          Save connection
        </button>
      </form>
      {createMutation.isError && (
        <p className="state-message state-message--error">
          Save failed: {(createMutation.error as Error).message}
        </p>
      )}

      <QueryState
        isLoading={connectionsQuery.isPending}
        isError={connectionsQuery.isError}
        error={connectionsQuery.error}
        isEmpty={connectionsQuery.data?.length === 0}
        emptyMessage="No saved connections yet."
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Engine</th>
              <th>Host</th>
              <th>Port</th>
              <th>Username</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {connectionsQuery.data?.map((c) => (
              <tr key={c.connection_id}>
                <td>{c.engine}</td>
                <td>{c.host}</td>
                <td>{c.port}</td>
                <td>{c.username}</td>
                <td>{c.created_at}</td>
                <td>
                  <button
                    type="button"
                    disabled={deleteMutation.isPending}
                    onClick={() => deleteMutation.mutate(c.connection_id)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>

      <p className="hint">
        Ready to clone a database? <Link to="/clone">Start a clone job</Link>.
      </p>
    </section>
  );
}
