# Terms

One fixed term per concept (J5). Use these words in every document. Each row
names where the concept lives in the code (`path::symbol`).

## Values and results

<!-- verified: 9f27526 -->

| Term | Definition | Code |
|---|---|---|
| Normalizer | An adapter that turns raw values of one or more semantic types into normalized values. | `packages/normcore/src/normcore/interfaces.py::Normalizer` |
| Normalized value | The one result shape: original, display, comparison, search, structured parts, status, confidence, flags, trace. | `packages/normcore/src/normcore/models.py::NormalizedValue` |
| Original | The raw input, kept byte for byte and never overwritten. | `packages/normcore/src/normcore/models.py::NormalizedValue` |
| Display | The human-readable canonical form. | `packages/normcore/src/normcore/models.py::NormalizedValue` |
| Comparison | A key for equality and fuzzy matching. It is lossy on purpose. | `packages/normcore/src/normcore/models.py::NormalizedValue` |
| Semantic type | What kind of field a column holds, such as `PHONE` or `DATE`. It selects the normalizer. | `packages/normcore/src/normcore/enums.py::FieldSemanticType` |
| Status | The outcome for one value: `NORMALIZED`, `UNCHANGED`, `REPAIRED`, `PARSED`, `AMBIGUOUS`, `INVALID`, `FAILED`, `PARTIAL` or `NEEDS_REVIEW`. | `packages/normcore/src/normcore/enums.py::NormalizationStatus` |
| Ambiguous | Status of a value the engine refused to resolve because two or more readings are valid. The original is kept. | `packages/normcore/src/normcore/enums.py::NormalizationStatus` |
| Needs review | Status of a value that was emitted but that a person must confirm. Only a changed verdict produces it. | `packages/normcore/src/normcore/enums.py::NormalizationStatus` |
| Confidence | A number from 0 to 1 that a normalizer states for its answer. It is not a probability until calibrated. | `packages/normcore/src/normcore/models.py::NormalizedValue` |
| Quality flag | A named warning on a value, such as `AMBIGUOUS_DATE` or `MOJIBAKE_FIXED`. | `packages/normcore/src/normcore/enums.py::QualityFlag` |
| Missing kind | The kind of missing value a sentinel stands for, such as `NULL` or `NOT_APPLICABLE`. | `packages/normcore/src/normcore/enums.py::MissingKind` |
| Reversibility | How much of the original a transform can recover: `LOSSLESS`, `REVERSIBLE`, `PARTIALLY_REVERSIBLE` or `LOSSY`. | `packages/normcore/src/normcore/enums.py::Reversibility` |
| Error policy | What to do with a value that fails, such as `RETURN_ORIGINAL`. | `packages/normcore/src/normcore/enums.py::ErrorPolicy` |
| Trace | The step-by-step record of how a value changed. It holds hashes and masks, never raw values. | `packages/normcore/src/normcore/trace.py::TraceStep` |
| Mask | The Unicode character-class shape of a value. It stands in for the value in traces. | `packages/normcore/src/normcore/pii.py::character_class_mask` |

## Engine

<!-- verified: 9f27526 -->

| Term | Definition | Code |
|---|---|---|
| Dispatcher | The single entry point. It picks the normalizer, stamps `profile_version` and `env_id`, and checks `context_hash`. | `packages/normcore/src/normcore/dispatch.py::Dispatcher` |
| Registry | The map from semantic type to normalizer, built once per process. | `packages/normcore/src/normcore/dispatch.py::NormalizerRegistry` |
| Context | The facts about a field that change how a value reads: country, locale, source, table, field. | `packages/normcore/src/normcore/context.py::NormalizationContext` |
| Context hash | A hash of the context, without the value. It is part of cache and verdict keys. | `packages/normcore/src/normcore/context.py::NormalizationContext` |
| Profile | A versioned set of per-field settings for a run. | `packages/normcore/src/normcore/rules.py::NormalizationProfile` |
| Run | One execution of a profile over values, with metrics and a status. | `packages/normcore/src/normcore/run.py::NormalizationRun` |
| Environment id (`env_id`) | A hash of package versions, own source, ICU and CLDR versions, and dictionaries. Equal ids make two runs comparable. | `packages/normexec/src/normexec/env_fingerprint.py::compute_env_id` |
| Distinct-value planner | Normalizes each distinct value of a column once and maps the results back to the rows. | `packages/normexec/src/normexec/planner.py::DistinctValuePlanner` |
| Cache | An in-memory LRU plus a DuckDB tier, keyed by hashes of the raw value, profile, type, context and `env_id`. | `packages/normexec/src/normexec/cache.py::NormalizationCache` |
| Dictionary | A versioned, checksummed data file, such as the missing-value sentinels. | `packages/normdict/src/normdict/loader.py::DictionaryLoader` |
| Sidecar store | A Parquet and DuckDB store for normalized columns, keyed by source row. | `packages/normio/src/normio/sidecar_store.py::SidecarStore` |
| Data contract | The rule that `NormalizedValue` is declared once and the JSON and Arrow forms derive from it. | `packages/normcore/src/normcore/contract.py::normalized_value_json_schema` |

