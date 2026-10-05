# Normalization Data Contract

Status: living document. Last updated: M1 (2026-08-17).

Satisfies `Source.txt` §107 (data contract) and §133 (normalization output
contract). This document describes the one shape every normalized value
takes, in every representation it appears in (Python object, JSON over the
API, Arrow/Parquet in the sidecar store) — and, critically, how those three
representations are kept from drifting apart.

## 1. The single source of truth

`packages/normcore/src/normcore/models.py::NormalizedValue` (a frozen
pydantic model) is the **only** place the contract's shape is declared.
Every other representation is *derived* from it programmatically, never
hand-maintained in parallel:

- **JSON Schema** (used in the OpenAPI document `normapi` publishes) comes
  from `NormalizedValue.model_json_schema()` — see
  `normcore.contract.normalized_value_json_schema()`.
- **Arrow schema** (used by the sidecar store, `normio.sidecar_store`)
  is declared once in `normcore.contract.NORMALIZED_VALUE_ARROW_SCHEMA`,
  with explicit `normalized_value_to_arrow_row()` /
  `arrow_row_to_normalized_value()` converters proven to round-trip
  losslessly in `tests/unit/test_data_contract.py`.

If a field is ever added to `NormalizedValue` without updating the Arrow
schema and converters, the round-trip test fails immediately — this is the
mechanism that prevents the three representations from silently drifting,
not a documentation promise.

## 2. Field-by-field contract

Per §0/§2, six distinct value types are never collapsed into one:

| Field | Type | Meaning |
|---|---|---|
| `original` | `str \| None` | Byte-preserved raw input. Never overwritten, never absent when the input had a value. |
| `original_kind` | `MissingKind \| None` | Set when `original` represents a detected missing-value sentinel (§53/§54), distinguishing NULL / EMPTY_STRING / NOT_APPLICABLE / etc. |
| `repaired` | `str \| None` | Post encoding/mojibake repair (§4.2, §10) — populated only when repair was evidence-gated and actually applied. |
| `display` | `str \| None` | Safe, human-readable canonical form (§2.A). |
| `comparison` | `str \| None` | Designed for equality/fuzzy comparison (§2.B) — deliberately lossy in ways `display` is not. |
| `search` | `str \| None` | Designed for lookup (§2.C). |
| `ascii` | `str \| None` | Optional lossy ASCII transliteration (§2.D, §16) — null unless explicitly requested for the field; never substitutes for the Unicode representation. |
| `structured` | `dict[str, Any]` | Parsed components (§2.E) — e.g. name/address/phone parts. Domain-specific shape per semantic type. |
| `validation_status` | `str \| None` | Domain-specific validation outcome (§2.F) — e.g. phone `is_valid`, email `VALID_SYNTAX`. |
| `normalization_status` | `NormalizationStatus` | One of NORMALIZED / UNCHANGED / REPAIRED / PARSED / AMBIGUOUS / INVALID / FAILED / PARTIAL / NEEDS_REVIEW (§67). `AMBIGUOUS`: the engine refused to choose (the value is queued for adjudication, ADR-018). `NEEDS_REVIEW`: a value was emitted and a person must confirm it — produced only when an adjudicated value now normalizes differently than when its verdict was given. |
| `confidence` | `float \| None` (0.0-1.0) | Per §66 — required for every parser/inference-heavy operation. |
| `flags` | `list[QualityFlag]` | §114's flag vocabulary (MOJIBAKE_FIXED, AMBIGUOUS_DATE, POTENTIAL_COLLISION, ...). |
| `warnings` | `list[str]` | Human-readable, non-fatal diagnostics. |
| `errors` | `list[str]` | Human-readable error messages (§68). |
| `trace` | `list[TraceStep]` | Full step-by-step transformation history (§65) — see §3 below. |
| `lossiness` | `Reversibility` | LOSSLESS / REVERSIBLE / PARTIALLY_REVERSIBLE / LOSSY (§80), empirically verified per ADR-012, not self-declared. |
| `profile_version` | `str` | Stamped by the `Dispatcher`, never trusted from the normalizer (see ADR-014 and `normcore.dispatch`). |
| `env_id` | `str` | The full environment fingerprint (ADR-014) — same stamping rule as `profile_version`. |
| `semantic_type` | `FieldSemanticType` | What kind of field this is (§60). |
| `context_hash` | `str` | Derived from `NormalizationContext` — verified by the `Dispatcher` to actually match the context passed in, catching normalizer bugs (see `tests/unit/test_dispatch.py::test_dispatcher_rejects_context_hash_mismatch_from_a_buggy_normalizer`). |

