"""NormalizationContext — Source.txt §101.

Normalization may depend on field_name, semantic_type, country, locale,
language, source, table, entity_type, project, user_profile, and
custom_dictionary. Context must be explicit — never inferred implicitly
inside a normalizer.
"""

from __future__ import annotations

import json
from functools import cached_property
from typing import TYPE_CHECKING, Any, Self

import blake3
from pydantic import BaseModel, ConfigDict

from normcore.enums import ErrorPolicy, FieldSemanticType

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    # The day/month order the column's own values prove, and how many distinct
    # values prove it (none contradict it): ADR-008 amendment 2026-10-17.
    column_date_order: tuple[str, int] | None = None
    # The same for the decimal mark (`.` or `,`) of a NUMERIC or MONEY column.
    column_decimal_mark: tuple[str, int] | None = None
    # Whether the column's own values prove LANGUAGE codes (`code`) or names (`name`), and how
    # many distinct values prove it (ADR-010 amendment 2026-10-27).
    column_language_form: tuple[str, int] | None = None
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL
    pii_visibility: str = "masked"
    # Whether normalizers build the per-step `trace` (Source.txt §65).
    # Default True — every interactive path (/preview, /field-test, /runs)
    # needs it, and §65 is not optional for them. Bulk clone jobs set it
    # False: clone_executor reads only `.display` and `.errors` off each
    # result and discards the trace entirely, while building it costs 36%
    # of COMPANY_NAME normalize time (cProfile on real data — the masks
    # and content hashes behind each step run ~16 character_class_mask
    # calls and ~328 unicodedata.category lookups PER VALUE).
    #
    # Deliberately NOT excluded from context_hash below (unlike
    # pii_visibility): a traceless result is a different result, and must
    # never be served from cache to a caller that asked for a traced one.
    include_trace: bool = True

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """A copy hashes its own fields. pydantic copies the instance
        `__dict__`, where `context_hash` below is cached, so a copy with a
        different country kept its parent's hash: the clone executor's
        no-country retry was served the country result it was retrying."""
        copy = super().model_copy(update=update, deep=deep)
        copy.__dict__.pop("context_hash", None)
        return copy

    @cached_property
    def context_hash(self) -> str:
        """Stable hash of everything that can change normalization behavior
        for a given value — used as part of cache keys (never includes the
        raw value itself, see ADR-016).

        Cached, not recomputed per access: the model is frozen, so the
        inputs to this hash cannot change over the instance's life. It was
        a plain @property, which cost a full model_dump + json.dumps +
        blake3 (measured 6.5us) on EVERY access — and a single value is
        hashed 2-3 times (planner cache key, Dispatcher's context_hash
        assertion, and the normalizer stamping it onto its NormalizedValue)
        while one context is reused across an entire column's distinct
        values. cached_property does not appear in model_dump/model_fields,
        so serialization and the hash payload below are unaffected.
        """
        # A context without a column order hashes as it did before the field
        # existed: stored verdict keys and cache keys hold these hashes.
        unset = {
            f for f in ("column_date_order", "column_decimal_mark") if getattr(self, f) is None
        }
        payload = self.model_dump(mode="json", exclude={"pii_visibility", *unset})
        canonical = _canonical_json(payload)
        # errors="surrogatepass": field_name and friends are caller-supplied
        # strings too (e.g. a request's field_name), not just normalized
        # values — same defensive reasoning as normcore.pii.content_hash.
        return blake3.blake3(canonical.encode("utf-8", errors="surrogatepass")).hexdigest()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
