# Unicode / Text Normalization, Encodings, Transliteration, Scripts & String Security — Verified Resource List

**90 entries, 12 groups. Every URL HTTP-verified (200 OK) at compile time.** Single exception noted inline: MySQL's docs return 403 to command-line clients (bot wall) but the pages resolve and were content-verified via extraction.

Each entry: **name — URL — why/when it matters for a normalization engine.**

---

## 1. Core Unicode standards & annexes (13)

These are the normative ground truth. When the engine must "never guess ambiguously," the disambiguation rule is almost always written down in one of these.

1. **UAX #15: Unicode Normalization Forms** — https://www.unicode.org/reports/tr15/ — The normative definition of NFC/NFD/NFKC/NFKD, canonical ordering, and the stability guarantees your whole text layer rests on.
2. **UAX #31: Unicode Identifier and Pattern Syntax** — https://www.unicode.org/reports/tr31/ — Defines XID_Start/XID_Continue and profiles for identifiers; use it instead of hand-rolling "is this a valid name character."
3. **UTS #39: Unicode Security Mechanisms** — https://www.unicode.org/reports/tr39/ — Normative source for confusable detection, restriction levels, mixed-script detection, and Identifier_Status/Identifier_Type.
4. **UTS #46: Unicode IDNA Compatibility Processing** — https://www.unicode.org/reports/tr46/ — The mapping/validation algorithm for domain names; the reference for transitional vs. nontransitional processing decisions.
5. **UAX #29: Unicode Text Segmentation** — https://www.unicode.org/reports/tr29/ — Grapheme cluster, word, and sentence boundaries; required before any "length," "truncate," or "reverse" operation is safe.
6. **UAX #44: Unicode Character Database** — https://www.unicode.org/reports/tr44/ — Documents every UCD property, file format, and derivation rule; the spec for how to read the data files you ship.
7. **UAX #24: Unicode Script Property** — https://www.unicode.org/reports/tr24/ — Defines Script and Script_Extensions, including the Common/Inherited handling that mixed-script detection depends on.
8. **UTS #10: Unicode Collation Algorithm** — https://www.unicode.org/reports/tr10/ — Defines DUCET, collation strength levels, and why "equal under comparison" differs from "equal after normalization."
9. **UAX #9: Unicode Bidirectional Algorithm** — https://www.unicode.org/reports/tr9/ — Specifies the embedding/override/isolate controls exploited by Trojan Source; read it to know which controls to strip or reject.
10. **UTS #18: Unicode Regular Expressions** — https://www.unicode.org/reports/tr18/ — Conformance levels for `\p{...}` property matching; tells you what your regex engine must support to be correct.
11. **UTS #35: Unicode LDML** — https://www.unicode.org/reports/tr35/ — Spec behind CLDR locale data, collation tailorings, and transform rule syntax used by ICU transliterators.
12. **UTR #36: Unicode Security Considerations** — https://www.unicode.org/reports/tr36/ — The threat-model companion to UTS #39: spoofing, non-visual attacks, and encoding-level exploits explained with rationale.
13. **UTS #55: Unicode Source Code Handling** — https://www.unicode.org/reports/tr55/ — Modern guidance for tools handling source text: bidi hazards, invisible characters, normalization of identifiers.

---

## 2. UCD data files & Unicode tooling (7)

14. **UCD latest — main data directory** — https://www.unicode.org/Public/UCD/latest/ucd/ — Canonical source of UnicodeData.txt, Scripts.txt, PropList.txt, etc.; pin a version and vendor these rather than trusting a runtime.
15. **DerivedNormalizationProps.txt** — https://www.unicode.org/Public/UCD/latest/ucd/DerivedNormalizationProps.txt — Supplies NFKC_Casefold, NFKC_SCF, and the quick-check (NFC_QC/NFD_QC) properties that make fast-path normalization possible.
16. **confusables.txt (Unicode security data)** — https://www.unicode.org/Public/security/latest/confusables.txt — The actual confusable mapping table behind every skeleton/spoof check; ship it versioned so results are reproducible.
17. **intentional.txt (intentionally confusable pairs)** — https://www.unicode.org/Public/security/latest/intentional.txt — Lists pairs confusable by design (e.g. across scripts); useful to avoid over-flagging legitimate text.
18. **Unicode Utilities: Confusables tool** — https://util.unicode.org/UnicodeJsps/confusables.jsp — Interactive oracle for manually checking a string's skeleton and confusable set when debugging a false positive.
19. **unicode-org/unicodetools** — https://github.com/unicode-org/unicodetools — The reference implementation that generates UCD and security data; consult it when a derivation is ambiguous.
20. **Unicode FAQ — Security Issues** — https://www.unicode.org/faq/security.html — Short, practical answers to the recurring spoofing/normalization security questions, with pointers into the specs.

