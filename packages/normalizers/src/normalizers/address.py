"""AddressNormalizer — Source.txt Phase 8 (§29-§32, §76).

Pipeline: raw -> shared `UnicodeNormalizer` cleanup -> libpostal sidecar
parse -> components -> structured address. `display`/`comparison` are
never collapsed to one lossy joined string (§30) — `display` is the
cleaned full address text, `comparison`/`search` are built from the
parsed components, and the full component breakdown lives in
`structured`.

Postal codes are validated per-country via `google-i18n-address`'s
`postal_code_matchers` (§32) — no universal regex. A `country` component
(from libpostal) or `ctx.country` is required to validate; without one,
`postal_code_valid` stays `None` (unchecked, not "invalid").

The libpostal sidecar is a network dependency; a small circuit breaker
(open after `_CIRCUIT_FAILURE_THRESHOLD` consecutive failures, half-open
after `_CIRCUIT_COOLDOWN_SECONDS`) avoids hammering an unavailable
sidecar with per-value HTTP calls during a batch run. On any failure
(circuit open or a fresh request failing), the result is
`ADDRESS_PARSE_PARTIAL` + `PARSER_FALLBACK`, never a crash (§68).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import blake3
import httpx
import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep
from normcore.unicode_policy import UnicodeForm

from normalizers import text_ops
from normalizers.country_codes import resolve_country_alpha2
from normalizers.postcode_validation import validate_postcode_format
from normalizers.unicode_normalizer import (
    UnicodeNormalizer,
    UnicodeProcessingOptions,
    build_unicode_trace,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# libpostal label -> our §29 vocabulary, where the names differ. Every
# other libpostal label (e.g. `state_district`, `category`, `near`,
# already-matching names like `house_number`/`road`/`postcode`) is passed
# through as-is into `structured` — additive, not filtered out.
_LABEL_ALIASES = {"house": "building", "city_district": "district"}

_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_COOLDOWN_SECONDS = 30.0


class LibpostalUnavailableError(RuntimeError):
    pass


@runtime_checkable
class LibpostalParser(Protocol):
    """Structural interface `AddressNormalizer` depends on — satisfied by
    the real `LibpostalClient` below, and by lightweight test doubles in
    the unit test suite without needing real HTTP/Docker. Must raise
    `LibpostalUnavailableError` (never let a transport-specific exception
    leak through) on any failure to parse."""

    def parse(self, address: str) -> list[tuple[str, str]]: ...


@runtime_checkable
class BatchLibpostalParser(Protocol):
    """Optional — Phase 3 item 5: a client that can parse many addresses
    in one real round trip. Kept separate from `LibpostalParser` (rather
    than adding a required method to it) so every existing test double
    that implements only `.parse()` keeps working unchanged;
    `AddressNormalizer.normalize_many` checks for this capability and
    falls back to a per-value `normalize()` loop when the injected
    client doesn't have it."""

    def parse_batch(self, addresses: list[str]) -> list[list[tuple[str, str]]]: ...


class LibpostalClient:
    """Thin HTTP client for the libpostal sidecar (services/libpostal).
    A real network dependency, not a Protocol/mock — callers needing a
    test double implement the same two methods directly."""

    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def parse(self, address: str) -> list[tuple[str, str]]:
        return self.parse_batch([address])[0]

    def parse_batch(self, addresses: list[str]) -> list[list[tuple[str, str]]]:
        """Phase 3 item 5 of the throughput/memory program (2026-08-29):
        one real HTTP round trip for the whole list, not one per address
        — `services/libpostal/server.py`'s `/parse` already accepts a
        list (`ParseRequest.addresses`) and was simply being sent exactly
        one address per call regardless, which this program's own plan
        flagged as an available, unused win. `parse()` above is now
        implemented in terms of this (a batch of one), so there is
        exactly one real request-building code path, not two to keep in
        sync."""
        if not addresses:
            return []
        try:
            resp = self._client.post("/parse", json={"addresses": addresses})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"libpostal sidecar request failed: {exc}"
            raise LibpostalUnavailableError(msg) from exc
        results = resp.json()
        return [[(c["value"], c["label"]) for c in entry["components"]] for entry in results]

    def health(self) -> dict[str, object]:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return dict(resp.json())

    def version(self) -> str | None:
        """The libpostal model data's SHA-256, from the sidecar's real
        `GET /version` (services/libpostal/server.py) — one of §73/
        ADR-014's env_id inputs. Returns `None` (never raises) on any
        failure: env_id computation happens at API startup and must not
        crash the whole process just because the sidecar isn't reachable
        yet, matching how `scripts/env_fingerprint.py`'s CLI has always
        treated a missing `--libpostal-model-sha256` as a legitimate,
        gracefully-degraded input rather than a hard error.
        """
        try:
            resp = self._client.get("/version")
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        model_sha256 = resp.json().get("model_sha256")
        return model_sha256 if isinstance(model_sha256, str) else None

    def close(self) -> None:
        self._client.close()


