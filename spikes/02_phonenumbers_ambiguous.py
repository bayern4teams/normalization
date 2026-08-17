"""Spike: python-phonenumbers on ambiguous input (Source.txt §36, §37, §38).

Proves:
- A number with an explicit country context parses to a correct, valid
  E.164 representation.
- The SAME national-format digits, with NO region context, do NOT get
  guessed at — phonenumbers refuses to produce a result at all without a
  default region, which is exactly the "do not guess" behavior §36
  mandates. We must not defeat this by inventing a fallback region.
- Extensions are kept separate from the canonical number, never merged in.

Run: uv run python spikes/02_phonenumbers_ambiguous.py
"""

from __future__ import annotations

import sys

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

sys.stdout.reconfigure(encoding="utf-8")


def parse_with_explicit_region(raw: str, region: str) -> None:
    parsed = phonenumbers.parse(raw, region)
    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    is_valid = phonenumbers.is_valid_number(parsed)
    is_possible = phonenumbers.is_possible_number(parsed)
    print(
        f"  input={raw!r} region={region!r} -> e164={e164} valid={is_valid} possible={is_possible} "
        f"country_code={parsed.country_code} national_number={parsed.national_number}"
    )


def parse_without_region(raw: str) -> None:
    try:
        # region=None is only valid for already-international (+prefixed)
        # numbers; a bare national-format number with no region context
        # must fail here, not silently resolve to some default.
        parsed = phonenumbers.parse(raw, None)
        e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        print(
            f"  input={raw!r} region=None -> parsed OK (input was already unambiguous, e.g. +prefixed): {e164}"
        )
    except NumberParseException as exc:
        print(f"  input={raw!r} region=None -> NumberParseException ({exc.error_type}): {exc}")
        print("  => this is the CORRECT behavior: status must be AMBIGUOUS, not a guessed region.")


def demo_extension_separation() -> None:
    raw = "+1 415 555 0142 ext 123"
    parsed = phonenumbers.parse(raw, "US")
    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    print(f"  input={raw!r}")
    print(f"  e164 (canonical, NO extension merged in) = {e164}")
    print(f"  extension (kept separate)                = {parsed.extension!r}")
    assert parsed.extension == "123"
    assert "123" not in e164, "extension must never be merged into the canonical E.164 number"


if __name__ == "__main__":
    print(
        "=== Explicit region context (Source.txt §37 precedence: explicit record context wins) ==="
    )
    parse_with_explicit_region("+1 415 555 0142", "US")
    parse_with_explicit_region("415-555-0142", "US")
    parse_with_explicit_region("020 8366 1177", "GB")

    print(
        "\n=== Same national-format digits, NO region context (must NOT guess, Source.txt §36) ==="
    )
    parse_without_region("415-555-0142")  # ambiguous: could be US, could be many NANP countries
    parse_without_region("020 8366 1177")  # ambiguous: UK-shaped but not marked as such
    parse_without_region("+14155550142")  # unambiguous because it's already E.164-prefixed

    print("\n=== Extensions kept separate from canonical number (Source.txt §38) ===")
    demo_extension_separation()

    print(
        "\nConclusion: phonenumbers' own parse() function refuses to resolve "
        "region-ambiguous national-format numbers without an explicit default "
        "region — this IS the AMBIGUOUS status the spec requires, provided "
        "for free by the library rather than something we have to build."
    )
