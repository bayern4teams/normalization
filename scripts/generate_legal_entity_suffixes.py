"""Regenerate the legal-entity-suffix dictionary from GLEIF's ISO 20275
Entity Legal Forms code list.

    python scripts/generate_legal_entity_suffixes.py path/to/elf-code-list.csv

The shipped dictionary was a 40-entry hand-curated seed whose own source
note said so: "NOT the full 3,400+ entry GLEIF dataset (no network access
to GLEIF's published list was available in this environment); expanding
to the full official list is tracked as a follow-up". Its `elf_code`
values were placeholders (XXX1, XX10) rather than real ELF codes.

The curated seed is overlaid ON TOP of the generated entries, so its
human-readable `organization_type` labels and its canonical spellings
win wherever the two overlap. GLEIF is purely additive here.

Three rules keep the generated half safe for a trailing-suffix matcher:

- Single-character abbreviations are dropped. "A" is a real ELF
  abbreviation, and stripping it would turn "Company A" into "Company".
- Keys are normalized exactly the way `company._normalize_suffix_key`
  normalizes a candidate (dots stripped, casefolded, single-spaced), or
  they could never match. This is what makes "S.A." resolve at all.
- An abbreviation used by more than one ELF code (203 of them: "AG",
  "AS", "SA" and friends are legal forms in many countries) keeps its
  canonical spelling, so the suffix is still stripped, but reports NO
  elf_code and NO jurisdiction — the same "never guess" rule the country
  resolver follows.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_OUT_DIR = _ROOT / "data/dictionaries/legal-entity-suffixes.common"
_SEED = _OUT_DIR / "2026.08.json"
_VERSION = "2026.09"

# company._MAX_SUFFIX_TOKENS — a longer key can never be matched.
_MAX_SUFFIX_TOKENS = 4
_MIN_ABBREVIATION_LENGTH = 2


def _key(text: str) -> str | None:
    """Mirror of company._normalize_suffix_key applied to a whole string."""
    tokens = [t.strip(".").casefold() for t in text.split()]
    tokens = [t for t in tokens if t]
    if not tokens or len(tokens) > _MAX_SUFFIX_TOKENS:
        return None
    return " ".join(tokens)


def build(csv_path: Path) -> tuple[dict[str, dict[str, object]], dict[tuple[str, str], str]]:
    with csv_path.open(encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if r["ELF Status ACTV/INAC"] == "ACTV"]

    # key -> {(elf_code, country)}, to detect the ambiguous ones.
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)
    canonical: dict[str, str] = {}
    local_name: dict[str, str] = {}

    for row in rows:
        elf = row["ELF Code"].strip()
        country = row["Country Code (ISO 3166-1)"].strip()
        name = row["Entity Legal Form name Local name"].strip()
        candidates = [
            value.strip()
            for field in (
                "Abbreviations Local language",
                "Abbreviations transliterated",
                "Entity Legal Form name Local name",
                "Entity Legal Form name Transliterated name (per ISO 01-140-10)",
            )
            for value in row[field].split(";")
            if value.strip()
        ]
        for candidate in candidates:
            if len(candidate.strip(".")) < _MIN_ABBREVIATION_LENGTH:
                continue
            key = _key(candidate)
            if key is None:
                continue
            seen[key].add((elf, country))
            canonical.setdefault(key, candidate.strip())
            local_name.setdefault(key, name)

    # (key, country) -> ELF code, but ONLY where that pair names exactly
    # one form. An abbreviation ambiguous on its own ("Inc" is used in
    # several countries) can become unambiguous once a jurisdiction is
    # known — but "Ltd" in GB is still several distinct ELF codes
    # (limited by shares, limited by guarantee, ...), and picking one of
    # those is a guess, not a resolution.
    by_country_codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key, pairs in seen.items():
        for elf, country in pairs:
            if country:
                by_country_codes[(key, country)].add(elf)
    by_country = {
        pair: next(iter(codes)) for pair, codes in by_country_codes.items() if len(codes) == 1
    }

    entries: dict[str, dict[str, object]] = {}
    for key, pairs in sorted(seen.items()):
        codes = {elf for elf, _ in pairs}
        countries = {country for _, country in pairs if country}
        unambiguous = len(codes) == 1
        entries[key] = {
            "canonical": canonical[key],
            "elf_code": next(iter(codes)) if unambiguous else None,
            "jurisdiction_hint": (
                next(iter(countries)) if unambiguous and len(countries) == 1 else None
            ),
            "organization_type": local_name[key] if unambiguous else None,
        }
    return entries, by_country


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    generated, by_country = build(Path(sys.argv[1]))
    seed = json.loads(_SEED.read_text(encoding="utf-8"))
    # Field-level merge, not whole-entry. The seed's human-readable
    # `organization_type` and canonical spellings are better than what can
    # be derived from GLEIF, but its `elf_code` values are PLACEHOLDERS
    # ("XXX1", "XX10") invented before the real list was reachable —
    # keeping those would defeat the point of fetching it.
    merged = dict(generated)
    for key, curated in seed["entries"].items():
        official = generated.get(key, {})
        entry = dict(curated)
        jurisdiction = curated.get("jurisdiction_hint")
        scoped = by_country.get((key, jurisdiction)) if jurisdiction else None
        if official.get("elf_code"):
            entry["elf_code"] = official["elf_code"]
            entry["jurisdiction_hint"] = official.get("jurisdiction_hint")
        elif scoped:
            # Ambiguous on its own, resolved by the seed's jurisdiction.
            entry["elf_code"] = scoped
        elif str(entry.get("elf_code", "")).startswith("XX"):
            # No official code for this spelling: report none rather than
            # a placeholder that looks like an ELF code and is not one.
            entry["elf_code"] = None
        merged[key] = entry

    out = _OUT_DIR / f"{_VERSION}.json"
    out.write_text(
        json.dumps(
            {
                "id": "legal-entity-suffixes.common",
                "version": _VERSION,
                "locale": "mul",
                "source": (
                    "GLEIF ISO 20275 Entity Legal Forms code list v1.6 (2026-02-19), "
                    "ACTV entries only, merged with the M3 curated seed which takes "
                    "precedence. Regenerate with scripts/generate_legal_entity_suffixes.py."
                ),
                "license": "CC0-1.0 (GLEIF publishes the ELF code list for free reuse)",
                "created_at": f"{dt.datetime.now(tz=dt.UTC).date().isoformat()}T00:00:00Z",
                "entries": dict(sorted(merged.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {out}: {len(merged)} entries "
        f"({len(generated)} from GLEIF, {len(seed['entries'])} curated)"
    )


if __name__ == "__main__":
    main()
