# ADR-001: Unicode Strategy

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §11 requires an explicit Unicode policy: support for NFC/NFD/NFKC/NFKD,
a conservative default, documented rules for when each form is used, and a hard
requirement that the original Unicode representation is never discarded. §17
additionally requires confusable/look-alike detection without automatic character
substitution.

Two implementation options exist for the underlying engine:

1. **PyICU** — mature Python bindings to ICU4C, requires a system ICU install or a
   prebuilt wheel; covers normalization, case mapping, collation, transliteration,
   script property lookup, and `SpoofChecker` (UTS #39 confusable detection).
2. **`icu4py`** — a newer binding (first released February 2026) that ships
   precompiled wheels with ICU statically bundled, solving PyICU's classic
   system-ICU version-skew problem. As of evaluation it exposes only boundary
   analysis (word/sentence segmentation) and MessageFormat — no normalization,
   collation, transliteration, or SpoofChecker.
3. **stdlib `unicodedata` + `regex`** — covers NFC/NFD/NFKC/NFKD and Unicode
   property queries, but has no locale-aware case mapping (fails on Turkish
   dotted/dotless İ/ı), no script detection API, and no confusable detection.

## Decision

Use **PyICU**, pinned against whichever specific ICU release the installed
binding actually links against — queried at runtime via
`icu.ICU_VERSION`/`icu.UNICODE_VERSION` (see `scripts/env_fingerprint.py`)
rather than assumed, since the Windows wheel build and the Linux
system-ICU build are not guaranteed to link the same ICU minor version.
Both are expected to track a recent release (ICU 78.x / Unicode 17 / CLDR
48 as of M0); any mismatch between platforms is exactly what
`env_id`-based reproducibility (ADR-014) is designed to make visible rather
than silently ignored. PyICU ships **no official wheels on PyPI for any
platform** — only an sdist that builds against a system ICU via
`pkg-config`/`icu-config` at install time (confirmed empirically in M0: a
plain `uv sync` on Windows fails with `KeyError: 'ICU_VERSION'` /
`pkg-config` not found). The resolved install strategy per platform:

- **Windows**: pull prebuilt wheels directly from `cgohlke/pyicu-build`'s
  GitHub Releases (no PEP 503 index exists, so `[tool.uv.sources]` pins an
  explicit per-Python-version wheel URL — see `pyproject.toml`). Verified
  working for cp312/cp313 win_amd64 in M0.
- **Linux (CI + containers)**: install `libicu-dev` and `pkg-config` via
  `apt-get` before `uv sync`; the sdist then builds against system ICU.
  Wired into `ci-fast.yml`/`ci-full.yml`'s Linux jobs and the API
  Dockerfile.
- **macOS (if ever needed)**: `brew install icu4c pkg-config` plus
  `PKG_CONFIG_PATH` pointed at Homebrew's keg-only `icu4c`, following the
  same sdist-build path as Linux. Not currently in the CI matrix.

- Default normalization form is **NFC**. NFD/NFKC/NFKD are available per-field
  via `FieldNormalizationConfig`, never applied blanket.
- **NFKC is never applied to identifier-typed fields without explicit
  per-field configuration**, because compatibility normalization can collapse
  meaningful distinctions (e.g. superscripts, certain CJK compatibility
  ideographs, ligatures).
- The `original` value (bytes-preserved, pre-normalization) is always retained
  in `NormalizedValue.original`; NFC output goes to `display`/`comparison`
  views, never overwrites `original`.
- Confusable detection uses ICU `SpoofChecker` (UTS #39 skeleton algorithm) to
  populate `confusable_skeleton`, `confusable_detected`, `confusable_count`,
  `mixed_script_detected`, and `scripts_present` — additive diagnostic fields.
  No automatic character substitution ever occurs (per §17's explicit
  prohibition).
- ICU's exact version, and Unicode/CLDR versions it reports, are captured by
  `scripts/env_fingerprint.py` and folded into every run's `env_id`.

`icu4py` is tracked as a watch item, not adopted: it does not yet cover the
capabilities this project needs (normalization, SpoofChecker). Re-evaluate at
Milestone 8 (§102 performance work) if it has grown normalization/spoof
support and its bundled-ICU wheel model would simplify our build matrix.

## Consequences

- PyICU wheel availability must be maintained per-platform in CI; Windows dev
  machines depend on the `cgohlke/pyicu-build` project's release cadence,
  which is a supply-chain dependency worth monitoring (tracked in
  `docs/dependency-inventory.md`).
- Because PyICU wraps a specific ICU version, upgrading ICU is a deliberate,
  version-locked, `env_id`-changing event — caught automatically by the
  nightly drift job (`.github/workflows/drift.yml`), never silent.
- Unicode-form policy is centralized in one config table
  (`packages/normcore/src/normcore/unicode_policy.py`, built in M2) rather
  than scattered per-normalizer, making an audit of "which fields use NFKC"
  a single query.

## Revisit triggers

- `icu4py` (or another ICU binding) ships normalization + SpoofChecker with
  bundled-ICU wheels covering our platform matrix.
- ICU 79 / CLDR 49 (planned for October 2026, bringing Unicode 18) is
  released — re-run the nightly drift job's findings through a manual review
  before bumping the pin.
- PyICU wheel maintenance for a required platform lapses.

## Addendum (M2): PyICU vs PyArrow DLL load order on Windows

While building `GenericTextNormalizer` (M2), importing `pyarrow` before
`icu` in the same process reproducibly segfaulted on Windows — confirmed
with a minimal repro:

```python
import pyarrow as pa  # loads fine
import icu  # segfault, immediately, on this line
```

versus the reverse order, which works with both libraries fully
functional:

```python
import icu  # loads fine
import pyarrow as pa  # loads fine
```

Root cause: both wheels bundle their own native dependencies (PyICU's
ICU DLLs; PyArrow's bundled Arrow/ICU-adjacent DLLs), and whichever
loads first claims shared symbol names in the process — the loser's
native initializer then crashes the interpreter rather than raising a
catchable Python exception. This is a process-wide, first-import-wins
hazard, not specific to any one module in this codebase.

**Mitigation (defense in depth, since no single choke point covers every
entrypoint):**

1. `packages/normalizers/src/normalizers/__init__.py` imports `icu` as
   its literal first statement — protects any caller that imports the
   `normalizers` package (or a submodule of it) before `pyarrow`.
2. `packages/normalizers/src/normalizers/generic_text.py` explicitly
   orders its own imports so the normcore/normalizers imports (which
   pull in `icu`) precede `import pyarrow as pa`, rather than relying
   solely on (1).
3. Root `conftest.py` imports `icu` first, so `pytest` is safe regardless
   of which test file it happens to collect first across `tests/unit`
   and `tests/integration` (some of which import `pyarrow` directly with
   no normalizers/icu involvement at all, e.g. the sidecar store and
   connector tests).
4. `packages/normapi/src/normapi/main.py` (the actual `uvicorn` server
   entrypoint) imports `icu` first as well, since it is a distinct
   process entrypoint from the test suite.

Any new standalone script or entrypoint that imports both `pyarrow` and
(transitively) `normalizers` must apply the same ordering — `import icu`
before anything else is the simplest correct rule. This bit
`tests/integration/fixtures/run_passthrough_demo.py` in practice: it was
initially assumed safe because it only exercises `PassthroughNormalizer`
and never imports `icu` directly — but (1) above means importing so much
as `normalizers.passthrough` now *always* imports `icu` transitively (via
`normalizers/__init__.py`), regardless of which normalizer the script
actually uses. The script's original import order (`import pyarrow as pa`
before `from normalizers.passthrough import PassthroughNormalizer`)
therefore segfaulted the same way, caught by
`tests/integration/test_byte_identical_replay.py` failing with a
Windows access-violation exit code (`3221225477` / `0xC0000005`) instead
of a clean subprocess return. Fixed by reordering the script's imports
the same way as (2) above. The general lesson: being isolated in its own
`subprocess.run()` process protects a script from the *parent* process's
import history, but not from its own — every entrypoint that imports
`normalizers` at all needs the ordering guard, not just ones that visibly
touch `icu`.

Not yet confirmed whether this is Windows-specific (most likely, given
it is a native-DLL-symbol collision) or also reproducible on Linux/macOS
wheels — the mitigation above is applied unconditionally on every
platform since it is a correct no-op where no conflict exists.
