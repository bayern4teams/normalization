// Connections screen: add a Postgres or ClickHouse server. "Test connection" comes before
// "Save"; Save stays disabled until the exact values on screen passed the test. A refused
// address (D15, HTTP 422 from the API's address check) is shown next to the Host field.
import {
  Alert,
  Button,
  Group,
  NativeSelect,
  NumberInput,
  PasswordInput,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, createConnection, deleteConnection, listConnections, testConnection } from "../api/client";
import type { ConnectionEngine } from "../api/types";
import { QueryState } from "../components/QueryState";

// The connectors' own default ports (normio PostgresConnector / ClickHouseConnector).
const DEFAULT_PORT: Record<ConnectionEngine, number> = { postgres: 5432, clickhouse: 8123 };

// 422 is the address check's refusal (D15); other failures (wrong password, unreachable server)
// are not about the host field and are shown as an alert.
function hostRefusal(error: unknown): string | null {
  return error instanceof ApiError && error.status === 422 ? error.message : null;
}

export function ConnectionsPage() {
  const queryClient = useQueryClient();
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: listConnections });

  const [engine, setEngine] = useState<ConnectionEngine>("postgres");
  const [host, setHost] = useState("");
  const [port, setPort] = useState<number>(DEFAULT_PORT.postgres);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [hostError, setHostError] = useState<string | null>(null);
  // The values that last passed "Test connection"; Save needs the current values to equal them.
  const [testedKey, setTestedKey] = useState<string | null>(null);
  const [databaseCount, setDatabaseCount] = useState<number | null>(null);

  const body = { engine, host, port, username, password };
  const key = JSON.stringify(body);
  const complete = host !== "" && username !== "" && password !== "" && Number.isFinite(port);

  const testMutation = useMutation({
    mutationFn: () => testConnection(body),
    onMutate: () => {
      setHostError(null);
      setTestedKey(null);
    },
    onSuccess: (databases) => {
      setTestedKey(key);
      setDatabaseCount(databases.length);
    },
    onError: (error) => setHostError(hostRefusal(error)),
  });

  const saveMutation = useMutation({
    mutationFn: () => createConnection(body),
    onMutate: () => setHostError(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
      setUsername("");
      setPassword("");
      setTestedKey(null);
    },
    onError: (error) => setHostError(hostRefusal(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (connectionId: string) => deleteConnection(connectionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

  const otherError = [testMutation, saveMutation]
    .map((m) => (m.isError && !hostRefusal(m.error) ? (m.error as Error).message : null))
    .find(Boolean);

  return (
    <Stack>
      <Title order={1}>Connections</Title>
      <Text c="dimmed" maw="70ch">
        A server, not a database: you pick the database when you start a clone. Use an account that
        can only read for the origin, and a different account that can write for the destination.
        Passwords are stored encrypted.
      </Text>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (complete) testMutation.mutate();
        }}
      >
        <Stack maw={480}>
          <NativeSelect
            label="Engine"
            data={[
              { value: "postgres", label: "Postgres" },
              { value: "clickhouse", label: "ClickHouse" },
            ]}
            value={engine}
            onChange={(e) => {
              const next = e.currentTarget.value as ConnectionEngine;
              setEngine(next);
              setPort(DEFAULT_PORT[next]);
            }}
          />
          <TextInput
            label="Host"
            value={host}
            onChange={(e) => {
              setHost(e.currentTarget.value);
              setHostError(null);
            }}
            error={hostError}
            required
          />
          <NumberInput
            label="Port"
            value={port}
            onChange={(v) => setPort(Number(v))}
            min={1}
            max={65535}
            allowDecimal={false}
            required
          />
          <TextInput
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.currentTarget.value)}
            required
          />
          <PasswordInput
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
          />
          <Group>
            <Button type="submit" variant="default" disabled={!complete} loading={testMutation.isPending}>
              Test connection
            </Button>
            <Button
              type="button"
              disabled={testedKey !== key}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              Save
            </Button>
          </Group>
          {testedKey === key && (
            <Alert color="green">Connection works. The server lists {databaseCount} database(s).</Alert>
          )}
          {otherError && (
            <Alert color="red" title="Request failed">
              {otherError}
            </Alert>
          )}
        </Stack>
      </form>

      <Title order={2}>Saved connections</Title>
      <QueryState
        isLoading={connectionsQuery.isPending}
        isError={connectionsQuery.isError}
        error={connectionsQuery.error}
        isEmpty={connectionsQuery.data?.length === 0}
        emptyMessage="No saved connections yet."
      >
        <Table.ScrollContainer minWidth={560}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Engine</Table.Th>
                <Table.Th>Host</Table.Th>
                <Table.Th>Port</Table.Th>
                <Table.Th>Username</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {connectionsQuery.data?.map((c) => (
                <Table.Tr key={c.connection_id}>
                  <Table.Td>{c.engine}</Table.Td>
                  <Table.Td>{c.host}</Table.Td>
                  <Table.Td>{c.port}</Table.Td>
                  <Table.Td>{c.username}</Table.Td>
                  <Table.Td>{c.created_at}</Table.Td>
                  <Table.Td>
                    <Button
                      variant="subtle"
                      color="red"
                      size="xs"
                      loading={deleteMutation.isPending && deleteMutation.variables === c.connection_id}
                      onClick={() => deleteMutation.mutate(c.connection_id)}
                    >
                      Delete
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </QueryState>
    </Stack>
  );
}
