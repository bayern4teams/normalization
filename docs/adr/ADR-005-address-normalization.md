# ADR-005: Address Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §29–§32 identify addresses as "one of the highest-risk
normalization domains," requiring international parsing into components
(house_number, road, unit, level, staircase, po_box, postcode, city, state,
country, suburb, district, building, entrance), separated display vs.
comparison representations, non-destructive expansion handling (store
`expansion_candidates`, not one arbitrary winner), and country-aware postal
code validation rather than one universal regex.

Options evaluated:

1. **libpostal** — MIT-licensed C library, statistical-NLP address parser
   and expander trained on large open geodata, officially bound to Python
   via `pypostal`. Throughput 10–30k addresses/sec/thread. Requires ~1.8GB
   (default model) to ~2.2GB (Senzing-tuned model) resident memory per
   process, and a Windows build via MSys2/MinGW (no native Windows wheel).
2. **`deepparse`** — seq2seq BiLSTM / DistilBERT-based neural parser,
   published research shows it and transformer variants outperforming
   libpostal on some metrics for structured parsing accuracy, but it is a
   trained-model dependency with its own versioning/determinism story and
   materially smaller community/production track record than libpostal.
3. **Google `libaddressinput`** (via the `google-i18n-address` Python
   package) — not a parser; it is per-country address *metadata*: required
   fields, field ordering, administrative-area name tables, and critically
   a `postal_code_regexp` per country. This is validation/formatting
   metadata, not parsing.

libpostal parses; it does not validate. `google-i18n-address` validates and
formats; it does not parse free-text input. These are complementary, not
competing.

## Decision

- **Parser: libpostal**, deployed as a **Docker sidecar** (not in-process),
  for three concrete reasons: (a) it sidesteps the Windows MSys2/MinGW build
  entirely for developer machines, (b) it isolates the 1.8–2.2GB resident
  footprint to one container instead of every worker process, and (c) it
  lets us checksum the model data file tree once at image-build time and
  treat that checksum as a first-class, queryable, `env_id`-participating
  artifact (`GET /version` on the sidecar, wired into
  `scripts/env_fingerprint.py`).
- **Validation/formatting metadata: `google-i18n-address`**, providing
  per-country `postal_code_regexp` and required-field sets — this is what
  makes §32's "country context matters, no universal rule" concrete and
  testable rather than aspirational.
- **`deepparse` is not adopted for the shipped pipeline** — tracked as a
  watch item and used only in offline calibration (see the plan's
  dual-parser confidence-calibration approach): run over the golden corpus
  to calibrate libpostal's derived confidence thresholds via inter-parser
  agreement, never imported at runtime, preserving determinism (§72, §129).
- **Sidecar contract**: batch HTTP endpoints `/parse` and `/expand`,
  request/response schemas versioned alongside the sidecar image, health
  check reporting `model_sha256`, and a circuit breaker in
  `AddressNormalizer` that falls back to `PARSER_FALLBACK`-flagged
  structured-passthrough (original preserved, components empty, status
  `PARTIAL`) if the sidecar is unreachable — never a hard pipeline failure
  (§68).
- **Expansions never collapse to one truth**: libpostal's expansion
  candidates are stored as a set (`expansion_candidates`); `primary_normalized`
  is populated only under a documented safe-expansion policy, never as a
  silent default.

## Consequences

- Address normalization has a network hop (sidecar call) even in-process
  deployments would not need — accepted deliberately, and mitigated by the
  distinct-value-first execution model (ADR-016): only unique address
  strings are ever sent to the sidecar, not every row.
- The sidecar's Dockerfile pins a specific libpostal git ref
  (`LIBPOSTAL_COMMIT` build arg, default `v1.1.4` — the earlier `v1.1` tag
  was tried first during M0 and found incompatible with the pinned
  `pypostal` binding's near-duplicate-hashing API, which requires struct
  members only present from `v1.1.2` onward), making the parser version as
  reproducible as any pinned Python package.
