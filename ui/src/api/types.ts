// Hand-written TypeScript mirrors of the real normcore/normapi Pydantic
// models and normanalysis report shapes (Source.txt §107, §133), kept in
// sync with the actual JSON the live API returns — verified against a
// running `uvicorn normapi.main:app` during development, not guessed
// from the Python source alone.

export type FieldSemanticType =
  | "FREE_TEXT"
  | "PERSON_NAME"
  | "GIVEN_NAME"
  | "FAMILY_NAME"
  | "COMPANY_NAME"
  | "PHONE"
  | "EMAIL"
  | "ADDRESS"
  | "POSTCODE"
  | "DATE"
  | "DATETIME"
  | "COUNTRY"
  | "LANGUAGE"
  | "SCRIPT"
  | "IDENTIFIER"
  | "TAX_ID"
  | "CODE"
  | "UUID"
  | "NUMERIC"
  | "CURRENCY"
  | "QUANTITY"
  | "BOOLEAN"
  | "URL"
  | "UNKNOWN";

export type NormalizationStatus =
  | "NORMALIZED"
  | "UNCHANGED"
  | "REPAIRED"
  | "PARSED"
  | "AMBIGUOUS"
  | "INVALID"
  | "FAILED"
  | "PARTIAL"
  | "NEEDS_REVIEW";

export type MissingKind =
  | "NULL"
  | "EMPTY_STRING"
  | "UNKNOWN_VALUE"
  | "NOT_APPLICABLE"
  | "REDACTED"
  | "INVALID"
  | "PARSING_FAILED";

export type Reversibility = "LOSSLESS" | "REVERSIBLE" | "PARTIALLY_REVERSIBLE" | "LOSSY";

export type ErrorPolicy =
  | "FAIL_RECORD"
  | "SKIP_FIELD"
  | "RETURN_ORIGINAL"
  | "RETURN_NULL"
  | "MARK_INVALID";

export type ProfileStatus = "DRAFT" | "ACTIVE" | "DEPRECATED";
export type RunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "PARTIAL";

export interface TraceStep {
  step_order: number;
  rule_id: string;
  operation: string;
  params_hash: string;
  input_hash: string;
  output_hash: string;
  input_mask: string;
  output_mask: string;
  changed: boolean;
  lossy: boolean;
  reversibility: Reversibility;
  library: string | null;
  library_version: string | null;
  duration_us: number | null;
}

export interface NormalizedValue {
  original: string | null;
  original_kind: MissingKind | null;
  repaired: string | null;
  display: string | null;
  comparison: string | null;
  search: string | null;
  ascii: string | null;
  structured: Record<string, unknown>;
  validation_status: string | null;
  normalization_status: NormalizationStatus;
  confidence: number | null;
  flags: string[];
  warnings: string[];
  errors: string[];
  trace: TraceStep[];
  lossiness: Reversibility;
  profile_version: string;
  env_id: string;
  semantic_type: FieldSemanticType;
  context_hash: string;
}

export interface NormalizationStep {
  step_id: string;
  rule_id: string;
  operation: string;
  parameters: Record<string, unknown>;
  enabled: boolean;
  on_error: string;
  produces_view: string | null;
  claimed_reversibility: Reversibility;
  lossy: boolean;
}

export interface FieldNormalizationConfig {
  field_ref: string;
  semantic_type: FieldSemanticType;
  semantic_confidence: number;
  semantic_source: string;
  pipeline: { steps: NormalizationStep[] };
  error_policy: ErrorPolicy;
  locale_overrides: Record<string, string>;
  dictionary_refs: string[];
  emitted_views: string[];
}

export interface NormalizationProfile {
  id: string;
  name: string;
  version: string;
  description: string;
  status: ProfileStatus;
  locale_policy: Record<string, string>;
  default_operations: string[];
  field_configs: FieldNormalizationConfig[];
  created_at: string;
  updated_at: string;
  created_by: string;
  parent_version: string | null;
}

export interface NormalizationRunMetrics {
  records_processed: number;
  fields_processed: number;
  changed_values: number;
  unchanged_values: number;
  warnings: number;
  errors: number;
  cache_hits: number;
  cache_misses: number;
}

// M17 — one column a multi-column run normalizes.
export interface RunColumnSpec {
  table: string;
  column: string;
  semantic_type: FieldSemanticType;
}

// M17 — mid-run progress for a multi-column chunked execution.
export interface RunProgress {
  total_rows_estimate: number | null;
  rows_done: number;
  chunks_done: number;
  current_table: string | null;
  current_column: string | null;
  // M20
  rows_skipped_null_watermark: number;
}

