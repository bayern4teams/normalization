"""FastAPI application factory — Source.txt §98.

Builds the app, registers the §98 router, and wires up the process-wide
singletons (InMemoryStore, Dispatcher, DictionaryLoader) via `app.state`,
read by normapi.dependencies at request time.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import blake3
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.boolean import BooleanNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.generic_text import GenericTextNormalizer, load_missing_value_sentinels
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.money import MoneyNormalizer
from normalizers.name import NameNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.postcode import PostcodeNormalizer
from normalizers.script import ScriptNormalizer
from normalizers.unit import UnitNormalizer
from normalizers.url import URLNormalizer
from normexec.cache import NormalizationCache
from normexec.env_fingerprint import current_env_id
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, PlainTextResponse

from normapi.address_policy import AddressPolicyError, check_caller
from normapi.adjudication import migrate_sources
from normapi.pg_persistence import PgPersistence
from normapi.routes import router
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normapi.store import DEFAULT_MAX_RUN_ROWS, InMemoryStore
from normcore import Dispatcher, NormalizerRegistry
from normdict import CustomDictionaryStore, DictionaryLoader

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# env_id used to be a hardcoded placeholder — the SAME hash in every
# environment, for every dictionary and every dependency version. That
# made it useless as a cache key: ADR-014's whole promise is that a
# result computed under different inputs cannot be replayed as current,
# and a constant defeats it silently. The computation now lives in
# normexec.env_fingerprint (shared with scripts/env_fingerprint.py, so
# there is one implementation rather than two that drift).
#
# Computed ONCE per process, at startup, per ADR-014 — never per value.
# It walks the dictionaries directory and reads installed package
# metadata, so it is not free, but it happens exactly once.

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

# ADR-013's metadata store. Unset (the default for `uv run` outside
# Docker/tests) means InMemoryStore keeps its original pure-in-memory
# behavior — no Postgres round-trip forced on every contributor's laptop.
# compose.yaml sets this for the real deployment.
_DEFAULT_PG_DSN = os.environ.get("NORM_PG_DSN")

# A real run OOM-killed the api container in live testing — see
# store.py's DEFAULT_MAX_RUN_ROWS for the measured per-row memory cost
# this default (and compose.yaml's api.mem_limit: 4g) are actually based
# on. Rejecting an oversized run outright (HTTP 413, routes.py) is a
# predictable failure an operator can raise deliberately once they've
# measured their own container's headroom, in place of an unpredictable
# crash nobody chose.
_DEFAULT_MAX_RUN_ROWS = int(os.environ.get("NORM_MAX_RUN_ROWS", str(DEFAULT_MAX_RUN_ROWS)))


def build_normalizer_registry(
    loader: DictionaryLoader | None = None, *, libpostal_url: str | None = None
) -> NormalizerRegistry:
    """Every real normalizer, registered. Extracted from `create_app` so a
    clone-job worker PROCESS can build the same registry without also
    building a FastAPI app, a Postgres pool and a DuckDB cache it will
    never use — see clone_executor's process pool.

    Both arguments default to the same env-driven values `create_app` uses,
    so a worker can call this with no arguments at all and be guaranteed
    the same dictionaries and sidecar as the parent, with no second copy
    of the default-resolution logic to drift.

    PassthroughNormalizer registers first (covers every type as a
    placeholder), then real adapters register after it and win for the
    specific types they support — NormalizerRegistry.register() simply
    overwrites the dict entry per semantic type, so registration order is
    the mechanism, not a special-cased "prefer real over placeholder"
    rule.
    """
    if loader is None:
        loader = DictionaryLoader(_DEFAULT_DICTIONARIES_DIR)
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(GenericTextNormalizer(loader))
    registry.register(NameNormalizer(loader))
    registry.register(CompanyNormalizer(loader))
    registry.register(PhoneNormalizer())
    registry.register(EmailNormalizer())
    registry.register(AddressNormalizer(LibpostalClient(libpostal_url or _DEFAULT_LIBPOSTAL_URL)))
    registry.register(PostcodeNormalizer())
    registry.register(DateNormalizer())
    registry.register(CountryNormalizer())
    registry.register(LanguageNormalizer())
    registry.register(ScriptNormalizer())
    registry.register(IdentifierNormalizer())
    registry.register(UuidNormalizer())
    registry.register(NumericNormalizer())
    registry.register(CurrencyNormalizer())
    registry.register(MoneyNormalizer())
    registry.register(UnitNormalizer())
    registry.register(BooleanNormalizer())
    registry.register(URLNormalizer())
    return registry


def _resolve_env_id(dictionaries_dir: str | None = None) -> str:
    """This environment's real ADR-014 fingerprint.

    A failure here must not stop the service from starting: an env_id
    that cannot be computed is a reproducibility problem, not an
    availability one. The fallback is deliberately marked so a bad
    env_id is obvious in stored results rather than silently plausible.
    """
    try:
        return current_env_id(
            dictionaries_dir=dictionaries_dir or _DEFAULT_DICTIONARIES_DIR,
            profile_version=SCAFFOLD_PROFILE.version,
            libpostal_model_sha256=os.environ.get("NORM_LIBPOSTAL_MODEL_SHA256"),
        )
    except Exception:
        logger.exception("env_id could not be computed; results will be stamped unreproducible")
        return "UNRESOLVED-" + blake3.blake3(b"env-id-unavailable").hexdigest()


def build_dispatcher(loader: DictionaryLoader | None = None, *, env_id: str) -> Dispatcher:
    """Registry + the shared missing-value sentinel table, wired together.

    Both Dispatcher construction sites (the app and the clone-job worker)
    go through here so neither can end up with sentinel handling the other
    lacks — the table is loaded from the same dictionary the FREE_TEXT
    normalizer uses.
    """
    if loader is None:
        loader = DictionaryLoader(_DEFAULT_DICTIONARIES_DIR)
    return Dispatcher(
        build_normalizer_registry(loader, libpostal_url=_DEFAULT_LIBPOSTAL_URL),
        env_id=env_id,
        missing_sentinels=load_missing_value_sentinels(loader),
    )


def _allowed_hosts() -> list[str]:
    """Host-header allowlist (the DNS-rebinding defence, ADR-022): loopback
    names, the LAN address compose binds, and any names the deployer lists."""
    extra = [
        os.environ.get("NORM_BIND_ADDR", ""),
        *os.environ.get("NORM_ALLOWED_HOSTS", "").split(","),
    ]
    return ["localhost", "127.0.0.1", *(h.strip() for h in extra if h.strip())]


class LocalCallersOnly:
    """Refuses a peer outside the allowed set (ADR-022). `X-Forwarded-For` is
    never read: there is no proxy in front of this app."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if not check_caller(client[0] if client else None):
                if scope["type"] == "http":
                    await PlainTextResponse("Forbidden: caller outside the local network", 403)(
                        scope, receive, send
                    )
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


