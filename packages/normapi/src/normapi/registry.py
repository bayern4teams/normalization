"""Builds the real 20-normalizer registry — extracted from `app.py`'s
`create_app()` (Phase 3 of the throughput/memory program, 2026-08-29) so
it can be called from a place other than the FastAPI app factory: a
process-pool worker (`normexec.parallel.DistinctValueWorkerPool`) needs a
picklable, MODULE-LEVEL factory function to rebuild a real `Dispatcher`
inside each fresh worker process, and a closure captured inside
`create_app()`'s local scope cannot be pickled for the `spawn` start
method the pool always uses.

`packages/normcli/src/normcli/registry.py` already duplicates this same
list for a different reason (a local CLI process should not need
FastAPI/uvicorn/psycopg just to build a normalizer registry) — that
file's own docstring anticipated exactly this: "a future Phase 3
process-pool worker that needs the same construction from *inside*
normapi's own process can still extract a shared helper there without
normcli taking on normapi's dependency weight." This is that shared
helper, living where the process-pool workers that need it actually run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.boolean import BooleanNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.generic_text import GenericTextNormalizer
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.name import NameNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.postcode import PostcodeNormalizer
from normalizers.script import ScriptNormalizer
from normalizers.unit import UnitNormalizer
from normalizers.url import URLNormalizer

from normcore import Dispatcher, NormalizerRegistry
from normdict import DictionaryLoader

if TYPE_CHECKING:
    from pathlib import Path


def build_normalizer_registry(
    dictionaries_dir: Path, libpostal_client: LibpostalClient
) -> NormalizerRegistry:
    """Same registration order as `create_app()` used to build inline —
    PassthroughNormalizer first (covers every type as a placeholder),
    then real adapters win for the specific types they support, since
    `NormalizerRegistry.register()` simply overwrites the dict entry per
    semantic type."""
    loader = DictionaryLoader(dictionaries_dir)
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(GenericTextNormalizer(loader))
    registry.register(NameNormalizer(loader))
    registry.register(CompanyNormalizer(loader))
    registry.register(PhoneNormalizer())
    registry.register(EmailNormalizer())
    registry.register(AddressNormalizer(libpostal_client))
    registry.register(PostcodeNormalizer())
    registry.register(DateNormalizer())
    registry.register(CountryNormalizer())
    registry.register(LanguageNormalizer())
    registry.register(ScriptNormalizer())
    registry.register(IdentifierNormalizer())
    registry.register(UuidNormalizer())
    registry.register(NumericNormalizer())
    registry.register(CurrencyNormalizer())
    registry.register(UnitNormalizer())
    registry.register(BooleanNormalizer())
    registry.register(URLNormalizer())
    return registry


def build_worker_dispatcher(dictionaries_dir: Path, libpostal_url: str, env_id: str) -> Dispatcher:
    """The `normexec.parallel.DispatcherFactory` this process's Phase 3
    pool workers actually run — module-level and picklable by reference
    (`functools.partial(build_worker_dispatcher, dictionaries_dir,
    libpostal_url, env_id)`, built once in `create_app()`), unlike a
    closure over `create_app()`'s local variables. `env_id` is passed in
    already-computed rather than recomputed per worker, so every worker's
    `Dispatcher` stamps the exact same env_id the main process's own
    `Dispatcher` does (ADR-014) — never a second, potentially different,
    per-worker env fingerprint.
    """
    registry = build_normalizer_registry(dictionaries_dir, LibpostalClient(libpostal_url))
    return Dispatcher(registry, env_id=env_id)
