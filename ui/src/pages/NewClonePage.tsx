// New clone screen, three steps: (1) origin and destination, (2) the columns to normalize and
// their semantic types, (3) "Check your answers". The Start button exists only in step 3.
// Step 2 chooses the tables (all of them by default) and, per column of a chosen table, a
// semantic type or "copy unchanged".
import {
  Accordion,
  Alert,
  Button,
  Checkbox,
  Group,
  NativeSelect,
  Stack,
  Stepper,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCloneJob, listColumns, listConnections, listDatabases, listSchemas, listTables } from "../api/client";
import { FIELD_SEMANTIC_TYPES, type Connection, type FieldSemanticType } from "../api/types";
import { QueryState } from "../components/QueryState";

type FieldConfigs = Record<string, Record<string, FieldSemanticType | null>>;

const COPY_UNCHANGED = { value: "", label: "Copy unchanged" };
const TYPE_OPTIONS = [COPY_UNCHANGED, ...FIELD_SEMANTIC_TYPES.map((t) => ({ value: t, label: t }))];

function connectionOptions(connections: Connection[] | undefined) {
  return [
    { value: "", label: "Select…" },
    ...(connections ?? []).map((c) => ({
      value: c.connection_id,
      label: `${c.engine} ${c.host}:${c.port} (${c.username})`,
    })),
  ];
}

function configured(config: Record<string, FieldSemanticType | null> | undefined) {
  return Object.entries(config ?? {}).filter(([, type]) => type);
}

