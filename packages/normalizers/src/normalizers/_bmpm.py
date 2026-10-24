"""Beider-Morse Phonetic Matching (GENERIC name type, APPROX rules).

An independent Python port of the algorithm in Apache Commons Codec's
`org.apache.commons.codec.language.bm` (Apache-2.0). The rule files in
`_bmpm_data/` are Commons Codec 1.17.1's, copied unmodified, with their
LICENSE and NOTICE; no rule lives in this file.

The engine guesses the language SET of the spelling from the rule files
(`gen_lang.txt`) exactly as the reference encoder does; that set only selects
rules, it is never reported as the name's language.

ponytail: GENERIC + APPROX only (the Ashkenazi/Sephardic name types and the
EXACT rule type are not vendored); `encode` always uses the reference
encoder's defaults (concatenate, 20 phonemes). Upgrade path: vendor the other
rule files and thread name type / rule type through `_rules`.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import NamedTuple

_DATA = Path(__file__).parent / "_bmpm_data"
_MAX_PHONEMES = 20

# A language set is a frozenset of language names; None is the reference
# encoder's ANY_LANGUAGE (compatible with everything), frozenset() is empty.
_Langs = frozenset[str] | None


class _Rule(NamedTuple):
    pattern: str
    left: re.Pattern[str]
    right: re.Pattern[str]
    phonemes: tuple[tuple[str, _Langs], ...]


def _restrict(a: _Langs, b: _Langs) -> _Langs:
    return a if b is None else b if a is None else a & b


def _merge(a: _Langs, b: _Langs) -> _Langs:
    return b if a is None else None if b is None else a | b


def _lines(name: str) -> list[str]:
    """File lines without comments (`/* */` blocks and `//` tails) and blanks."""
    out: list[str] = []
    in_block = False
    for raw in (_DATA / f"{name}.txt").read_text(encoding="utf-8").splitlines():
        if in_block:
            in_block = not raw.endswith("*/")
        elif raw.startswith("/*"):
            in_block = True
        elif line := raw.split("//", 1)[0].strip():
            out.append(line)
    return out


def _unquote(token: str) -> str:
    """Drop ONE leading and ONE trailing quote (the pattern `\\"` keeps its escape)."""
    return token.removeprefix('"').removesuffix('"')


def _context(regex: str) -> re.Pattern[str]:
    """A rule context, compiled exactly as Commons Codec's `Rule.pattern` does."""
    # ponytail: upstream treats bracket-less contexts as literals, so e.g.
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    # `(а|е|о|и|у)` never fires; 4/131 Cyrillic names lose alternatives.  # noqa: RUF003
    # Upgrade path: follow upstream if Commons Codec fixes it; re-vendor the rule files.
    start, end = regex.startswith("^"), regex.endswith("$")
    core = regex[start : len(regex) - end]
    if "[" in core or not (start or end) or not core:
        return re.compile(regex)
    return re.compile(("^" if start else "") + re.escape(core) + ("$" if end else ""))


def _phoneme(text: str) -> tuple[str, _Langs]:
    if "[" in text:
        before, _, rest = text.partition("[")
        return before, frozenset(rest.removesuffix("]").split("+"))
    return text, None


def _phoneme_expr(text: str) -> tuple[tuple[str, _Langs], ...]:
    if not text.startswith("("):
        return (_phoneme(text),)
    body = text[1:-1]
    parts = body.split("|")
    while parts and not parts[-1]:  # the reference split drops trailing empties
        parts.pop()
    out = [_phoneme(p) for p in parts]
    if body.startswith("|") or body.endswith("|"):
        out.append(("", None))
    return tuple(out)


def _parse_rules(name: str) -> dict[str, list[_Rule]]:
    rules: dict[str, list[_Rule]] = {}
    for line in _lines(name):
        if line.startswith("#include"):
            rules.update(_parse_rules(line.removeprefix("#include").strip()))
            continue
        pat, lcon, rcon, ph = (_unquote(p) for p in line.split())
        rule = _Rule(pat, _context(lcon + "$"), _context("^" + rcon), _phoneme_expr(ph))
        rules.setdefault(pat[0], []).append(rule)
    return rules


