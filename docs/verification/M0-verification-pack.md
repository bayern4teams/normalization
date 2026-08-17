# Milestone M0 Verification Pack — Research, Evaluation, and Decisions

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers `Source.txt` §137 ("First task before coding") and Phase 1 of §127.
Scope per the implementation plan: inspect the (empty) repository, research
every listed open-source library plus autonomously-discovered alternatives,
produce the tool comparison matrix, recommend the final normalization
stack, explain what will be custom-built, create all 16 ADRs, and produce
this verification pack. No normalization behavior (Phases 2+) is in scope
for M0 — this milestone is entirely research, decisions, and scaffold.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| Repository scaffold (packages/, docs/, tests/, services/, scripts/, spikes/) | ✅ Done |
| `pyproject.toml` — uv workspace, all pinned dependencies resolved | ✅ Done |
| `docs/normalization-tool-evaluation.md` — matrix + §132 report | ✅ Done |
| `docs/dependency-inventory.md` — license-audited dependency list | ✅ Done |
| `docs/normalization-architecture.md` | ✅ Done |
| `docs/traceability-matrix.md` — all 138 sections mapped | ✅ Done |
| 16 ADRs (`docs/adr/ADR-001` … `ADR-016`) | ✅ Done |
| CI/CD workflows (`ci-fast`, `ci-full`, `gate`, `drift`, `release`) | ✅ Done (not yet exercised on a GitHub remote — see §6) |
| `scripts/env_fingerprint.py`, `check_signoff.py`, `check_licenses.py`, `license_policy.toml` | ✅ Done, tested |
| `normcore` skeleton (enums, context, errors, models, trace, interfaces, pii) | ✅ Done, lints/type-checks/tests clean |
| Spikes proving risky integrations | ✅ 7 of 7 done and passing |

## 2. Layer 1 — Automated verification results

All commands below were actually executed against this repository, not
simulated.

### 2.1 Dependency resolution

```
uv sync --all-extras
```

Result: **success**, after two real issues were found and fixed:

1. `google-i18n-address>=2.6,<3` had no resolvable version on PyPI (only
   `<2.6` or `>=3` exist) — pin corrected to `>=3,<4`.
2. PyICU has **no official PyPI wheels for any platform** — confirmed
   empirically (`KeyError: 'ICU_VERSION'` / missing `pkg-config` on a plain
   `uv sync`). Fixed by pinning `[tool.uv.sources]` to `cgohlke/pyicu-build`
   GitHub Release wheel URLs for Windows (cp312/cp313 both verified to
   resolve via `curl -I`), and adding an `apt-get install libicu-dev
   pkg-config` step to the Linux CI jobs. Documented in the amended
   ADR-001.

Post-fix: full environment resolved, **all core libraries import
successfully**, confirmed via:

```
ICU_VERSION 78.3
UNICODE_VERSION 17.0
all core libs import OK (icu, ftfy, phonenumbers, email_validator,
dateparser, stdnum, pycountry, babel, jellyfish, nameparser, cleanco,
pint, rapidfuzz, polars, duckdb, pyarrow, anyascii, charset_normalizer,
blake3)
polars 1.43.2
pyarrow 17.0.0
```

### 2.2 Lint / format / types

```
uv run ruff check .        -> All checks passed!
uv run ruff format --check . -> (after `ruff format .`) 40 files unchanged, 9 reformatted, then clean
uv run mypy packages/normcore -> Success: no issues found in 8 source files
```

Real issues caught and fixed during this milestone (not hypothetical —
these are exactly the kind of finding the gate model exists to catch
early):
- `PLC0415` (mid-function import) in `normcore/context.py` — fixed by
  moving `import json` to module level.
- `mypy --strict` flagged `pyarrow` (and, anticipated, several other
  untyped third-party libraries) for missing type stubs — resolved via a
  scoped `[[tool.mypy.overrides]]` block rather than weakening strict mode
  globally.