- **Operational risk, found and root-caused empirically during M0**:
  libpostal's own `make all-local` step invokes its bundled
  `libpostal_data` shell script, which downloads three release assets
  (`libpostal_data.tar.gz` ~10MB, `language_classifier.tar.gz` ~50MB,
  `parser.tar.gz` ~752MB — all pinned to the `v1.0.0` data release
  independently of the code tag) from `github.com/openvenues/libpostal/
  releases`. The parser file is fetched as **12 parallel 64MB-range
  requests** (`NUM_WORKERS=12` in `libpostal_data.in`), each with only
  3 retries and no explicit timeout. On a bandwidth-constrained connection
  this is actively harmful: 12 connections competing for the same limited
  bandwidth each proceed so slowly that one or more stall past whatever
  implicit tolerance causes `curl`/the shell pipeline to give up, failing
  the whole build with `Error 123` after using up most of the available
  wall-clock time. Root cause was confirmed directly during M0: a
  single-connection ranged `curl` request against the same host measured
  ~430KB/s sustained — at that rate the full ~813MB (three files
  combined) takes over 30 minutes on ONE connection, and considerably
  longer per-connection when split 12 ways.

  **Adopted fix**: pre-fetch all three tarballs on the **host**, outside
  Docker, using a single-connection, resumable download
  (`curl -C - --retry 10`) — see `services/libpostal/_data_cache/
  download_data.sh`. The Dockerfile then configures libpostal with
  `--disable-data-download` (a documented upstream flag,
  `AC_ARG_ENABLE([data-download], ...)` in `configure.ac`) and extracts
  the pre-fetched tarballs itself. This is not a workaround pending a
  retry — it is the adopted, permanent build mechanism for this project:
  it removes libpostal's in-container network dependency entirely, makes
  the model data explicitly cacheable on the host across rebuilds, and is
  strictly more reliable than depending on 12-way parallel download
  contention succeeding inside the container network on every environment
  this image is ever built in (including, notably, resource-constrained
  CI runners).

- **Two further bugs found and fixed while wiring up the pre-fetch path**,
  both confirmed by actually running the built image rather than assuming
  correctness from the Dockerfile alone:

  1. **Data path mismatch between compile-time and run-time.**
     `./configure --datadir=X` compiles a default read path of
     `X/libpostal` into the C library (per `src/Makefile.am`'s
     `-DLIBPOSTAL_DATA_DIR='"$(datadir)/libpostal"'`). We initially
     extracted the pre-fetched tarballs to match that path
     (`$LIBPOSTAL_DATA_DIR/libpostal/...`). At container runtime this
     failed with `SystemError: initialization of _expand raised
     unreported exception`, traced (via a direct `python3 -c "from
     postal import _expand"` inside the container) to `Error loading
     transliteration module, dir=/data/libpostal/transliteration/
     transliteration.dat` — i.e. the running process was looking one
     level higher than where we put the data. Root cause: **`pypostal`'s
     Python wrapper reads the `LIBPOSTAL_DATA_DIR` *environment variable*
     at import time and calls `libpostal_setup_datadir()` with that value
     directly**, which overrides the compiled-in default. Since the
     final image sets `ENV LIBPOSTAL_DATA_DIR=${LIBPOSTAL_DATA_DIR}` with
     no `/libpostal` suffix, that env-var path — not the compiled
     default — is what the server process actually reads. Fix: extract
     data directly into `${LIBPOSTAL_DATA_DIR}` (no nested subdirectory)
     to match.
  2. **Stale Docker named volume shadowed the fix.** `compose.yaml` mounts
     a named volume (`libpostal_data`) at the data path so the ~1.8GB of
     model data isn't duplicated into every container layer on restart.
     Docker only auto-populates a named volume from the image's content
     the *first* time it's created empty; a `docker compose down`
     (without `-v`) leaves the volume — and its now-stale content from
     the first, wrong-path build — in place, silently shadowing every
     subsequent image rebuild's corrected data. The container kept
     failing with the identical error after the path fix above until this
     was noticed and the volume was explicitly removed
     (`docker compose down -v`) before the next `up`. This is now a
     documented gotcha for anyone rebuilding this image after a
     data-layout change: **a plain rebuild is not sufficient; the named
     volume must be removed too.**

  Both were only caught because the container was actually started and
  its logs/behavior inspected end-to-end (`docker logs`, a direct
  in-container Python import test, and finally the real `/parse` and
  `/expand` spike calls against a live server) — a Dockerfile that merely
  "builds successfully" said nothing about whether the running service
  actually worked, which is precisely why Layer 2 (liveness) of this
  project's gate model is a separate, mandatory check from Layer 1
  (build/lint/test) — see the implementation plan's Part C.1.
- A pluggable transport is preserved in the `Normalizer` interface
  (`AddressNormalizer` talks to an `AddressBackend` protocol) so an
  in-process `pypostal` backend remains possible for Linux production
  deployments without changing calling code, per the plan's "pluggable:
  sidecar + in-process" option.

## Revisit triggers

- `deepparse` or a successor demonstrates materially better accuracy on our
  own golden corpus (not just published benchmarks) during a scheduled
  M4+ re-evaluation.
- libpostal publishes a v2 data model with a substantially different memory
  profile — re-run the M4 gate benchmarks before adopting.
- Google deprecates or materially changes `libaddressinput` metadata
  licensing/availability.