## 3. Trace (§65)

Each `TraceStep` records one pipeline step: `step_order`, `rule_id`,
`operation`, `params_hash`, `input_hash`/`output_hash` (content hashes, not
raw values — see §5 below), `input_mask`/`output_mask` (character-class
masks, see `normcore.pii`), `changed`, `lossy`, `reversibility`, and the
`library`/`library_version` that performed it. This is what backs the
"Why did this change?" UX (§117, M7) and the reversibility empirical
verification (ADR-012).

## 4. Arrow / Parquet representation

Two fields (`structured`, `trace`) are stored as JSON-encoded strings
(`structured_json`, `trace_json`) rather than nested Arrow structs — a
deliberate simplification for the sidecar store's Parquet columns
(stable, simple, queryable via DuckDB's JSON functions) over exactly
mirroring the Python object graph as nested Arrow types. See
`normcore.contract.NORMALIZED_VALUE_ARROW_SCHEMA` for the full column
list.

## 5. PII safety (§123)

Trace `input_mask`/`output_mask` are Unicode general-category shapes
(e.g. `"José García"` → `"Lu Ll Ll Ll Zs Lu Ll Ll Ll Ll Ll"`), computed by
`normcore.pii.character_class_mask()` — never the raw value. Raw previews
require an explicit, role-gated `pii_visibility="unmasked"` context and are
never the default. This is enforced structurally: `TraceStep` has no field
that holds a raw value at all.

## 6. Reproducibility guarantee

Given identical `(original, semantic_type, context, profile_version,
env_id)`, `NormalizedValue` is required to be byte-identical across runs —
this is ADR-014's core claim. It is proven, not just asserted, in
`tests/integration/test_byte_identical_replay.py`: a 1,000,000-row
synthetic dataset flows through two **independent OS processes** (not two
in-process calls) via the full connector → distinct-value planner →
normalizer → sidecar-store path, and the resulting Parquet output files
are SHA-256-identical.

## 7. Dispatcher-enforced invariants

Two invariants are enforced by `normcore.dispatch.Dispatcher`, not by
convention:

1. `profile_version` and `env_id` are **always** stamped by the dispatcher
   after a normalizer returns — a normalizer implementation has no way to
   know either value (they're not part of `NormalizationContext`), so this
   removes an entire class of "normalizer author forgot to stamp this
   correctly" bugs by construction.
2. `context_hash` **is** derivable by the normalizer (it has the
   `NormalizationContext`), so the dispatcher instead *verifies* the
   returned value's `context_hash` matches what it independently computes
   from the same context — catching a genuine normalizer bug rather than
   silently trusting or silently overwriting it.

## 8. What is NOT yet part of the contract (deferred to later milestones)

- Real semantic-domain `structured` shapes (name components, address
  components, phone components, ...) — M2+ define these as each
  normalizer adapter ships. M1's only adapter, `PassthroughNormalizer`,
  never populates `structured`.
- Collision/impact diagnostics as part of the per-value contract — those
  are run-level/dataset-level outputs (§77-§80), not per-`NormalizedValue`
  fields; they land with `normanalysis`'s M6 profiling/impact/collision
  subsystem.