## Clone and normalize

<!-- verified: 9f27526 -->

| Term | Definition | Code |
|---|---|---|
| Origin | The source database. A normal clone only reads it. | `packages/normio/src/normio/connector.py::SourceConnector` |
| Destination | The new database that receives the cloned and normalized tables. | `packages/normio/src/normio/connectors/postgres_destination.py::PostgresDestination` |
| Clone job | One request to clone an origin into a destination and normalize it. | `packages/normapi/src/normapi/clone_executor.py::create_clone_job` |
| Clone job status | The job life cycle: `PENDING_DB_CREATE`, `SCHEMA_READY`, `RUNNING`, `COMPLETED`, `FAILED`. | `packages/normcore/src/normcore/enums.py::CloneJobStatus` |
| Phase 1 | Creates every destination table empty, after the user has run `CREATE DATABASE` by hand. | `packages/normapi/src/normapi/clone_executor.py::verify_and_create_schema` |
| Phase 2 | Streams, normalizes and writes the rows on a background thread. | `packages/normapi/src/normapi/clone_executor.py::start_phase2` |
| Checkpoint | The last committed row offset of a table, always at a block boundary. A resumed job starts after it. | `packages/normapi/src/normapi/clone_executor.py::_resume_point` |
| In-place clone | An opt-in clone that writes into the origin database under staging names and swaps each table in, replacing the original. | `packages/normapi/src/normapi/clone_executor.py::verify_and_create_schema` |
| Type autodetect | Suggesting a semantic type per column from a sample. It is off by default and writes nothing unless a column is opted in. | `packages/normapi/src/normapi/clone_executor.py::_suggest_field_types` |
| Typed destination | Destination columns typed for numbers, money, booleans and date bounds instead of all text. | `packages/normapi/src/normapi/clone_executor.py::_destination_plan` |
| Companion column | An extra destination column beside a normalized one, such as `<col>_code`. | `packages/normapi/src/normapi/clone_executor.py::_apply_value` |
| Lineage | OpenLineage events that record which destination column came from which origin column. | `packages/normapi/src/normapi/lineage.py::table_run` |
| Connection | A saved database login. The password is encrypted at rest. | `packages/normapi/src/normapi/secrets.py::encrypt` |

## Abstention and quality

<!-- verified: 9f27526 -->

| Term | Definition | Code |
|---|---|---|
| Abstention | Declining to answer: the engine keeps the original and returns `AMBIGUOUS` instead of guessing. | `packages/normapi/src/normapi/clone_executor.py::_calibrate` |
| Adjudication | A person or agent decides an ambiguous value. The decision is a verdict. | `packages/normapi/src/normapi/adjudication.py::Adjudication` |
| Queue | One row per ambiguous value and context, with an occurrence count. | `packages/normapi/src/normapi/adjudication.py::Adjudication.collect` |
| Verdict | An append-only decision for a queue key. It applies to every later run in the same context and profile version. | `packages/normapi/src/normapi/adjudication.py::apply_verdict` |
| Verdict key | A hash of semantic type, value, context hash and profile version. | `packages/normapi/src/normapi/adjudication.py::verdict_key` |
| Source identity | `engine://host:port/database[/schema]`. It keys verdicts so a re-saved connection keeps them. | `packages/normapi/src/normapi/adjudication.py::source_identity` |
| Calibration | Measuring whether stated confidence matches observed accuracy, and choosing a threshold. | `packages/normanalysis/src/normanalysis/calibration.py::calibration_table` |
| Calibrated abstention | An opt-in per-job mode that holds answers below a type's calibrated threshold. | `packages/normapi/src/normapi/clone_executor.py::_calibrate` |
| Cost ratio | How much worse a wrong answer is than an abstention. It has no default. | `packages/normanalysis/src/normanalysis/calibration.py::chow_threshold` |
| Gold corpus | Labelled cases with truth the engine does not decide, plus a scorer. | `packages/normanalysis/src/normanalysis/gold.py::score` |
| Disguised missing | A value that stands for "missing" but is not a known sentinel, such as `Ingen`. It is reported as a candidate and never rewritten unconfirmed. | `packages/normanalysis/src/normanalysis/disguised_missing.py::detect_disguised_missing` |
| Column evidence | The day/month order or decimal mark that the unambiguous values of a column prove. It resolves the ambiguous ones. | `packages/normcore/src/normcore/context.py::NormalizationContext` |