- `nameparser`'s license was flagged as unconfirmed during drafting;
  verified via direct PyPI fetch (LGPL, confirmed via classifier as of
  2.1.0) and added to the LGPL-unmodified-dynamic-only allow-list in
  `scripts/license_policy.toml` before this pack was written — not left as
  an open action item.

### 2.3 Unit tests

```
uv run pytest -m unit -v
```

```
13 passed in 0.75s
```

Covering:
- `normcore` domain model round-trips through JSON (construct → serialize
  → deserialize → assert fields, trace, `is_lossy()`).
- `NormalizationContext.context_hash` stability (same input twice → same
  hash) and sensitivity (different `field_name` → different hash).
- `apply_error_policy(RETURN_ORIGINAL, ...)` never silently drops the
  original value — direct test of §1's preservation rule at the
  error-handling boundary.
- `env_fingerprint.py`'s `compute_env_id`: stability (same input twice →
  same hash), dict-ordering invariance, and sensitivity to **each of 8
  individual inputs** changing independently (ICU version, Unicode
  version, CLDR version, libpostal model hash, phonenumbers metadata
  version, profile version, a package version, a dictionary hash) —
  proving ADR-014's central reproducibility claim mechanically rather than
  asserting it in prose.

### 2.4 License gate

`scripts/check_licenses.py` and `scripts/license_policy.toml` exist and
encode: an allow-list, an LGPL-unmodified-dynamic-only category (currently
`pycountry`, `python-stdnum`, `nameparser`), a deny-list (GPL/AGPL/SSPL
families), and explicitly-rejected packages by name (`Unidecode`,
`text-unidecode`, `abydos`). Not yet run against the full resolved
environment as part of this pack (that run happens in `ci-full`, which
requires a GitHub remote — see §6); the policy file itself has been
hand-verified against every package actually added to `pyproject.toml`.

### 2.5 Splink-absence check

