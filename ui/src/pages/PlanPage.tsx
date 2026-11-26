// The plan review screen: every column the detector suggested a type for,
// with confidence, how many sampled values actually validated, and the
// reason — plus what is already decided. The reviewer ticks the ones to
// accept (or "Accept confident" for the mass case), Save PATCHes them into
// the plan. Only while the job is PENDING_DB_CREATE: after Verify database
// the DDL exists and the plan locks (the API says so, and we show why).
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Container,
  Group,
  Paper,
  Progress,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiMessage } from "../api/review";
import { getCloneJobPlan, patchCloneJobPlan } from "../api/client";
import { QueryState } from "../components/QueryState";
import {
  acceptConfident,
  countSelected,
  hasAnySuggestion,
  isConfident,
  selectionToFieldConfigs,
  toggle,
  type Selection,
} from "../lib/planSuggestions";
import type { PlanTable } from "../api/types";

export function PlanPage() {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const queryClient = useQueryClient();
  const [selection, setSelection] = useState<Selection>({});
  const planQuery = useQuery({
    queryKey: ["plan", jobId],
    queryFn: () => getCloneJobPlan(jobId),
    retry: false,
  });
  const save = useMutation({
    mutationFn: (sel: Selection) =>
      patchCloneJobPlan(jobId, { field_configs: selectionToFieldConfigs(sel, planQuery.data!) }),
    onSuccess: () => {
      setSelection({});
      queryClient.invalidateQueries({ queryKey: ["plan", jobId] });
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    },
  });
  const plan = planQuery.data;
  const tablesWithSuggestions = plan ? plan.tables.filter((t) => t.columns.some((c) => c.suggestion)) : [];

  return (
    <Container size="lg" py="md">
      <Group mb="md" gap="md">
        <Title order={1}>Plan</Title>
        <Link to={`/jobs/${encodeURIComponent(jobId)}`}>Job</Link>
        <Link to="/jobs">All jobs</Link>
      </Group>
      <QueryState isLoading={planQuery.isPending} isError={planQuery.isError} error={planQuery.error}>
        {plan && (
          <Stack gap="md">
            {plan.status === "PENDING_DB_CREATE" ? (
              <Alert color="blue" title="Before the tables are built">
                Accepting a type here changes the destination column&apos;s type and can add a
                companion column. After &quot;Verify database&quot; the tables exist and the plan
                can no longer change — decide now.
              </Alert>
            ) : (
              <Alert color="gray" title={`The plan is locked (job is ${plan.status})`}>
                Types can only be chosen while the job is PENDING_DB_CREATE, before any table was
                created. This view is read-only; the applied types are shown.
              </Alert>
            )}
            {hasAnySuggestion(plan) && plan.amendable && (
              <Group justify="space-between">
                <Group gap="xs">
                  <Button
                    variant="default"
                    onClick={() => setSelection(acceptConfident(plan))}
                    data-testid="accept-confident"
                  >
                    Accept confident suggestions
                  </Button>
                  <Text size="sm" c="dimmed">
                    confidence ≥ 0.85 with at least some sampled values validating; weak or
                    contradicted suggestions stay unticked for you to judge.
                  </Text>
                </Group>
                <Group gap="xs">
                  <Text size="sm" data-testid="selected-count">
                    {countSelected(selection)} selected
                  </Text>
                  <Button
                    variant="filled"
                    disabled={countSelected(selection) === 0}
                    loading={save.isPending}
                    onClick={() => save.mutate(selection)}
                    data-testid="save-plan"
                  >
                    Save to plan
                  </Button>
                </Group>
              </Group>
            )}
            {save.isSuccess && (
              <Alert color="green" title="Saved" data-testid="plan-saved">
                The selected types are now part of the plan.
              </Alert>
            )}
            {save.isError && <Alert color="red">{apiMessage(save.error)}</Alert>}
            {tablesWithSuggestions.length === 0 && (
              <Text data-testid="no-suggestions">The detector suggested a type for no column.</Text>
            )}
            {tablesWithSuggestions.map((t) => (
              <SuggestionTable
                key={t.table}
                table={t}
                amendable={plan.amendable}
                selection={selection[t.table] ?? {}}
                onToggle={(column, on) => setSelection((s) => toggle(s, t.table, column, on))}
              />
            ))}
            {plan.amendable && hasAnySuggestion(plan) && (
              <Text size="sm" c="dimmed">
                A column you do not select keeps exactly what it has now (usually &quot;copy
                unchanged&quot;).
              </Text>
            )}
          </Stack>
        )}
      </QueryState>
    </Container>
  );
}

function SuggestionTable({
  table,
  amendable,
  selection,
  onToggle,
}: {
  table: PlanTable;
  amendable: boolean;
  selection: Record<string, boolean>;
  onToggle: (column: string, on: boolean) => void;
}) {
  const suggested = table.columns.filter((c) => c.suggestion);
  const applied = table.columns.filter((c) => c.semantic_type && !c.suggestion);
  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={3}>{table.table}</Title>
          <Text size="sm" c="dimmed">
            {suggested.length} suggested of {table.columns.length} columns
            {applied.length > 0 ? `, ${applied.length} applied without a suggestion` : ""}
          </Text>
        </Group>
        <Table.ScrollContainer minWidth={720}>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                {amendable && <Table.Th w={40} aria-label="Accept" />}
                <Table.Th>Column</Table.Th>
                <Table.Th>Type in the origin</Table.Th>
                <Table.Th>Suggested type</Table.Th>
                <Table.Th w={150}>Values that validate</Table.Th>
                <Table.Th>Confidence</Table.Th>
                <Table.Th>Why</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {suggested.map((c) => {
                const s = c.suggestion!;
                const share = c.suggestion!.validated_share;
                const weak = !isConfident(s);
                return (
                  <Table.Tr key={c.column} data-testid={`row-${table.table}-${c.column}`}>
                    {amendable && (
                      <Table.Td>
                        <Checkbox
                          aria-label={`Accept ${s.semantic_type} for ${table.table}.${c.column}`}
                          checked={selection[c.column] === true}
                          disabled={c.semantic_type !== null}
                          onChange={(e) => onToggle(c.column, e.currentTarget.checked)}
                        />
                      </Table.Td>
                    )}
                    <Table.Td ff="monospace">{c.column}</Table.Td>
                    <Table.Td>{c.source_type}</Table.Td>
                    <Table.Td>
                      <Group gap="xs">
                        <Badge variant="light">{s.semantic_type}</Badge>
                        {c.semantic_type && (
                          <Text size="xs" c="dimmed" data-testid="already-applied">
                            applied ({c.decided_by?.toLowerCase()})
                          </Text>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {share === null ? (
                        <Text size="xs" c="dimmed">
                          not sampled
                        </Text>
                      ) : (
                        <Group gap="xs">
                          <Progress
                            value={share * 100}
                            size="sm"
                            w={70}
                            color={share === 0 ? "red" : share < 0.6 ? "yellow" : "green"}
                          />
                          <Text size="xs">
                            {Math.round(share * 100)}% of {c.suggestion!.sampled}
                          </Text>
                        </Group>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" data-testid="confidence">
                        {s.confidence.toFixed(2)}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c={weak ? "dimmed" : undefined}>
                        {s.reason}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {applied.length > 0 && (
          <Text size="xs" c="dimmed">
            Applied with no suggestion (typed at job creation):{" "}
            {applied.map((c) => `${c.column} → ${c.semantic_type}`).join(", ")}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
