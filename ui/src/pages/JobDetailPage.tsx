// One job: state, progress and the error report. The error page lives in the URL
// (`?page=`), so a reload shows the same page. Polls while the job runs.
import { Alert, Badge, Button, Container, Group, Loader, Progress, Stack, Table, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { startCloneJob, verifyCloneJobDatabase } from "../api/client";
import { apiMessage, getJob, getJobErrorsPage } from "../api/review";
import { POLL_MS, stateLabel } from "../lib/reviewJobs";

const ERRORS_PER_PAGE = 50;

export function JobDetailPage() {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const [params, setParams] = useSearchParams();
  const page = Math.max(0, Number(params.get("page")) || 0);
  const queryClient = useQueryClient();

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => (q.state.data?.status === "RUNNING" ? POLL_MS : false),
  });
  const running = jobQuery.data?.status === "RUNNING";
  const errorsQuery = useQuery({
    queryKey: ["job-errors", jobId, page],
    queryFn: () => getJobErrorsPage(jobId, ERRORS_PER_PAGE, page * ERRORS_PER_PAGE),
    refetchInterval: running ? POLL_MS : false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["job", jobId] });
  const verify = useMutation({ mutationFn: () => verifyCloneJobDatabase(jobId), onSuccess: refresh });
  const start = useMutation({ mutationFn: () => startCloneJob(jobId), onSuccess: refresh });
  const goToPage = (n: number) => setParams(n > 0 ? { page: String(n) } : {});

  const job = jobQuery.data;
  const total = errorsQuery.data?.total ?? null;
  const rows = errorsQuery.data?.rows ?? [];
  const lastPage = total === null ? null : Math.max(0, Math.ceil(total / ERRORS_PER_PAGE) - 1);

  return (
    <Container size="lg" py="md">
      <Group mb="md" gap="md">
        <Title order={1}>Job</Title>
        <Link to="/jobs">All jobs</Link>
        <Link to={`/quality?job=${encodeURIComponent(jobId)}`}>Quality report</Link>
      </Group>
      {jobQuery.isPending && <Loader size="sm" aria-label="Loading" />}
      {jobQuery.isError && (
        <Alert color="red" title="Could not load the job">
          {apiMessage(jobQuery.error)}
        </Alert>
      )}
      {job && (
        <Stack gap="md">
          <Group gap="xs">
            <Text ff="monospace">{job.job_id}</Text>
            <Badge variant="light" color={job.status === "FAILED" ? "red" : undefined} data-testid="job-state">
              {stateLabel(job.status)}
            </Badge>
            {job.stale && <Badge color="orange">stale: no progress recently, start it again to resume</Badge>}
          </Group>
          <Text>
            {job.source_database} to {job.destination_database}
          </Text>
          <Stack gap={4}>
            <Progress
              value={job.tables.length === 0 ? 0 : (job.progress.tables_completed.length / job.tables.length) * 100}
              aria-label="Tables completed"
            />
            <Text size="sm" data-testid="progress-text">
              {job.progress.tables_completed.length} of {job.tables.length} tables done, {job.progress.rows_done} rows
              {job.progress.current_table ? `, now ${job.progress.current_table}` : ""}
            </Text>
          </Stack>
          {job.error && (
            <Alert color="red" title="The job failed">
              {job.error}
            </Alert>
          )}
          {job.status === "PENDING_DB_CREATE" && (
            <Group>
              <Text size="sm">Create the destination database by hand, then verify it.</Text>
              <Button variant="default" loading={verify.isPending} onClick={() => verify.mutate()}>
                Verify database
              </Button>
            </Group>
          )}
          {job.status === "SCHEMA_READY" && (
            <Group>
              <Text size="sm">The empty tables exist.</Text>
              <Button variant="default" loading={start.isPending} onClick={() => start.mutate()}>
                Start clone
              </Button>
            </Group>
          )}
          {(verify.isError || start.isError) && <Alert color="red">{apiMessage(verify.error ?? start.error)}</Alert>}

          <Title order={2}>Errors{total !== null ? ` (${total})` : ""}</Title>
          {errorsQuery.isError && <Alert color="red">{apiMessage(errorsQuery.error)}</Alert>}
          {errorsQuery.data && rows.length === 0 && <Text>No errors.</Text>}
          {rows.length > 0 && (
            <Table.ScrollContainer minWidth={560}>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Table and column</Table.Th>
                    <Table.Th>Row</Table.Th>
                    <Table.Th>Error</Table.Th>
                    <Table.Th>Masked preview</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((e, i) => (
                    <Table.Tr key={i}>
                      <Table.Td>{e.field}</Table.Td>
                      <Table.Td>{e.record_ref}</Table.Td>
                      <Table.Td>{e.error}</Table.Td>
                      <Table.Td ff="monospace">{e.safe_preview}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {(page > 0 || (lastPage !== null && page < lastPage)) && (
            <Group>
              <Button variant="default" disabled={page === 0} onClick={() => goToPage(page - 1)}>
                Previous
              </Button>
              <Text size="sm">
                Page {page + 1}
                {lastPage !== null ? ` of ${lastPage + 1}` : ""}
              </Text>
              <Button variant="default" disabled={lastPage === null || page >= lastPage} onClick={() => goToPage(page + 1)}>
                Next
              </Button>
            </Group>
          )}
        </Stack>
      )}
    </Container>
  );
}