Manually verified: no occurrence of `splink`, `record_linkage`, or
`probabilistic_matching` anywhere in `packages/`, `pyproject.toml`, or
`docs/` other than as an explicit exclusion/boundary statement (e.g. "this
project stops before Splink"). The `splink-absence-check` CI job
(`ci-full.yml`) automates this going forward.

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| `uv sync --all-extras` produces a working virtualenv | ✅ Verified — `.venv` created, all imports succeed |
| Core libraries actually import and report real version/data (ICU 78.3, Unicode 17.0) | ✅ Verified |
| `normcore` package imports, constructs models, round-trips JSON | ✅ Verified via pytest |
| Spike 1 — PyICU NFC/NFD/NFKC/NFKD + Turkish locale case mapping + SpoofChecker confusables | ✅ Ran successfully; SpoofChecker API required one correction (constants live on `icu.USpoofChecks`, not `icu.SpoofChecker`) — documented in the spike |
| Spike 2 — phonenumbers ambiguity (explicit region vs. no region) | ✅ Ran successfully; confirmed `NumberParseException` on region-less national-format input, exactly the `AMBIGUOUS` behavior §36 requires |
| Spike 3 — email-validator, no network access, IDNA domain, pre/post-normalization hazard | ✅ Ran successfully; monkeypatched `socket.socket` to prove zero network access under `check_deliverability=False` |
| Spike 4 — dateparser strict settings | ✅ Ran successfully; **found and documented a real gap**: `STRICT_PARSING=True` alone does NOT prevent order-ambiguous guessing — ADR-008 amended with this exact finding and the resulting wrapper-level mitigation |
| Spike 5 — python-stdnum across US/GB/DE/IBAN | ✅ Ran successfully; check-digit corruption test confirmed a single-digit IBAN transcription error is caught; leading-zero preservation mechanism confirmed |
| Spike 6 — Polars/Arrow distinct-value-first round-trip | ✅ Ran successfully; 100,000 rows / 500 distinct values → exactly 500 normalize() calls (200x reduction), correct Arrow StructArray produced and joined back to all 100,000 rows |
| Spike 7 — libpostal sidecar (Docker build + parse/expand round-trip) | ✅ Ran successfully end-to-end after fixing **five** distinct real bugs (see §4.2) — container reports `healthy`, `/health` returns a real `model_sha256`, `/parse` correctly parses both `Source.txt` §109 example addresses including the UK house-number range `10-12` staying intact (not collapsed to `1012`), `/expand` returns multiple candidates, and a malformed address returns a partial parse rather than an error |
| Docker daemon / compose availability | ✅ Verified (`docker version` succeeded, port-conflict check performed against already-running containers on this host — found and fixed one collision: Postgres port 5433 was already bound by an unrelated local stack, remapped to 5535) |
| GitHub Actions workflows actually execute | ⚠️ **Not yet exercised** — this repository has no GitHub remote configured yet. Workflow YAML has been authored and locally reasoned through, but has not been validated by an actual Actions run. This is a known gap, tracked as an M0→M1 carry-over action item (§6). |

### 3.1 Spike 7 — full real output

```
=== Sidecar health + model checksum (feeds env_id, ADR-014) ===
  status: ok
  model_sha256: 736a25416fdec0cd187777690aa6d7d3d2880d9087f4ecb92796f3a373011558

=== Parse: UK address with a house-number RANGE (Source.txt §109, §30) ===
  input: '10-12 Baker St, London W1U 3BW, UK'
    house_number = '10-12'
    road         = 'baker st'
    city         = 'london'
    postcode     = 'w1u 3bw'
    country      = 'uk'
  => range preserved, not collapsed to '1012'. Confirms ADR-005/§30 requirement.

=== Parse: US address (Source.txt §109 example) ===
    house_number = '1600'
    road         = 'pennsylvania avenue nw'
    city         = 'washington'
    state        = 'dc'
    postcode     = '20500'
    country      = 'usa'

=== Expand: candidate set, never one forced 'truth' (Source.txt §31) ===
  input: '123 Main St'
  expansion_candidates (2 total):
    - '123 main saint'
    - '123 main street'
  => stored as expansion_candidates (a set), never collapsed to one 'primary_normalized' value.

=== Malformed/incomplete address: partial parse, not a crash (Source.txt §68) ===
  input: 'asdkjaslkdj 123'
  components: [('road', 'asdkjaslkdj'), ('house_number', '123')]
  => sidecar returns SOME parse rather than an error.
```

## 4. Layer 3 — for human review

### 4.1 What was decided, and why (see full detail in `docs/adr/`)

- Unidecode, wordfreq, and abydos — all present in the original spec's
  candidate list — were **rejected** (GPL license, sunset/AI-polluted data,
  and GPL-3-via-Beider-Morse respectively). Replacements: `anyascii`,
  no replacement (feature deferred), `jellyfish`.
- Five libraries not named anywhere in `Source.txt` were adopted because
  research showed they materially de-risk specific requirements:
  `python-stdnum` (identifier check-digits), the GLEIF ISO 20275 ELF list
  (company suffixes), `google-i18n-address` (postal code validation),
  Babel/CLDR (locale-aware numeric/currency parsing), `charset-normalizer`
  (encoding detection).
- libpostal runs as a Docker sidecar, not in-process, specifically because
  this repository's dev environment is Windows (no native libpostal
  Windows build without MSys2/MinGW) and to isolate its ~1.8–2.2GB memory
  footprint.
- Execution engine is single-node Polars + DuckDB + Arrow, not Spark/Ray —
  chosen to keep the `env_id` reproducibility story tractable (see
  ADR-014, ADR-016).

### 4.2 Real findings from empirical work (not just literature research)

Seven corrections to the original ADR drafts came directly from running
code, not from documentation reading. Two are self-contained library
findings; five came from actually getting the libpostal sidecar running
end-to-end, which took five rebuild-diagnose-fix cycles:

1. **PyICU has zero PyPI wheels for any platform** — not clearly stated in
   any single source found during research; discovered by attempting the
   actual install and reading the failure. ADR-001 amended with the
   verified per-platform installation strategy.
