// Pure helpers for the plan-suggestions panel, kept out of the page so the
// rules (which columns are decidable, what a PATCH must send) are testable
// without a browser. The plan shapes themselves live in api/types.ts.

import type { FieldSemanticType, PlanResponse, PlanSuggestion } from "../api/types";

// Below this the detector is guessing; accepting en masse would paste
// wrong types over whole tables. Per-column checkboxes stay available for
// anything suggested — this cutoff only guards the mass-accept button.
export const CONFIDENT_CONFIDENCE = 0.85;

export function isConfident(s: PlanSuggestion): boolean {
  if (s.confidence < CONFIDENT_CONFIDENCE) return false;
  // A validated_share of 0 means sampled values actively failed the
  // type's validator (e.g. a `name` column that is not person names);
  // confidence alone must not override measurement.
  return s.validated_share === null || s.validated_share > 0;
}

export function hasAnySuggestion(plan: PlanResponse): boolean {
  return plan.tables.some((t) => t.columns.some((c) => c.suggestion !== null));
}

export type Selection = Record<string, Record<string, boolean>>;

export function toggle(selection: Selection, table: string, column: string, on: boolean): Selection {
  const forTable = { ...(selection[table] ?? {}) };
  if (on) forTable[column] = true;
  else delete forTable[column];
  const next = { ...selection, [table]: forTable };
  if (Object.keys(forTable).length === 0) delete next[table];
  return next;
}

export function acceptConfident(plan: PlanResponse): Selection {
  const next: Selection = {};
  for (const t of plan.tables) {
    for (const c of t.columns) {
      if (c.suggestion && c.semantic_type === null && isConfident(c.suggestion)) {
        (next[t.table] ??= {})[c.column] = true;
      }
    }
  }
  return next;
}

export function countSelected(selection: Selection): number {
  return Object.values(selection).reduce((n, cols) => n + Object.keys(cols).length, 0);
}

// What a Save sends: only toggled columns, merged server-side (the PATCH
// merges per table/column, so untouched columns keep whatever they had).
export function selectionToFieldConfigs(
  selection: Selection,
  plan: PlanResponse,
): Record<string, Record<string, FieldSemanticType | null>> {
  const typeOf = new Map<string, FieldSemanticType>();
  for (const t of plan.tables) {
    for (const c of t.columns) {
      if (c.suggestion) typeOf.set(`${t.table}.${c.column}`, c.suggestion.semantic_type);
    }
  }
  const out: Record<string, Record<string, FieldSemanticType | null>> = {};
  for (const [table, cols] of Object.entries(selection)) {
    for (const column of Object.keys(cols)) {
      const semanticType = typeOf.get(`${table}.${column}`);
      if (semanticType) (out[table] ??= {})[column] = semanticType;
    }
  }
  return out;
}
