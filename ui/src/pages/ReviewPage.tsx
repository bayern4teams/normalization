// Review: one distinct ambiguous value at a time, with its count and every candidate
// reading. Nothing is pre-selected: a number key picks the n-th reading (that is "accept"),
// `o` opens a text field, `k` keeps the value ambiguous, `u` undoes. A decision is held for
// UNDO_WINDOW_MS before its POST, so a key press changes the DOM without waiting for the
// network. This is the only screen that shows the raw value (R23).
import { Alert, Badge, Button, Code, Container, Group, Kbd, Loader, Paper, Stack, Text, TextInput, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiMessage, getReviewEntries, postVerdict, type ReviewEntry } from "../api/review";
import { actionForKey, KEEP_KEY, OTHER_KEY, UNDO_KEY, type ReviewAction } from "../lib/reviewKeys";
import { initialQueue, isCurrent, queueReducer, UNDO_WINDOW_MS } from "../lib/reviewQueue";
import { extractNotes, extractReadings } from "../lib/reviewReadings";

const DECIDED_BY = "human:reviewer";
// shortcut: kept in memory, so a refusal after a real tab close is never shown (the page is gone);
// upgrade path: store it in sessionStorage if decisions are lost that way.
const lostOnLeave: string[] = [];

export function ReviewPage() {
  // Refusals of decisions sent while leaving; read once when the screen opens again.
  const [lost] = useState(() => lostOnLeave.splice(0));
  const query = useQuery({
    queryKey: ["review-entries"],
    queryFn: getReviewEntries,
    // The list is read once; later decisions are tracked here, not by refetching (R22).
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
  // The API already sends most frequent first; sorting again keeps the order if it ever does not.
  const entries = useMemo(
    () => (query.data ? [...query.data.entries].sort((a, b) => b.occurrences - a.occurrences) : null),
    [query.data],
  );

  return (
    <Container size="sm" py="md">
      <Title order={1} mb="md">
        Review
      </Title>
      {lost.length > 0 && (
        <Alert color="red" title="Decisions sent when you left were not saved" mb="md" data-testid="lost-on-leave">
          The values are still pending and are in the list below. {lost.join(" ")}
        </Alert>
      )}
      {query.isPending && <Loader size="sm" aria-label="Loading" />}
      {query.isError && (
        <Alert color="red" title="Could not load the review list">
          {apiMessage(query.error)}
        </Alert>
      )}
      {entries && entries.length === 0 && (
        <Text>
          Nothing to review. Values that cannot be normalized without a guess appear here after a clone job runs; see{" "}
          <Link to="/jobs">Jobs</Link>.
        </Text>
      )}
      {entries && query.data && query.data.total !== null && query.data.total > entries.length && (
        <Alert color="yellow" title="Not every pending value is shown" mb="md" data-testid="truncated">
          This list holds the {entries.length.toLocaleString("en-US")} most frequent of{" "}
          {query.data.total.toLocaleString("en-US")} pending values ({entries.length.toLocaleString("en-US")} of{" "}
          {query.data.total.toLocaleString("en-US")}). Reload the page after deciding these to get the next ones.
        </Alert>
      )}
      {entries && entries.length > 0 && <ReviewSession entries={entries} />}
    </Container>
  );
}

function ReviewSession({ entries }: { entries: ReviewEntry[] }) {
  const [state, dispatch] = useReducer(queueReducer, entries, (e) => initialQueue(e.map((x) => x.key)));
  const [otherFor, setOtherFor] = useState<string | null>(null);
  const [otherText, setOtherText] = useState("");
  const timers = useRef(new Map<string, number>());
  const itemsRef = useRef(state.items);

  const entry = isCurrent(state) ? entries[state.cursor] : null;
  const item = entry ? state.items[state.cursor] : null;
  const readings = useMemo(() => (entry ? extractReadings(entry.detail) : []), [entry]);
  const otherOpen = entry !== null && otherFor === entry.key;

  const act = (action: ReviewAction) => {
    // A focused button would otherwise take Enter or Space for the next value.
    (document.activeElement as HTMLElement | null)?.blur();
    if (action.type === "undo") return dispatch({ type: "undo" });
    if (!entry) return;
    if (action.type === "keep") return dispatch({ type: "skip" });
    if (action.type === "other") return setOtherFor(entry.key);
    const reading = readings[action.index];
    if (!reading) return;
    if (reading.value === null) return dispatch({ type: "notice", text: reading.note });
    dispatch({
      type: "decide",
      value: reading.value,
      rationale: `Reading ${action.index + 1} of ${readings.length} chosen in the review screen`,
    });
  };

  const submitOther = () => {
    if (!entry || otherText.trim() === "") return;
    dispatch({ type: "decide", value: otherText, rationale: "Value typed in the review screen" });
    setOtherFor(null);
    setOtherText("");
  };

  // Keys. Re-registered after every render so the handler always sees the current state.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const action = actionForKey(event, readings.length, event.target as HTMLElement | null);
      if (!action) return;
      event.preventDefault(); // the key must not also be typed into the field it opens
      act(action);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  // Send each held decision once its undo window has passed; cancel the timer on undo.
  useEffect(() => {
    itemsRef.current = state.items;
    for (const it of state.items) {
      const timer = timers.current.get(it.key);
      if (it.status === "held" && timer === undefined) {
        const { key, value, rationale } = it;
        timers.current.set(
          key,
          window.setTimeout(() => {
            timers.current.delete(key);
            dispatch({ type: "sending", key });
            postVerdict(key, { decided_value: value ?? "", decided_by: DECIDED_BY, rationale: rationale ?? "" })
              .then(() => dispatch({ type: "saved", key }))
              .catch((error: unknown) => dispatch({ type: "failed", key, message: apiMessage(error) }));
          }, UNDO_WINDOW_MS),
        );
      } else if (it.status !== "held" && timer !== undefined) {
        window.clearTimeout(timer);
        timers.current.delete(it.key);
      }
    }
  }, [state.items]);

  // Leaving the page must not lose a decision that is still held back.
  useEffect(() => {
    const timerMap = timers.current;
    const sent = new Set<string>(); // pagehide and unmount both call flush: send once
    const flush = () => {
      for (const it of itemsRef.current) {
        if (it.status !== "held" || sent.has(it.key)) continue;
        sent.add(it.key);
        window.clearTimeout(timerMap.get(it.key));
        timerMap.delete(it.key);
        void postVerdict(
          it.key,
          { decided_value: it.value ?? "", decided_by: DECIDED_BY, rationale: it.rationale ?? "" },
          { keepalive: true },
        ).catch((error: unknown) => lostOnLeave.push(apiMessage(error)));
      }
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, []);

  const count = (status: string) => state.items.filter((i) => i.status === status).length;
  const waiting = count("held") + count("sending");
  const failed = state.items.map((i, n) => ({ ...i, n })).filter((i) => i.error !== undefined && i.status === "pending");

  return (
    <Stack gap="md">
      <Group justify="space-between" aria-live="polite">
        <Text data-testid="position">
          {entry ? `${state.cursor + 1} of ${entries.length}` : `${entries.length} values`}
        </Text>
        <Text size="sm" c="dimmed">
          {count("saved")} saved, {waiting} waiting to send, {count("skipped")} kept ambiguous
        </Text>
      </Group>

      {failed.length > 0 && (
        <Alert color="red" title="A decision was not saved">
          {failed.map((f) => (
            <Group key={f.key} justify="space-between">
              <Text size="sm">
                Value {f.n + 1}: {f.error}
              </Text>
              <Button size="compact-sm" variant="default" onClick={() => dispatch({ type: "goto", index: f.n })}>
                Go back to it
              </Button>
            </Group>
          ))}
        </Alert>
      )}

      {entry && item ? (
        <Paper key={entry.key} withBorder p="lg">
          <Stack gap="md">
            <Group gap="xs">
              <Badge variant="light">{entry.semantic_type}</Badge>
              <Badge variant="outline" color="gray" data-testid="occurrences">
                {entry.occurrences} {entry.occurrences === 1 ? "occurrence" : "occurrences"}
              </Badge>
            </Group>
            <Code block fz="xl" data-testid="raw-value" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {entry.original}
            </Code>
            <ContextBadges context={entry.context} />
            {item.error && <Alert color="red">{item.error}</Alert>}
            <Stack gap="xs" role="group" aria-label="Candidate readings">
              {readings.map((reading, index) => (
                <Button
                  key={index}
                  variant="default"
                  justify="flex-start"
                  fullWidth
                  aria-keyshortcuts={String(index + 1)}
                  leftSection={<Kbd>{index + 1}</Kbd>}
                  onClick={() => act({ type: "pick", index })}
                >
                  {reading.shown}
                  {reading.tag ? ` (${reading.tag})` : ""}
                </Button>
              ))}
            </Stack>
            {readings.length === 0 && (
              <Text size="sm">
                No candidate readings were found in this entry. Detail as the API sent it:
                <Code block mt="xs">
                  {JSON.stringify(entry.detail, null, 2)}
                </Code>
              </Text>
            )}
            {extractNotes(entry.detail).map((note, index) => (
              <Text key={index} size="sm" c="dimmed">
                {note}
              </Text>
            ))}
            {otherOpen && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  submitOther();
                }}
              >
                <Group align="flex-end">
                  <TextInput
                    style={{ flex: 1 }}
                    label="Other value"
                    description="Enter saves it, Escape cancels. The API only stores a value that normalizes cleanly."
                    value={otherText}
                    onChange={(event) => setOtherText(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") setOtherFor(null);
                    }}
                    data-autofocus
                    autoFocus
                  />
                  <Button type="submit">Save</Button>
                </Group>
              </form>
            )}
            <Group>
              <Button variant="default" aria-keyshortcuts={OTHER_KEY} leftSection={<Kbd>{OTHER_KEY}</Kbd>} onClick={() => act({ type: "other" })}>
                Other value
              </Button>
              <Button variant="default" aria-keyshortcuts={KEEP_KEY} leftSection={<Kbd>{KEEP_KEY}</Kbd>} onClick={() => act({ type: "keep" })}>
                Keep ambiguous
              </Button>
              <Button variant="default" aria-keyshortcuts={UNDO_KEY} leftSection={<Kbd>{UNDO_KEY}</Kbd>} onClick={() => act({ type: "undo" })}>
                Undo
              </Button>
            </Group>
          </Stack>
        </Paper>
      ) : (
        <Paper withBorder p="lg" data-testid="review-done">
          <Stack gap="sm">
            <Title order={2}>No value is waiting for you</Title>
            <Text>
              {count("saved") + waiting} decided, {count("skipped")} kept ambiguous, {failed.length} not saved.
            </Text>
            <Group>
              {state.items.some((i) => i.status === "skipped" || i.status === "pending") && (
                <Button variant="default" onClick={() => dispatch({ type: "reviewAgain" })}>
                  Review the open values again
                </Button>
              )}
              <Button variant="default" aria-keyshortcuts={UNDO_KEY} leftSection={<Kbd>{UNDO_KEY}</Kbd>} onClick={() => act({ type: "undo" })}>
                Undo
              </Button>
            </Group>
          </Stack>
        </Paper>
      )}

      {state.notice && (
        <Text size="sm" role="status">
          {state.notice}
        </Text>
      )}
      {waiting > 0 && (
        <Text size="sm" c="dimmed" role="status">
          Decisions are sent about {UNDO_WINDOW_MS / 1000} seconds after you make them. Press {UNDO_KEY} to cancel the last.
        </Text>
      )}
    </Stack>
  );
}

function ContextBadges({ context }: { context: Record<string, unknown> }) {
  // Scalars only; a hash says nothing to a person.
  const shown = Object.entries(context).filter(
    ([name, v]) => v !== null && typeof v !== "object" && !name.includes("hash"),
  );
  if (shown.length === 0) return null;
  return (
    <Group gap="xs">
      {shown.map(([name, v]) => (
        <Badge key={name} variant="outline" color="gray" tt="none">
          {name}: {String(v)}
        </Badge>
      ))}
    </Group>
  );
}
