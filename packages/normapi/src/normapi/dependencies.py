"""FastAPI dependency providers — reads singletons off `app.state`, set up
once at application startup (normapi.app.create_app), rather than
constructing a new Dispatcher/store/loader per request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from normexec.cache import NormalizationCache

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
