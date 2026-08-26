// Thin fetch wrapper over the real normapi §98 surface. Every function
// here calls a real endpoint — there is no mock data anywhere in this
// client; a page with nothing to show renders an honest empty state
// instead.

import { getApiKey } from "./authStore";
import type {
  AbComparisonReport,
  CollisionDecision,
  CollisionDecisionType,
  CollisionGroup,
  ColumnMappingResponse,
  ConnectionKindInfo,
  ConnectionResponse,
  ConnectionTestResponse,
  DictionarySummary,
  ErrorPolicy,
  FieldNormalizationConfig,
  FieldProfile,
  FieldSemanticType,
  FieldSummary,
  ImpactReport,
  NormalizationError,
  NormalizationProfile,
  NormalizationRun,
  NormalizedValue,
  OverviewReport,
  ProfileSuggestion,
  QualityReport,
  RunColumnSpec,
  RunSourceRequest,
  TableSpecResponse,
  TypeSuggestion,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8080";
const BASE = `${API_BASE}/normalization`;

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
  const apiKey = getApiKey();
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      ...(init?.headers ?? {}),
    },
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

// --- profiles ---------------------------------------------------------

export function listProfiles(): Promise<NormalizationProfile[]> {
  return request("/profiles");
}

export function getProfile(profileId: string): Promise<NormalizationProfile> {
  return request(`/profiles/${profileId}`);
}

export function listProfileVersions(profileId: string): Promise<NormalizationProfile[]> {
  return request(`/profiles/${profileId}/versions`);
}

export function createProfile(body: {
  name: string;
  description?: string;
  locale_policy?: Record<string, string>;
  default_operations?: string[];
  field_configs?: FieldNormalizationConfig[];
  created_by: string;
}): Promise<NormalizationProfile> {
  return request("/profiles", { method: "POST", body: JSON.stringify(body) });
}

export function createProfileVersion(
  profileId: string,
  body: {
    description?: string | null;
    locale_policy?: Record<string, string> | null;
    default_operations?: string[] | null;
    field_configs?: FieldNormalizationConfig[] | null;
    created_by: string;
  },
): Promise<NormalizationProfile> {
  return request(`/profiles/${profileId}/versions`, { method: "POST", body: JSON.stringify(body) });
}

export function rollbackProfile(
  profileId: string,
  targetVersion: string,
): Promise<NormalizationProfile> {
  return request(`/profiles/${profileId}/rollback`, {
    method: "POST",
    body: JSON.stringify({ target_version: targetVersion }),
  });
}

// --- fields -------------------------------------------------------------

export function listFields(): Promise<FieldSummary[]> {
  return request("/fields");
}

// --- type detection / profile suggestion (§61, §62, §84) -------------------

export function detectType(
  fieldName: string,
  sampleValues: (string | null)[] = [],
): Promise<TypeSuggestion[]> {
  return request("/detect-type", {
    method: "POST",
    body: JSON.stringify({ field_name: fieldName, sample_values: sampleValues }),
  });
}

export function suggestProfile(
  semanticType: FieldSemanticType,
  sampleValue?: string,
): Promise<ProfileSuggestion> {
  const params = new URLSearchParams({ semantic_type: semanticType });
  if (sampleValue) params.set("sample_value", sampleValue);
  return request(`/suggest-profile?${params.toString()}`);
}

// --- preview / field-test ------------------------------------------------

export function preview(body: {
  field_name: string;
  semantic_type: FieldSemanticType;
  values: (string | null)[];
  error_policy?: ErrorPolicy;
}): Promise<NormalizedValue[]> {
  return request("/preview", { method: "POST", body: JSON.stringify(body) });
}

export function fieldTest(body: {
  field_name: string;
  semantic_type: FieldSemanticType;
  value: string | null;
  error_policy?: ErrorPolicy;
}): Promise<NormalizedValue> {
  return request("/field-test", { method: "POST", body: JSON.stringify(body) });
}

// --- runs -----------------------------------------------------------------

export function listRuns(): Promise<NormalizationRun[]> {
  return request("/runs");
}