def create_app(
    *,
    dictionaries_dir: Path | None = None,
    custom_dictionaries_dir: Path | None = None,
    cache_path: str | None = None,
    pg_dsn: str | None = None,
    max_run_rows: int | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Normalization Engine API",
        description="Source.txt §98 API surface.",
        version="0.1.0",
    )

    # ADR-022. add_middleware puts the last one added outermost, so the caller
    # check runs first, then the Host check, then CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*_DEFAULT_CORS_ORIGINS, *_EXTRA_CORS_ORIGINS],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AddressPolicyError)
    async def _address_refused(_request: Request, exc: AddressPolicyError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
    app.add_middleware(LocalCallersOnly)

    loader = DictionaryLoader(dictionaries_dir or _DEFAULT_DICTIONARIES_DIR)
    custom_store = CustomDictionaryStore(
        custom_dictionaries_dir or _DEFAULT_CUSTOM_DICTIONARIES_DIR, loader
    )

    registry = build_normalizer_registry(loader, libpostal_url=_DEFAULT_LIBPOSTAL_URL)

    cache = NormalizationCache(cache_path or _DEFAULT_CACHE_PATH)

    resolved_pg_dsn = pg_dsn or _DEFAULT_PG_DSN
    persistence = None
    if resolved_pg_dsn:
        persistence = PgPersistence(resolved_pg_dsn)
        persistence.ensure_schema()
        migrated = migrate_sources(persistence)
        if any(migrated.values()):
            logger.info("adjudication sources re-keyed: %s", migrated)

    app.state.store = InMemoryStore(
        cache, persistence, max_run_rows=max_run_rows or _DEFAULT_MAX_RUN_ROWS
    )
    app.state.dispatcher = Dispatcher(
        registry,
        env_id=_resolve_env_id(),
        missing_sentinels=load_missing_value_sentinels(loader),
    )
    app.state.dictionary_loader = loader
    app.state.custom_dictionary_store = custom_store
    app.state.cache = cache
    # DB-clone-and-normalize feature (saved connections + clone jobs) —
    # requires durable storage (crash-resumability, decision #10), so it's
    # only available when NORM_PG_DSN is configured; normapi.dependencies.
    # get_connections turns None here into a clean 503, not a crash.
    app.state.connections = persistence

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
