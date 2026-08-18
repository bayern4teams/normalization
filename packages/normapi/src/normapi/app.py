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
from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.generic_text import GenericTextNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.name import NameNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.script import ScriptNormalizer

from normapi.routes import router
from normapi.store import InMemoryStore
from normcore import Dispatcher, NormalizerRegistry
from normdict import DictionaryLoader

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


def create_app(*, dictionaries_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Normalization Engine API",
        description="Source.txt §98 API surface.",
        version="0.1.0",
    )

    loader = DictionaryLoader(dictionaries_dir or _DEFAULT_DICTIONARIES_DIR)

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
    registry.register(DateNormalizer())
    registry.register(CountryNormalizer())
    registry.register(LanguageNormalizer())
    registry.register(ScriptNormalizer())

    app.state.store = InMemoryStore()
    app.state.dispatcher = Dispatcher(registry, env_id=_SCAFFOLD_ENV_ID)
    app.state.dictionary_loader = loader

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
