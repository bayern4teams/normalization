"""Per-semantic-type Unicode normalization-form policy — Source.txt §11,
ADR-001.

Centralized here (rather than scattered per-normalizer) so "which fields
use NFKC" is a single query. The default form is NFC everywhere; NFKC is
never applied to identifier-shaped fields unless a profile explicitly
opts in, because compatibility normalization can collapse meaningful
distinctions (superscripts, certain CJK compatibility ideographs,
ligatures, fullwidth forms).
"""

from __future__ import annotations

from enum import StrEnum

from normcore.enums import FieldSemanticType


class UnicodeForm(StrEnum):
    NFC = "NFC"
    NFD = "NFD"
    NFKC = "NFKC"
    NFKD = "NFKD"


DEFAULT_FORM = UnicodeForm.NFC

# Semantic types where NFKC/NFKD compatibility normalization would risk
# collapsing a meaningful distinction (e.g. a superscript digit inside a
# tracking code, a fullwidth character intentionally present in an ID).
# NFKC/NFKD are only usable for these types via an explicit per-field
# profile override — never the type-level default.
_NFKC_RESTRICTED_TYPES = frozenset(
    {
        FieldSemanticType.IDENTIFIER,
        FieldSemanticType.UUID,
        FieldSemanticType.TAX_ID,
        FieldSemanticType.CODE,
        FieldSemanticType.URL,
    }
)


def default_form_for(semantic_type: FieldSemanticType) -> UnicodeForm:
    """The type-level default normalization form. Always NFC unless a
    profile's per-field config explicitly overrides it (see
    normcore.rules.FieldNormalizationConfig)."""
    return DEFAULT_FORM


def is_compatibility_form_allowed(
    semantic_type: FieldSemanticType, *, explicit_override: bool
) -> bool:
    """NFKC/NFKD may be used for a restricted type only when the caller
    passed an explicit per-field override (never as a blanket/type-level
    default) — enforces ADR-001's "never applied blanket" rule at the
    single choke point every normalizer using this policy goes through.
    """
    if semantic_type not in _NFKC_RESTRICTED_TYPES:
        return True
    return explicit_override
