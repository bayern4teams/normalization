"""Planted ground truth for D11 (phonetics that fit the data). Independent of the
implementation and of every repo test: nothing here imports a normalizer.

Sources, so nothing is tuned to the code under test:

* RUSSIAN_TABLE: Cyrillic given names transliterated by the `iuliia` package
  (MIT, v0.13.0, 20 published schemes) with the ASCII-only schemes BGN_PCGN,
  ICAO_DOC_9303, MVD_782, WIKIPEDIA, YANDEX_MAPS, TELEGRAM, MOSMETRO,
  GOST_779_ALT, ALA_LC_ALT, MVD_310, GOST_52535 and GOST_52290. Every value of a
  row is one real person's name spelled by a published scheme, so every pair in a
  row is a same-name pair. Generated with:
      for s in SCHEMES: iuliia.translate(name, schema=getattr(iuliia, s))
  (iuliia is not a repo dependency: the output is pasted here once, deduplicated.)
* ARABIC_GROUPS: human-asserted spellings of Arabic/Persian-origin names; the
  Latin variants are those listed in the "Name variants" sections of the
  Wikipedia articles "Muhammad (name)", "Hussein", "Ahmad (name)", "Omar",
  "Fatima (name)", "Ali (name)" and the Cyrillic forms are those article titles
  on ru.wikipedia. Arabic and Persian script forms are the names' own spelling.
  No repo test is a source.
* DIFFERENT_NAME_PAIRS: different consonant skeletons, so no reasonable phonetic
  key may be shared. Real homophones (Robert/Rupert) are deliberately absent.
* Scripts the plan says are not Latin: CJK (polyphonic, no key at all), plus
  Greek, Hebrew, Devanagari, Thai (no Anglo-centric key; no key at all either,
  because the plan only names Latin, Cyrillic and Arabic/Persian for keys).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

LEGACY_KEYS: Final = ("soundex", "nysiis", "metaphone", "match_rating_codex")
NEW_KEYS: Final = ("double_metaphone", "beider_morse")

RUSSIAN_TABLE: Final[dict[str, tuple[str, ...]]] = {
    "Юрий": ("Yuriy", "Iurii", "Yury", "Yurij"),
    "Александр": ("Aleksandr",),
    "Елена": ("Yelena", "Elena"),
    "Сергей": ("Sergey", "Sergei", "Sergej"),
    "Дмитрий": ("Dmitriy", "Dmitrii", "Dmitry", "Dmitrij"),
    "Михаил": ("Mikhail", "Mihail", "Mixail"),
    "Анастасия": ("Anastasiya", "Anastasiia"),
    "Владимир": ("Vladimir",),
    "Ольга": ("Olga", "Ol'ga", "Ol`ga"),
    "Наталья": ("Natalia", "Natal'ya", "Natalya", "Natal`ya", "Natal'ia"),
    "Татьяна": ("Tatiana", "Tat'yana", "Tatyana", "Tat`yana", "Tat'iana"),
    "Григорий": ("Grigoriy", "Grigorii", "Grigory", "Grigorij"),
    "Евгений": ("Yevgeniy", "Evgenii", "Evgeniy", "Yevgeny", "Evgeny", "Evgenij"),
    "Мария": ("Mariya", "Mariia"),
    "Андрей": ("Andrey", "Andrei", "Andrej"),
}

# (group id, ((spelling, script), ...)). Human-asserted, see module docstring.
ARABIC_GROUPS: Final[tuple[tuple[str, tuple[tuple[str, str], ...]], ...]] = (
    (
        "muhammad",
        (
            ("Мухаммед", "Cyrillic"),
            ("محمد", "Arabic"),
            ("Muhammad", "Latin"),
            ("Mohammed", "Latin"),
            ("Mohammad", "Latin"),
            ("Mohamed", "Latin"),
            ("Muhammed", "Latin"),
        ),
    ),
    (
        "hussein",
        (
            ("Хусейн", "Cyrillic"),
            ("حسین", "Arabic"),
            ("Hussein", "Latin"),
            ("Hossein", "Latin"),
            ("Husayn", "Latin"),
            ("Husain", "Latin"),
        ),
    ),
    (
        "ahmad",
        (
            ("Ахмед", "Cyrillic"),
            ("أحمد", "Arabic"),
            ("Ahmad", "Latin"),
            ("Ahmed", "Latin"),
        ),
    ),
    (
        "omar",
        (
            ("Омар", "Cyrillic"),
            ("عمر", "Arabic"),
            ("Omar", "Latin"),
            ("Umar", "Latin"),
        ),
    ),
    (
        "fatima",
        (
            ("Фатима", "Cyrillic"),
            ("فاطمه", "Arabic"),
            ("Fatima", "Latin"),
            ("Fatimah", "Latin"),
        ),
    ),
)

# The pairs Phase 0 recorded as "no shared key today" (PHASE0_REPORT section 4).
MUST_FIX_PAIRS: Final = (
    ("Мухаммед", "Muhammad"),
    ("Мухаммед", "Mohammed"),
    ("Мухаммед", "Mohammad"),
    ("Мухаммед", "محمد"),
    ("Елена", "Yelena"),
)


@dataclass(frozen=True)
class Pair:
    group: str
    a: str
    b: str
    a_script: str
    b_script: str


def same_name_pairs() -> list[Pair]:
    """Every distinct-text pair inside one group. Latin-only scheme variants
    (Yuriy/Yury) are included: they are the same name by construction."""
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    for cyr, latin in RUSSIAN_TABLE.items():
        groups.append((cyr, [(cyr, "Cyrillic"), *((x, "Latin") for x in latin)]))
    for gid, spellings in ARABIC_GROUPS:
        groups.append((gid, list(spellings)))
    out: list[Pair] = []
    for gid, members in groups:
        for i, (a, sa) in enumerate(members):
            for b, sb in members[i + 1 :]:
                if a != b:
                    out.append(Pair(gid, a, b, sa, sb))
    return out


DIFFERENT_NAME_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("Muhammad", "Yuri"),
    ("Мухаммед", "Юрий"),
    ("محمد", "Юрий"),
    ("Мухаммед", "Yuri"),
    ("محمد", "Yuri"),
    ("Alexander", "Hossein"),
    ("Александр", "Hossein"),
    ("Елена", "Muhammad"),
    ("حسین", "Alexander"),
    ("Mohammad", "Olga"),
    ("Sergey", "Fatima"),
    ("Сергей", "Fatima"),
    ("Владимир", "Omar"),
    ("Vladimir", "عمر"),
    ("Дмитрий", "Ahmad"),
    ("Dmitri", "أحمد"),
    ("Татьяна", "Hussein"),
    ("Tatiana", "حسین"),
    ("Григорий", "Mariya"),
    ("Андрей", "Natalya"),
    ("Anastasia", "Evgeny"),
    ("Mikhail", "Olga"),
)

# Non-Latin scripts: input -> accepted script labels (case-insensitive, either the
# ISO 15924 long name or its 4-letter code).
CJK_NAMES: Final = ("王小明", "山田太郎", "单田芳", "乐嘉", "김민준", "田中 太郎")
OTHER_NON_LATIN: Final = (
    ("Γιώργος", ("greek", "grek")),
    ("משה", ("hebrew", "hebr")),
    ("राजेश", ("devanagari", "deva")),
    ("สมชาย", ("thai",)),
)
SCRIPT_LABELS: Final[dict[str, tuple[str, ...]]] = {
    "Cyrillic": ("cyrillic", "cyrl"),
    "Arabic": ("arabic", "arab"),
    "Han": ("han", "hani", "cjk"),
    "Hangul": ("hangul", "hang"),
}
HAN_NAMES: Final = ("王小明", "山田太郎", "单田芳", "乐嘉", "田中 太郎")
HANGUL_NAMES: Final = ("김민준",)

# Strings that identify these fixtures; a production-source grep must find none.
FIXTURE_LITERALS: Final = tuple(
    sorted(
        {
            *RUSSIAN_TABLE,
            *(v for vs in RUSSIAN_TABLE.values() for v in vs),
            *(s for _, g in ARABIC_GROUPS for s, _ in g),
            *CJK_NAMES,
            *(n for n, _ in OTHER_NON_LATIN),
        }
    )
)
