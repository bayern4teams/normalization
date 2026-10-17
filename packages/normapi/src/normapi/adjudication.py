"""Abstention with an exit — ADR-018.

An `AMBIGUOUS` value is queued once per key; a verdict on that key answers
it on every later run, in that context, until the profile changes. The key
holds the value (hashed: ADR-016 keeps raw values out of keys), the whole
`context_hash` and the profile version. It deliberately omits `env_id`
(ADR-014 hashes all normalizer source into it, so keying on it would orphan
every verdict at every normalizer edit); `env_id` is recorded instead.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import blake3
from normcore.pii import character_class_mask, content_hash, sanitize_surrogates
from normcore.trace import TraceStep

from normcore import NormalizationStatus, NormalizedValue

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from normapi.pg_persistence import PgPersistence
    from normcore import FieldSemanticType, NormalizationContext, NormalizationProfile

# Q15: a human and an agent decide through the same column; which one did is
# this string, so swapping one for the other is data, not a migration.
DECIDED_BY = re.compile(r"(human|agent):[A-Za-z0-9._@+-]+")

# What a decided value must normalize to before a verdict is stored. An
# already-canonical decided value comes back UNCHANGED, which is as clean
# as NORMALIZED; AMBIGUOUS, INVALID, FAILED and PARTIAL are not answers.
CLEAN_STATUSES = frozenset(
    {
        NormalizationStatus.NORMALIZED,
        NormalizationStatus.PARSED,
        NormalizationStatus.REPAIRED,
        NormalizationStatus.UNCHANGED,
    }
)


def _question(context: NormalizationContext) -> NormalizationContext:
    """The context a value is asked and decided in. The order a column's
    values prove is derived from the data, not part of the question: a verdict
    stays found when that evidence appears, and wins over it."""
    if context.column_date_order is None:
        return context
    return context.model_copy(update={"column_date_order": None})


def verdict_key(
    semantic_type: FieldSemanticType,
    original: str,
    context: NormalizationContext,
    profile_version: str,
) -> str:
    context = _question(context)
    payload = json.dumps(
        {
            "semantic_type": semantic_type.value,
            "value_hash": content_hash(original),
            "context_hash": context.context_hash,
            "profile_version": profile_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return blake3.blake3(payload.encode("utf-8")).hexdigest()


def apply_verdict(
    original: str, verdict: Mapping[str, Any], decided: NormalizedValue
) -> NormalizedValue:
    """The decided value's own normalization, re-labelled as the answer
    for `original`: the cell keeps provenance (the source string stays
    `original`, the trace says who decided and under which env_id).

    If the decided value no longer normalizes to what it did when the
    verdict was accepted, a normalizer changed since: the new value is
    emitted as NEEDS_REVIEW (ADR-018, D12) — emitted, but a person must
    confirm it — rather than silently applied or silently dropped."""
    step = TraceStep(
        step_order=len(decided.trace) + 1,
        rule_id="adjudication",
        operation=f"verdict by {verdict['decided_by']} at {verdict['decided_at']}",
        params_hash=content_hash(
            json.dumps(
                {k: verdict[k] for k in ("decided_by", "decided_at", "rationale", "env_id")},
                sort_keys=True,
            )
        ),
        input_hash=content_hash(original),
        output_hash=content_hash(decided.display or ""),
        input_mask=character_class_mask(original),
        output_mask=character_class_mask(decided.display or ""),
        changed=decided.display != original,
        lossy=False,
        reversibility=decided.lossiness,
        library="adjudication",
        library_version=verdict["env_id"],
    )
    update: dict[str, Any] = {"original": original, "trace": [*decided.trace, step]}
    if decided.display != verdict["decided_display"]:
        update["normalization_status"] = NormalizationStatus.NEEDS_REVIEW
        update["errors"] = [
            *decided.errors,
            "adjudicated value normalizes differently than when it was decided; "
            "confirm the verdict",
        ]
    return decided.model_copy(update=update)


class Adjudication:
    """One clone job's view of the queue and the verdicts.

    `resolve` answers the values that have a verdict; `collect` buffers
    the AMBIGUOUS ones for the queue until `drain` hands them to the
    transaction that checkpoints the chunk."""

    def __init__(self, persistence: PgPersistence, profile: NormalizationProfile) -> None:
        self._persistence = persistence
        self._profile_version = profile.version
        self._verdicts: dict[str, dict[str, dict[str, Any]]] = {}
        self._pending: dict[str, dict[str, Any]] = {}

    def resolve(
        self,
        values: Iterable[str],
        *,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        renormalize: Callable[[list[str]], Mapping[str, NormalizedValue]],
    ) -> dict[str, NormalizedValue]:
        verdicts = self._verdicts_for(semantic_type, context)
        if not verdicts:
            return {}
        hits = {
            value: verdicts[key]
            for value in values
            if (key := verdict_key(semantic_type, value, context, self._profile_version))
            in verdicts
        }
        if not hits:
            return {}
        decided = renormalize(sorted({v["decided_value"] for v in hits.values()}))
        # A decided value that no longer normalizes cleanly at all is not
        # applied: the value goes through dispatch as if undecided, and is
        # queued again if it is still AMBIGUOUS.
        return {
            value: apply_verdict(value, verdict, decided[verdict["decided_value"]])
            for value, verdict in hits.items()
            if decided[verdict["decided_value"]].normalization_status in CLEAN_STATUSES
        }

    def collect(
        self,
        by_value: Mapping[str, NormalizedValue],
        occurrences: Mapping[str, int],
        *,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
    ) -> None:
        """Only AMBIGUOUS is queued (Q14): INVALID is not a question."""
        context = _question(context)
        for value, result in by_value.items():
            if result.normalization_status is not NormalizationStatus.AMBIGUOUS:
                continue
            key = verdict_key(semantic_type, value, context, self._profile_version)
            item = self._pending.get(key)
            if item is not None:
                item["occurrences"] += occurrences[value]
                continue
            self._pending[key] = {
                "key": key,
                "semantic_type": semantic_type.value,
                "context_hash": context.context_hash,
                "profile_version": self._profile_version,
                "context": context.model_dump_json(),
                # Shown, never matched on (the key hashes the raw value): a
                # lone surrogate cannot be stored as text, and must not fail
                # the chunk that only wanted to ask about it.
                "original": sanitize_surrogates(value),
                "detail": json.dumps(
                    {
                        "structured": result.structured,
                        "warnings": result.warnings,
                        "errors": result.errors,
                    },
                    sort_keys=True,
                    default=str,
                ),
                "occurrences": occurrences[value],
            }

    def drain(self) -> list[dict[str, Any]]:
        pending, self._pending = list(self._pending.values()), {}
        return pending

    def _verdicts_for(
        self, semantic_type: FieldSemanticType, context: NormalizationContext
    ) -> dict[str, dict[str, Any]]:
        # Per job, not per chunk: a verdict given mid-job applies from the
        # next run, which is when the queue promised it would.
        context = _question(context)
        cache_key = f"{semantic_type.value}:{context.context_hash}"
        if cache_key not in self._verdicts:
            self._verdicts[cache_key] = self._persistence.load_verdicts(
                semantic_type=semantic_type.value,
                context_hash=context.context_hash,
                profile_version=self._profile_version,
            )
        return self._verdicts[cache_key]
