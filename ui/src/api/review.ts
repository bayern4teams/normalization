// API calls for the Review, Jobs and Quality screens (U1 lane C). Kept apart from
// client.ts so these screens do not depend on it; the base is the page's own
// origin because the API serves the UI (one port, no CORS, no absolute URL).
// Job calls that client.ts already has (getCloneJob, startCloneJob,
// verifyCloneJobDatabase) are reused from there, not repeated.

import type { CloneJob, FieldSemanticType, NormalizationError } from "./types";
import { ApiError } from "./client";

// VITE_API_BASE_URL stays an opt-in for `vite dev`; unset, requests are same-origin.
const BASE = `${(import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ""}/normalization`;

/** One open question (GET /adjudication/review). The only response with the raw value (R23). */
export interface ReviewEntry {
  key: string;
  semantic_type: FieldSemanticType;
  original: string;
  context: Record<string, unknown>;
  detail: Record<string, unknown>;
  occurrences: number;
  decided: boolean;
}

export interface VerdictBody {
  decided_value: string;
  decided_by: string;
  rationale: string;
}

/** Job as the API returns it, plus the advisory `stale` flag (GET /clone-jobs/{id}). */
export type JobListItem = CloneJob & { stale?: boolean };

/** `tables[table][column]` of GET /clone-jobs/{id}/quality. `disguised_missing` carries raw
 * values, so the Quality screen reads its length only (R23). */
export interface ColumnQuality {
  values: number;
  statuses: Record<string, number>;
  emptied: number;
  checked_idempotent: number;
  not_idempotent: number;
  calibration?: { below_threshold?: number } | null;
  disguised_missing?: unknown[];
}

export interface JobQuality {
  job_id: string;
  status: string;
  tables: Record<string, Record<string, ColumnQuality>>;
}

/** Text the person can act on: FastAPI's 422 body is a string or a list of {msg}. */
export function apiMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.detail as { detail?: unknown } | undefined;
    const detail = body && typeof body === "object" ? body.detail : undefined;
    if (Array.isArray(detail)) {
      return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d))).join("; ");
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Unknown error";
}

async function get<T>(path: string): Promise<{ body: T; headers: Headers }> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new ApiError(resp.status, detail);
  }
  return { body: (await resp.json()) as T, headers: resp.headers };
}

export async function getReviewEntries(): Promise<ReviewEntry[]> {
  return (await get<ReviewEntry[]>("/adjudication/review")).body;
}

/** `keepalive` lets a held decision still reach the API while the page closes. */
export async function postVerdict(
  key: string,
  body: VerdictBody,
  options: { keepalive?: boolean } = {},
): Promise<void> {
  const resp = await fetch(`${BASE}/adjudication/queue/${encodeURIComponent(key)}/verdicts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: options.keepalive,
  });
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new ApiError(resp.status, detail);
  }
}

// ponytail: GET /clone-jobs (list) is not in the API yet; this expects an array of the same
// objects as GET /clone-jobs/{id}. Upgrade path: none needed once the route exists.
export async function listCloneJobs(): Promise<JobListItem[]> {
  return (await get<JobListItem[]>("/clone-jobs")).body;
}

export async function getJob(jobId: string): Promise<JobListItem> {
  return (await get<JobListItem>(`/clone-jobs/${encodeURIComponent(jobId)}`)).body;
}

export async function getJobQuality(jobId: string): Promise<JobQuality> {
  return (await get<JobQuality>(`/clone-jobs/${encodeURIComponent(jobId)}/quality`)).body;
}

/** One page of the job's errors with the job-wide total from `X-Total-Count`. */
export async function getJobErrorsPage(
  jobId: string,
  limit: number,
  offset: number,
): Promise<{ rows: NormalizationError[]; total: number | null }> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const { body, headers } = await get<NormalizationError[]>(
    `/clone-jobs/${encodeURIComponent(jobId)}/errors?${params.toString()}`,
  );
  const total = Number(headers.get("X-Total-Count"));
  return { rows: body, total: Number.isFinite(total) && headers.has("X-Total-Count") ? total : null };
}