@cache
def _languages() -> frozenset[str]:
    return frozenset(_lines("gen_languages"))


@cache
def _rules(kind: str, lang: str) -> dict[str, list[_Rule]]:
    return _parse_rules(f"gen_{kind}_{lang}")


@cache
def _lang_rules() -> tuple[tuple[re.Pattern[str], frozenset[str], bool], ...]:
    out = []
    for line in _lines("gen_lang"):
        pattern, langs, accept = line.split()
        out.append((re.compile(pattern), frozenset(langs.split("+")), accept == "true"))
    return tuple(out)


@cache
def _prefixes() -> tuple[str, ...]:
    return tuple(_lines("gen_name_prefixes"))


def _guess_languages(text: str) -> _Langs:
    text = text.lower()
    langs = set(_languages())
    for pattern, rule_langs, accept in _lang_rules():
        if pattern.search(text):
            langs = langs & rule_langs if accept else langs - rule_langs
    return frozenset(langs) if langs else None


def _rule_set(kind: str, langs: _Langs) -> dict[str, list[_Rule]]:
    return _rules(kind, next(iter(langs)) if langs and len(langs) == 1 else "any")


def _apply(
    rules: dict[str, list[_Rule]],
    text: str,
    i: int,
    phonemes: list[tuple[str, _Langs]],
) -> tuple[int, bool, list[tuple[str, _Langs]]]:
    """Apply the first rule matching at `i`; returns (next index, found, phonemes)."""
    for rule in rules.get(text[i], ()):
        end = i + len(rule.pattern)
        if (
            text.startswith(rule.pattern, i)
            and rule.right.search(text[end:])
            and rule.left.search(text[:i])
        ):
            out: list[tuple[str, _Langs]] = []
            for left, left_langs in phonemes:
                for right, right_langs in rule.phonemes:
                    langs = _restrict(left_langs, right_langs)
                    if langs is None or langs:
                        out.append((left + right, langs))
                        if len(out) >= _MAX_PHONEMES:
                            return end, True, out
            return end, True, out
    return i + 1, False, phonemes


def _final(
    phonemes: list[tuple[str, _Langs]], rules: dict[str, list[_Rule]]
) -> list[tuple[str, _Langs]]:
    if not rules:
        return phonemes
    merged: dict[str, _Langs] = {}
    for text, langs in phonemes:
        sub: list[tuple[str, _Langs]] = [("", langs)]
        i = 0
        while i < len(text):
            i, found, sub = _apply(rules, text, i, sub)
            if not found:
                sub = [(t + text[i - 1], lg) for t, lg in sub]
        for t, lg in sub:
            merged[t] = _merge(merged[t], lg) if t in merged else lg
    return sorted(merged.items())


def _encode(text: str) -> str:
    langs = _guess_languages(text)
    text = text.lower().replace("-", " ").strip()
    if text.startswith("d'"):
        rest = text[2:]
        return f"({_encode(rest)})-({_encode('d' + rest)})"
    for prefix in _prefixes():
        if text.startswith(prefix + " "):
            rest = text[len(prefix) + 1 :]
            return f"({_encode(rest)})-({_encode(prefix + rest)})"
    text = " ".join(text.split())
    phonemes: list[tuple[str, _Langs]] = [("", langs)]
    rules = _rule_set("rules", langs)
    i = 0
    while i < len(text):
        i, _, phonemes = _apply(rules, text, i, phonemes)
    phonemes = _final(phonemes, _rules("approx", "common"))
    phonemes = _final(phonemes, _rule_set("approx", langs))
    return "|".join(t for t, _ in phonemes)


def encode(name: str) -> tuple[str, ...]:
    """Sorted alternative Beider-Morse codes of `name` (empty if it has none)."""
    return tuple(sorted({c for c in re.split(r"[()|-]+", _encode(name)) if c}))
