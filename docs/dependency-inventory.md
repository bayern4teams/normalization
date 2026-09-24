# Dependency Inventory

Status: living document, regenerated/reviewed at every milestone gate.
Last updated: M0 (2026-08-17); `cryptography` added 2026-09-15 for the
DB-clone-and-normalize feature (see `docs/adr/ADR-017-clone-normalize-engine-scope.md`) —
the rest of this table was not re-audited against the current `uv.lock`
for this pass.

Satisfies `Source.txt` §124. This is the human-readable companion to the
machine-enforced `scripts/license_policy.toml` (checked by
`scripts/check_licenses.py` in every `ci-full` and `gate` CI run). If this
table and the policy file ever disagree, the policy file is authoritative
for CI purposes and this table is out of date — treat that as a documentation
bug to fix immediately.

## Allow-list categories

- **allowed** — unrestricted use, including modification/vendoring if ever needed.
- **allowed (LGPL, unmodified/dynamic only)** — permitted strictly as an
  unmodified, dynamically-imported dependency. Never vendored or patched
  in-tree. Currently: `pycountry`, `python-stdnum`.
- **denied** — must never appear in the resolved dependency tree.
  `scripts/check_licenses.py` fails the build if one does.

## Core dependencies

| Name | Version (pinned range) | License | Source | Purpose | Transitive risk | Upgrade notes |
|---|---|---|---|---|---|---|
| PyICU | >=2.14,<3 | ICU License | [pypi.org/project/pyicu](https://pypi.org/project/pyicu/) | Unicode normalization, case mapping, script detection, SpoofChecker | Wheel availability per-platform (see `cgohlke/pyicu-build` for Windows) | ICU version bump = `env_id` change; run nightly drift job before bumping |
| ftfy | >=6.3,<7 | Apache-2.0 | [github.com/rspeer/python-ftfy](https://github.com/rspeer/python-ftfy) | Mojibake detection/repair | Low — pure Python, no native deps | Heuristic changes across versions can shift repair output; golden corpus catches this |
| charset-normalizer | >=3.4,<4 | MIT | PyPI | Encoding detection | Low | Low-risk incremental updates |
| anyascii | >=0.3.2,<1 | ISC | [github.com/anyascii/anyascii](https://github.com/anyascii/anyascii) | ASCII transliteration (Unidecode replacement) | Low | Table updates can change transliteration output; feeds `env_id` |
| regex | latest 2024.x | Apache-2.0/PSF-2.0 | PyPI | Unicode-aware regex beyond stdlib `re` | Low | — |
| nameparser | >=2.1.0,<3 | LGPL (confirmed via PyPI classifier, 2.1.0) | [nameparser.readthedocs.io](https://nameparser.readthedocs.io/en/latest/) | Person name parsing | **LGPL — unmodified, dynamic-import only** (added to `scripts/license_policy.toml`) | New locale packs / lexicon updates feed `env_id` |
| jellyfish | >=1.1,<2 | MIT | [github.com/jamesturk/jellyfish](https://github.com/jamesturk/jellyfish) | Phonetic algorithms (Soundex/NYSIIS/Metaphone/Match Rating) | Low | — |
| cleanco | >=2.3,<3 | MIT | [pypi.org/project/cleanco](https://pypi.org/project/cleanco/) | Company suffix stripping (secondary source) | Low — small, stable library | Suffix list updates rare |
| phonenumbers | >=8.13,<9 | Apache-2.0 | [github.com/daviddrysdale/python-phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) | Phone parsing/validation | Low | Metadata releases can change validity for specific numbers — feeds `env_id` |
| email-validator | >=2.2,<3 | Unlicense | [github.com/JoshData/python-email-validator](https://github.com/JoshData/python-email-validator) | Email syntax/normalization | Low | `check_deliverability=False` must be re-verified as default after every upgrade |
| dateparser | >=1.4.2,<2 | BSD-3-Clause | [github.com/scrapinghub/dateparser](https://github.com/scrapinghub/dateparser) | Multilingual date parsing | **Medium** — historically small volunteer maintainer base | Monitor via nightly drift job; no maintained fork identified as needed currently |
| edtf | >=5.0,<6 | MIT | [github.com/ixc/python-edtf](https://github.com/ixc/python-edtf) | EDTF / ISO 8601-2 dates: decades, intervals, uncertainty | **Low** — small, stable, no new transitive deps (needs only python-dateutil and pyparsing, both already present) | Keeps a decade (`1990s`) from being flattened to a year; dateparser cannot express qualified or range-valued dates |
| python-dateutil | >=2.9,<3 | Apache-2.0/BSD dual | PyPI | ISO-adjacent date parsing fallback | Low | — |
| ciso8601 | >=2.3,<3 | MIT | PyPI | Fast-path ISO 8601 parsing | Low — C extension, has wheels for all target platforms | — |
| pycountry | >=24.6,<25 | LGPL-2.1 | [github.com/flyingcircusio/pycountry](https://github.com/pycountry/pycountry) | ISO 3166/639/4217/15924 codes | **LGPL — unmodified, dynamic-import only** | Data updates (new territories, currency changes) are frequent; low code risk |
| Babel | >=2.16,<3 | BSD-3-Clause | PyPI | CLDR locale data (numeric/currency/display) | Low | CLDR data version feeds `env_id` |
| lingua-language-detector | >=1.4,<2 | Apache-2.0 | [pypi.org/project/lingua-language-detector](https://pypi.org/project/lingua-language-detector/) | Language hinting (diagnostic only) | Low | — |
| python-stdnum | >=1.20,<2 | LGPL-2.1 | [github.com/arthurdejong/python-stdnum](https://github.com/arthurdejong/python-stdnum) | Identifier/check-digit validation | **LGPL — unmodified, dynamic-import only** | New country modules or corrected algorithms feed `env_id` |
| Pint | >=0.24,<1 | BSD-3-Clause | [github.com/hgrecco/pint](https://github.com/hgrecco/pint) | Unit conversion | Low | Unit registry definitions feed `env_id` |
| RapidFuzz | >=3.10,<4 | MIT | [github.com/rapidfuzz/RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | Fuzzy matching — **analysis/offline only, never imported by `normalizers`** | Low | CI boundary check enforces the import restriction |
| google-i18n-address | >=3,<4 | BSD-3-Clause | [github.com/mirumee/google-i18n-address](https://github.com/mirumee/google-i18n-address) | Address validation/format metadata | Low — data-only package | Google's underlying metadata updates occasionally |
| polars | >=1.9,<2 | MIT | PyPI | Batch execution engine | Low | Fast-moving project; pin minor versions, re-test at each bump |
| duckdb | >=1.1,<2 | MIT | PyPI | Sidecar catalog, analytical queries | Low | — |
| pyarrow | >=17.0,<18 | Apache-2.0 | PyPI | Columnar interchange format | Low | — |
| blake3 | >=0.4,<1 | CC0-1.0/Apache-2.0 dual | PyPI | `env_id`, cache keys, trace hashes | Low | — |
| fastapi | >=0.115,<1 | MIT | PyPI | API layer | Low | — |
| sqlalchemy | >=2.0,<3 | MIT | PyPI | Metadata store ORM, connector reflection | Low | — |
| httpx | >=0.27,<1 | BSD-3-Clause | PyPI | libpostal sidecar client | Low | — |
| cryptography | >=42,<44 | Apache-2.0 OR BSD-3-Clause (dual) | [github.com/pyca/cryptography](https://github.com/pyca/cryptography) | `Fernet` symmetric encryption for saved DB-clone-and-normalize connection passwords at rest | Low — widely-used, actively maintained; ships prebuilt wheels for all target platforms | New dependency, added for the DB-clone-and-normalize feature (ADR-017); nothing in this repo did encryption before it |

## Rejected dependencies (do not (re-)add without a superseding ADR)

| Name | License | Reason | ADR |
|---|---|---|---|
| Unidecode | GPL-2.0-or-later | Copyleft risk; superseded by anyascii | ADR-015 |
| text-unidecode | Artistic License (GPL-adjacent lineage) | Same lineage concern as Unidecode; anyascii preferred | ADR-015 |
| wordfreq | MIT (license not the issue) | Sunset by author Sept 2024; data no longer trustworthy as current | ADR-015 |
| abydos | GPL-3 | Beider-Morse port is GPL-3; jellyfish covers non-GPL subset of needed algorithms | ADR-003, ADR-015 |
| Deepparse | LGPL-3 | Evaluated for ADDRESS parsing and rejected: it is a PyTorch model (~800MB of dependency, per-address inference) for a job libpostal already does in the existing sidecar, in a pipeline whose memory ceiling is a standing constraint. Reconsider only if libpostal is measurably wrong on real data AND a run can afford a model. | — |

## Container / service dependencies

| Component | Version pin | License | Purpose | Notes |
|---|---|---|---|---|
| libpostal | git ref `v1.1` (pinned in `services/libpostal/Dockerfile`) | MIT | Address parsing/expansion | Model data SHA-256 computed at image build, feeds `env_id` |
| postgres (image) | 16-alpine | PostgreSQL License | Metadata store | — |
| Node.js / npm (UI toolchain, from M7) | LTS at time of M7 | MIT (Node itself) | React + TypeScript UI build | Front-end dependency inventory tracked separately in `ui/package.json` audit, same policy applies |

## Action items tracked from this milestone

1. ~~Verify `nameparser`'s exact SPDX license classifier~~ — **done**:
   confirmed LGPL via PyPI classifier as of 2.1.0 (2026-08-07); added to
   `scripts/license_policy.toml`'s LGPL-allowed-unmodified-dynamic-only list
   alongside `pycountry` and `python-stdnum`.
2. Re-run `scripts/check_licenses.py` against the fully resolved `uv.lock`
   once M1's `uv sync` is first run in CI, to catch any transitive
   dependency license surprises not visible from direct dependencies alone.
3. Track `dateparser` maintenance health explicitly at each milestone gate
   given its history of relying on a small volunteer base.
