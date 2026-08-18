"""normalizers — the semantic-domain Normalizer adapters (GenericText,
Unicode, Name, Company, Address, Phone, Email, Date, ...) built on top of
normcore's contracts.

`import icu` is deliberately the first statement in this file, before any
other import anywhere in this package. On Windows, PyICU's and PyArrow's
bundled native DLLs conflict when PyArrow's extension module is loaded
into the process first — `import pyarrow` after `import icu` is safe;
the reverse order segfaults immediately on the `import icu` line
(confirmed empirically in M2: see
docs/adr/ADR-001-unicode-strategy.md's DLL-load-order addendum). Since
every module in this package that touches text eventually imports icu
(directly or via `normalizers.text_ops`), forcing it here guarantees any
caller that imports so much as `normalizers.passthrough` before `pyarrow`
is safe, without every individual submodule having to get its own
internal import order exactly right.
"""

import icu  # noqa: F401 - see module docstring; must stay the first import