function ColumnTable({
  connectionId,
  database,
  schema,
  table,
  config,
  onChange,
}: {
  connectionId: string;
  database: string;
  schema: string | undefined;
  table: string;
  config: Record<string, FieldSemanticType | null>;
  onChange: (table: string, column: string, value: FieldSemanticType | null) => void;
}) {
  const columnsQuery = useQuery({
    queryKey: ["clone-columns", connectionId, database, schema, table],
    queryFn: () => listColumns(connectionId, database, table, schema),
  });
  return (
    <QueryState isLoading={columnsQuery.isPending} isError={columnsQuery.isError} error={columnsQuery.error}>
      <Table.ScrollContainer minWidth={420}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Column</Table.Th>
              <Table.Th>Type in the origin</Table.Th>
              <Table.Th>Semantic type</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {columnsQuery.data?.map((col) => (
              <Table.Tr key={col.name}>
                <Table.Td>{col.name}</Table.Td>
                <Table.Td>{col.native_type}</Table.Td>
                <Table.Td>
                  <NativeSelect
                    aria-label={`Semantic type of ${table}.${col.name}`}
                    data={TYPE_OPTIONS}
                    value={config[col.name] ?? ""}
                    onChange={(e) =>
                      onChange(table, col.name, (e.currentTarget.value || null) as FieldSemanticType | null)
                    }
                  />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </QueryState>
  );
}

export function NewClonePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: listConnections });

  const [sourceConnectionId, setSourceConnectionId] = useState("");
  const [sourceDatabase, setSourceDatabase] = useState("");
  const [chosenSchema, setChosenSchema] = useState("");
  const [destConnectionId, setDestConnectionId] = useState("");
  const [destDatabase, setDestDatabase] = useState("");
  const [fieldConfigs, setFieldConfigs] = useState<FieldConfigs>({});
  const [openTables, setOpenTables] = useState<string[]>([]);
  const [skippedTables, setSkippedTables] = useState<string[]>([]);

  const databasesQuery = useQuery({
    queryKey: ["clone-databases", sourceConnectionId],
    queryFn: () => listDatabases(sourceConnectionId),
    enabled: Boolean(sourceConnectionId),
  });
  // Postgres only: the schemas that hold tables. ClickHouse answers [] and has none.
  const schemasQuery = useQuery({
    queryKey: ["clone-schemas", sourceConnectionId, sourceDatabase],
    queryFn: () => listSchemas(sourceConnectionId, sourceDatabase),
    enabled: Boolean(sourceConnectionId && sourceDatabase),
  });
  const schemas = schemasQuery.data ?? [];
  const sourceSchema = schemas.includes(chosenSchema) ? chosenSchema : schemas[0];
  const tablesQuery = useQuery({
    queryKey: ["clone-tables", sourceConnectionId, sourceDatabase, sourceSchema],
    queryFn: () => listTables(sourceConnectionId, sourceDatabase, sourceSchema),
    enabled: schemasQuery.isSuccess,
  });

  const startMutation = useMutation({
    mutationFn: () =>
      createCloneJob({
        source_connection_id: sourceConnectionId,
        source_database: sourceDatabase,
        ...(sourceSchema && { source_schema: sourceSchema }),
        destination_connection_id: destConnectionId,
        destination_database: destDatabase,
        ...(skippedTables.length > 0 && { tables: chosenTables }),
        field_configs: chosenConfigs,
      }),
    onSuccess: (job) => navigate(`/jobs/${job.job_id}`),
  });

  function resetColumns() {
    setChosenSchema("");
    setFieldConfigs({});
    setOpenTables([]);
    setSkippedTables([]);
  }

  function setColumnType(table: string, column: string, value: FieldSemanticType | null) {
    setFieldConfigs((prev) => ({ ...prev, [table]: { ...prev[table], [column]: value } }));
  }

  const connections = connectionsQuery.data;
  const label = (id: string) => connectionOptions(connections).find((o) => o.value === id)?.label ?? id;
  const step1Done = Boolean(sourceConnectionId && sourceDatabase && destConnectionId && destDatabase.trim());
  const tables = tablesQuery.data ?? [];
  const chosenTables = tables.filter((table) => !skippedTables.includes(table));
  const chosenConfigs = Object.fromEntries(
    Object.entries(fieldConfigs).filter(([table]) => chosenTables.includes(table)),
  );

  return (
    <Stack>
      <Title order={1}>New clone</Title>
      <Stepper active={step} size="sm">
        <Stepper.Step label="Origin and destination" />
        <Stepper.Step label="Columns" />
        <Stepper.Step label="Check your answers" />
      </Stepper>

      {step === 0 && (
        <Stack maw={520}>
          {connections?.length === 0 && (
            <Alert color="yellow">No saved connections yet. Add one on the Connections screen first.</Alert>
          )}
          <NativeSelect
            label="Origin connection (read only)"
            data={connectionOptions(connections)}
            value={sourceConnectionId}
            onChange={(e) => {
              setSourceConnectionId(e.currentTarget.value);
              setSourceDatabase("");
              resetColumns();
            }}
          />
          <NativeSelect
            label="Origin database"
            data={[{ value: "", label: "Select…" }, ...(databasesQuery.data ?? [])]}
            value={sourceDatabase}
            disabled={!sourceConnectionId}
            error={databasesQuery.isError ? (databasesQuery.error as Error).message : undefined}
            onChange={(e) => {
              setSourceDatabase(e.currentTarget.value);
              resetColumns();
            }}
          />
          {schemasQuery.isError && (
            <Alert color="red" title="Could not list the schemas">
              {(schemasQuery.error as Error).message}
            </Alert>
          )}
          {schemas.length > 0 && (
            <NativeSelect
              label="Origin schema"
              description="Postgres: the schema whose tables are cloned. Clone another schema with another job."
              data={schemas}
              value={sourceSchema}
              onChange={(e) => {
                resetColumns();
                setChosenSchema(e.currentTarget.value);
              }}
            />
          )}
          <NativeSelect
            label="Destination connection (can write)"
            data={connectionOptions(connections)}
            value={destConnectionId}
            onChange={(e) => setDestConnectionId(e.currentTarget.value)}
          />
          <TextInput
            label="Destination database"
            description="A new name. You create it by hand after you start; the origin is never changed."
            value={destDatabase}
            onChange={(e) => setDestDatabase(e.currentTarget.value)}
          />
          <Group>
            <Button disabled={!step1Done} onClick={() => setStep(1)}>
              Next
            </Button>
          </Group>
        </Stack>
      )}

      {step === 1 && (
        <Stack>
          <Text maw="70ch">
            {skippedTables.length === 0 ? "All" : `${chosenTables.length} of`} {tables.length} table(s) of{" "}
            <b>{sourceDatabase}</b> are cloned. For each column you want normalized, choose its
            semantic type. Every other column is copied unchanged.
          </Text>
          <QueryState isLoading={tablesQuery.isPending} isError={tablesQuery.isError} error={tablesQuery.error}>
            <Group>
              {tables.map((table) => (
                <Checkbox
                  key={table}
                  label={table}
                  aria-label={`Clone table ${table}`}
                  checked={!skippedTables.includes(table)}
                  onChange={(e) => {
                    const { checked } = e.currentTarget;
                    setSkippedTables((prev) => (checked ? prev.filter((t) => t !== table) : [...prev, table]));
                  }}
                />
              ))}
            </Group>
            <Accordion multiple value={openTables} onChange={setOpenTables}>
              {chosenTables.map((table) => (
                <Accordion.Item key={table} value={table}>
                  <Accordion.Control>
                    {table}
                    {configured(fieldConfigs[table]).length > 0 &&
                      ` (${configured(fieldConfigs[table]).length} to normalize)`}
                  </Accordion.Control>
                  <Accordion.Panel>
                    {openTables.includes(table) && (
                      <ColumnTable
                        connectionId={sourceConnectionId}
                        database={sourceDatabase}
                        schema={sourceSchema}
                        table={table}
                        config={fieldConfigs[table] ?? {}}
                        onChange={setColumnType}
                      />
                    )}
                  </Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          </QueryState>
          <Group>
            <Button variant="default" onClick={() => setStep(0)}>
              Back
            </Button>
            <Button disabled={chosenTables.length === 0} onClick={() => setStep(2)}>
              Next
            </Button>
          </Group>
        </Stack>
      )}

      {step === 2 && (
        <Stack>
          <Title order={2}>Check your answers</Title>
          <Table>
            <Table.Tbody>
              <Table.Tr>
                <Table.Th scope="row">Origin</Table.Th>
                <Table.Td>
                  {label(sourceConnectionId)} / {sourceDatabase}
                </Table.Td>
                <Table.Td>
                  <Button variant="subtle" size="xs" onClick={() => setStep(0)}>
                    Change origin
                  </Button>
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th scope="row">Destination</Table.Th>
                <Table.Td>
                  {label(destConnectionId)} / {destDatabase}
                </Table.Td>
                <Table.Td>
                  <Button variant="subtle" size="xs" onClick={() => setStep(0)}>
                    Change destination
                  </Button>
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Th scope="row">Tables cloned</Table.Th>
                <Table.Td>{skippedTables.length === 0 ? `${tables.length} (all)` : chosenTables.join(", ")}</Table.Td>
                <Table.Td />
              </Table.Tr>
              <Table.Tr>
                <Table.Th scope="row">Columns to normalize</Table.Th>
                <Table.Td>
                  {Object.keys(chosenConfigs).every((t) => configured(chosenConfigs[t]).length === 0) ? (
                    <Text>None. Every column is copied unchanged.</Text>
                  ) : (
                    <Stack gap={2}>
                      {Object.keys(chosenConfigs).flatMap((t) =>
                        configured(chosenConfigs[t]).map(([column, type]) => (
                          <Text key={`${t}.${column}`}>
                            {t}.{column}: {type}
                          </Text>
                        )),
                      )}
                    </Stack>
                  )}
                </Table.Td>
                <Table.Td>
                  <Button variant="subtle" size="xs" onClick={() => setStep(1)}>
                    Change columns
                  </Button>
                </Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
          {startMutation.isError && (
            <Alert color="red" title="Could not start">
              {(startMutation.error as Error).message}
            </Alert>
          )}
          <Group>
            <Button variant="default" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button loading={startMutation.isPending} onClick={() => startMutation.mutate()}>
              Start
            </Button>
          </Group>
        </Stack>
      )}
    </Stack>
  );
}
