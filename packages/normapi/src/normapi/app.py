"""FastAPI application factory — Source.txt §98.

Builds the app, registers the §98 router, and wires up the process-wide
singletons (InMemoryStore, Dispatcher, DictionaryLoader) via `app.state`,
read by normapi.dependencies at request time.
"""

from __future__ import annotations

import os
from pathlib import Path

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
from normexec.env_fingerprint import compute_env_id, gather

from normanalysis import NormalizationMetrics, setup_telemetry
from normapi.routes import router
from normapi.sources import SourceRegistry
from normapi.store import InMemoryStore
from normcore import Dispatcher, NormalizerRegistry
from normdict import CustomDictionaryStore, DictionaryLoader

# `profile_version` is one of env_id's real, tested inputs (ADR-014,
# scripts/env_fingerprint.py's own `EnvFingerprintInputs` — mutating it
# is asserted to change env_id in tests/unit/test_env_fingerprint.py).
# But `Dispatcher` is a single process-wide singleton shared across every
# profile this service serves (see Dispatcher's own docstring: "env_id
# computed once per run/process... never recomputed per value") — there
# is no single "the active profile" for it to bind to, since many
# profiles can exist simultaneously, each independently versioned. This
# constant is the deliberate, disclosed resolution: env_id at this
# process-wide granularity represents the library/ICU/dictionary
# environment snapshot only, using env_fingerprint's own "no specific
# profile" default (matching what its CLI already defaults
# `--profile-version` to when not given a real one) rather than
# arbitrarily picking one profile's version to represent all of them.
_ENV_ID_PROFILE_VERSION_PLACEHOLDER = "unversioned"

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

# Real persistence (ADR-013, M9) — set in compose.yaml to
# postgresql://normalization:normalization@postgres:5432/normalization,
# declared there since M0 but never actually read by any code until now.
# None (the default for local `uv run uvicorn` outside Docker unless set)
# means pure in-memory, matching every prior milestone's behavior —
# nothing survives a restart.
_DEFAULT_POSTGRES_DSN = os.environ.get("NORM_PG_DSN")

# Real per-value result persistence (ADR-013, this segment) — set in
# compose.yaml to a shared volume path, declared there since M0 but never
# actually read by any code until now. Both must be set (mirrors the
# Postgres None-means-in-memory default above); either being unset means
# a run's results live only in-process, same as every prior milestone.
_DEFAULT_SIDECAR_PARQUET_ROOT = os.environ.get("NORM_SIDECAR_PARQUET_ROOT")
_DEFAULT_SIDECAR_DUCKDB_PATH = os.environ.get("NORM_SIDECAR_DUCKDB_PATH")

# Real DB/file source connectors wired into the live API (§105, M10) — a
# JSON file of `{source_id: {"type": ..., ...connector-specific params}}`,
# never a client-supplied DSN in a request body (see normapi.sources'
# own docstring for why). Unset means no sources are registered, matching
# every other optional-integration env var's "off by default" behavior.
_DEFAULT_SOURCES_CONFIG_PATH = os.environ.get("NORM_SOURCES_CONFIG_PATH")

# Lightweight API-key auth (M11, see normapi.auth) — unset means auth is
# fully disabled, matching every other optional-integration env var's
# "off by default" behavior; every existing test's plain
# TestClient(create_app()) construction is unaffected.
_DEFAULT_API_KEY = os.environ.get("NORM_API_KEY")

# Real OTLP export destination (M12, see normanalysis.telemetry) — unset
# means every run's §122 metrics/spans still land in this process's own
# in-memory exporter (real, but not "exported" anywhere), matching every
# other optional-integration env var's "off by default" behavior.
_DEFAULT_OTLP_ENDPOINT = os.environ.get("NORM_OTLP_ENDPOINT")


def create_app(
    *,
    dictionaries_dir: Path | None = None,
    custom_dictionaries_dir: Path | None = None,
    cache_path: str | None = None,
    postgres_dsn: str | None = None,
    sidecar_parquet_root: str | Path | None = None,
    sidecar_duckdb_path: str | Path | None = None,
    sources_config_path: str | Path | None = None,
    api_key: str | None = None,
    otlp_endpoint: str | None = None,
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
    libpostal_client = LibpostalClient(_DEFAULT_LIBPOSTAL_URL)

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

    cache = NormalizationCache(cache_path or _DEFAULT_CACHE_PATH)

    # Real env_id (§73/ADR-014) — reuses the same LibpostalClient instance
    # AddressNormalizer already holds, rather than opening a second HTTP
    # client just to ask its /version once. `version()` never raises (see
    # its own docstring) so a libpostal sidecar that isn't up yet cannot
    # crash API startup — env_id is simply computed with
    # libpostal_model_sha256=None in that case, same as the CLI tool's own
    # graceful-degradation behavior when it isn't given one.
    env_fingerprint_inputs = gather(
        libpostal_model_sha256=libpostal_client.version(),
        profile_version=_ENV_ID_PROFILE_VERSION_PLACEHOLDER,
        dictionaries_dir=dictionaries_dir or _DEFAULT_DICTIONARIES_DIR,
    )
    env_id = compute_env_id(env_fingerprint_inputs)

    # Real §122 metrics/spans (M12) — setup_telemetry()/NormalizationMetrics
    # were real and tested since M1 but never actually reachable from the
    # live app until now. Always on (an in-memory exporter costs nothing
    # meaningful and needs no configuration); NORM_OTLP_ENDPOINT additionally
    # makes it leave the process to a real collector.
    telemetry_handles = setup_telemetry(
        "normalization-engine", otlp_endpoint=otlp_endpoint or _DEFAULT_OTLP_ENDPOINT
    )
    telemetry_metrics = NormalizationMetrics(telemetry_handles.meter)
    app.state.telemetry_handles = telemetry_handles
    app.state.telemetry_metrics = telemetry_metrics

    app.state.store = InMemoryStore(
        cache,
        postgres_dsn=postgres_dsn or _DEFAULT_POSTGRES_DSN,
        sidecar_parquet_root=sidecar_parquet_root or _DEFAULT_SIDECAR_PARQUET_ROOT,
        sidecar_duckdb_path=sidecar_duckdb_path or _DEFAULT_SIDECAR_DUCKDB_PATH,
        telemetry=(telemetry_handles, telemetry_metrics),
    )
    app.state.dispatcher = Dispatcher(registry, env_id=env_id)
    app.state.dictionary_loader = loader
    app.state.custom_dictionary_store = custom_store
    app.state.cache = cache

    resolved_sources_config_path = sources_config_path or _DEFAULT_SOURCES_CONFIG_PATH
    app.state.source_registry = (
        SourceRegistry.from_config_file(resolved_sources_config_path)
        if resolved_sources_config_path
        else SourceRegistry({})
    )
    app.state.api_key = api_key or _DEFAULT_API_KEY

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
