# Traceability Matrix

Status: living document — every row must remain accurate as implementation
proceeds; update in the same PR that touches the corresponding module or
test. Last updated: M16 catalog API + mappings (2026-08-26) — M16 row
marked Done with its real commit and pack link. Prior update: M15
connection registry (2026-08-26) — M15 row marked Done with its real
commit and pack link. Prior update: M14 connector
catalog + real streaming (2026-08-26) — M14 row marked Done with its real
commit and pack link. Prior update: M13
ledger catch-up (2026-08-26) — added the "M13–M22 program" section below
mapping the new product-pipeline milestones
(`docs/plan/M13-M22-program-plan.md`), none of Source.txt's original 138
sections. Prior update: M7 follow-up self-audit (2026-08-19) — the user
asked for an unbiased, from-scratch audit of M1–M7 before M8 began. That
audit cross-checked this file against the real repository state for the
first time since M0 and found several real, previously-undisclosed gaps
(not just staleness): §32 (POSTCODE had no registered normalizer),
§61/§62/§84 (field-type detection and profile auto-suggestion were never
built), and missing regression coverage for §123/§129/§135. All were
fixed, tested, and verified live in the same session — see
`docs/verification/M7-verification-pack.md`'s addendum for the full list.

**Test location columns below are the topic/intent captured at the time
each row was written, not a guaranteed exact current filename** — actual
test organization consolidated multiple sections' golden-corpus tests
into fewer per-milestone files (e.g. `tests/golden/test_m5_corpus.py`
covers §46–§55) rather than one file per section, a deliberate,
disclosed choice, not drift. To verify current *section coverage*
(every §N present somewhere), run the real mechanical check:

```bash
uv run python -m normcli check-traceability
```

(This command itself was, ironically, one of the audit's own findings —
this file had claimed since M0 that it was "built in M1" and ran at
every gate; neither was true until this same audit session built
`normcli` for real. See §127/§136 rows below.)

Maps every numbered section of the original specification (`Source.txt`,
138 sections numbered §0–§137) to the milestone and phase that implements
it, the module expected to contain the implementation, and the test
location expected to prove it. This is the mechanism that prevents any
requirement from being silently dropped across an 8-milestone, 18-phase
build — at every gate, this table is checked against actual repository
state as part of the verification pack.

Legend — **Mile.**: milestone; **Ph.**: implementation phase per §127.

