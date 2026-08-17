"""PII-safe value previews for traces, logs, and metrics — Source.txt §123.

Traces store a blake3 hash plus a character-class mask instead of the raw
value by default. Raw previews are available only under an explicit,
role-gated PII-visibility grant (NormalizationContext.pii_visibility) and
must never be written to logs, metrics, or default trace output.
"""

from __future__ import annotations

import unicodedata

import blake3

_MAX_MASK_LENGTH = 64


def content_hash(value: str) -> str:
    return blake3.blake3(value.encode("utf-8")).hexdigest()


def character_class_mask(value: str) -> str:
    """Render a value as its Unicode general-category shape, e.g.
    "José García" -> "Lu Ll Ll Ll Zs Lu Ll Ll Ll Ll Ll" (truncated).

    This preserves *structure* (length, casing pattern, script boundaries,
    punctuation positions) without revealing content — enough to debug a
    normalization rule without exposing the underlying PII.
    """
    truncated = value[:_MAX_MASK_LENGTH]
    categories = [unicodedata.category(ch) for ch in truncated]
    suffix = " …" if len(value) > _MAX_MASK_LENGTH else ""
    return " ".join(categories) + suffix


def safe_preview(value: str, *, pii_visibility: str = "masked") -> str:
    """The value to embed in a trace/log/error at the given visibility level.

    "masked" (default): hash + character-class mask only, no raw content.
    "unmasked": raw value — callers MUST verify the caller is an
    authorized, audited role before requesting this; normcore itself does
    not perform that authorization check (that's an API/UI-layer concern),
    it only refuses to default to it.
    """
    if pii_visibility == "unmasked":
        return value
    return f"hash={content_hash(value)[:16]} mask=[{character_class_mask(value)}]"
