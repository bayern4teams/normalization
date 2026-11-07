// Jobs: every clone job, filterable by state. The filter lives in the URL (`?state=`), so a
// reload shows the same list. The state buttons come from the states present in the data, so
// no list of states is typed here.
import { Alert, Badge, Button, Container, Group, Loader, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { apiMessage, listCloneJobs } from "../api/review";
import { POLL_MS, stateLabel } from "../lib/reviewJobs";

export function JobsPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("state");
  const query = useQuery({
    queryKey: ["jobs"],
    queryFn: listCloneJobs,
    retry: false,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "RUNNING") ? POLL_MS : false),
  });

  const jobs = query.data ?? [];
  const counts = new Map<string, number>();
  for (const job of jobs) counts.set(job.status, (counts.get(job.status) ?? 0) + 1);
  // A state from the URL stays selectable even when no job has it right now.
  if (selected && !counts.has(selected)) counts.set(selected, 0);
  const shown = selected ? jobs.filter((j) => j.status === selected) : jobs;
  const choose = (state: string | null) => setParams(state ? { state } : {});

  return (
    <Container size="lg" py="md">
      <Title order={1} mb="md">
        Jobs
      </Title>
      {query.isPending && <Loader size="sm" aria-label="Loading" />}
      {query.isError && (
        <Alert color="red" title="Could not load the jobs">
          {apiMessage(query.error)}
        </Alert>
      )}
      {query.data && (
        <>
          <Group gap="xs" mb="md" role="group" aria-label="Filter by state">
            <Button size="compact-md" variant={selected ? "default" : "filled"} aria-pressed={!selected} onClick={() => choose(null)}>
              All ({jobs.length})
            </Button>
            {[...counts].map(([state, n]) => (
              <Button
                key={state}
                size="compact-md"
                variant={selected === state ? "filled" : "default"}
                aria-pressed={selected === state}
                onClick={() => choose(state)}
              >
                {stateLabel(state)} ({n})
              </Button>
            ))}
          </Group>
          {shown.length === 0 ? (
            <Text>{jobs.length === 0 ? "No clone jobs yet. Start one from New clone." : "No job in this state."}</Text>
          ) : (
            <Table.ScrollContainer minWidth={640}>
              <Table highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Job</Table.Th>
                    <Table.Th>State</Table.Th>
                    <Table.Th>Source to destination</Table.Th>
                    <Table.Th>Tables done</Table.Th>
                    <Table.Th>Rows</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {shown.map((job) => (
                    <Table.Tr key={job.job_id}>
                      <Table.Td>
                        <Link to={`/jobs/${job.job_id}`}>{job.job_id}</Link>
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs">
                          <Badge variant="light" color={job.status === "FAILED" ? "red" : undefined}>
                            {stateLabel(job.status)}
                          </Badge>
                          {job.stale && (
                            <Badge variant="light" color="orange">
                              stale
                            </Badge>
                          )}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        {job.source_database} to {job.destination_database}
                      </Table.Td>
                      <Table.Td>
                        {job.progress.tables_completed.length} of {job.tables.length}
                      </Table.Td>
                      <Table.Td>{job.progress.rows_done}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </>
      )}
    </Container>
  );
}
