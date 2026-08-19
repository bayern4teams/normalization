"""FastAPI application factory — Source.txt §98.

Builds the app, registers the §98 router, and wires up the process-wide
singletons (InMemoryStore, Dispatcher, DictionaryLoader) via `app.state`,
read by normapi.dependencies at request time.
"""

from __future__ import annotations

import os
from pathlib import Path

import blake3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
from normexec.cache import NormalizationCache

from normapi.routes import router
from normapi.store import InMemoryStore
from normcore import Dispatcher, NormalizerRegistry
from normdict import CustomDictionaryStore, DictionaryLoader

# Real env_id computation (scripts/env_fingerprint.py) hashes actual
# resolved package/ICU/dictionary versions and is intentionally a
# standalone script, not something a running service imports (that would
# make CI/ops tooling a runtime dependency of the API). Promoting that
# logic into a shared normcore/normexec module so the live API can stamp
# a REAL env_id (not this scaffold placeholder) is a known follow-up —
# tracked for the milestone that wires real normalizers into normapi.
_SCAFFOLD_ENV_ID = blake3.blake3(b"normapi-m1-scaffold-env-id").hexdigest()

# NORM_DICTIONARIES_DIR (set in compose.yaml to /app/data/dictionaries,
# matching the Dockerfile's COPY destination) overrides this for container
# deployment. The relative "data/dictionaries" default only resolves
# correctly for local `uv run` invocations from the repo root — it would
# NOT resolve correctly via a __file__-relative path once normapi is
# installed into site-packages, which is why this is env-var-driven
# instead.
_DEFAULT_DICTIONARIES_DIR = Path(os.environ.get("NORM_DICTIONARIES_DIR", "data/dictionaries"))

# Set in compose.yaml to http://libpostal:8081 (the sidecar's in-network
# address). Defaults to localhost for `uv run uvicorn` outside Docker,
# matching the port compose.yaml also exposes on the host.
_DEFAULT_LIBPOSTAL_URL = os.environ.get("NORM_LIBPOSTAL_URL", "http://localhost:8081")

# Custom (user) dictionaries live in a completely separate root from the
# built-in dictionaries dir above — CustomDictionaryStore refuses to ever
# write into it (§59), so the two are kept physically apart, not just
# logically.
_DEFAULT_CUSTOM_DICTIONARIES_DIR = Path(
    os.environ.get("NORM_CUSTOM_DICTIONARIES_DIR", "data/custom-dictionaries")
)

# The M7 UI (ui/) is a separate origin from the API — without CORS
# headers the browser blocks every fetch outright (caught by actually
# loading the UI in a real browser against a real running server, not by
# reasoning about the two processes in isolation). Comma-separated so a
# deployment can widen this without a code change; both Vite's dev-server
# origin (5173) and its `vite preview`/production-build origin (4173,
# what the Playwright e2e suite builds and serves) are included by
# default since both are this milestone's own consumers.
_DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
_EXTRA_CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("NORM_CORS_ORIGINS", "").split(",")
    if origin.strip()
]

# §103's normalization cache — defaults to an in-process-only DuckDB
# (":memory:") so a fresh `InMemoryStore` and a fresh cache always start
# together (consistent with the store itself not surviving a restart);
# set NORM_CACHE_PATH to a real file for cross-restart/cross-run reuse in
# a real deployment. Raw values never appear in cache keys (normexec.
# cache.make_cache_key hashes them) — see §103's own "never leak
# sensitive raw values through cache keys" requirement.
_DEFAULT_CACHE_PATH = os.environ.get("NORM_CACHE_PATH", ":memory:")


def create_app(
    *,
    dictionaries_dir: Path | None = None,
    custom_dictionaries_dir: Path | None = None,
    cache_path: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Normalization Engine API",
        description="Source.txt §98 API surface.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*_DEFAULT_CORS_ORIGINS, *_EXTRA_CORS_ORIGINS],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    loader = DictionaryLoader(dictionaries_dir or _DEFAULT_DICTIONARIES_DIR)
    custom_store = CustomDictionaryStore(
        custom_dictionaries_dir or _DEFAULT_CUSTOM_DICTIONARIES_DIR, loader
    )

    # PassthroughNormalizer registers first (covers every type as a
    # placeholder), then real adapters register after it and win for the
    # specific types they support — NormalizerRegistry.register() simply
    # overwrites the dict entry per semantic type, so registration order
    # is the mechanism, not a special-cased "prefer real over
    # placeholder" rule.
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(GenericTextNormalizer(loader))
    registry.register(NameNormalizer(loader))
    registry.register(CompanyNormalizer(loader))
    registry.register(PhoneNormalizer())
    registry.register(EmailNormalizer())
    registry.register(AddressNormalizer(LibpostalClient(_DEFAULT_LIBPOSTAL_URL)))
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

    cache = NormalizationCache(cache_path or _DEFAULT_CACHE_PATH)

    app.state.store = InMemoryStore(cache)
    app.state.dispatcher = Dispatcher(registry, env_id=_SCAFFOLD_ENV_ID)
    app.state.dictionary_loader = loader
    app.state.custom_dictionary_store = custom_store
    app.state.cache = cache

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