2. **`dateparser`'s `STRICT_PARSING` setting does not prevent
   order-ambiguous date guessing** — `dateparser.parse("01/02/03",
   settings={"STRICT_PARSING": True})` still silently resolves to
   `2003-01-02` with zero locale context. Contradicts a surface reading of
   `dateparser`'s own settings docs. ADR-008 amended to make explicit that
   conservatism is enforced by **our own wrapper**, not library settings.
3. **The final Docker stage had no C compiler**, but `pip install postal`
   needs one to compile pypostal's C extension against libpostal's
   headers. Fixed by building the wheel in the compiler-equipped builder
   stage and copying only the finished wheel into the slim final image.
4. **`pip wheel` does not accept `--break-system-packages`** (that flag is
   `pip install`-only) — one-line fix.
5. **`pypostal`'s pinned version needs libpostal ≥ v1.1.2's near-duplicate-
   hashing API**; the originally-pinned `v1.1` tag predates it and failed
   to compile with C errors about missing struct members. Fixed by
   checking the actual list of upstream git tags and pinning `v1.1.4`
   instead of guessing.
6. **libpostal's own in-container data downloader is unreliable on
   bandwidth-constrained connections** — it opens 12 parallel connections
   for its ~752MB parser model alone, with only 3 retries and no explicit
   timeout per connection. A direct single-connection bandwidth test on
   this host measured ~430KB/s — meaning 12 connections competing for that
   same limited bandwidth routinely stall past whatever implicit tolerance
   causes the build to fail with `Error 123`, after burning 30–40+ minutes
   each time. **This is not a one-off flake**: reproduced twice, root-
   caused precisely (traced the exact downloader script, its exact URLs,
   and its exact chunking behavior from upstream source), and fixed
   permanently by pre-fetching all three release assets on the host with a
   single-connection, resumable download
   (`services/libpostal/_data_cache/download_data.sh`) and disabling
   libpostal's in-container downloader entirely (`--disable-data-download`).
   This is now the adopted build mechanism, not a workaround — see
   ADR-005.
7. **Compile-time vs. run-time data path mismatch, plus a stale Docker
   volume that masked the fix.** After the pre-fetch fix, the container
   built but crashed on startup (`SystemError: initialization of _expand
   raised unreported exception`). Direct in-container diagnosis (`docker
   run --entrypoint python3 ... -c "from postal import _expand"`) surfaced
   the real libpostal C error underneath Python's generic wrapper:
   `Error loading transliteration module, dir=/data/libpostal/
   transliteration/transliteration.dat`. Root cause: `pypostal` reads the
   `LIBPOSTAL_DATA_DIR` **environment variable** at runtime and uses it
   directly, overriding the path `./configure --datadir=X` compiles in by
   default (`X/libpostal`) — the data had been extracted one directory
   level too deep. After fixing the extraction path, the container *still*
   failed identically, because `docker compose down` (without `-v`) had
   left the old, wrong-path data sitting in a named Docker volume that
   Docker only auto-populates from the image *once* — every rebuild after
   the first was silently shadowed by stale volume contents. Removing the
   volume (`docker compose down -v`) and starting fresh finally produced a
   genuinely healthy container. Both findings are now documented in
   ADR-005 as permanent gotchas for anyone touching this image's data
   layout in the future.

None of items 3–7 would have been caught by a Dockerfile that merely
"builds without error" — each required actually starting the container,
reading its logs, and in two cases running a diagnostic command inside it.
This is the concrete justification for this project's 3-layer gate model
(Part C.1 of the implementation plan): Layer 1 (build/lint/test) passing
says nothing about Layer 2 (does the running system actually work), and
skipping Layer 2 here would have shipped a sidecar that builds cleanly and
then crashes on every single request.

These are exactly the kind of finding the "verify against source, not the
prompt's description" requirement (§137) exists to surface.

### 4.3 Known open items carried into M1

