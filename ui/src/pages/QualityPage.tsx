// Quality: one clone job's quality report as a live page. The job is in the URL
// (`?job=`), and the page polls while the job runs. Per column it shows how the values came
// out; it never shows a value, because `disguised_missing` carries raw ones (R23): only how
// many candidates there are.
import { Alert, Badge, Container, Group, Loader, Progress, Select, Stack, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { apiMessage, getJobQuality, listCloneJobs, type ColumnQuality } from "../api/review";
import { POLL_MS, stateLabel } from "../lib/reviewJobs";

// Colours by position in the sorted status names, so a status keeps its colour in every row.
const PALETTE = ["teal", "blue", "yellow", "orange", "red", "grape", "cyan", "gray"];

export function QualityPage() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get("job");

  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: listCloneJobs });
  const quality = useQuery({
    queryKey: ["job-quality", jobId],
    queryFn: () => getJobQuality(jobId ?? ""),
    enabled: jobId !== null,
    refetchInterval: (q) => (q.state.data?.status === "RUNNING" ? POLL_MS : false),
  });

  const report = quality.data;
  const tables = report ? Object.entries(report.tables) : [];
  const statuses = [
    ...new Set(tables.flatMap(([, columns]) => Object.values(columns).flatMap((c) => Object.keys(c.statuses)))),
  ].sort();
  const colour = (status: string) => PALETTE[statuses.indexOf(status) % PALETTE.length];

  return (
    <Container size="lg" py="md">
      <Title order={1} mb="md">
        Quality
      </Title>
      <Select
        label="Job"
        placeholder={jobsQuery.isPending ? "Loading jobs" : "Choose a job"}
        data={(jobsQuery.data ?? []).map((j) => ({
          value: j.job_id,
          label: `${j.source_database} to ${j.destination_database}, ${stateLabel(j.status)} (${j.job_id.slice(0, 8)})`,
        }))}
        value={jobId}
        onChange={(value) => setParams(value ? { job: value } : {})}
        mb="md"
        allowDeselect={false}
      />
      {jobsQuery.isError && <Alert color="red">{apiMessage(jobsQuery.error)}</Alert>}
      {jobId === null && <Text>Choose a job to see how its columns normalized.</Text>}
      {jobId !== null && quality.isPending && <Loader size="sm" aria-label="Loading" />}
      {quality.isError && (
        <Alert color="red" title="Could not load the report">
          {apiMessage(quality.error)}
        </Alert>
      )}
      {report && (
        <Stack gap="lg">
          <Group gap="xs">
            <Badge variant="light" data-testid="quality-state">
              {stateLabel(report.status)}
            </Badge>
            {report.status === "RUNNING" && <Text size="sm">Updating while the job runs.</Text>}
            <Link to={`/jobs/${encodeURIComponent(report.job_id)}`}>Job detail</Link>
          </Group>
          {tables.length === 0 && (
            <Text>No table has finished yet. A table appears here as soon as it completes.</Text>
          )}
          {statuses.length > 0 && (
            <Group gap="sm" aria-label="Legend">
              {statuses.map((s) => (
                <Badge key={s} color={colour(s)} variant="light">
                  {s}
                </Badge>
              ))}
            </Group>
          )}
          {tables.map(([table, columns]) => (
            <Stack key={table} gap="xs">
              <Title order={2}>{table}</Title>
              <Table.ScrollContainer minWidth={640}>
                <Table>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Column</Table.Th>
                      <Table.Th>Values</Table.Th>
                      <Table.Th w="40%">Outcome</Table.Th>
                      <Table.Th>Emptied</Table.Th>
                      <Table.Th>Second pass changed</Table.Th>
                      <Table.Th>Below threshold</Table.Th>
                      <Table.Th>Disguised-missing candidates</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {Object.entries(columns).map(([column, c]) => (
                      <ColumnRow key={column} name={column} c={c} colour={colour} />
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </Stack>
          ))}
        </Stack>
      )}
    </Container>
  );
}

function ColumnRow({ name, c, colour }: { name: string; c: ColumnQuality; colour: (status: string) => string }) {
  const entries = Object.entries(c.statuses);
  return (
    <Table.Tr>
      <Table.Td>{name}</Table.Td>
      <Table.Td>{c.values}</Table.Td>
      <Table.Td>
        <Progress.Root size="lg" aria-label={`Outcome of ${name}`}>
          {entries.map(([status, n]) => (
            <Progress.Section key={status} value={c.values > 0 ? (n / c.values) * 100 : 0} color={colour(status)} title={`${status}: ${n}`} />
          ))}
        </Progress.Root>
        <Text size="xs" c="dimmed">
          {entries.map(([status, n]) => `${status} ${n}`).join(", ")}
        </Text>
      </Table.Td>
      <Table.Td>{c.emptied}</Table.Td>
      <Table.Td>
        {c.not_idempotent} of {c.checked_idempotent} checked
      </Table.Td>
      <Table.Td>{c.calibration?.below_threshold ?? "none"}</Table.Td>
      <Table.Td>{c.disguised_missing?.length ?? 0}</Table.Td>
    </Table.Tr>
  );
}
