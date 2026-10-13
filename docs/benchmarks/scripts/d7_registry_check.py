"""LOCAL_VERIFY D7: no number taken from a national register may come back INVALID as TAX_ID.

Every value comes from the register itself (Norway Enhetsregisteret, France SIRENE), so each is
registry-valid by construction. The app's verdict (dispatcher, TAX_ID, country context) is
cross-tabulated against python-stdnum's own validators, which do not go through the app.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import psycopg
from normapi.app import build_dispatcher
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from stdnum.fr import siren, tva
from stdnum.no import mva, orgnr

SOURCES = {
    "NO": (
        "ref_norway",
        'SELECT "organisasjonsnummer" FROM enheter',
        {"no.orgnr": orgnr, "no.mva": mva},
    ),
    "FR": ("ref_france", 'SELECT "siren" FROM unite_legale', {"fr.siren": siren, "fr.tva": tva}),
}


def main() -> None:
    dispatcher = build_dispatcher(env_id="bench-d7")
    report = {}
    for country, (db, sql, validators) in SOURCES.items():
        with psycopg.connect(f"postgresql://source_admin:source_admin@localhost:5436/{db}") as c:
            numbers = [r[0] for r in c.execute(sql)]
        ctx = NormalizationContext(
            field_name="tax_id", semantic_type=FieldSemanticType.TAX_ID, country=country
        )
        verdicts: Counter[str] = Counter()
        cross: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        invalid_examples: list[str] = []
        for n in numbers:
            r = dispatcher.normalize(n, FieldSemanticType.TAX_ID, ctx, SCAFFOLD_PROFILE)
            v = f"{r.normalization_status.value}/{r.validation_status}"
            verdicts[v] += 1
            ok = ",".join(k for k, mod in validators.items() if mod.is_valid(n)) or "none"
            cross[f"app={v} | stdnum valid: {ok}"] += 1
            if r.validation_status == "INVALID" or r.normalization_status.value == "INVALID":
                if len(invalid_examples) < 10:
                    invalid_examples.append(n)
                for w in (r.warnings or [])[:1]:
                    reasons[str(w)[:120]] += 1
        report[country] = {
            "numbers": len(numbers),
            "distinct": len(set(numbers)),
            "app_verdicts": dict(verdicts),
            "cross_tab": dict(cross),
            "invalid_examples": invalid_examples,
            "invalid_reasons": dict(reasons.most_common(5)),
        }
        print(country, json.dumps(report[country], indent=1), flush=True)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
