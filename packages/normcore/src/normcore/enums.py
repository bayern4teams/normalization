"""Enumerations shared across the normalization engine.

Every enum here corresponds directly to a named list in Source.txt so that
the mapping in docs/traceability-matrix.md stays literal and checkable.
"""

from __future__ import annotations

from enum import StrEnum


class NormalizationStatus(StrEnum):
    """Source.txt §67."""

    NORMALIZED = "NORMALIZED"
    UNCHANGED = "UNCHANGED"
    REPAIRED = "REPAIRED"
    PARSED = "PARSED"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class MissingKind(StrEnum):
    """Source.txt §54 — NULL vs EMPTY vs UNKNOWN must remain distinguishable."""

    NULL = "NULL"
    EMPTY_STRING = "EMPTY_STRING"
    UNKNOWN_VALUE = "UNKNOWN_VALUE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REDACTED = "REDACTED"
    INVALID = "INVALID"
    PARSING_FAILED = "PARSING_FAILED"


class QualityFlag(StrEnum):
    """Source.txt §114, extended with a few M2/M0-research-driven additions
    (CONFUSABLE_DETECTED, MIXED_SCRIPT, ENCODING_REPAIRED) documented in
    docs/adr/ADR-001-unicode-strategy.md and ADR-002-text-repair.md.
    """

    MOJIBAKE_FIXED = "MOJIBAKE_FIXED"
    UNICODE_NORMALIZED = "UNICODE_NORMALIZED"
    AMBIGUOUS_LOCALE = "AMBIGUOUS_LOCALE"
    AMBIGUOUS_DATE = "AMBIGUOUS_DATE"
    PHONE_INVALID = "PHONE_INVALID"
    PHONE_REGION_INFERRED = "PHONE_REGION_INFERRED"
    EMAIL_INVALID = "EMAIL_INVALID"
    ADDRESS_PARSE_PARTIAL = "ADDRESS_PARSE_PARTIAL"
    POTENTIAL_COLLISION = "POTENTIAL_COLLISION"
    LOSSY_TRANSFORMATION = "LOSSY_TRANSFORMATION"
    UNKNOWN_SEMANTIC_TYPE = "UNKNOWN_SEMANTIC_TYPE"
    PARSER_FALLBACK = "PARSER_FALLBACK"
    CUSTOM_RULE_APPLIED = "CUSTOM_RULE_APPLIED"
    CONFUSABLE_DETECTED = "CONFUSABLE_DETECTED"
    MIXED_SCRIPT = "MIXED_SCRIPT"
    ENCODING_REPAIRED = "ENCODING_REPAIRED"


class ErrorPolicy(StrEnum):
    """Source.txt §69."""

    FAIL_RECORD = "FAIL_RECORD"
    SKIP_FIELD = "SKIP_FIELD"
    RETURN_ORIGINAL = "RETURN_ORIGINAL"
    RETURN_NULL = "RETURN_NULL"
    MARK_INVALID = "MARK_INVALID"


class Reversibility(StrEnum):
    """Source.txt §80. Empirically verified per rule — see ADR-012."""

    LOSSLESS = "LOSSLESS"
    REVERSIBLE = "REVERSIBLE"
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
    LOSSY = "LOSSY"


class FieldSemanticType(StrEnum):
    """Source.txt §60 — the semantic types a field can be classified as."""

    PERSON_NAME = "PERSON_NAME"
    GIVEN_NAME = "GIVEN_NAME"
    FAMILY_NAME = "FAMILY_NAME"
    COMPANY_NAME = "COMPANY_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    POSTCODE = "POSTCODE"
    COUNTRY = "COUNTRY"
    LANGUAGE = "LANGUAGE"
    SCRIPT = "SCRIPT"
    DATE = "DATE"
    DATETIME = "DATETIME"
    IDENTIFIER = "IDENTIFIER"
    UUID = "UUID"
    TAX_ID = "TAX_ID"
    URL = "URL"
    NUMERIC = "NUMERIC"
    CURRENCY = "CURRENCY"
    QUANTITY = "QUANTITY"
    BOOLEAN = "BOOLEAN"
    FREE_TEXT = "FREE_TEXT"
    CODE = "CODE"
    UNKNOWN = "UNKNOWN"


class SemanticSource(StrEnum):
    """Where a field's semantic type assignment came from (§61, §85)."""

    DETECTED = "DETECTED"
    USER = "USER"
    LLM_SUGGESTED_USER_APPROVED = "LLM_SUGGESTED_USER_APPROVED"


class ProfileStatus(StrEnum):
    """Source.txt §95, §120."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
