// M21 step 1 of 3 — Connect. Source.txt's own product-redesign ask: pick
// a DB kind, fill in real credentials, test the connection against the
// real server, then save it and move to Explore. Every call here hits
// the real M15 connection-registry API — no mock data.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createConnection, listConnectionKinds, testConnection } from "../api/client";
import { QueryState } from "../components/QueryState";

export function ConnectPage() {
  const navigate = useNavigate();
  const kindsQuery = useQuery({ queryKey: ["connection-kinds"], queryFn: listConnectionKinds });

  const [kind, setKind] = useState("");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState<string>("");
  const [username, setUsername] = useState("default");
  const [password, setPassword] = useState("");
  const [database, setDatabase] = useState("");
  const [alias, setAlias] = useState("");

  const defaultPort = kindsQuery.data?.find((k) => k.kind === kind)?.default_port;

  const testMutation = useMutation({
    mutationFn: () =>
      testConnection({
        kind,
        host,
        port: port ? Number(port) : undefined,
        username,
        password,
        database,
      }),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createConnection({
        alias: alias || `${kind}-${host}-${database}`,
        kind,
        host,
        port: port ? Number(port) : undefined,
        username,
        password,
        database,
      }),
    onSuccess: (connection) => {
      navigate(`/explore/${connection.id}`);
    },
  });

  const canTest = Boolean(kind && host && username && database);

  return (
    <section>
      <h1>Connect</h1>
      <p className="hint">Step 1 of 3 — point at a real database to normalize.</p>

      <QueryState
        isLoading={kindsQuery.isPending}
        isError={kindsQuery.isError}
        error={kindsQuery.error}
      >
        <form
          className="preview-form"
          onSubmit={(e) => {
            e.preventDefault();
          }}
        >
          <div className="preview-form__row">
            <label>
              Database kind
              <select
                value={kind}
                onChange={(e) => {
                  const nextKind = e.target.value;
                  setKind(nextKind);
                  const nextDefault = kindsQuery.data?.find((k) => k.kind === nextKind)?.default_port;
                  if (nextDefault) setPort(String(nextDefault));
                  testMutation.reset();
                }}
                required
              >
                <option value="">Select a kind…</option>
                {kindsQuery.data?.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.kind}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Host
              <input value={host} onChange={(e) => setHost(e.target.value)} required />
            </label>
            <label>
              Port
              <input
                value={port}
                onChange={(e) => setPort(e.target.value)}
                placeholder={defaultPort ? String(defaultPort) : undefined}
                inputMode="numeric"
              />
            </label>
          </div>
          <div className="preview-form__row">
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
              />
            </label>
            <label>
              Database
              <input value={database} onChange={(e) => setDatabase(e.target.value)} required />
            </label>
          </div>
          <div className="preview-form__row">
            <label>
              Alias (optional)
              <input
                value={alias}
                onChange={(e) => setAlias(e.target.value)}
                placeholder="a name for this connection"
              />
            </label>
          </div>

          <button
            type="button"
            disabled={!canTest || testMutation.isPending}
            onClick={() => testMutation.mutate()}
          >
            Test connection
          </button>
        </form>

        {testMutation.isError && (
          <p className="state-message state-message--error">
            Test failed: {(testMutation.error as Error).message}
          </p>
        )}
        {testMutation.data && !testMutation.data.ok && (
          <p className="state-message state-message--error">
            {testMutation.data.error ?? "Connection failed."}
          </p>
        )}
        {testMutation.data?.ok && (
          <div className="detail-card">
            <p className="state-message state-message--success">
              Connected — {testMutation.data.databases.length} real database(s) visible.
            </p>
            <p className="plain-list">{testMutation.data.databases.join(", ")}</p>
            <button
              type="button"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              Save connection and continue
            </button>
          </div>
        )}
        {createMutation.isError && (
          <p className="state-message state-message--error">
            Could not save connection: {(createMutation.error as Error).message}
          </p>
        )}
      </QueryState>
    </section>
  );
}