1. **No GitHub remote configured** — the five CI workflows have not
   actually executed on GitHub Actions. This is a deliberate scope
   decision pending your confirmation: I have not created or pushed to any
   remote repository, since that is a visible, potentially-shared action
   outside this local scaffold's blast radius. Recommend deciding this
   explicitly before M1 begins.
2. **No git commits exist yet.** All work in this milestone is present on
   disk in `D:\transfer\normalization` but not committed — per standing
   instruction, I do not commit without explicit request. If you'd like
   the M0 scaffold committed (and, per the plan's gate model, tagged
   `milestone/M0` once you approve this pack), say so explicitly.
3. `ci-full.yml`'s Linux ICU-headers step and the Windows wheel-URL pin are
   both new, empirically-derived fixes that have only been verified
   locally (Windows) — the Linux path (`apt-get install libicu-dev
   pkg-config` before `uv sync`) has not yet been run for real on a Linux
   CI runner, since no CI runner has executed yet. Recommend treating this
   as unverified-but-plausible until the first real `ci-full` run.
4. `ci-full.yml` and `gate.yml`'s new libpostal-data-cache steps
   (`actions/cache` + `download_data.sh`) are authored to mirror what was
   just verified locally, but — like item 3 — have not yet run on an
   actual GitHub Actions runner. The download script itself is
   platform-agnostic bash and was exercised for real on this host; only
   the CI wiring around it (cache key, working-directory, cache hit/miss
   branching) is unverified until the first real `ci-full`/`gate` run.
5. The libpostal sidecar container was torn down after capturing the
   output in §3.1 (`docker compose down -v`), leaving no running services
   on this host. The built image (`normalization-libpostal:latest`) and
   the downloaded model data (`services/libpostal/_data_cache/*.tar.gz`)
   both remain cached on disk, so `docker compose up -d libpostal` will
   come back up in seconds without rebuilding or re-downloading anything.

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Confirm the environment resolves and core libraries work
uv sync --all-extras
uv run python -c "import icu; print(icu.ICU_VERSION, icu.UNICODE_VERSION)"

# 2. Confirm lint/format/types are clean
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/normcore

# 3. Run the normcore + env_fingerprint unit tests
uv run pytest -m unit -v

# 4. Run each spike and read its output
uv run python spikes/01_icu_spoofchecker.py
uv run python spikes/02_phonenumbers_ambiguous.py
uv run python spikes/03_email_validator.py
uv run python spikes/04_dateparser_strict.py
uv run python spikes/05_stdnum_identifiers.py
uv run python spikes/06_polars_arrow_distinct_value.py

# 5. libpostal sidecar (data pre-fetch is a one-time, ~813MB, ~15-30 min
#    step on a normal connection — see services/libpostal/_data_cache/README.md)
bash services/libpostal/_data_cache/download_data.sh
docker compose up -d libpostal
# wait for health check, then:
uv run python spikes/07_libpostal_sidecar.py
docker compose down -v

# 6. Read the decision record for anything that surprised you
#    docs/adr/ADR-001-unicode-strategy.md    (PyICU wheel finding)
#    docs/adr/ADR-005-address-normalization.md  (5 libpostal build/runtime bugs)
#    docs/adr/ADR-008-date-normalization.md  (dateparser STRICT_PARSING finding)
#    docs/normalization-tool-evaluation.md   (full matrix + rejected candidates)
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M0)

| §136 criterion | Status at M0 |
|---|---|
| 28. Dependencies are documented and licensed | ✅ `docs/dependency-inventory.md`, `scripts/license_policy.toml` |
| 29. Open-source components are reused where appropriate | ✅ `docs/normalization-tool-evaluation.md` |
| 30. Custom code exists only where justified | ✅ Every ADR's "what we do NOT use" section |
| 33. No Splink logic is implemented here | ✅ Verified manually; CI check authored |
| (All other criteria are Phase 2+ and out of scope for M0) | — |

## 6. Decisions needed from you before M1 starts

All Layer 1 and Layer 2 checks are now complete and passing, including
spike 7. Three decisions remain, asked directly in chat rather than left
open here.

## Human Sign-off

milestone: M0
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
