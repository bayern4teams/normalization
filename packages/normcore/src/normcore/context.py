"""NormalizationContext — Source.txt §101.

Normalization may depend on field_name, semantic_type, country, locale,
language, source, table, entity_type, project, user_profile, and
custom_dictionary. Context must be explicit — never inferred implicitly
inside a normalizer.
"""

from __future__ import annotations

import json
from typing import Any

import blake3
from pydantic import BaseModel, ConfigDict, PrivateAttr

from normcore.enums import ErrorPolicy, FieldSemanticType


class NormalizationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_name: str
    semantic_type: FieldSemanticType
    country: str | None = None
    locale: str | None = None
    language: str | None = None
    script: str | None = None
    source: str | None = None
    table: str | None = None
    entity_type: str | None = None
    project: str | None = None
    user_profile: str | None = None
    dictionary_set: tuple[str, ...] = ()
    default_region: str | None = None
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL
    pii_visibility: str = "masked"

    # Phase 1 (2026-08-29 throughput program): `context_hash` was a plain
    # `@property` recomputing model_dump + json.dumps + blake3 on every
    # access — measured 19.28 µs/access, hit ~3x per value (planner.py,
    # every normalizer's NormalizedValue construction, dispatch.py's
    # mismatch check), ~58 µs/value of pure redundant work on a model
    # that can never change once constructed (frozen=True). Memoized via
    # a `PrivateAttr`, not `functools.cached_property` — private attrs
    # stay mutable on a frozen pydantic model (pydantic's frozen check
    # only guards real fields' `__setattr__`), whereas
    # `cached_property` writes into `__dict__`, which collides with how
    # pydantic itself stores field values and does not work reliably on
    # a `BaseModel`.
    _context_hash_cache: str | None = PrivateAttr(default=None)

    @property
    def context_hash(self) -> str:
        """Stable hash of everything that can change normalization behavior
        for a given value — used as part of cache keys (never includes the
        raw value itself, see ADR-016).
        """
        if self._context_hash_cache is None:
            payload = self.model_dump(mode="json", exclude={"pii_visibility"})
            canonical = _canonical_json(payload)
            self._context_hash_cache = blake3.blake3(canonical.encode("utf-8")).hexdigest()
        return self._context_hash_cache


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
