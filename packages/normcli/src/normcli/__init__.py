"""normcli — the gate/tooling CLI (`python -m normcli <command>`). See
`normcli.cli` for the real command implementations.
"""

from normcli.cli import main
from normcli.mutation_gate import MutationScoreResult, compute_mutation_score
from normcli.traceability import TraceabilityCheckResult, check_traceability

__all__ = [
    "MutationScoreResult",
    "TraceabilityCheckResult",
    "check_traceability",
    "compute_mutation_score",
    "main",
]