| § | Title | Mile. | Ph. | Module | Test location |
|---|---|---|---|---|---|
| 0 | Most important design principle | M1–M2 | 2–3 | `normcore` (cross-cutting) | `tests/unit/test_design_principles.py` |
| 1 | Absolute data preservation rule | M1 | 2 | `normcore.models.NormalizedValue.original` | `tests/contract/test_data_contract.py` |
| 2 | Multi-view normalization | M1–M2 | 2–3 | `normcore.models`, `normalizers.*` | `tests/contract/test_multi_view.py` |
| 3 | Open-source-first requirement | M0 | 1 | — (process requirement) | `docs/normalization-tool-evaluation.md` |
| 4 (4.1–4.8) | Mandatory research phase | M0 | 1 | — | `docs/adr/ADR-001` … `ADR-016`, `docs/normalization-tool-evaluation.md` |
| 5 | Additional libraries to evaluate | M0 | 1 | — | `docs/normalization-tool-evaluation.md` §1, §4 |
| 6 | Tool evaluation document | M0 | 1 | — | `docs/normalization-tool-evaluation.md` |
| 7 | Normalization domain model | M1 | 2 | `normcore.models` | `tests/unit/test_domain_model.py` |
| 8 | Raw data must remain immutable | M1 | 2 | `normio.connectors.*` (no write method) | `tests/integration/test_readonly_connectors.py` |
| 9 | Normalization pipeline architecture | M1–M2 | 2–3 | `normcore.pipeline` | `tests/unit/test_pipeline.py` |
| 10 | General text normalization | M2 | 3 | `normalizers.generic_text` | `tests/golden/test_generic_text.py` |
| 11 | Unicode policy | M2 | 3 | `normalizers.unicode_normalizer` | `tests/golden/test_unicode.py` |
| 12 | Case normalization | M2 | 3 | `normalizers.unicode_normalizer` | `tests/golden/test_case.py` |
| 13 | Whitespace normalization | M2 | 3 | `normalizers.generic_text` | `tests/golden/test_whitespace.py` |
| 14 | Punctuation normalization | M2 | 3 | `normalizers.generic_text` | `tests/golden/test_punctuation.py` |
| 15 | Diacritics / accents | M2 | 3 | `normalizers.unicode_normalizer` | `tests/golden/test_diacritics.py` |
| 16 | Transliteration | M2 | 3 | `normalizers.unicode_normalizer` | `tests/golden/test_transliteration.py` |
| 17 | Confusable / look-alike handling | M2 | 3 | `normalizers.unicode_normalizer` (SpoofChecker) | `tests/golden/test_confusables.py` |
| 18 | Control characters | M2 | 3 | `normalizers.generic_text` | `tests/golden/test_control_chars.py` |
| 19 | Generic string derivatives | M2 | 3 | `normalizers.generic_text` | `tests/contract/test_derivatives.py` |
| 20 | Person name normalization | M3 | 4 | `normalizers.name` | `tests/golden/test_names.py` |
| 21 | Name tokenization | M3 | 4 | `normalizers.name` | `tests/golden/test_name_tokenization.py` |
| 22 | Name honorifics | M3 | 4 | `normalizers.name`, `normdict` | `tests/golden/test_honorifics.py` |
| 23 | Name suffixes | M3 | 4 | `normalizers.name`, `normdict` | `tests/golden/test_name_suffixes.py` |
| 24 | Nicknames / aliases | M3 | 4 | `normalizers.name` (disabled by default) | `tests/unit/test_nicknames_disabled.py` |
| 25 | Phonetic name variants | M3 | 4 | `normalizers.name` (jellyfish) | `tests/golden/test_phonetics.py` |
| 26 | Company name normalization | M3 | 5 | `normalizers.company` | `tests/golden/test_company.py` |
| 27 | Company suffix configuration | M3, M6 | 5, 13 | `normdict` (GLEIF ELF) | `tests/golden/test_company_suffixes.py` |
| 28 | Company name structure | M3 | 5 | `normalizers.company` | `tests/contract/test_company_structure.py` |
| 29 | Address normalization | M4 | 8 | `normalizers.address`, `services/libpostal` | `tests/golden/test_address.py` |
| 30 | Address display vs comparison | M4 | 8 | `normalizers.address` | `tests/contract/test_address_views.py` |
| 31 | Address expansion | M4 | 8 | `normalizers.address` | `tests/golden/test_address_expansion.py` |
| 32 | Postal code normalization | M4 (embedded-in-address), M7-audit (standalone `POSTCODE` field) | 8 | `normalizers.address` (google-i18n-address), `normalizers.postcode` (standalone field, real gap found/closed by the M7 follow-up audit — `FieldSemanticType.POSTCODE` existed since M1 but had no registered normalizer) | `tests/unit/test_address_normalizer.py`, `tests/unit/test_postcode_normalizer.py` |
| 33 | Country normalization | M4 | 10 | `normalizers.country` | `tests/golden/test_country.py` |
| 34 | Language normalization | M4 | 10 | `normalizers.language` | `tests/golden/test_language.py` |
| 35 | Script normalization | M4 | 10 | `normalizers.script` | `tests/golden/test_script.py` |
| 36 | Phone normalization | M3 | 6 | `normalizers.phone` | `tests/golden/test_phone.py` |
| 37 | Phone default region | M3 | 6 | `normalizers.phone` | `tests/golden/test_phone_region.py` |
| 38 | Phone extensions | M3 | 6 | `normalizers.phone` | `tests/golden/test_phone_extensions.py` |
| 39 | Email normalization | M3 | 7 | `normalizers.email` | `tests/golden/test_email.py` |
| 40 | Email domain normalization | M3 | 7 | `normalizers.email` | `tests/golden/test_email_domain.py` |
| 41 | Email validation | M3 | 7 | `normalizers.email` | `tests/golden/test_email_validation.py` |
| 42 | URL normalization | M6 (planned M5; delivered late as a discovered gap against §99's adapter list) | 12 | `normalizers.url` | `tests/unit/test_url_normalizer.py` |
| 43 | Date normalization | M4 | 9 | `normalizers.date` | `tests/golden/test_date.py` |
| 44 | Timezone normalization | M4 | 9 | `normalizers.date` | `tests/golden/test_timezone.py` |
| 45 | Non-Gregorian dates | M4 | 9 | `normalizers.date` | `tests/golden/test_nongregorian_dates.py` |
| 46 | Numeric normalization | M5 | 12 | `normalizers.numeric` | `tests/golden/test_numeric.py` |
| 47 | Currency normalization | M5 | 12 | `normalizers.currency` | `tests/golden/test_currency.py` |
| 48 | Unit normalization | M5 | 12 | `normalizers.unit` | `tests/golden/test_unit.py` |
| 49 | Identifier normalization | M5 | 11 | `normalizers.identifier` | `tests/golden/test_identifier.py` |
| 50 | UUID normalization | M5 | 11 | `normalizers.identifier` | `tests/golden/test_uuid.py` |
| 51 | Postcode / tax ID / business ID | M5 | 11 | `normalizers.identifier` (stdnum registry) | `tests/golden/test_country_specific_ids.py` |
| 52 | Boolean normalization | M5 | 12 | `normalizers.boolean` | `tests/golden/test_boolean.py` |
| 53 | Missing value normalization | M2 | 3 | `normalizers.missing_value` | `tests/golden/test_missing_values.py` |
| 54 | NULL vs empty vs unknown | M2 | 3 | `normcore.enums.MissingKind` | `tests/contract/test_missing_kind.py` |
| 55 | Numeric / text confusion | M5 | 11 | `normalizers.identifier` | `tests/golden/test_numeric_text_confusion.py` |
| 56 | Token normalization | M2 | 3 | `normalizers.generic_text` | `tests/golden/test_tokenization.py` |
| 57 | Abbreviation normalization | M4 (address abbreviations only, verified M7-audit) | 8 | Delegated entirely to libpostal inside `normalizers.address` — §57 explicitly prohibits "a universal expansion dictionary," and no other field type in this system has an abbreviation concept, so no separate `normdict` abbreviation dictionary was built (a deliberate non-gap, confirmed during the M7-audit, not an oversight) | `tests/unit/test_address_normalizer.py` |
| 58 | Dictionary framework | M1 (read), M6 (full) | 2, 13 | `normdict.loader`, `normdict.custom_store` | `tests/unit/test_normdict.py`, `tests/unit/test_custom_dictionary_store.py` |
| 59 | User custom dictionaries | M6 | 13 | `normdict.custom_store.CustomDictionaryStore` | `tests/unit/test_custom_dictionary_store.py`, `tests/golden/test_m6_corpus.py` |
| 60 | Semantic normalization | M1 (dispatch), M7 (UI) | 2, 16 | `normcore.dispatch`, `normapi` | `tests/unit/test_semantic_dispatch.py` |
| 61 | Automatic field type detection | M7-audit (planned M7, not actually built until the follow-up self-audit) | 16 | `normanalysis.type_detection`, `POST /normalization/detect-type`, Fields page UI | `tests/unit/test_type_detection.py` |
| 62 | Normalization profile auto-generation | M7-audit (planned M7, not actually built until the follow-up self-audit) | 16 | `normanalysis.profile_suggestion`, `GET /normalization/suggest-profile`, Fields page UI | `tests/unit/test_profile_suggestion.py` |
| 63 | Safe defaults | M2 | 3 | `normcore.default_profile` | `tests/unit/test_safe_defaults.py` |
| 64 | Lossy transformations | M1 (model), M6 (policy) | 2, 14 | `normcore` (`Reversibility`) | `tests/property/test_reversibility.py` |
| 65 | Normalization trace | M1 (model), M6 (full) | 2, 14 | `normcore.trace` | `tests/contract/test_trace.py` |
| 66 | Normalization confidence | M3+ | 4–12 | `normalizers.*` | `tests/golden/test_confidence.py` |
| 67 | Normalization status | M1 | 2 | `normcore.enums.NormalizationStatus` | `tests/contract/test_status_enum.py` |
| 68 | Error handling | M1 | 2 | `normcore.errors` | `tests/unit/test_error_handling.py` |
| 69 | Field-level error policy | M1 | 2 | `normcore.errors.ErrorPolicy` | `tests/unit/test_error_policy.py` |
| 70 | Normalization runs | M1 (model), M6 (full), M11 (RUNNING/FAILED lifecycle states actually reachable — the model always had them, but `execute_run()` finished synchronously within one request until now, so no caller could ever observe them; `POST /runs` returns immediately via `InMemoryStore.start_run_execution`, a background-thread wrapper, and `NormalizationRun` gains `failure_reason`) | 2, 14 | `normcore.run`, `normapi.store.InMemoryStore.execute_run`/`.start_run_execution` | `tests/unit/test_run_execution.py` (`TestExecuteRun`, `TestStartRunExecution`), `tests/golden/test_m6_corpus.py`/`test_m10_corpus.py`/`test_m10_source_execution.py` (all updated to poll `GET /runs/{id}` for a terminal status, the real M11 behavior change) |
| 71 | Idempotency | M2+ (unit/property), M6 (runtime-sampled) | 3–12, 14 | `normcore` testing helpers, `normanalysis.invariant_sampler` | `tests/property/test_idempotency_determinism.py`, `tests/unit/test_analysis_m6.py` |
| 72 | Determinism | M2+ | 3–12 | `normcore` testing helpers | `tests/property/test_determinism.py` |
| 73 | Version locking | M1 (real computation built but never importable by a running service), M9 (wired into the live `Dispatcher` for real — `env_id` was an M1-era hardcoded placeholder until now) | 2, 14 | `normexec.env_fingerprint`, `scripts/env_fingerprint.py` (thin CLI wrapper) | `tests/unit/test_env_fingerprint.py`, `tests/unit/test_normdict.py`; live-verified: two independent real server processes against the same environment produced the identical `env_id` |
| 74 | Normalization regression testing | M2+, finalized M8 | 3–18 | `tests/golden/` | `tests/golden/*` |
| 75 | Cross-language testing | M2, finalized M8 | 3, 18 | `tests/golden/cross_language/` | `tests/golden/cross_language/*` |
| 76 | Cultural safety | M3, M4 (real per-normalizer AMBIGUOUS/hint behaviors), M8 (consolidated cross-cutting proof) | 4, 8–10, 18 | `NameNormalizer`, `AddressNormalizer`, `PostcodeNormalizer`, `CompanyNormalizer`, `EmailNormalizer` | `tests/unit/test_cultural_safety.py` (all 6 named assumptions, one file) |
| 77 | Normalization profiling | M6 | 15 | `normanalysis.profiling` | `tests/unit/test_analysis_m6.py`, `tests/golden/test_m6_corpus.py` |
| 78 | Impact analysis | M6 | 15 | `normanalysis.impact` | `tests/unit/test_analysis_m6.py`, `tests/golden/test_m6_corpus.py` |
| 79 | Collision analysis | M6 | 15 | `normanalysis.collisions` | `tests/unit/test_analysis_m6.py`, `tests/golden/test_m6_corpus.py` |
| 80 | Reversibility analysis | M2–M5 (classification, per-rule), M7 (UI display) | 3–15, 16 | `normcore.enums.Reversibility`, per-normalizer `steps()` | `tests/golden/test_reversibility.py` |
| 81 | Normalization rule builder | M7 | 16 | `ui/src/features/rule-builder` | `tests/e2e/test_rule_builder.spec.ts` |
| 82 | Before / after UI | M7 | 16 | `ui/src/features/preview` | `tests/e2e/test_before_after.spec.ts` |
| 83 | Sample-based preview | M7 | 16 | `normapi` preview endpoint, UI | `tests/e2e/test_sample_preview.spec.ts` |
| 84 | Profile auto-suggestions | M7-audit (planned M7, not actually built until the follow-up self-audit) | 16 | `normanalysis.profile_suggestion`, Fields page UI (§61's detection UI and §84's suggestion UI share one compact widget rather than separate pages) | `tests/unit/test_profile_suggestion.py`; verified live in-browser (no dedicated e2e spec yet) |
| 85 | User control | M7 | 16 | UI (accept/modify/reject) | `tests/e2e/test_user_control.spec.ts` |
| 86 | Expert mode | M7 | 16 | `ui/src/modes/expert` | `tests/e2e/test_expert_mode.spec.ts` |
| 87 | Normal mode | M7 | 16 | `ui/src/modes/normal` | `tests/e2e/test_normal_mode.spec.ts` |
| 88 | Admin / engineering mode | M7 | 16 | `ui/src/modes/admin` | `tests/e2e/test_admin_mode.spec.ts` |
| 89 | Normalization UI (nav) | M7 | 16 | `ui/src/app` | `tests/e2e/test_navigation.spec.ts` |
| 90 | Normalization overview | M7 | 16 | `ui/src/features/overview` | `tests/e2e/test_overview.spec.ts` |
| 91 | Field detail UI | M7 | 16 | `ui/src/features/field-detail` | `tests/e2e/test_field_detail.spec.ts` |
| 92 | Collision dashboard | M7 (UI: Inspect only — Accept/Reject/Whitelist deliberately not rendered, no backend to back them, disclosed in the UI's own comment), M11 (backend: `CollisionDecisionType`/`CollisionDecision`, `POST /runs/{id}/collisions/decision`, Postgres-persisted per ADR-013's own explicit naming of collisions as metadata — UI wiring for these three buttons remains M12's job, same backend-then-UI-catch-up split as M10's DB connectors) | 16 | `ui/src/pages/CollisionsPage.tsx`, `normanalysis.collisions.CollisionDecision`, `normapi.store.InMemoryStore.record_collision_decision` | `tests/e2e/test_collision_dashboard.spec.ts`, `tests/golden/test_m11_collision_workflow.py`, `tests/integration/test_postgres_store_integration.py` (real Postgres round-trip + restart survival) |
| 93 | Quality dashboard | M7 | 16 | `ui/src/features/quality` | `tests/e2e/test_quality_dashboard.spec.ts` |
| 94 | Normalization run UI | M7 | 16 | `ui/src/features/runs` | `tests/e2e/test_run_detail.spec.ts` |
| 95 | Profile versioning | M1 (create/version), M6 (rollback) | 2, 14 | `normapi.store.InMemoryStore` | `tests/unit/test_normapi.py`, `tests/golden/test_m6_corpus.py` |
| 96 | A/B normalization | M6 | 15 | `normanalysis.ab_comparison` | `tests/unit/test_analysis_m6.py`, `tests/golden/test_m6_corpus.py` |
| 97 | Impact on downstream entity resolution | M6 (unique-ratio/candidate-key diagnostics folded into `ab_comparison`/`impact`, no separate module) | 15 | `normanalysis.ab_comparison`, `normanalysis.impact` | `tests/unit/test_analysis_m6.py` |
| 98 | API design | M1 (scaffold), M6 (all routes real, no remaining 501 stubs), M11 (lightweight API-key auth — `normapi.auth.enforce_api_key_for_mutations`, a pragmatic roadmap addition, not itself a numbered spec requirement; gates POST/PUT/PATCH/DELETE only, `NORM_API_KEY` unset means disabled, matching every other optional-integration env var) | 2, 14 | `normapi.routes`, `normapi.auth` | `tests/unit/test_normapi.py`, `tests/golden/test_m6_corpus.py`, `tests/unit/test_auth.py` |
| 99 | Internal normalizer interface | M1 | 2 | `normcore.interfaces` | `tests/unit/test_normalizer_interface.py` |
| 100 | No universal clean function | M1 | 2 | `normcore.dispatch` | `tests/unit/test_no_universal_clean.py` |
| 101 | Context object | M1 (`NormalizationContext` model — several normalizers already branched on `ctx.country`/`ctx.locale`/`ctx.default_region`/`ctx.dictionary_set`, e.g. phone region resolution, date MDY/DMY, currency symbol disambiguation), M10 (`NormalizationProfile.build_context` — the real, previously-missing plumbing from a profile's `locale_policy`/field-level `locale_overrides`/`dictionary_refs`/`error_policy` into that context; `InMemoryStore.execute_run` now calls it instead of building a bare context that left those fields `None` regardless of profile config) | 2 | `normcore.context`, `normcore.rules.NormalizationProfile.build_context` | `tests/unit/test_context.py`, `tests/unit/test_normcore_profile_and_run.py::TestBuildContext`, `tests/golden/test_m10_corpus.py` (proves real output changes through the live API, e.g. the same ambiguous date resolving MDY vs DMY purely from profile config) |
| 102 | Performance | M1 (`DistinctValuePlanner`/`NormalizationCache` built, real, but never connected to the live run path), M8 (wired into `InMemoryStore.execute_run` for real; a real ~10x cold-cache DuckDB-statement-overhead regression found by benchmarking and fixed via batched `get_many`/`put_many`) | 2, 17 | `normexec.planner.DistinctValuePlanner`, `normapi.store.InMemoryStore._normalize_deduped` | `tests/unit/test_planner.py`, `tests/unit/test_execution_caching.py` (live dedup/caching through `execute_run`), `tests/bench/test_execution_caching_benchmark.py` (real cache-cold/cache-warm/no-cache timings) |
| 103 | Normalization cache | M1 (skeleton), M8 (`get_many`/`put_many` batched reads/writes — DuckDB's real per-statement overhead made individual calls far slower than one batched call for the same N) | 2, 17 | `normexec.cache.NormalizationCache` | `tests/unit/test_cache.py` (`TestPutMany`, `TestGetMany`) |
| 104 | Batch processing | M1 (skeleton), M8 (tuned) | 2, 17 | `normexec.batch` | `tests/unit/test_batch_apis.py` |
| 105 | Database integration | M1 (`normio.connectors.*` — Postgres/MySQL/Mongo/ClickHouse/file, all real and tested, but never reachable from the live API — every run only ever accepted pasted `values`), M10 (`normapi.sources.SourceRegistry` wires all 5 into `POST /normalization/runs` via a new `source: {source_id, table, column, row_limit}` execution mode, plus `GET /normalization/sources`/`GET /normalization/sources/{id}/tables`; synchronous with an explicit row cap — default 10k, max 100k per request — since the async/chunked execution model is M11's job, not this one; source connection config comes from a server-side `NORM_SOURCES_CONFIG_PATH` JSON file, never a client-supplied DSN) | 2 | `normio.connectors.*`, `normapi.sources.SourceRegistry` | `tests/integration/test_readonly_connectors.py` (connector-level, real containers), `tests/unit/test_sources.py` (registry, real local FileConnector), `tests/golden/test_m10_source_execution.py` (live API, FileConnector), `tests/integration/test_run_execution_from_source.py` (live API against all 4 real demo-* DB containers) |
| 106 | Raw / normalized storage strategy | M1 (`SidecarStore` built, real, but never connected to the live API — a run's results only ever lived in `InMemoryStore._executions`, lost on restart, disclosed as a gap in M9's verification pack), M9 follow-up (wired into `InMemoryStore.execute_run`/`get_execution`: every run's real results are written through to Parquet and transparently rehydrated after a restart) | 2 | `normio.sidecar_store.SidecarStore`, `normapi.store.InMemoryStore._write_execution_to_sidecar`/`_hydrate_execution_from_sidecar` | `tests/unit/test_file_connector_and_sidecar.py`, `tests/unit/test_sidecar_persistence.py` (real restart simulated via a second independent `InMemoryStore`) |
| 107 | Data contract | M1 | 2 | `normcore.contract` | `tests/contract/test_data_contract.py` |
| 108 | Testing | M8 (finalized), incremental | 3–18 | `tests/` | (all) |
| 109 | Golden test data | M2+ | 3–18 | `tests/golden/fixtures/identity_corpus/` | `tests/golden/*` |
| 110 | Edge case tests | M2+, M8 | 3–18 | `tests/golden/fixtures/edge_cases/` | `tests/golden/test_edge_cases.py` |
| 111 | Collision tests | M5, M6 | 11, 15 | `tests/golden/fixtures/collisions/` | `tests/golden/test_collisions.py` |
| 112 | False-merge safety | M6, M8 | 15, 18 | — | `tests/golden/test_false_merge_safety.py` |
| 113 | Normalization should help, not pretend to know | M3, M6 (cross-cutting) | 4–5, 15 | — | `tests/unit/test_normalization_vs_aliasing.py` |
| 114 | Data quality flags | M1 (enum), M2+ (population) | 2–12 | `normcore.enums.QualityFlag` | `tests/contract/test_quality_flags.py` |
| 115 | Dictionary management UI | M7 | 16 | `ui/src/features/dictionaries` | `tests/e2e/test_dictionary_ui.spec.ts` |
| 116 | Rule builder UX | M7 | 16 | `ui/src/features/rule-builder` | `tests/e2e/test_rule_builder_ux.spec.ts` |
| 117 | Explanation UX | M7 | 16 | `ui/src/features/explanation` | `tests/e2e/test_explanation.spec.ts` |
| 118 | Normalization preview UX | M7 | 16 | `ui/src/features/preview` | `tests/e2e/test_preview_ux.spec.ts` |
| 119 | Change impact UI | M7 | 16 | `ui/src/features/impact` | `tests/e2e/test_change_impact.spec.ts` |
| 120 | Safe rollback | M6 (engine), M7 (UI) | 14, 16 | `normcore.profile`, UI | `tests/integration/test_rollback.py` |
| 121 | Normalization comparison workspace | M7 | 16 | `ui/src/features/comparison` | `tests/e2e/test_comparison_workspace.spec.ts` |
| 122 | Observability | M1 (OTel spans/metrics infra), M8 (full §122 counter set wired into live `execute_run`'s `NormalizationRunMetrics`), M12 (the OTel infra itself — real, tested since M1 — was never actually reachable from the live app until now: `create_app()` calls `setup_telemetry()` at startup, `InMemoryStore.execute_run` calls the new `record_run_metrics()` at completion; `NormalizationMetrics` gained the counters its own docstring already claimed but never created — `values_unchanged`/`parser_failures`/`validation_failures`/`library_calls`/`rows_per_second`; real OTLP/HTTP export added, `otlp_endpoint`/`NORM_OTLP_ENDPOINT`, closing a gap `setup_telemetry`'s own docstring had promised since M1) | 2, 17 | `normanalysis.telemetry`, `normanalysis.instrumentation.record_run_metrics`, `normanalysis.run_recorder.RunRecorder`, `normcore.run.NormalizationRunMetrics`, `normexec.planner.DistinctValuePlanner.distinct_value_results`'s `on_computed` hook | `tests/unit/test_telemetry.py` (includes a real local-HTTP-receiver test proving OTLP export puts real bytes on a socket), `tests/unit/test_run_recorder.py`, `tests/unit/test_planner.py`, `tests/unit/test_observability_metrics.py` |
| 123 | Security | M1 (wired), M8 (complete) | 2, 17 | `normcore.pii` | `tests/unit/test_pii_masking.py` |
| 124 | Open-source license tracking | M0, every gate | 1 | `docs/dependency-inventory.md`, `scripts/check_licenses.py` | CI (`ci-full`, `gate`) |
| 125 | Architecture decision records | M0 | 1 | `docs/adr/*` | — |
| 126 | Required documentation | M0, maintained every gate | 1–18 | `docs/*` | — |
| 127 | Implementation phases | gate model | — | — | — |
| 128 | Development rule (post-phase discipline) | gate model | — | CI workflows | — |
| 129 | Do not use LLM for core normalization | enforced every gate | 1–18 | `normcore`, `normalizers.*` (no LLM import) | `tests/unit/test_no_llm_in_core.py` |
| 130 | Autonomous research requirement | M0 | 1 | — | `docs/normalization-tool-evaluation.md` §4 |
| 131 | Best-of-breed selection | M0 | 1 | — | `docs/normalization-tool-evaluation.md` |
| 132 | Final tool evaluation report | M0 | 1 | — | `docs/normalization-tool-evaluation.md` §3 |
| 133 | Normalization output contract | M1 | 2 | `normcore.contract` | `tests/contract/test_output_contract.py` |
| 134 | Handoff to Data Discovery | M8 | 18 | `normanalysis.handoff.build_handoff_artifact`, `GET /normalization/runs/{run_id}/handoff` | `tests/unit/test_handoff.py` (7 tests against real normalizer output); live-verified via a real running `uvicorn` server (profile create -> run execute -> `GET .../handoff`, confirmed all 8 §134 fields: schema, semantic type, comparison values, parsed components, country metadata, VALID/INVALID validation status, real 3-way collision group) |
| 135 | Handoff to Splink (must stop before) | enforced every gate | 1–18 | CI check (no splink import) | `tests/unit/test_no_splink.py` |
| 136 | Final acceptance criteria | G8 | 18 | — | `docs/verification/M8-verification-pack.md` |
| 137 | First task before coding | M0 | 1 | — | this milestone itself |

## Coverage check (M0, mechanically verified M7-audit)

- 138 sections total (§0–§137).
- All 138 mapped to at least one milestone/phase/module/test location above.
- Cross-cutting requirements (§0, §71, §72, §108, §113, §123, §126, §129,
  §135) intentionally appear at multiple milestones because they are
  enforced continuously, not delivered once — this is by design, not
  duplication.
- This table's section-number coverage (not the module/test-location
  prose, which isn't mechanically checkable) is verified by
  `uv run python -m normcli check-traceability`, which parses every real
  `§N` header out of `Source.txt` and asserts each one has at least one
  row here. **This command did not exist before the M7 follow-up
  self-audit** despite this file claiming since M0 that it was "built in
  M1" and ran at every gate — neither was true. `.github/workflows/
  gate.yml` does not yet invoke it in any job; wiring it into the gate
  script proper (so a future PR that silently drops a row is caught by
  CI, not just by a human re-reading this file) is a reasonable M8
  follow-up, tracked here rather than silently assumed done.

## M13–M22 program (beyond Source.txt's original 138 sections)

`docs/plan/M13-M22-program-plan.md` is a user-approved follow-on program,
not part of the original spec — the `check-traceability` §N coverage check
above does not and should not cover these rows, since there is no
corresponding `§N` header in `Source.txt` for any of them. Tracked here for
the same reason every other milestone is tracked here: so no piece of this
program's own scope is silently dropped as work proceeds.

**All rows below are PLANNED, not yet implemented**, as of 2026-08-26. Do
not treat a row's presence here as evidence of real work — only a real,
live-verified `docs/verification/M{n}-verification-pack.md` is evidence.
This table is updated to reflect real status as each milestone closes,
matching the discipline every M0–M12 row above already follows.

| Item | Milestone | Module (planned) | Test location (planned) | Status |
|---|---|---|---|---|
| Ledger catch-up (retrospective plan, M12 pack, `check_signoff.py` fix) | M13 | `docs/plan/*`, `docs/verification/M12-verification-pack.md`, `scripts/check_signoff.py` | — (docs + a small script fix, no new test surface) | Done, this session |
| Connector catalog (databases/tables/columns/samples) + real streaming reads | M14 | `normio.catalog`, `normio.capabilities`, `normio.connectors.clickhouse`/`_sql_base`, `normapi.store` (`row_ordinal` fix) | `tests/unit/test_catalog.py`, `tests/integration/test_catalog_and_streaming.py` (live against real ClickHouse origin1/origin2 + demo-postgres/demo-mysql) | Done, `023b11d` — [pack](verification/M14-verification-pack.md) |
| Connection registry with encrypted credentials | M15 | `normapi.secrets`, `normapi.connections`, `normapi.migrations`, `normapi.postgres_store`, `normapi.sources` (hybrid pool), `normapi.routes`/`schemas`/`app` | `tests/unit/test_secrets.py`, `tests/unit/test_connections.py`, `tests/integration/test_connection_registry.py` (live against real ClickHouse origin2 + real Postgres) | Done, `7374055` — [pack](verification/M15-verification-pack.md) |
| Catalog API + connection-keyed column mappings; semantic-type-not-read-from-profile bug fix | M16 | `normapi.mappings`, `normapi.routes` (catalog + mapping endpoints), `normapi.store.execute_run`, `normapi.schemas` (`RunSourceRequest.database`) | `tests/unit/test_mappings.py`, `tests/golden/test_m16_field_ref_regression.py`, `tests/integration/test_catalog_and_mappings_api.py` (live against real ClickHouse origin2 + real Postgres) | Done, `078c597` — [pack](verification/M16-verification-pack.md) |
| Multi-column, chunked, resumable runs | M17 | `normcore.run` (`RunColumnSpec`, `RunProgress`), `normexec.stream`, `normexec.sinks`, `normapi.executor` | `tests/integration/test_stream_column.py`, `tests/integration/test_multi_column_runs_api.py` (live, includes a real resume-after-key test), `tests/bench/test_persistent_cache_benchmark.py` | Done, `63307ea` — [pack](verification/M17-verification-pack.md) |
| Multi-column reporting rebuilt on the sidecar (incl. bounded `/overview`/`/quality`) | M18 | `normapi.routes` (9 handlers), `normapi.store`, `normanalysis.column_stats`, `normio.sidecar_store` | `tests/integration/test_multi_column_reporting.py` (live), `tests/unit/test_overview_quality_bounded.py`, `tests/golden/test_m18_quality_predicate_parity.py` | Done, `7bee522` — [pack](verification/M18-verification-pack.md) |
| Destination writer — schema-mirrored write-back, side table for quality data | M19 | `normsink` (new package: `safety`, `destination`, `clickhouse`, `typed_values`), `normexec.destination_stream` | `tests/unit/test_self_write_refusal.py`, `tests/unit/test_typed_values.py`, `tests/integration/test_destination_writer.py` (live, includes idempotency + self-write-refusal proof) | Done, `6cb807d` — [pack](verification/M19-verification-pack.md) |
| Incremental watermark + full resync | M20 | `normapi.postgres_store` (`source_watermarks`), `normapi.store` (watermark resolve/advance), `normio` `read_chunk`'s `since` param, `CatalogConnector.count_null` | `tests/integration/test_incremental_watermark.py` (live, includes a NULL-watermark-skip proof) | Done, `196bf5b` — [pack](verification/M20-verification-pack.md) |
| 3-step UI (Connect / Explore / Report), legacy tabs behind `ModeContext` | M21 | `ui/src/pages/{Connect,Explore,Report}Page.tsx`, `ui/src/app/{App,Nav}.tsx`, `ui/src/api/{client,types}.ts`, `normapi.store` (sidecar-hydration 500 fix) | `ui/e2e/three-step-flow.spec.ts` (live, against real ClickHouse), `tests/integration/test_multi_column_reporting.py::test_legacy_no_selector_route_on_a_multi_column_run_returns_empty_not_500` | Done — [pack](verification/M21-verification-pack.md) |
| One-command startup (`ui` compose service, source env wiring) | M22 | `ui/Dockerfile`, `ui/nginx.conf`, `compose.yaml` | Manual: `docker compose up -d` from a clean clone → full flow | Planned |