---

## 3. CLDR, ICU4C & ICU4X (10)

21. **Unicode CLDR project** — https://cldr.unicode.org/ — Locale data (collation tailorings, casing exceptions, transliteration rules) that drive locale-sensitive normalization behavior.
22. **unicode-org/icu (source repository)** — https://github.com/unicode-org/icu — Authoritative ICU4C/ICU4J source; read it when PyICU behavior surprises you and the docs are silent.
23. **ICU User Guide — Normalization** — https://unicode-org.github.io/icu/userguide/transforms/normalization/ — Explains Normalizer2 modes (NFC, NFKC, NFKC_Casefold, FCD) and how to compose custom normalizers.
24. **ICU User Guide — Transforms / Transliteration** — https://unicode-org.github.io/icu/userguide/transforms/general/ — How to build transform chains like `NFD; [:Nonspacing Mark:] Remove; NFC` — the correct way to strip diacritics.
25. **ICU User Guide — Boundary Analysis** — https://unicode-org.github.io/icu/userguide/boundaryanalysis/ — BreakIterator semantics for grapheme/word/line breaks, including dictionary-based breaking for Thai/Khmer/CJK.
26. **ICU4C API: icu::Normalizer2** — https://unicode-org.github.io/icu-docs/apidoc/dev/icu4c/classicu_1_1Normalizer2.html — Exact API contract for `getNFCInstance`, `getNFKCCasefoldInstance`, `quickCheck`, `isNormalized`, `spanQuickCheckYes`.
27. **ICU4C API: icu::Transliterator** — https://unicode-org.github.io/icu-docs/apidoc/dev/icu4c/classicu_1_1Transliterator.html — Reference for rule-based transliteration, including `Any-Latin` and script-to-script IDs.
28. **ICU4C API: uspoof.h (SpoofChecker)** — https://unicode-org.github.io/icu-docs/apidoc/dev/icu4c/uspoof_8h.html — Full SpoofChecker surface: restriction levels, `getSkeleton`, `areConfusable`, allowed-character sets — the production-grade UTS #39 implementation.
29. **ICU4C API: uidna.h (IDNA/UTS #46)** — https://unicode-org.github.io/icu-docs/apidoc/dev/icu4c/uidna_8h.html — The UTS #46 implementation with per-label error bits; prefer it over ad-hoc IDNA handling.
30. **ICU4X** — https://icu4x.unicode.org/ — Modular, no-std Unicode library; a useful cross-check implementation and a reference for data-slicing strategies.

---

## 4. Python stdlib & Python Unicode bindings (7)

31. **Python `unicodedata`** — https://docs.python.org/3/library/unicodedata.html — Stdlib baseline: `normalize`, `combining`, `category`, `is_normalized`; note it tracks the Python build's Unicode version, not the latest.
32. **`unicodedata2`** — https://pypi.org/project/unicodedata2/ — Drop-in backport tracking newer Unicode versions; use when stdlib lags and property results must match your shipped UCD.
33. **Python `stringprep`** — https://docs.python.org/3/library/stringprep.html — Stdlib RFC 3454 tables; legacy but required if you must interoperate with SASLprep/Nameprep systems.
34. **Python `codecs`** — https://docs.python.org/3/library/codecs.html — Codec registry, error handlers (`surrogateescape`, `replace`), and BOM handling — the foundation of lossless decode/re-encode paths.
35. **Python `str.casefold`** — https://docs.python.org/3/library/stdtypes.html#str.casefold — Caseless-matching primitive; documents why `casefold()` ≠ `lower()` and where full case folding applies.
36. **PyICU (PyPI)** — https://pypi.org/project/PyICU/ — Python bindings exposing Normalizer2, Transliterator, SpoofChecker, BreakIterator — the main route to ICU-grade correctness from Python.
37. **ovalhub/pyicu (source)** — https://github.com/ovalhub/pyicu — Build instructions and wrapper-level details needed to diagnose ICU-version mismatches at runtime.

---

## 5. Mojibake repair & encoding detection (7)

38. **ftfy documentation** — https://ftfy.readthedocs.io/en/latest/ — The reference tool for repairing mojibake, mis-decoded UTF-8, and HTML entity soup; its `explain` mode shows the exact fix chain.
39. **rspeer/python-ftfy** — https://github.com/rspeer/python-ftfy — Source and heuristics; read it to decide which ftfy fixers are safe to enable in a never-guess pipeline.
40. **chardet** — https://pypi.org/project/chardet/ — Classic Mozilla-derived encoding detector; useful as a second opinion but returns confidences, so gate it behind a threshold.
41. **charset-normalizer (PyPI)** — https://pypi.org/project/charset-normalizer/ — Modern pure-Python detector using normalization-aware heuristics; the `requests` ecosystem default.
42. **jawah/charset_normalizer (source)** — https://github.com/jawah/charset_normalizer — Explains its mess/coherence scoring, which you need to understand before trusting a detection result.
43. **faust-cchardet** — https://pypi.org/project/faust-cchardet/ — Maintained C-backed (uchardet) binding; the fast path when detecting encodings over large corpora (original `cchardet` is unmaintained).
44. **WHATWG Encoding Standard** — https://encoding.spec.whatwg.org/ — Defines the web's authoritative label→encoding mapping and the `replacement` encoding; the rule set for "what does this charset label actually mean."

---

## 6. Transliteration & ASCII folding (4)

45. **Unidecode** — https://pypi.org/project/Unidecode/ — Widely used lossy Unicode→ASCII transliteration; good for slugs/search keys, never for round-tripping.
46. **text-unidecode** — https://pypi.org/project/text-unidecode/ — Permissively licensed alternative when Unidecode's GPL is a problem.
47. **AnyAscii** — https://anyascii.com/ — Broader script coverage than Unidecode with consistent cross-language implementations; useful when your engine must match a non-Python service.
48. **unihandecode** — https://github.com/miurahr/unihandecode — Language-aware CJK transliteration (ja/ko/zh differ for the same Han character); use when a single Unidecode table would guess wrong.

---

## 7. Segmentation, regex & property matching (4)

49. **`regex` module** — https://pypi.org/project/regex/ — Provides `\p{Script=...}`, `\X` grapheme matching, and full case folding that stdlib `re` lacks; effectively required for UTS #18 work.
50. **uniseg** — https://pypi.org/project/uniseg/ — Pure-Python UAX #29 grapheme/word/sentence and UAX #14 line breaking; a dependency-free fallback when ICU isn't available.
51. **grapheme** — https://pypi.org/project/grapheme/ — Minimal grapheme-cluster API (`length`, `slice`, `graphemes`) for safe user-visible string handling.
52. **emoji** — https://pypi.org/project/emoji/ — Emoji sequence data (ZWJ sequences, skin-tone modifiers) so normalization doesn't shatter multi-codepoint emoji.

---

## 8. Confusables, homoglyphs, bidi & IDNA libraries (5)

53. **confusable_homoglyphs** — https://pypi.org/project/confusable-homoglyphs/ — Pure-Python confusable/mixed-script checks derived from Unicode data; a lightweight alternative when PyICU is too heavy.
54. **homoglyphs** — https://pypi.org/project/homoglyphs/ — Generates homoglyph variants and infers candidate languages/scripts; handy for building spoof test corpora.
55. **python-bidi** — https://pypi.org/project/python-bidi/ — UAX #9 implementation for reordering and reasoning about bidi text and its control characters.
56. **kjd/idna (source)** — https://github.com/kjd/idna — IDNA 2008 + UTS #46 for Python; documents the strictness differences that cause domains to validate in one library and fail in another.
57. **idna (PyPI)** — https://pypi.org/project/idna/ — Release/install surface for the above; pin it, since IDNA tables shift with Unicode versions.

---

## 9. IETF specs: PRECIS, stringprep, IDNA, punycode (8)

58. **RFC 8264 — PRECIS Framework** — https://www.rfc-editor.org/rfc/rfc8264.html — The modern replacement for stringprep: IdentifierClass/FreeformClass and the width-mapping/casefolding/normalization rule order.
59. **RFC 8265 — PRECIS for usernames & passwords** — https://www.rfc-editor.org/rfc/rfc8265.html — Exact profiles for comparing usernames and preparing passwords; the spec to implement for auth-adjacent normalization.
60. **RFC 8266 — PRECIS for nicknames** — https://www.rfc-editor.org/rfc/rfc8266.html — Display-name profile allowing spaces while still normalizing for comparison.
61. **RFC 3454 — Stringprep** — https://www.rfc-editor.org/rfc/rfc3454.html — The obsolete-but-still-deployed framework; needed to interoperate with legacy SASL/LDAP/XMPP systems.
62. **RFC 4013 — SASLprep** — https://www.rfc-editor.org/rfc/rfc4013.html — The stringprep profile still referenced by SCRAM and many databases; note it's frozen at Unicode 3.2.
63. **RFC 3492 — Punycode** — https://www.rfc-editor.org/rfc/rfc3492.html — The Bootstring encoding for IDNA; implement or verify against it when handling `xn--` labels.
64. **RFC 5890 — IDNA 2008 definitions & framework** — https://www.rfc-editor.org/rfc/rfc5890.html — Terminology (A-label/U-label) that prevents category errors in domain normalization code.
65. **RFC 5892 — IDNA code points** — https://www.rfc-editor.org/rfc/rfc5892.html — Derived property rules (PVALID/DISALLOWED/CONTEXTJ/CONTEXTO) including ZWJ/ZWNJ contextual rules.

---

## 10. Language & script detection (10)

66. **fastText language identification (lid.176)** — https://fasttext.cc/docs/en/language-identification.html — 176-language classifier; fast and accurate on sentence-length text, weak on very short strings.
67. **fasttext-langdetect** — https://pypi.org/project/fasttext-langdetect/ — Convenient Python wrapper handling model download/caching for lid.176.
68. **GlotLID** — https://github.com/cisnlp/GlotLID — LID covering 1600+ languages including low-resource ones; the best option when detection must not collapse to majority languages.
69. **GlotLID paper (EMNLP 2023 Findings)** — https://aclanthology.org/2023.findings-emnlp.410/ — Documents the label set, contamination issues, and evaluation — read before trusting any LID confidence score.
70. **lingua-language-detector** — https://pypi.org/project/lingua-language-detector/ — Rule+statistical detector with explicit confidence values and strong short-text accuracy.
71. **pemistahl/lingua-py (source)** — https://github.com/pemistahl/lingua-py — Accuracy benchmarks against langdetect/langid/CLD; useful for justifying a detector choice.
72. **langdetect** — https://pypi.org/project/langdetect/ — Port of Nakagawa's language-detection; widely used, nondeterministic unless you seed it — a classic source of "ambiguous guessing."
73. **langid.py** — https://github.com/saffsd/langid.py — Self-contained 97-language detector needing no training data; good offline baseline.
74. **pycld3** — https://pypi.org/project/pycld3/ — Python bindings for Google's neural CLD3; strong on short text, but the project is in maintenance mode.
75. **CLD2** — https://github.com/CLD2Owners/cld2 — Chrome's original Naive-Bayes detector; still notable for returning multiple languages with byte percentages on mixed documents.
76. **whatlang-rs** — https://github.com/greyblake/whatlang-rs — Rust detector that reports both language and script; a useful reference for script-first detection design.

---

## 11. Papers, essays & foundational reading (7)

77. **Trojan Source: Invisible Vulnerabilities (arXiv)** — https://arxiv.org/abs/2111.00169 — Boucher & Anderson's paper on bidi-override and homoglyph attacks on source code; the canonical justification for rejecting bidi controls.
78. **Trojan Source project site** — https://trojansource.codes/ — Proof-of-concept exploits per language plus vendor responses; an excellent test corpus for your control-character policy.
79. **The Absolute Minimum Every Developer Must Know About Unicode (Spolsky, 2003)** — https://www.joelonsoftware.com/2003/10/08/the-absolute-minimum-every-software-developer-absolutely-positively-must-know-about-unicode-and-character-sets-no-excuses/ — The origin text on "there is no plain text".
80. **The Absolute Minimum … in 2023 (Nikita Prokopov / tonsky)** — https://tonsky.me/blog/unicode/ — The modern update: grapheme clusters, extended grapheme boundaries, and why code-point counting is wrong.
81. **Let's Stop Ascribing Meaning to Code Points (Goregaokar)** — https://manishearth.github.io/blog/2017/01/14/stop-ascribing-meaning-to-unicode-code-points/ — Argues code points are not characters; directly shapes API design for length/indexing in a text layer.
82. **Breaking Our Latin-1 Assumptions (Goregaokar)** — https://manishearth.github.io/blog/2017/01/15/breaking-our-latin-1-assumptions/ — Concrete counterexamples (Hangul, Devanagari, Arabic) that break naive casing/diacritic logic.
83. **UTF-8 Everywhere** — https://utf8everywhere.org/ — Manifesto for UTF-8 as the single internal encoding; the architectural argument for normalizing at the boundary and never storing alternatives.

---

## 12. Normalization in databases & query engines (7 + bonus)

84. **PostgreSQL `unaccent`** — https://www.postgresql.org/docs/current/unaccent.html — Diacritic-removing dictionary; know that it's rule-table-driven and not equivalent to NFD+mark-stripping.
85. **PostgreSQL `citext`** — https://www.postgresql.org/docs/current/citext.html — Case-insensitive text type whose folding depends on the database collation — a classic source of cross-environment mismatches.
86. **PostgreSQL Collation Support** — https://www.postgresql.org/docs/current/collation.html — Explains libc vs. ICU providers and deterministic vs. nondeterministic collations, where `=` stops meaning byte equality.
87. **PostgreSQL `CREATE COLLATION`** — https://www.postgresql.org/docs/current/sql-createcollation.html — Syntax for ICU locales and `deterministic = false`, enabling DB-side case/accent-insensitive comparison.
88. **ICU features in PostgreSQL 15 (Eisentraut)** — https://peter.eisentraut.org/blog/2022/09/26/icu-features-in-postgresql-15 — From the implementer: what ICU collations changed and the upgrade hazards for indexes.
89. **How collation works (Eisentraut)** — https://peter.eisentraut.org/blog/2023/03/14/how-collation-works — Clear explanation of collation versioning and why a library upgrade can silently corrupt indexes.
90. **MySQL Unicode character sets & collations** — https://dev.mysql.com/doc/refman/8.4/en/charset-unicode-sets.html — utf8mb4 collation semantics (`_ai_ci`, `_as_cs`, UCA versions). *(Page live and content-verified; dev.mysql.com returns 403 to CLI clients.)*

**Bonus:** **ClickHouse string functions** — https://clickhouse.com/docs/sql-reference/functions/string-functions — Documents `normalizeUTF8NFC/NFD/NFKC/NFKD` and case functions, letting you push normalization into the query engine and verify parity with your Python layer.

---

## Notes on use

- **Pin your Unicode version.** Entries 14–17 change between Unicode releases; normalization and confusable results are only reproducible if the UCD version is fixed and recorded alongside outputs.
- **Prefer ICU for security decisions.** For confusables and IDNA (entries 28–29), the pure-Python alternatives (53–54) are convenient but lag the spec; use them for pre-filtering, not for final verdicts.
- **Detection is probabilistic; normalization should not be.** Every resource in group 10 returns confidences. For a "never guess ambiguously" engine, treat LID output as advisory metadata and require an explicit threshold plus a fallback-to-undetermined path.
- **Normalization order matters.** UTS #46 (4), RFC 8264 (58), and UAX #15 (1) each specify a *sequence* of mapping → normalization → validation. Applying the same operations in a different order produces different results and is a common interoperability bug.
