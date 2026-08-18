"""Repository-root pytest conftest.

`import icu` here, before pytest imports any test module, guarantees
PyICU's native DLLs load before PyArrow's regardless of which test file
pytest happens to collect first. On Windows the two libraries' bundled
native DLLs conflict when PyArrow claims the process first (`import
pyarrow` then `import icu` segfaults immediately; the reverse order is
safe) — see docs/adr/ADR-001-unicode-strategy.md's DLL-load-order
addendum. Individual packages (`normalizers/__init__.py`) apply the same
fix for non-pytest entrypoints; this conftest is the pytest-specific
belt-and-suspenders since collection order across `tests/unit` and
`tests/integration` is not something we control or want to depend on.
"""

import icu  # noqa: F401
