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


def sanitize_surrogates(value: str) -> str:
    """Replaces any unpaired UTF-16 surrogate in `value` with U+FFFD
    (the standard Unicode replacement character).

    A `str` can legally hold a lone surrogate (Python doesn't validate
    this on construction), but such a value cannot be encoded as UTF-8
    at all, which is what JSON — and therefore every HTTP response this
    API returns — requires. Undetected, this crashed the whole pipeline
    on ANY value containing one: content_hash() during trace-building,
    normexec.cache.make_cache_key() during cache-key hashing, and even a
    value that got past both still crashed pydantic's own JSON
    serializer when the response was built, since `original` preserved
    the raw surrogate. Called once, at the single point every value
    enters the system (Dispatcher.normalize), so every `NormalizedValue`
    this API can ever return is guaranteed representable — same
    root-cause-once approach as content_hash's own defensive encode
    below, kept as a second line of defense.
    """
    return value.encode("utf-8", errors="replace").decode("utf-8")


def content_hash(value: str) -> str:
    # errors="surrogatepass": a value can legally reach here containing an
    # unpaired UTF-16 surrogate (a routine artifact of legacy encoding
    # pipelines — MySQL's non-mb4 utf8 charset, truncated UTF-16 re-encodes)
    # even though it's already survived the Unicode-repair stage untouched.
    # Plain "utf-8" raises UnicodeEncodeError on such a value, which is not
    # a NormalizerFailure, so it was never caught by the dispatcher's
    # error-policy handling — one malformed value crashed the entire batch
    # (found via live testing: a single poisoned row 500'd a 5-row run
    # outright). surrogatepass encodes it deterministically instead of
    # raising; the hash is still PII-safe either way, since it's a hash.
    return blake3.blake3(value.encode("utf-8", errors="surrogatepass")).hexdigest()


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
