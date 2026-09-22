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


class LibpostalClient:
    """Thin HTTP client for the libpostal sidecar (services/libpostal).
    A real network dependency, not a Protocol/mock — callers needing a
    test double implement the same two methods directly."""

    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def parse(self, address: str) -> list[tuple[str, str]]:
        try:
            resp = self._client.post("/parse", json={"addresses": [address]})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"libpostal sidecar request failed: {exc}"
            raise LibpostalUnavailableError(msg) from exc
        results = resp.json()
        components = results[0]["components"]
        return [(c["value"], c["label"]) for c in components]

    def parse_many(self, addresses: Sequence[str]) -> list[list[tuple[str, str]]]:
        """One sidecar round-trip for a whole batch. The /parse endpoint
        already took a LIST (`{"addresses": [...]}`) — `parse` above was
        sending exactly one item per request, so a column of N addresses
        cost N serial HTTP round-trips. Same wire format, same response
        shape, N times fewer requests.

        Deliberately not part of `LibpostalParser`: the Protocol is
        satisfied by lightweight test doubles that implement only `parse`,
        and `AddressNormalizer` probes for this method rather than
        requiring it, so those doubles keep working unchanged.
        """
        if not addresses:
            return []
        try:
            resp = self._client.post("/parse", json={"addresses": list(addresses)})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"libpostal sidecar batch request failed: {exc}"
            raise LibpostalUnavailableError(msg) from exc
        results = resp.json()
        return [[(c["value"], c["label"]) for c in r["components"]] for r in results]

    def health(self) -> dict[str, object]:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return dict(resp.json())

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
        # Filled by prepare_batch, read by normalize. Keyed by the RAW
        # input value, holding that value's own unicode result and parsed
        # components, so a concurrent caller replacing this dict can only
        # ever cost a cache miss (-> the per-value path below), never hand
        # one value's components to a different value. Replaced wholesale
        # per batch, so it is bounded by one chunk's distinct values and
        # cannot grow across a run.
        self._primed: dict[str, tuple[object, list[tuple[str, str]]]] = {}

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def prepare_batch(self, values: Sequence[str], ctx: NormalizationContext) -> None:
        """Optional batch hook (DistinctValuePlanner probes for it): does
        the unicode pass plus ONE batched sidecar call for every distinct
        value up front, so the per-value `normalize` below becomes pure
        assembly with no network in it.

        The unicode result is memoized alongside the components precisely
        so this is a MOVE of work, not a duplicate of it — `normalize`
        reuses both. Any failure here is swallowed: the memo just stays
        empty and every value takes the original per-value path, which
        still has its own circuit breaker and fallback.
        """
        parse_many = getattr(self._libpostal, "parse_many", None)
        if parse_many is None or self._circuit.is_open():
            return
        uniq = [v for v in dict.fromkeys(values) if v is not None and v.strip() != ""]
        if not uniq:
            return
        options = UnicodeProcessingOptions(
            form=UnicodeForm.NFC, include_accent_stripped=True, include_confusables=False
        )
        unicode_results = [self._unicode.process(v, options) for v in uniq]
        try:
            batched = parse_many([r.final_value for r in unicode_results])
        except LibpostalUnavailableError:
            self._circuit.record_failure()
            self._primed = {}
            return
        if len(batched) != len(uniq):
            # A short/over-long response means the sidecar did not answer
            # per-address in order; trusting it would silently misattribute
            # components. Drop the batch and let every value go per-value.
            self._primed = {}
            return
        self._circuit.record_success()
        self._primed = dict(zip(uniq, zip(unicode_results, batched, strict=True), strict=True))

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        primed = self._primed.get(value)
        if primed is not None:
            unicode_result, raw_components = primed
            cleaned = unicode_result.final_value
            trace = build_unicode_trace(unicode_result, enabled=ctx.include_trace)
        else:
            options = UnicodeProcessingOptions(
                form=UnicodeForm.NFC, include_accent_stripped=True, include_confusables=False
            )
            unicode_result = self._unicode.process(value, options)
            cleaned = unicode_result.final_value
            trace = build_unicode_trace(unicode_result, enabled=ctx.include_trace)

            if self._circuit.is_open():
                return _fallback(value, cleaned, ctx, trace, reason="circuit breaker open")

            try:
                raw_components = self._libpostal.parse(cleaned)
            except LibpostalUnavailableError as exc:
                self._circuit.record_failure()
                return _fallback(value, cleaned, ctx, trace, reason=str(exc))

            self._circuit.record_success()

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

        trace = [*trace, _parse_trace_step(cleaned, changed=True)]

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
            trace=trace,
            lossiness=Reversibility.PARTIALLY_REVERSIBLE,
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

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