export function createRun(
  profileId: string,
  sourceSnapshot: string,
  execution?:
    | {
        field_name: string;
        semantic_type: FieldSemanticType;
        values: (string | null)[];
        error_policy?: ErrorPolicy;
      }
    | {
        field_name: string;
        semantic_type: FieldSemanticType;
        source: RunSourceRequest;
        error_policy?: ErrorPolicy;
      },
): Promise<NormalizationRun> {
  const params = new URLSearchParams({
    profile_id: profileId,
    source_snapshot: sourceSnapshot,
  });
  return request(`/runs?${params.toString()}`, {
    method: "POST",
    body: execution ? JSON.stringify(execution) : undefined,
  });
}

export function getRun(runId: string): Promise<NormalizationRun> {
  return request(`/runs/${runId}`);
}

// M18: `table`/`column` select one column of a multi-column run; omitted,
// the original single-column lookup is unchanged.
export interface ColumnSelector {
  table?: string;
  column?: string;
}

function selectorParams(selector?: ColumnSelector): string {
  if (!selector?.table) return "";
  const params = new URLSearchParams({ table: selector.table });
  if (selector.column) params.set("column", selector.column);
  return `?${params.toString()}`;
}

export function getRunErrors(
  runId: string,
  selector?: ColumnSelector,
): Promise<NormalizationError[]> {
  return request(`/runs/${runId}/errors${selectorParams(selector)}`);
}

export function getRunCollisions(
  runId: string,
  selector?: ColumnSelector,
): Promise<CollisionGroup[]> {
  return request(`/runs/${runId}/collisions${selectorParams(selector)}`);
}

