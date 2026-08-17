"""The Normalizer interface — Source.txt §99, §100, §101.

There is deliberately no `normalize_string(value)` anywhere in this
codebase. The only entrypoint is `normalize(value, semantic_type, context,
profile)`. Every semantic-domain adapter (name, company, address, phone,
email, date, ...) implements this same Protocol so the dispatch layer
(built in normexec, M1) can treat them uniformly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from normcore.enums import FieldSemanticType, Reversibility

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pyarrow as pa

    from normcore.context import NormalizationContext
    from normcore.models import NormalizedValue


class ComponentVersion(Protocol):
    """Declared with `@property` (not plain attributes) so both mutable
    and frozen/immutable concrete implementations satisfy it — mypy treats
    a plain `name: str` Protocol attribute as requiring a *settable*
    member, which a frozen pydantic model's read-only field cannot
    provide even though it is structurally compatible for reading.
    """

    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...


class StepSpec(Protocol):
    """Every pipeline step declares its own reversibility claim up front.

    CI empirically verifies this claim against the golden corpus at every
    gate from M2 onward — see docs/adr/ADR-012-lossy-transform-policy.md.
    A step whose observed behavior contradicts its claimed class fails the
    build; this is what makes Source.txt §80's reversibility UI trustworthy
    rather than aspirational.

    `@property`-based (not plain attributes) so both mutable step classes
    and frozen pydantic models (e.g. `normcore.rules.NormalizationStep`)
    satisfy it — see `ComponentVersion` above for why this matters.
    """

    @property
    def step_id(self) -> str: ...
    @property
    def operation(self) -> str: ...
    @property
    def claimed_reversibility(self) -> Reversibility: ...
    @property
    def lossy(self) -> bool: ...


class ValidationResult(Protocol):
    """`@property`-based for the same reason as `ComponentVersion` above —
    concrete implementations are frozen pydantic models."""

    @property
    def is_valid(self) -> bool: ...
    @property
    def status(self) -> str: ...
    @property
    def reason(self) -> str | None: ...


class Explanation(Protocol):
    """Backs the "Why did this change?" UX — Source.txt §117.

    `plain_language` is what a normal-mode user sees; `technical` is only
    surfaced in expert/admin mode (§86, §88). `@property`-based for the
    same reason as `ComponentVersion` above.
    """

    @property
    def plain_language(self) -> str: ...
    @property
    def technical(self) -> str: ...


@runtime_checkable
class Normalizer(Protocol):
    """Source.txt §99: `can_handle`, `normalize`, `validate`, `explain`,
    `version` — plus the batch entrypoint required by §104 and the
    `steps`/`inverse` pair required by the reversibility-verification
    design in ADR-012.
    """

    name: str
    supported_types: frozenset[FieldSemanticType]

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool: ...

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue: ...

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray: ...

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult: ...

    def explain(self, result: NormalizedValue) -> Explanation: ...

    def version(self) -> ComponentVersion: ...

    def steps(self) -> Sequence[StepSpec]: ...

    def inverse(self, step_id: str, value: str) -> str | None:
        """Returns None if the named step has no defined inverse (i.e. it
        is declared LOSSY, or it is LOSSLESS and therefore needs no
        inverse to prove injectivity — see ADR-012 for how each
        reversibility class is actually verified)."""
        ...
