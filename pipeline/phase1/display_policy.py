"""Which Arabic reading is displayed for a Quran record.

Phase 0 preserves every source's Arabic and picks no winner. Phase 1 left the
choice open, so every record with a variant was held at REVIEW_REQUIRED by
`gate1.undecided_display_text` - 2,172 ayat, a third of the Quran.

DISPLAY POLICY v1 (2026-10-06). Measured over the whole corpus, the variants
fall into three groups:

  * The same reading in another script: ELQV's Uthmani text (`Verse Diac`) and
    its undiacritised copy (`Verse`). 4,136 of 4,274 variants match the primary
    text letter for letter once diacritics, Quranic annotation signs and
    alif/hamza seats are set aside, and the rest differ only by Uthmani spelling
    conventions within a word: a doubled letter written once (`اليل` for
    `الليل`, `نجي` for `ننجي`).
  * A prefixed Basmala: Complete_Quran_data prepends it to ayah 1 of surahs
    10-114 (but not 2-8), where QSAC does not. Exactly 105 records. In the Hafs
    numbering all of these sources follow, the Basmala is an ayah only in
    Al-Fatihah, so the reading without it is displayed.
  * Anything else: none today. Such a record keeps `needs_decision` and stays in
    review, because that would be a real textual question, not a script one.

No text is edited. The displayed string is always one source's text, verbatim,
and the rule that chose it is recorded on the enrichment record.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

BASMALA = "بسم الله الرحمن الرحيم"

# Alif and hamza carriers, which the scripts place differently.
_SEATS = frozenset("اأإآٱءٰ")
_FOLD = {"ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}


def skeleton(text: str) -> str:
    """Consonantal letters only: no vowels, signs, seats, punctuation or spaces."""
    out = []
    for ch in unicodedata.normalize("NFKD", text):
        category = unicodedata.category(ch)
        if category[0] in ("M", "P", "Z") or ch == "ـ" or "ۖ" <= ch <= "ۭ":
            continue
        ch = _FOLD.get(ch, ch)
        if ch in _SEATS:
            continue
        out.append(ch)
    return "".join(out)


def _loose(text: str) -> str:
    # Uthmani spells some long vowels with waw or ya; set those aside too.
    return skeleton(text).replace("و", "").replace("ي", "")


def _collapse(text: str) -> str:
    # Uthmani writes some doubled letters once: the lam of al-layl, the nun of
    # nunji. Collapsing runs of one letter equates exactly those spellings.
    return re.sub(r"(.)\1+", r"\1", text)


def _same_word(a: str, b: str) -> bool:
    return _loose(a) == _loose(b) or _collapse(_loose(a)) == _collapse(_loose(b))


def same_reading(a: str, b: str) -> bool:
    """True when two strings are one reading written in different scripts."""
    if skeleton(a) == skeleton(b) or _loose(a) == _loose(b):
        return True
    # Pause signs stand alone between words in some scripts; they are not words.
    words_a = [w for w in a.split() if skeleton(w)]
    words_b = [w for w in b.split() if skeleton(w)]
    if len(words_a) != len(words_b):
        return False
    return all(_same_word(x, y) for x, y in zip(words_a, words_b))


def _without_basmala(text: str) -> str | None:
    words = text.split()
    if len(words) > 4 and skeleton(" ".join(words[:4])) == skeleton(BASMALA):
        return " ".join(words[4:])
    return None


def display_original(record: dict[str, Any]) -> dict[str, Any]:
    """The Arabic to display for a record, and the rule that chose it."""
    if record["religion"] != "quran":
        return {"rule": "not_applicable", "text": None, "source": None, "needs_decision": False}

    text = record["text"]
    original = text.get("original") or ""
    source = text.get("original_source")
    variants = text.get("original_variants") or []

    if all(same_reading(original, v["text"]) for v in variants):
        return {
            "rule": "primary_reading" if not variants else "primary_reading_other_scripts_agree",
            "text": original,
            "source": source,
            "needs_decision": False,
        }

    stripped = _without_basmala(original)
    surah, ayah = record["location"]["chapter_or_surah_number"], record["location"]["verse_start"]
    if stripped is not None and ayah == 1 and surah != 1:
        unprefixed = [v for v in variants if same_reading(stripped, v["text"]) and not _without_basmala(v["text"])]
        others_agree = all(
            same_reading(stripped, v["text"]) or same_reading(original, v["text"]) for v in variants
        )
        if unprefixed and others_agree:
            chosen = next(
                (v for v in unprefixed if any(s["source"] == "QSAC" for s in v["sources"])),
                unprefixed[0],
            )
            return {
                "rule": "ayah_without_prefixed_basmala",
                "text": chosen["text"],
                "source": chosen["sources"][0]["source"],
                "needs_decision": False,
            }

    return {"rule": "undecided", "text": original, "source": source, "needs_decision": True}
