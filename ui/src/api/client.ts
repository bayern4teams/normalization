// Thin fetch wrapper over the real normapi §98 surface. Every function
// here calls a real endpoint — there is no mock data anywhere in this
// client; a page with nothing to show renders an honest empty state
// instead.

import type {
  CloneJob,
  CloneJobCreateResponse,
  ColumnInfo,
  Connection,
  ConnectionEngine,
  FieldSemanticType,
} from "./types";

// Same origin: the API serves this UI (ADR-023, one port, no CORS). `npm run dev` and
// `npm run preview` forward this prefix to the API (vite.config.ts).
const BASE = "/normalization";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(ApiError.describeDetail(status, detail));
    this.status = status;
    this.detail = detail;
  }

  private static describeDetail(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "detail" in detail) {
      const inner = (detail as { detail: unknown }).detail;
      if (typeof inner === "string") return inner;
    }
    return `API request failed with status ${status}`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

// --- DB-clone-and-normalize: saved connections -------------------------------

export function listConnections(): Promise<Connection[]> {
  return request("/connections");
}

export function createConnection(body: {
  engine: ConnectionEngine;
  host: string;
  port: number;
  username: string;
  password: string;
}): Promise<Connection> {
  return request("/connections", { method: "POST", body: JSON.stringify(body) });
}

// "Test connection" (U1): the API has no test route; listing the server's databases with the
// not-yet-saved credentials ("adhoc") is the same check Save's later use would make, and it
// goes through the address check (D15), which answers 422 for a refused host.
export function testConnection(body: {
  engine: ConnectionEngine;
  host: string;
  port: number;
  username: string;
  password: string;
}): Promise<string[]> {
  return request("/connections/adhoc/databases", { method: "POST", body: JSON.stringify(body) });
}

export function deleteConnection(connectionId: string): Promise<void> {
  return request(`/connections/${connectionId}`, { method: "DELETE" });
}

// --- DB-clone-and-normalize: discovery ---------------------------------------

export function listDatabases(connectionId: string): Promise<string[]> {
  return request(`/connections/${connectionId}/databases`, { method: "POST" });
}

export function listTables(connectionId: string, database: string): Promise<string[]> {
  return request(`/connections/${connectionId}/databases/${database}/tables`);
}

export function listColumns(
  connectionId: string,
  database: string,
  table: string,
): Promise<ColumnInfo[]> {
  return request(`/connections/${connectionId}/databases/${database}/tables/${table}/columns?limit=1000`);
}

// --- DB-clone-and-normalize: clone jobs --------------------------------------

export function createCloneJob(body: {
  source_connection_id: string;
  source_database: string;
  destination_connection_id: string;
  destination_database: string;
  tables?: string[];
  field_configs: Record<string, Record<string, FieldSemanticType | null>>;
}): Promise<CloneJobCreateResponse> {
  return request("/clone-jobs", { method: "POST", body: JSON.stringify(body) });
}

export function verifyCloneJobDatabase(jobId: string): Promise<CloneJob> {
  return request(`/clone-jobs/${jobId}/verify-database`, { method: "POST" });
}

export function startCloneJob(jobId: string): Promise<CloneJob> {
  return request(`/clone-jobs/${jobId}/start`, { method: "POST" });
}