class _CircuitBreaker:
    def __init__(self, *, threshold: int, cooldown_seconds: float) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._cooldown:
            self._opened_at = None
            self._consecutive_failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._opened_at = time.monotonic()


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_PARSE_STEP = _StaticStepSpec(
    "address.libpostal_parse", "address.libpostal_parse", Reversibility.PARTIALLY_REVERSIBLE, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (
    *(
        _StaticStepSpec(name, spec.operation, spec.claimed_reversibility, spec.lossy)
        for name, spec in text_ops.OPERATIONS.items()
    ),
    _PARSE_STEP,
)


class AddressNormalizer:
    name = "AddressNormalizer"
    supported_types = frozenset({FieldSemanticType.ADDRESS})

    def __init__(self, libpostal_client: LibpostalParser) -> None:
        self._unicode = UnicodeNormalizer()
        self._libpostal = libpostal_client
        self._circuit = _CircuitBreaker(
            threshold=_CIRCUIT_FAILURE_THRESHOLD, cooldown_seconds=_CIRCUIT_COOLDOWN_SECONDS
        )

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned, trace = self._clean(value)

        if self._circuit.is_open():
            return _fallback(value, cleaned, ctx, trace, reason="circuit breaker open")

        try:
            raw_components = self._libpostal.parse(cleaned)
        except LibpostalUnavailableError as exc:
            self._circuit.record_failure()
            return _fallback(value, cleaned, ctx, trace, reason=str(exc))

        self._circuit.record_success()
        return _build_parsed_result(value, cleaned, trace, raw_components, ctx)

    def normalize_many(
        self, values: Sequence[str | None], ctx: NormalizationContext
    ) -> list[NormalizedValue]:
        """Phase 3 item 5 of the throughput/memory program (2026-08-29):
        the real batch entrypoint `normcore.dispatch.Dispatcher.
        normalize_many` calls instead of `len(values)` separate
        `normalize()` calls — one real libpostal HTTP round trip for
        every value that actually needs parsing (null/empty values never
        reach the network either way, matching `normalize()`).

        Falls back to the per-value path entirely when the injected
        client doesn't support real batching (`BatchLibpostalParser` —
        e.g. a test double implementing only `.parse()`), or when the
        circuit is already open (nothing to batch — every real value
        would fall back anyway). A failed batch call counts as ONE
        circuit-breaker failure, not `len(values)` — see this method's
        own reasoning: the batch already represents one real network
        attempt, and inflating the failure count by batch size would
        make the circuit trip on the very first batch against a large
        distinct-value set, which is not what "3 consecutive failures"
        was calibrated to mean.
        """
        if not isinstance(self._libpostal, BatchLibpostalParser) or self._circuit.is_open():
            return [self.normalize(v, ctx) for v in values]

        results: list[NormalizedValue | None] = [None] * len(values)
        real_indices: list[int] = []
        # Keyed by index — carries the original `str` value alongside its
        # cleaned form/trace, so the two branches below never need to
        # re-index `values` itself (which mypy correctly types as
        # `str | None`, even though every index reachable here was
        # already proven non-null/non-empty above).
        real_by_index: dict[int, tuple[str, str, list[TraceStep]]] = {}
        for i, value in enumerate(values):
            if value is None:
                results[i] = _missing(None, MissingKind.NULL, ctx)
            elif value.strip() == "":
                results[i] = _missing(value, MissingKind.EMPTY_STRING, ctx)
            else:
                cleaned, trace = self._clean(value)
                real_by_index[i] = (value, cleaned, trace)
                real_indices.append(i)

        if real_indices:
            cleaned_addresses = [real_by_index[i][1] for i in real_indices]
            try:
                parsed_batch = self._libpostal.parse_batch(cleaned_addresses)
            except LibpostalUnavailableError as exc:
                self._circuit.record_failure()
                for i in real_indices:
                    value, cleaned, trace = real_by_index[i]
                    results[i] = _fallback(value, cleaned, ctx, trace, reason=str(exc))
            else:
                self._circuit.record_success()
                for i, raw_components in zip(real_indices, parsed_batch, strict=True):
                    value, cleaned, trace = real_by_index[i]
                    results[i] = _build_parsed_result(value, cleaned, trace, raw_components, ctx)

        return [r for r in results if r is not None]  # every index was filled above

    def _clean(self, value: str) -> tuple[str, list[TraceStep]]:
        options = UnicodeProcessingOptions(
            form=UnicodeForm.NFC, include_accent_stripped=True, include_confusables=False
        )
        unicode_result = self._unicode.process(value, options)
        return unicode_result.final_value, build_unicode_trace(unicode_result)

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        results = [self.normalize(v, ctx) for v in values.to_pylist()]
        return pa.StructArray.from_arrays(
            [
                pa.array([r.original for r in results], type=pa.large_string()),
                pa.array([r.display for r in results], type=pa.large_string()),
                pa.array([r.comparison for r in results], type=pa.large_string()),
                pa.array([r.normalization_status.value for r in results], type=pa.large_string()),
            ],
            names=["original", "display", "comparison", "status"],
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        result = self.normalize(value, ctx)
        if result.original_kind is not None:
            return ValidationOutcome(
                is_valid=False, status="MISSING", reason=result.original_kind.value
            )
        is_valid = QualityFlag.ADDRESS_PARSE_PARTIAL not in result.flags
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "incomplete address parse",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if QualityFlag.PARSER_FALLBACK in result.flags:
            return ExplanationText(
                plain_language="The address parsing service was unavailable; left as-is.",
                technical=f"errors={result.errors}",
            )
        return ExplanationText(
            plain_language="Parsed into address components.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        if step_id.startswith("unicode_normalize_"):
            form_name = step_id.removeprefix("unicode_normalize_").upper()
            form = UnicodeForm(form_name)
            inverse_form = text_ops.inverse_unicode_form(form)
            if inverse_form is None:
                return None
            output, _ = text_ops.unicode_normalize(value, inverse_form)
            return output
        return None


def _build_parsed_result(
    value: str,
    cleaned: str,
    trace: list[TraceStep],
    raw_components: list[tuple[str, str]],
    ctx: NormalizationContext,
) -> NormalizedValue:
    """The post-parse half of `normalize()`, extracted so `normalize_many`
    (Phase 3 item 5) can share it exactly: whether `raw_components` came
    from one `parse()` call or one entry of a `parse_batch()` call, the
    result must be identical."""
    structured = _build_component_structure(raw_components)
    postcode_valid = _validate_postcode(structured, ctx)
    if postcode_valid is not None:
        structured["postcode_valid"] = postcode_valid

    # raw_components entries are (value, label) — matching
    # LibpostalClient.parse()'s return shape, NOT (label, value).
    comparison_parts = [
        value
        for value, label in raw_components
        if label not in {"category", "near"} and value.strip()
    ]
    comparison, _ = text_ops.casefold(" ".join(comparison_parts), ctx.locale)
    search = comparison

    flags: list[QualityFlag] = []
    if not structured.get("road") or not structured.get("city"):
        flags.append(QualityFlag.ADDRESS_PARSE_PARTIAL)

    confidence = 1.0
    if postcode_valid is False:
        confidence = 0.6
    if QualityFlag.ADDRESS_PARSE_PARTIAL in flags:
        confidence = min(confidence, 0.7)

    full_trace = [*trace, _parse_trace_step(cleaned, changed=True)]

    return NormalizedValue(
        original=value,
        display=cleaned,
        comparison=comparison,
        search=search,
        structured=structured,
        validation_status="VALID" if not flags else "PARTIAL",
        normalization_status=(
            NormalizationStatus.PARSED
            if QualityFlag.ADDRESS_PARSE_PARTIAL not in flags
            else NormalizationStatus.PARTIAL
        ),
        confidence=confidence,
        flags=flags,
        trace=full_trace,
        lossiness=Reversibility.PARTIALLY_REVERSIBLE,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _build_component_structure(raw_components: list[tuple[str, str]]) -> dict[str, object]:
    structured: dict[str, object] = {}
    for value, label in raw_components:
        key = _LABEL_ALIASES.get(label, label)
        structured[key] = value
    return structured


def _validate_postcode(structured: dict[str, object], ctx: NormalizationContext) -> bool | None:
    postcode = structured.get("postcode")
    if not postcode or not isinstance(postcode, str):
        return None
    raw_country = structured.get("country") or ctx.country
    if not isinstance(raw_country, str) or not raw_country:
        return None
    # libpostal's `country` component is often a free-text abbreviation
    # (e.g. "uk", "usa") rather than an ISO 3166-1 alpha-2 code, which is
    # what `google-i18n-address` requires — resolve it first rather than
    # passing it through directly (a real gap found empirically in M4:
    # postal-code validation silently never triggered for real UK/US
    # addresses until this resolution step was added).
    country_code = resolve_country_alpha2(raw_country)
    if country_code is None:
        return None
    return validate_postcode_format(postcode, country_code)


def _fallback(
    original: str,
    cleaned: str,
    ctx: NormalizationContext,
    trace: list[TraceStep],
    *,
    reason: str,
) -> NormalizedValue:
    return NormalizedValue(
        original=original,
        display=cleaned,
        normalization_status=NormalizationStatus.PARTIAL,
        validation_status="PARTIAL",
        confidence=0.3,
        flags=[QualityFlag.ADDRESS_PARSE_PARTIAL, QualityFlag.PARSER_FALLBACK],
        errors=[reason],
        structured={},
        trace=trace,
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _missing(value: str | None, kind: MissingKind, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        original_kind=kind,
        normalization_status=NormalizationStatus.NORMALIZED,
        validation_status="MISSING",
        confidence=1.0,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _parse_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=99,
        rule_id="address.libpostal_parse",
        operation="address.libpostal_parse",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        library="libpostal",
        library_version="1.1.4",
    )
