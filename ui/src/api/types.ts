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

// --- DB-clone-and-normalize (normio wiring) ---------------------------------

export type ConnectionEngine = "postgres" | "clickhouse";

export interface Connection {
  connection_id: string;
  engine: ConnectionEngine;
  host: string;
  port: number;
  username: string;
  created_at: string;
}

export interface ColumnInfo {
  name: string;
  native_type: string;
}

export type CloneJobStatus = "PENDING_DB_CREATE" | "SCHEMA_READY" | "RUNNING" | "COMPLETED" | "FAILED";

export interface CloneJobProgress {
  current_table: string | null;
  tables_completed: string[];
  rows_done: number;
  checkpoints: Record<string, number>;
}

export interface CloneJob {
  job_id: string;
  status: CloneJobStatus;
  source_connection_id: string;
  source_database: string;
  destination_connection_id: string;
  destination_database: string;
  tables: string[];
  field_configs: Record<string, Record<string, FieldSemanticType | null>>;
  progress: CloneJobProgress;
  error: string | null;
}

export interface CloneJobCreateResponse {
  job_id: string;
  status: CloneJobStatus;
  create_database_sql: string;
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
