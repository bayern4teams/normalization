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
