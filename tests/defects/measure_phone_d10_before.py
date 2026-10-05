"""Snapshot the CURRENT PhoneNormalizer outputs over a phone corpus (D10 acceptance).

Run: `uv run python tests/defects/measure_phone_d10_before.py`

Writes `tests/defects/phone_d10_baseline.json`. It was generated on the code BEFORE D10 was
implemented; do not regenerate it after the fix (that would make the byte-identity check
vacuous). The corpus is built from libphonenumber example numbers (every supported region, each
in national form with that region as context and in international form with none) plus hand-made
edge cases: invalid, ambiguous, too short, vanity letters, odd whitespace, extension spellings.
Not collected by pytest (no test_ prefix).
"""

from __future__ import annotations

import json
from pathlib import Path

import phonenumbers
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from phonenumbers import PhoneNumberFormat as Fmt
from phonenumbers import PhoneNumberType as T

OUT = Path(__file__).with_name("phone_d10_baseline.json")

# (value, country, default_region)
Case = tuple[str, str | None, str | None]


def corpus() -> list[Case]:
    cases: list[Case] = []
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        fixed = phonenumbers.example_number_for_type(region, T.FIXED_LINE)
        mobile = phonenumbers.example_number_for_type(region, T.MOBILE)
        if fixed is not None:
            cases.append((phonenumbers.format_number(fixed, Fmt.NATIONAL), region, None))
            cases.append((phonenumbers.format_number(fixed, Fmt.INTERNATIONAL), None, None))
        if mobile is not None:
            cases.append((phonenumbers.format_number(mobile, Fmt.E164), None, None))
            cases.append((phonenumbers.format_number(mobile, Fmt.NATIONAL), None, region))
    hand: list[Case] = [
        ("+1 415-555-2671", None, None),
        ("+44 20 7946 0958", None, None),
        ("+49 30 123456", None, None),
        ("415-555-2671", None, None),
        ("415-555-2671", "US", None),
        ("415-555-2671", None, "US"),
        ("415-555-2671", "US", "GB"),
        ("+1 415-555-2671", "GB", None),
        ("020 7946 0958", None, None),
        ("020 7946 0958", "GB", None),
        ("00 44 20 7946 0958", None, None),
        ("00 44 20 7946 0958", "US", None),
        ("123", "US", None),
        ("not a phone number", "US", None),
        ("not a phone number", None, None),
        ("+", None, None),
        ("+999 123 4567", None, None),
        ("+1 555", None, None),
        ("1-800-FLOWERS", None, None),
        ("1-800-FLOWERS", "US", None),
        ("  +1 (415) 555-2671  ", None, None),
        ("+1\u00a0415\u00a0555\u00a02671", None, None),
        ("+1 415 555 2671 45", None, None),
        ("+1 415-555-2671 x12345678901234567890", None, None),
        ("tel:+14155552671", "US", None),
        ("tel:+14155552671", None, None),
        ("+1 415-555-2671 x", None, None),
        ("+1 415-555-2671 ext.", None, None),
        ("x45", None, None),
        ("x45", "US", None),
        ("+4915112345678", None, None),
        ("+81 3-1234-5678", None, None),
        ("+81 3-1234-5678", "US", None),
        ("0", "US", None),
        ("٠١٢٣٤٥٦٧٨٩", "EG", None),
        ("+1 415-555-2671, 415-555-2672", None, None),
    ]
    return cases + hand


def run(value: str, country: str | None, default_region: str | None) -> dict[str, object]:
    ctx = NormalizationContext(
        field_name="phone",
        semantic_type=FieldSemanticType.PHONE,
        country=country,
        default_region=default_region,
    )
    r = PhoneNormalizer().normalize(value, ctx)
    return {
        "status": r.normalization_status.value,
        "display": r.display,
        "comparison": r.comparison,
        "search": r.search,
        "structured": r.structured,
        "flags": sorted(str(f.value) for f in r.flags),
        "errors": [str(e) for e in r.errors],
    }


def main() -> None:
    rows = []
    for value, country, default_region in corpus():
        rows.append(
            {
                "value": value,
                "country": country,
                "default_region": default_region,
                "out": run(value, country, default_region),
            }
        )
    OUT.write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True, indent=0) + "\n")
    with_ext = sum(1 for r in rows if r["out"]["structured"].get("extension"))  # type: ignore[index, union-attr]
    print(f"{len(rows)} cases written to {OUT.name}; {with_ext} carry an extension today")


if __name__ == "__main__":
    main()
