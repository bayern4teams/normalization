# Verified Resources — Language Normalization Idempotency: Code vs Display Name

**Scope:** for the LANGUAGE normalizer defect pinned by `tests/property/test_idempotency_determinism.py::test_language_ga_script_input_converges_in_one_pass`: `normalize('กา')` gives display `Ga`, and `normalize('Ga')` gives `Irish`. Covers how standards and libraries separate a language code from a display name, what they do when a name collides with a code, and idempotence of normalization as a property.

**Verification:** 45 entries. Every URL below was fetched in this session and resolved to the stated resource; content claims come from the fetched page text (page text was truncated for the very long RFC, IANA, UTS #35, ECMA-402 and FHIR pages, so claims about them are limited to the part read). 0 entries bot-walled (403); 0 dropped as unconfirmed except two that failed to fetch (Hypothesis ghostwriter page, empty body; Babel GitHub README, no useful content) and were left out. Code diagnosis and collision counts are computed from the repo, read-only, on branch `docs/improvement-round-2`.

---

## Diagnosis (from the code)

1. **What a LANGUAGE value holds.** `packages/normalizers/src/normalizers/language.py::LanguageNormalizer.normalize` returns `display = language.name` (the pycountry English name, e.g. `Irish`) and `comparison = search = canonical_code` (ISO 639-1 `alpha_2` if present, else `alpha_3`, e.g. `ga`, `gaa`). `structured` carries `canonical_code`, `language_name`, `source_value`. So display is the English NAME and the canonical form is the CODE.
2. **Lookup order** in `language.py::_resolve_language`: (a) a 2-letter input is tried as `alpha_2` first; (b) a 3-letter input as `alpha_3`; (c) `pycountry.languages.lookup()` (code-or-name); (d) the deprecated-subtag map `_LANGUAGE_ALIASES` (Babel `language_aliases`); (e) `CLDR_LANGUAGE_NAMES` (endonyms and translated names). The docstring says code-first order was chosen on purpose: `lookup("en")` otherwise returns the obscure language named "En" (`enc`).
3. **Why `กา` becomes `Ga`.** pycountry does not know it. Step (e) finds it: `normalizers/_cldr_language_names.py::CLDR_LANGUAGE_NAMES['กา'] == 'gaa'` (the Thai-script CLDR name of the Gã language of Ghana). `gaa` is looked up with `get(alpha_3='gaa')`. That entry has no `alpha_2`, so `canonical_code = 'gaa'` and `display = language.name = 'Ga'`.
4. **Why `Ga` is then a code.** `Ga` has length 2, so step (a) runs `get(alpha_2='ga')` which is Irish. The code branch wins before any name lookup. Result: `display='Irish'`, `comparison='ga'`.
5. **The generator guard does not cover this.** `scripts/generate_cldr_names.py::_is_too_short_to_be_a_name` drops 1- and 2-letter Latin keys from the CLDR table, so CLDR names cannot shadow a 639-1 code. It does not apply to the display value taken from pycountry: pycountry itself names `gaa` as `Ga`.
6. **The fixed point exists for the code, not the display.** Re-normalizing `comparison` is stable for all 7,910 pycountry languages (0 changes, computed below). Re-normalizing `display` is not. The test asserts on `display`.
7. **Other types.** `packages/normalizers/src/normalizers/country.py::CountryNormalizer.normalize` has the same shape (`display = country.name`, `comparison = country.alpha_2`). Computed: all 249 pycountry countries are stable when `display` is fed back, and no ISO 3166 country name is 3 letters or shorter. Same pattern, no collision in the data today. Not checked: CURRENCY and other code-based types.
8. **Second, related defect (found while computing).** `language.py::_split_language_tag` treats any value containing `-` or `_` as a BCP 47 tag and keeps only the first piece. A hyphenated NAME is therefore cut: `Alumu-Tesu` is INVALID, `Judeo-Arabic` is INVALID, `Kuku-Yalanji` resolves to `ukv` (display `Kuku`). Not the `Ga` bug, but it also breaks display re-normalization.
9. **Not checked:** whether any production path feeds a stored `display` back into the normalizer (the property test does it on purpose; the dispatcher path was not traced). `graphify`, `graft` and codebase-memory were not needed; files were read directly.

## Collision examples (computed)

Commands (read-only, `ulimit -v 8000000`, `uv run python`; probe scripts are in the session scratchpad, `probe.py` and `probe2.py`, not in the repo):

```
cd /home/bayern/Projects/normalization && uv run python <probe2.py>
  # for each of the 7,910 pycountry languages:
  #   r  = LanguageNormalizer().normalize(alpha_2 or alpha_3)
  #   r2 = LanguageNormalizer().normalize(r.display)
  #   compare r2.comparison with r.comparison
  # same for 249 countries via CountryNormalizer
```

Results:

- 7,910 languages resolved by code. Feeding `comparison` back: **0** changes. Feeding `display` back: **440** change (5.6%).
  - **208** resolve to a different language. **232** become INVALID (the hyphen defect, item 8 above; 384 pycountry names contain `-`).
  - Of the 208, 134 have a display of 3 letters or fewer, a code shape.
- **13** languages have a pycountry name that is another language's ISO 639-1 code. `code -> display -> re-normalize`:
  `gaa Ga -> ga (Irish)`; `enc En -> en (English)`; `fuj Ko -> ko (Korean)`; `haq Ha -> ha (Hausa)`; `huo Hu -> hu (Hungarian)`; `sax Sa -> sa (Sanskrit)`; `wbm Wa -> wa (Walloon)`; `nbt Na -> na (Nauru)`; `toz To -> to (Tonga)`; `asz As -> as (Assamese)`; `akq Ak -> ak (Akan)`; `hoc Ho -> ho (Hiri Motu)`; `ikx Ik -> ik (Inupiaq)`.
- 3-letter collisions (name equals another language's `alpha_3`), a sample: `dnj Dan -> dan (Danish)`; `mnw Mon -> mon (Mongolian)`; `cla Ron -> ron (Romanian)`; `fqs Fas -> fas (Persian)`; `kuv Kur -> kur (Kurdish)`; `mlf Mal -> mal (Malayalam)`.
- Name-to-name collisions: `ttb` (name `Gaa`) re-reads as `gaa` (display `Ga`); `kkt Koi` re-reads as Komi-Permyak `koi`; `ong Olo <-> oog Ong`; `ong -> Olo -> olo (Livvi)`.
- Alias case: `sh` (display `Serbo-Croatian`) re-reads as `sr` through the hyphen defect.
- Direct runs: `normalize('gaa')`, `normalize('Gaa')`, `normalize('กา')` give `Ga`/`gaa`; `normalize('Ga')`, `normalize('ga')` give `Irish`/`ga`.
- Countries: 249 checked, 0 unstable.

## Fix options seen in the field

No choice is made here. Entry numbers refer to the lists below.

- **A. Store the code, show the name, never parse a display.** Code and display are separate fields; the code carries the meaning (FHIR Coding, 43; ICU, 19; Java, 21; Intl.DisplayNames, 17; Go display, 23; Babel, 26; libphonenumber stores the normalized number and formats for display only, 42). In this repo that means the idempotence contract and the test are on `comparison`/`canonical_code`, and `display` is output-only.
- **B. Refuse to guess on name/code ambiguity.** `langcodes.find` returns no match for a name that is ambiguous across languages and takes `language=` to disambiguate (24, 25). Maps to the project rule of returning `AMBIGUOUS`: `Ga` as a bare 2-letter string is both code `ga` and the name of `gaa`.
- **C. Make display names unique so they cannot equal another code.** UTS #35 says distinct codes must not share a display name (5); the standards call codes identifiers, not names (10, 11, 12). A display such as `Ga (gaa)` is the pattern; langcodes, Java and Babel show names with parenthetical qualifiers (24, 21, 26). Not checked: whether CLDR English also names `gaa` as `Ga`.
- **D. Case-sensitive code matching.** iso639-lang treats `ak` (Akan) and `Ak` (a different language, `akq`) as different (29, 30). BCP 47 tags are case-insensitive (1, 6, 7), so this departs from the standard.
- **E. Tag the output with its form.** FHIR pairs every code with a `system` (43, 44); schema.org takes a BCP 47 code or a Language object (45); a `structured` field with `kind=code|name` is the same idea. Parsing formatted output back needs the context it was formatted with (42, region for phone numbers).
- **F. Canonicalize once, then verify stability.** Canonicalization must satisfy `c(s) = c(c(s))` (35, 34); Unicode forms are idempotent by specification (32, 33); RFC 8264 re-applies rules until stable and rejects input that does not settle (36); ECMA-402 and ICU canonicalize identifiers, not names (15, 19, 20); Go `Canonicalize` is configurable by `CanonType` and the page does not state idempotence (22).
- **G. Test the property directly.** Idempotence as a named property category (37), as a generated Hypothesis check `f(x) == f(f(x))` (38), round-trip invariants (39), shrunk minimal examples (40, which is how `กา` was found). Phone numbers: format-then-parse only with the same region (41, 42).

## Open questions for the owner

1. Is the contract "re-normalizing `display` converges" (current xfail) or "re-normalizing the canonical code converges" (already true for 7,910/7,910)? These lead to different fixes (A versus B/C).
2. Should a bare 2-letter value that is both a 639-1 code and a pycountry name (`Ga`, `En`, `Ko`, `Ha`, ...) be `AMBIGUOUS`, or stay code-first (the documented M4 decision)?
3. Is `display` ever fed back into the normalizer outside the property test (stored column re-normalized, export then import)? Not traced.
4. Should hyphenated names (`Kuku-Yalanji`, `Judeo-Arabic`, 384 pycountry names) be a separate defect? It makes 232 displays INVALID on a second pass.
5. Are other code-keyed types (currency, script, unit) in scope for the same property test? Country was checked and is clean.

---

## 1. Standards: codes versus names (14)

1. IETF — RFC 5646, *Tags for Identifying Languages* (BCP 47) — https://www.rfc-editor.org/rfc/rfc5646 — the tag grammar; registry descriptions "are not intended to be the localized English names", so a name is never a subtag; recommended case is lowercase language, titlecase script, uppercase region.
2. IETF — RFC 4647, *Matching of Language Tags* — https://www.rfc-editor.org/rfc/rfc4647 — matching is defined between tags and ranges only, never between names; shows where fuzzy matching belongs (filtering and lookup of tags).
3. IANA — Language Subtag Registry — https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry — the authority for codes; `Deprecated` and `Preferred-Value` fields are the canonicalization map (read: File-Date 2026-09-17).
4. Unicode — UTS #35 Part 1: Core — https://www.unicode.org/reports/tr35/ — Annex C "LocaleId Canonicalization" and `languageAlias`: canonicalization is defined on identifiers (read in part).
5. Unicode — UTS #35 Part 2: General (Locale Display Name Algorithm) — https://www.unicode.org/reports/tr35/tr35-general.html — display names are for UI menus, and "two distinct codes would not get the same display name"; name generation is a one-way code-to-name step (read in part).
6. W3C — *Choosing a Language Tag* — https://www.w3.org/International/questions/qa-choosing-language-tags — look the name up in the registry, then use the `Subtag` code, not the name.
7. W3C — *Language tags in HTML and XML* — https://www.w3.org/International/articles/language-tags/ — "tags are built from registry codes, not language names"; two-letter code if one exists, case is only a convention; the shortest-tag rule.
8. Library of Congress — ISO 639-2 Language Code Agency — https://www.loc.gov/standards/iso639-2/ — registration authority for the 3-letter set; the page does not compare 639-1 and 639-2.
9. SIL — ISO 639-3 code `gaa` — https://iso639-3.sil.org/code/gaa — `gaa` is the Ga language, with no ISO 639-1 code; the `ga` that the normalizer reads for `Ga` is Irish.
10. SIL — *About ISO 639-3* — https://iso639-3.sil.org/about — describes the codes as "three-letter identifiers", i.e. identifiers, not names.
11. Wikipedia — ISO 639 — https://en.wikipedia.org/wiki/ISO_639 — set 1 is two-letter, sets 2, 3 and 5 three-letter; some codes "sound nothing like" the name, so name-like strings and codes overlap by accident.
12. Wikipedia — IETF language tag — https://en.wikipedia.org/wiki/IETF_language_tag — "Tags are codes, not language names"; main subtag from ISO 639.
13. Wikipedia — Gã language — https://en.wikipedia.org/wiki/Ga_language — ISO 639-3 `gaa`, no 639-1; carries a hatnote that the 639-1 code `ga` is Irish: the same collision documented by humans.
14. Unicode — CLDR project page — https://cldr.unicode.org/ — source of the language names and aliases the repo uses; the page itself is general and does not describe display names (included as the project root only).

## 2. Platform APIs: canonical form versus display name (9)

15. ECMA — ECMA-402, `CanonicalizeUnicodeLocaleId` — https://tc39.es/ecma402/#sec-canonicalizeunicodelocaleid — canonicalization delegates to UTS #35 Annex C and operates on identifiers only (read in part).
16. MDN — `Intl.getCanonicalLocales()` — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/getCanonicalLocales — returns canonical-case tags, deduplicated; a name or malformed tag throws `RangeError` instead of being guessed.
17. MDN — `Intl.DisplayNames` — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DisplayNames — `of(code)` returns a name; no name-to-code method exists in the platform API.
18. MDN — `Intl.Locale` — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/Locale — models the identifier as parts (language, script, region), not a name; points to UTS #35 canonical identifiers.
19. ICU user guide — Locale — https://unicode-org.github.io/icu/userguide/locale/ — IDs "identify a locale and are not meant for display"; `getDisplayXXX` is the separate display path; canonicalization level 1 and 2.
20. ICU4J — `ULocale` — https://unicode-org.github.io/icu-docs/apidoc/released/icu4j/com/ibm/icu/util/ULocale.html — `forLanguageTag`/`toLanguageTag` for interchange, `getDisplayName` for humans, `canonicalize` for CLDR canonical IDs (read in part).
21. Oracle — Java `Locale` — https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/Locale.html — parse (`forLanguageTag`), serialize (`toLanguageTag`) and display (`getDisplayLanguage`) are three separate methods; legacy `iw` maps to `he`; display falls back to the code.
22. Go — `golang.org/x/text/language` — https://pkg.go.dev/golang.org/x/text/language — `Parse` is strict, `CanonType` selects which canonicalizations run; idempotence is not stated on the page.
23. Go — `golang.org/x/text/language/display` — https://pkg.go.dev/golang.org/x/text/language/display — display names live in a separate package; every API is code-to-name; no reverse lookup.

## 3. Libraries: name-versus-code handling (8)

24. langcodes (GitHub) — https://github.com/rspeer/langcodes — `Language.get(tag)` parses and normalizes a code; `find(name)` maps a name to a code and "in the few cases of actual interlingual ambiguity, langcodes won't match a result" (`find('tonga')` fails, `language='id'` gives `to`); `find` ignores parenthetical qualifiers.
25. langcodes (PyPI, 3.5.1) — https://pypi.org/project/langcodes/ — the same `find` ambiguity behaviour, `display_name` from CLDR, `Language.get` normalizes `sh-QU` and `sgn-US`.
26. Babel — Core API — https://babel.pocoo.org/en/latest/api/core.html — codes live in `language`/`territory`; `display_name`, `get_display_name` return localized names; `parse_locale` is syntactic only (the repo's `_split_language_tag` depends on this).
27. pycountry (GitHub) — https://github.com/pycountry/pycountry — `languages.get(alpha_2=...)`, `lookup()` is case-insensitive and "the search ends with the first match" across any key, which is the root of the first-match order issue.
28. pycountry (PyPI 26.2.16) — https://pypi.org/project/pycountry/ — ISO 639-3 names from Debian pkg-isocodes; "no changes to the data will be accepted", so a name like `Ga` for `gaa` cannot be fixed upstream.
29. iso639-lang (PyPI) — https://pypi.org/project/iso639-lang/ — `Lang` takes code or name; "`Lang` is case-sensitive": `ak` is Akan, `Ak` is another language (`akq`); invalid raises, deprecated names a replacement.
30. iso639 (GitHub, LBeaudoux) — https://github.com/LBeaudoux/iso639 — the same library's source repo: names and codes resolved to one language; case-sensitive.
31. language-tags (JS) — https://github.com/mattcg/language-tags — validation is on whole tags, lookup on subtags, `search()` by description is a separate call; `format()` applies RFC 5646 case, `preferred()` maps deprecated tags.

## 4. Idempotence and canonical forms (10)

32. Unicode — UAX #15, Normalization Forms — https://unicode.org/reports/tr15/ — "all of the transformations are idempotent", and already-normalized strings stay normalized; the model for a canonical form that is a fixed point.
33. Python — `unicodedata` — https://docs.python.org/3/library/unicodedata.html — `normalize` and `is_normalized` (3.8+): a cheap "is it already canonical" predicate, which the language normalizer lacks.
34. Wikipedia — Idempotence — https://en.wikipedia.org/wiki/Idempotence — definition; "pretty-printing" is expected to be idempotent, the closest everyday analogue to a display string.
35. Wikipedia — Canonical form — https://en.wikipedia.org/wiki/Canonical_form — canonicalization `c` requires idempotence `c(s) = c(c(s))` and decisiveness; the formal statement of the property the xfail test checks.
36. IETF — RFC 8264, PRECIS Framework — https://www.rfc-editor.org/rfc/rfc8264 — rule application is "not necessarily idempotent"; re-apply until stable, reject if it does not settle after three more passes (read in part).
37. Wlaschin — *Choosing properties for property-based testing* — https://fsharpforfunandprofit.com/posts/property-based-testing-2/ — "doing an operation twice is the same as doing it once", listed as a property category.
38. Hypothesis docs — Integrations reference (ghostwriter) — https://hypothesis.readthedocs.io/en/latest/reference/integrations.html — ghostwriter's `--idempotent` generates a `f(x) == f(f(x))` test (page confirmed to mention idempotent; flag text from the docs search result).
39. Hypothesis — *The Encode/Decode invariant* — https://hypothesis.works/articles/encode-decode-invariant/ — round-trip properties are one assertion and find real bugs in serialization code.
40. Hypothesis (GitHub) — https://github.com/HypothesisWorks/hypothesis — shrinks failures to the simplest input, which is how a one-pair Thai string became the pinned regression.
41. Google — libphonenumber README — https://github.com/google/libphonenumber — parse/normalize into a `PhoneNumber` object, then format (E.164, national, international) for output.

## 5. Industry patterns: store the code, format separately, tag the form (4)

42. Google — libphonenumber FAQ — https://github.com/google/libphonenumber/blob/master/FAQ.md — store the normalized number, format only for display; to parse formatted output back, use the international `+` form; same-region context is needed for national form.
43. HL7 FHIR — Datatypes, `Coding` — https://hl7.org/fhir/datatypes.html#Coding — `system` + `code` + `display` are three fields: the code is "a symbol in syntax defined by the system"; display is "a representation of the meaning" (matching guidance not in the part read).
44. HL7 FHIR — ValueSet `languages` — https://hl7.org/fhir/valueset-languages.html — language values are BCP 47 codes from `urn:ietf:bcp:47`; a missing display is mapped, "not simply" shown as the code.
45. Schema.org — `inLanguage` — https://schema.org/inLanguage — the value is an IETF BCP 47 code (Text) or a Language object, never a free name.
