"""FastAPI dependency providers — reads singletons off `app.state`, set up
once at application startup (normapi.app.create_app), rather than
constructing a new Dispatcher/store/loader per request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from normexec.cache import NormalizationCache

    from normapi.pg_persistence import PgPersistence
    from normapi.store import InMemoryStore
    from normcore import Dispatcher
    from normdict import CustomDictionaryStore, DictionaryLoader


def get_store(request: Request) -> InMemoryStore:
    return request.app.state.store  # type: ignore[no-any-return]


def get_dispatcher(request: Request) -> Dispatcher:
    return request.app.state.dispatcher  # type: ignore[no-any-return]


def get_dictionary_loader(request: Request) -> DictionaryLoader:
    return request.app.state.dictionary_loader  # type: ignore[no-any-return]


def get_custom_dictionary_store(request: Request) -> CustomDictionaryStore:
    return request.app.state.custom_dictionary_store  # type: ignore[no-any-return]


def get_cache(request: Request) -> NormalizationCache:
    return request.app.state.cache  # type: ignore[no-any-return]


def get_connections(request: Request) -> PgPersistence:
    """The DB-clone-and-normalize feature's "connection registry" — saved
    connections and clone jobs are durable-by-nature (crash-resumability,
    decision #10) and need no in-memory-with-optional-persistence
    fallback the way InMemoryStore's profiles/runs have, so this is just
    `PgPersistence` itself, reused directly rather than wrapped in a new
    class (`app.state.connections`, set up in `create_app` the same way
    `app.state.store` already is). 503, not a crash, when NORM_PG_DSN
    isn't configured — the same "predictable rejection over an
    unpredictable failure" choice RunTooLargeError already makes."""
    persistence = request.app.state.connections
    if persistence is None:
        raise HTTPException(
            status_code=503,
            detail="Clone feature requires NORM_PG_DSN to be configured.",
        )
    return persistence  # type: ignore[no-any-return]
