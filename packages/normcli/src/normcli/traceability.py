"""`normcli check-traceability` — cross-checks `docs/traceability-matrix.md`
against `Source.txt`'s real section headers.

`docs/traceability-matrix.md` claims (in its own text) that this check
"is verified for completeness at every gate by `normcli gate
--check-traceability`, which asserts every §N from Source.txt's section
headers appears in this file (built in M1)." That claim was false until
the M7 follow-up self-audit that added this module — the command never
existed. This is the real implementation the matrix always claimed to
have.

A real section header in `Source.txt` is a line matching `^\\d+\\. [A-Z`
immediately followed by a line of only `=` characters (Source.txt's own
box-drawing convention) — a plain numbered list item elsewhere in the
body text (e.g. "1. Raw value" inside §0's own worked example) does not
qualify, since it's never followed by a `====` line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SECTION_HEADER_RE = re.compile(r"^(\d+)\. [A-Z]")
_UNDERLINE_RE = re.compile(r"^=+$")
# A matrix row's §-number cell is normally just a bare integer, but a
# handful of rows legitimately annotate a sub-range (e.g. "4 (4.1-4.8)"
# for §4's own lettered sub-items) — match the leading integer only,
# don't require the cell to contain nothing else.
_MATRIX_ROW_RE = re.compile(r"^\|\s*(\d+)\b")


@dataclass(frozen=True)
class TraceabilityCheckResult:
    source_section_numbers: frozenset[int]
    matrix_section_numbers: frozenset[int]

    @property
    def missing_from_matrix(self) -> frozenset[int]:
        return self.source_section_numbers - self.matrix_section_numbers

    @property
    def extra_in_matrix(self) -> frozenset[int]:
        """Section numbers the matrix documents that Source.txt doesn't
        actually have — equally worth flagging as a real drift signal,
        not just missing rows."""
        return self.matrix_section_numbers - self.source_section_numbers

    @property
    def is_complete(self) -> bool:
        return not self.missing_from_matrix and not self.extra_in_matrix


def extract_source_section_numbers(source_text: str) -> frozenset[int]:
    lines = source_text.split("\n")
    numbers: set[int] = set()
    for i in range(len(lines) - 1):
        header_match = _SECTION_HEADER_RE.match(lines[i])
        if header_match and _UNDERLINE_RE.match(lines[i + 1]):
            numbers.add(int(header_match.group(1)))
    return frozenset(numbers)


def extract_matrix_section_numbers(matrix_text: str) -> frozenset[int]:
    numbers: set[int] = set()
    for line in matrix_text.split("\n"):
        match = _MATRIX_ROW_RE.match(line)
        if match:
            numbers.add(int(match.group(1)))
    return frozenset(numbers)


def check_traceability(*, source_path: Path, matrix_path: Path) -> TraceabilityCheckResult:
    source_numbers = extract_source_section_numbers(source_path.read_text(encoding="utf-8"))
    matrix_numbers = extract_matrix_section_numbers(matrix_path.read_text(encoding="utf-8"))
    return TraceabilityCheckResult(
        source_section_numbers=source_numbers, matrix_section_numbers=matrix_numbers
    )
