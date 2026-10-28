// Small helpers shared by the Jobs and Quality screens (named review* so the lane owns it).

// ponytail: a fixed 2 s poll while a job runs, carried over from the old clone-job page.
// Upgrade path: server push, if polling cost ever matters.
export const POLL_MS = 2000;

/** `PENDING_DB_CREATE` -> `pending db create`. The states themselves come from the API. */
export const stateLabel = (status: string): string => status.toLowerCase().replaceAll("_", " ");
