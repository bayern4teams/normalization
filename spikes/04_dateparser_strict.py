"""Spike: dateparser under strict, conservative settings (Source.txt §43-45;
decision recorded in docs/adr/ADR-008-date-normalization.md).

Proves:
- dateparser's PERMISSIVE defaults will happily guess an interpretation for
  genuinely ambiguous input like "01/02/03" — this is what we must NOT ship.
- STRICT_PARSING + an explicit DATE_ORDER (sourced from context.locale)
  changes that behavior and must be the actual runtime configuration.
- Multilingual parsing works (French, German date strings).
- ciso8601 fast-path handles already-ISO input without invoking dateparser
  at all.

Run: uv run python spikes/04_dateparser_strict.py
"""

from __future__ import annotations

import sys

import ciso8601
import dateparser

sys.stdout.reconfigure(encoding="utf-8")


def demo_permissive_default_is_dangerous() -> None:
    print("=== dateparser's PERMISSIVE default (what we must NOT ship as-is) ===")
    ambiguous = "01/02/03"
    result = dateparser.parse(ambiguous)
    print(f"  dateparser.parse({ambiguous!r})  [no settings]  -> {result}")
    print(
        "  => it silently picked ONE interpretation with no locale context. "
        "Source.txt §43 explicitly forbids shipping this as the default behavior."
    )


def demo_strict_settings_refuse_to_guess() -> None:
    print("\n=== STRICT_PARSING + no locale context: our actual runtime configuration ===")
    ambiguous = "01/02/03"
    result = dateparser.parse(
        ambiguous,
        settings={
            "STRICT_PARSING": True,
            "REQUIRE_PARTS": ["day", "month", "year"],
        },
    )
    print(f"  dateparser.parse({ambiguous!r}, settings=STRICT_PARSING=True) -> {result}")
    print(
        "  (even under strict settings, dateparser resolves to a best-effort date; "
        "our AddressNormalizer-equivalent DateNormalizer wrapper is responsible for "
        "checking whether a locale/DATE_ORDER was actually supplied by context, and "
        "if not, downgrading the result to status=AMBIGUOUS with the assumption "
        "recorded rather than trusting dateparser's internal default order silently.)"
    )


def demo_explicit_date_order_from_locale() -> None:
    print("\n=== Explicit DATE_ORDER sourced from context.locale (unambiguous once supplied) ===")
    ambiguous = "01/02/03"
    us_result = dateparser.parse(ambiguous, settings={"DATE_ORDER": "MDY", "STRICT_PARSING": True})
    uk_result = dateparser.parse(ambiguous, settings={"DATE_ORDER": "DMY", "STRICT_PARSING": True})
    print(f"  DATE_ORDER=MDY (US locale context) -> {us_result}  (Jan 2, 2003)")
    print(f"  DATE_ORDER=DMY (UK locale context) -> {uk_result}  (Feb 1, 2003)")
    print(
        "  => same string, different locale context, different — but each now "
        "EXPLAINABLE and traceable — result. This is what context.locale drives."
    )


def demo_multilingual() -> None:
    print("\n=== Multilingual parsing (Source.txt §4.6) ===")
    examples = [
        ("15 janvier 2024", "fr"),
        ("3. März 2024", "de"),
        ("2024年3月15日", "zh"),
    ]
    for text, lang in examples:
        result = dateparser.parse(text, languages=[lang])
        print(f"  [{lang}] {text!r} -> {result}")


def demo_ciso8601_fast_path() -> None:
    print("\n=== ciso8601 fast path for already-ISO input (performance, ADR-008) ===")
    iso_value = "2024-03-15T10:30:00Z"
    parsed = ciso8601.parse_datetime(iso_value)
    print(f"  ciso8601.parse_datetime({iso_value!r}) -> {parsed.isoformat()}")
    print(
        "  (dateparser never invoked for this value — DateNormalizer detects the "
        "already-ISO shape first and skips the heavier multilingual parser entirely.)"
    )


if __name__ == "__main__":
    demo_permissive_default_is_dangerous()
    demo_strict_settings_refuse_to_guess()
    demo_explicit_date_order_from_locale()
    demo_multilingual()
    demo_ciso8601_fast_path()
