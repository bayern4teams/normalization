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
  RunSourceRequest,
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

export function getRunErrors(runId: string): Promise<NormalizationError[]> {
  return request(`/runs/${runId}/errors`);
}

export function getRunCollisions(runId: string): Promise<CollisionGroup[]> {
  return request(`/runs/${runId}/collisions`);
}

export function recordCollisionDecision(
  runId: string,
  body: { normalized_value: string; decision: CollisionDecisionType; decided_by: string; note?: string },
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

export function getRunValues(
  runId: string,
): Promise<{ original: string | null; result: NormalizedValue }[]> {
  return request(`/runs/${runId}/values`);
}

export function getRunProfile(runId: string): Promise<FieldProfile> {
  return request(`/runs/${runId}/profile`);
}

export function compareRuns(runIdA: string, runIdB: string): Promise<AbComparisonReport> {
  const params = new URLSearchParams({ run_id_a: runIdA, run_id_b: runIdB });
  return request(`/runs/compare?${params.toString()}`);
}

// --- impact / overview / quality -------------------------------------------

export function getImpact(runId: string): Promise<ImpactReport> {
  const params = new URLSearchParams({ run_id: runId });
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