export interface NormalizationRun {
  id: string;
  profile_id: string;
  profile_version: string;
  env_id: string;
  source_snapshot: string;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  metrics: NormalizationRunMetrics;
  failure_reason: string | null;
  // M17 — present (non-empty) only for a multi-column/destination run;
  // absent/empty for the original single-column pasted-values path.
  columns: RunColumnSpec[];
  progress: RunProgress | null;
}

export interface RunSourceRequest {
  source_id: string;
  table: string;
  column: string;
  row_limit?: number;
}

export interface NormalizationError {
  field: string;
  record_ref: string;
  operation: string;
  error: string;
  severity: string;
  safe_preview: string;
  rule_id: string | null;
  library_version: string | null;
}

export type CollisionDecisionType = "ACCEPTED" | "REJECTED" | "WHITELISTED";

export interface CollisionDecision {
  run_id: string;
  normalized_value: string;
  decision: CollisionDecisionType;
  decided_by: string;
  decided_at: string;
  note: string | null;
}

export interface CollisionGroup {
  normalized_value: string;
  original_values: string[];
  total_occurrences: number;
  decision: CollisionDecision | null;
}

export interface ImpactReport {
  field_name: string;
  total_values: number;
  unique_before: number;
  unique_after: number;
  new_collisions: number;
  null_before: number;
  null_after: number;
  avg_length_before: number;
  avg_length_after: number;
  lossy_count: number;
  partially_reversible_count: number;
  warnings: string[];
}

export interface SideMetrics {
  profile_version: string;
  total_values: number;
  unique_values: number;
  unique_ratio: number;
  invalid_count: number;
  invalid_rate: number;
}

export interface AbComparisonReport {
  field_name: string;
  a: SideMetrics;
  b: SideMetrics;
  changed_between_a_and_b: number;
  changed_between_a_and_b_pct: number;
  collision_rate_delta: number;
}

export interface TransformationPatternCount {
  operation: string;
  count: number;
}

export interface FieldProfile {
  field_name: string;
  rows: number;
  changed: number;
  unchanged: number;
  warnings: number;
  errors: number;
  potentially_lossy: number;
  top_transformation_patterns: TransformationPatternCount[];
}

export interface OverviewReport {
  fields_analyzed: number;
  fields_normalized: number;
  rows_processed: number;
  values_changed: number;
  warnings: number;
  potential_collisions: number;
  ambiguous_values: number;
  errors: number;
}

export interface QualityMetric {
  name: string;
  semantic_type: string;
  count: number;
  total_evaluated: number;
}

export interface QualityReport {
  metrics: QualityMetric[];
}

export interface DictionarySummary {
  id: string;
  version: string;
  locale: string | null;
  source: string;
  license: string;
  entry_count: number;
  is_custom: boolean;
  active_version: string | null;
}

export interface FieldSummary {
  field_ref: string;
  semantic_type: FieldSemanticType;
  profile_ids: string[];
}

export interface TypeSuggestion {
  semantic_type: FieldSemanticType;
  confidence: number;
  reason: string;
}

export interface ProfileSuggestion {
  semantic_type: FieldSemanticType;
  recommended_summary: string;
  risk: string;
  real_steps: string[];
}

// --- connections (M15) -------------------------------------------------

export interface ConnectionResponse {
  id: string;
  alias: string;
  kind: string;
  host: string;
  port: number;
  username: string;
  database: string;
  identity: string;
  created_at: string;
  updated_at: string;
}

export interface ConnectionKindInfo {
  kind: string;
  default_port: number;
}

export interface ConnectionTestResponse {
  ok: boolean;
  databases: string[];
  error: string | null;
}

// --- catalog (M14/M16) ---------------------------------------------------

export interface ColumnSpecResponse {
  name: string;
  type: string;
  nullable: boolean;
  is_primary_key: boolean;
}

export interface TableSpecResponse {
  name: string;
  engine: string | null;
  approx_rows: number | null;
  columns: ColumnSpecResponse[];
}

export type SemanticSource = "USER" | "AUTO_DETECTED" | "DEFAULT";

export interface ColumnMappingResponse {
  database: string;
  table_name: string;
  column_name: string;
  semantic_type: FieldSemanticType;
  semantic_source: SemanticSource;
  enabled: boolean;
  updated_at: string;
  updated_by: string;
}

export const FIELD_SEMANTIC_TYPES: FieldSemanticType[] = [
  "FREE_TEXT",
  "PERSON_NAME",
  "GIVEN_NAME",
  "FAMILY_NAME",
  "COMPANY_NAME",
  "PHONE",
  "EMAIL",
  "ADDRESS",
  "POSTCODE",
  "DATE",
  "DATETIME",
  "COUNTRY",
  "LANGUAGE",
  "SCRIPT",
  "IDENTIFIER",
  "TAX_ID",
  "CODE",
  "UUID",
  "NUMERIC",
  "CURRENCY",
  "QUANTITY",
  "BOOLEAN",
  "URL",
  "UNKNOWN",
];