export function recordCollisionDecision(
  runId: string,
  body: {
    normalized_value: string;
    decision: CollisionDecisionType;
    decided_by: string;
    note?: string;
    table?: string;
    column?: string;
  },
): Promise<CollisionDecision> {
  return request(`/runs/${runId}/collisions/decision`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- sources (§105, M10) ---------------------------------------------------

export function listSources(): Promise<string[]> {
  return request("/sources");
}

export function listSourceTables(sourceId: string): Promise<string[]> {
  return request(`/sources/${sourceId}/tables`);
}

// M18: real offset/limit pagination, pushed down to DuckDB for a
// sidecar-backed selection — never fetches a whole multi-million-row
// column at once.
export function getRunValues(
  runId: string,
  selector?: ColumnSelector & { offset?: number; limit?: number },
): Promise<{ original: string | null; result: NormalizedValue }[]> {
  const params = new URLSearchParams();
  if (selector?.table) params.set("table", selector.table);
  if (selector?.column) params.set("column", selector.column);
  if (selector?.offset !== undefined) params.set("offset", String(selector.offset));
  if (selector?.limit !== undefined) params.set("limit", String(selector.limit));
  const qs = params.toString();
  return request(`/runs/${runId}/values${qs ? `?${qs}` : ""}`);
}

export function getRunProfile(runId: string, selector?: ColumnSelector): Promise<FieldProfile> {
  return request(`/runs/${runId}/profile${selectorParams(selector)}`);
}

export function compareRuns(
  runIdA: string,
  runIdB: string,
  selector?: ColumnSelector,
): Promise<AbComparisonReport> {
  const params = new URLSearchParams({ run_id_a: runIdA, run_id_b: runIdB });
  if (selector?.table) params.set("table", selector.table);
  if (selector?.column) params.set("column", selector.column);
  return request(`/runs/compare?${params.toString()}`);
}

// --- impact / overview / quality -------------------------------------------

export function getImpact(runId: string, selector?: ColumnSelector): Promise<ImpactReport> {
  const params = new URLSearchParams({ run_id: runId });
  if (selector?.table) params.set("table", selector.table);
  if (selector?.column) params.set("column", selector.column);
  return request(`/impact?${params.toString()}`);
}

export function getOverview(): Promise<OverviewReport> {
  return request("/overview");
}

export function getQuality(): Promise<QualityReport> {
  return request("/quality");
}

// --- dictionaries -----------------------------------------------------------

export function listDictionaries(): Promise<DictionarySummary[]> {
  return request("/dictionaries");
}

export interface DictionaryDetail {
  id: string;
  version: string;
  locale: string | null;
  source: string;
  license: string;
  created_at: string;
  entries: Record<string, unknown>;
  content_hash: string;
  is_custom: boolean;
}

export function getDictionary(dictionaryId: string, version?: string): Promise<DictionaryDetail> {
  const params = version ? `?${new URLSearchParams({ version }).toString()}` : "";
  return request(`/dictionaries/${dictionaryId}${params}`);
}

export function createDictionary(body: {
  id: string;
  entries?: Record<string, unknown>;
  locale?: string | null;
  source: string;
  license: string;
  created_by: string;
}): Promise<DictionarySummary> {
  return request("/dictionaries", { method: "POST", body: JSON.stringify(body) });
}

export function createDictionaryVersion(
  dictionaryId: string,
  body: {
    entries?: Record<string, unknown>;
    locale?: string | null;
    source?: string | null;
    license?: string | null;
    created_by: string;
    merge?: boolean;
  },
): Promise<DictionarySummary> {
  return request(`/dictionaries/${dictionaryId}/versions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function rollbackDictionary(
  dictionaryId: string,
  targetVersion: string,
  by: string,
): Promise<DictionarySummary> {
  return request(`/dictionaries/${dictionaryId}/rollback`, {
    method: "POST",
    body: JSON.stringify({ target_version: targetVersion, by }),
  });
}

export function deleteDictionary(dictionaryId: string, by: string): Promise<void> {
  const params = new URLSearchParams({ by });
  return request(`/dictionaries/${dictionaryId}?${params.toString()}`, { method: "DELETE" });
}

// --- connections (M15, M21 Connect step) ------------------------------

export function listConnectionKinds(): Promise<ConnectionKindInfo[]> {
  return request("/connection-kinds");
}

export function testConnection(body: {
  kind: string;
  host: string;
  port?: number;
  username: string;
  password: string;
  database: string;
}): Promise<ConnectionTestResponse> {
  return request("/connections/test", { method: "POST", body: JSON.stringify(body) });
}

export function createConnection(body: {
  alias: string;
  kind: string;
  host: string;
  port?: number;
  username: string;
  password: string;
  database: string;
}): Promise<ConnectionResponse> {
  return request("/connections", { method: "POST", body: JSON.stringify(body) });
}

export function listConnections(): Promise<ConnectionResponse[]> {
  return request("/connections");
}

export function deleteConnection(connectionId: string): Promise<void> {
  return request(`/connections/${connectionId}`, { method: "DELETE" });
}

// --- catalog browsing (M14/M16, M21 Explore step) -----------------------

export function listConnectionDatabases(connectionId: string): Promise<string[]> {
  return request(`/connections/${connectionId}/databases`);
}

export function listConnectionTables(connectionId: string, database: string): Promise<string[]> {
  return request(`/connections/${connectionId}/databases/${database}/tables`);
}

export function getConnectionTableColumns(
  connectionId: string,
  database: string,
  table: string,
): Promise<TableSpecResponse> {
  return request(`/connections/${connectionId}/databases/${database}/tables/${table}/columns`);
}

export function sampleConnectionTable(
  connectionId: string,
  database: string,
  table: string,
  n = 5,
): Promise<Record<string, string[]>> {
  const params = new URLSearchParams({ n: String(n) });
  return request(
    `/connections/${connectionId}/databases/${database}/tables/${table}/samples?${params.toString()}`,
  );
}

// --- column mappings (M16, M21 Explore step) -----------------------------

export function listColumnMappings(
  connectionId: string,
  database: string,
  table: string,
): Promise<ColumnMappingResponse[]> {
  return request(`/connections/${connectionId}/databases/${database}/tables/${table}/mappings`);
}

export function upsertColumnMapping(
  connectionId: string,
  database: string,
  table: string,
  column: string,
  body: { semantic_type: FieldSemanticType; enabled?: boolean; updated_by: string; profile_id?: string },
): Promise<ColumnMappingResponse> {
  return request(
    `/connections/${connectionId}/databases/${database}/tables/${table}/columns/${column}/mapping`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

// --- multi-column runs (M17, M21 Explore -> Report) ----------------------

export function startMultiColumnRun(
  runId: string,
  body: {
    connection_id: string;
    database: string;
    columns: RunColumnSpec[];
    chunk_size?: number;
    mode?: "incremental" | "full_resync";
  },
): Promise<NormalizationRun> {
  return request(`/runs/${runId}/columns`, { method: "POST", body: JSON.stringify(body) });
}
