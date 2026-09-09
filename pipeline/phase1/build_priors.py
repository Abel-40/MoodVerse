"""Compute priors/deterministic_priors.jsonl for all 37,339 records.

Pure functions of the Phase 0 corpus and the cross-reference graph's STRUCTURE.
No AI, no network, no randomness: the same corpus produces a byte-identical file.

Each prior is a stated, versioned rule that emits a `nudge` of at most +/-1
ordinal level on ONE named field. A prior never originates an assessment and
never decides a curation status - it only shifts an assessment the annotation
layer has already made, and every nudge is recorded with its rule id so it can
be traced, measured against the gold set, and switched off.

Cross-reference use is constrained by design:
  * `votes` is never read. The parser does not even extract the field.
  * Every cross-reference prior is Bible-only, so it is null for all 6,236 Quran
    records and MUST NOT be referenced by the curation cascade. Otherwise 31,103
    Bible verses gain a feature 6,236 Quran verses cannot have and the
    Bible/Quran asymmetry inverts.
  * Only edge existence and location are used - never edge weight.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import mv_common as mv

OUT = mv.ENRICHMENT / "priors" / "deterministic_priors.jsonl"
RULES_DOC = mv.ENRICHMENT / "priors" / "prior_rules.md"

PRIORS_VERSION = "1.0.0"

# --------------------------------------------------------------------------
# Bible genre grouping. Declared, not inferred - the canon's book list is fixed.
# --------------------------------------------------------------------------

POETRY_WISDOM = {"Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon", "Job", "Lamentations"}
LAW = {"Exodus", "Leviticus", "Numbers", "Deuteronomy"}
GOSPEL = {"Matthew", "Mark", "Luke", "John"}
PROPHETIC = {
    "Isaiah", "Jeremiah", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah",
    "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
}
EPISTLE = {
    "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians", "Philippians",
    "Colossians", "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus",
    "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude",
}

CONNECTIVE_RE = re.compile(
    r"^(And|But|For|Therefore|So|Then|Thus|Wherefore|Nevertheless|Moreover|Yet|Now|Because)\b"
)
PRONOUN_RE = re.compile(r"^(He|She|They|Them|Him|Her|His|Their|It|These|Those|This|That)\b")
SPEECH_RE = re.compile(r"\b(said|saith|answered|spake|says)\b", re.IGNORECASE)
GENEALOGY_RE = re.compile(
    r"\b(begat|the son of|the sons of|years old|cubits|numbered|according to their families|"
    r"the children of \w+, by their generations)\b",
    re.IGNORECASE,
)

VERY_SHORT_WORDS = 6
VERY_LONG_WORDS = 60

# A verse must fall inside at least this many OpenBible range targets before the
# range-membership prior fires. Calibrated against the measured distribution:
# median 8, p75 15, p90 24. A threshold of 5 fires on 73.7% of Bible verses, which
# is a constant rather than a signal; 20 fires on 16.0% and discriminates.
RANGE_MEMBERSHIP_THRESHOLD = 20

# How many distinct books must reference a verse before it counts as behaving
# like a self-contained aphorism. Measured distribution: median 8, p75 13,
# p90 19, p95 23. A threshold of 8 is merely "at the median" and fires on 55.4%
# of Bible verses; 20 fires on 8.7% and is genuinely distinctive.
REFERRER_SPREAD_THRESHOLD = 20


def genre_of(book: str) -> str:
    if book in POETRY_WISDOM:
        return "poetry_wisdom"
    if book in EPISTLE:
        return "epistle"
    if book in GOSPEL:
        return "gospel"
    if book in PROPHETIC:
        return "prophetic"
    if book in LAW:
        return "law"
    return "narrative"


# genre -> (field, nudge, why)
GENRE_NUDGE = {
    "poetry_wisdom": ("context_dependency", -1, "Psalms and Proverbs are composed as self-contained units; measured connective-opening rate 0.22 and 0.16 against a canon average of 0.58."),
    "epistle": ("context_dependency", 0, "Argued prose: sometimes self-contained, often mid-argument. No nudge."),
    "gospel": ("context_dependency", 0, "Mixed narrative and discourse. No nudge."),
    "prophetic": ("context_dependency", 0, "Oracles vary from self-contained to deeply situational. No nudge."),
    "law": ("context_dependency", 1, "Legal and ritual prescription presupposes a surrounding system."),
    "narrative": ("context_dependency", 1, "Narrative verses depend on preceding events; measured connective-opening rates of 0.86-0.91 in Genesis, Judges and 1 Samuel."),
}


# --------------------------------------------------------------------------
# cross-reference structure (Bible only; votes never read)
# --------------------------------------------------------------------------

def bible_ordinals() -> tuple[dict[str, int], list[str]]:
    """canonical_id -> position in canonical order, for range containment only."""
    ordinals: dict[str, int] = {}
    order: list[str] = []
    for record in mv.iter_corpus():
        if record["religion"] == "bible":
            ordinals[record["canonical_id"]] = len(order)
            order.append(record["canonical_id"])
    return ordinals, order


def xref_structure(ordinals: dict[str, int], order: list[str]) -> dict[str, dict]:
    """Range membership and referrer spread, from edge STRUCTURE only.

    Range containment is computed here as a statistic over the graph. It is NOT
    written back into the corpus and makes no verse-level claim about any
    source's intent - Phase 0 declined to expand ranges and that stands.
    """
    contained_in_ranges: Counter[str] = Counter()
    referrer_books: dict[str, set[str]] = defaultdict(set)
    referrer_count: Counter[str] = Counter()

    def book_of(canonical_id: str) -> str:
        return canonical_id.split(":", 2)[1] if canonical_id else ""

    with mv.XREF_GRAPH.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip().rstrip(",")
            if not line.startswith('{"source_ref"'):
                continue
            edge = json.loads(line)
            source_id = edge.get("source_canonical_id")
            if edge.get("is_range"):
                start = edge.get("target_start_canonical_id")
                end = edge.get("target_end_canonical_id")
                if start in ordinals and end in ordinals:
                    lo, hi = ordinals[start], ordinals[end]
                    if 0 <= lo <= hi and hi - lo < 200:
                        for idx in range(lo, hi + 1):
                            target_id = order[idx]
                            contained_in_ranges[target_id] += 1
                            referrer_count[target_id] += 1
                            if source_id:
                                referrer_books[target_id].add(book_of(source_id))
            else:
                target_id = edge.get("target_canonical_id")
                if target_id:
                    referrer_count[target_id] += 1
                    if source_id:
                        referrer_books[target_id].add(book_of(source_id))

    return {
        cid: {
            "contained_in_ranges": contained_in_ranges.get(cid, 0),
            "referrer_count": referrer_count.get(cid, 0),
            "referrer_book_spread": len(referrer_books.get(cid, ())),
        }
        for cid in set(contained_in_ranges) | set(referrer_count)
    }


# --------------------------------------------------------------------------

def build() -> tuple[list[dict], dict]:
    taxonomy = mv.Taxonomy()
    ordinals, order = bible_ordinals()
    xrefs = xref_structure(ordinals, order)

    ontology = mv.read_json(mv.QSAC_ONTOLOGY)
    tag_types: dict[str, list[str]] = {}
    for domain in ontology["domains"]:
        for category in domain["categories"]:
            for tag in category["tags"]:
                tag_types[tag["name"]] = tag.get("types", [])

    rows: list[dict] = []
    fired: Counter[str] = Counter()

    for record in mv.iter_corpus():
        cid = record["canonical_id"]
        religion = record["religion"]
        text, text_source = mv.display_text(record)
        words = len(text.split())
        priors: list[dict] = []
        features: dict = {"word_count": words, "text_source": text_source}

        def add(rule_id: str, field: str, nudge: int, basis: str, signal=True) -> None:
            priors.append(
                {"rule_id": rule_id, "field": field, "nudge": nudge, "basis": basis, "signal": signal}
            )
            fired[rule_id] += 1

        if religion == "bible":
            book = record["location"]["book"]
            genre = genre_of(book)
            features["genre"] = genre
            features["book"] = book
            field, nudge, why = GENRE_NUDGE[genre]
            if nudge:
                add(f"bible.genre.{genre}", field, nudge, why)

            if CONNECTIVE_RE.match(text):
                features["opens_with_connective"] = True
                add(
                    "bible.opens_with_connective", "context_dependency", 1,
                    "Opens with a discourse connective (And/But/For/Therefore/...). Measured on "
                    "58.2% of AKJV verses. CAVEAT: KJV 'And' frequently renders a Hebrew "
                    "waw-consecutive and is partly a translation artefact, so this is a prior "
                    "with a real false-positive rate and is overridable by the annotation layer.",
                )
            if PRONOUN_RE.match(text):
                features["opens_with_pronoun"] = True
                add(
                    "bible.opens_with_pronoun", "context_dependency", 1,
                    "Opens with a pronoun whose referent is not in the verse (5.9% of AKJV).",
                )
            if SPEECH_RE.search(text):
                features["contains_speech_verb"] = True
                add(
                    "bible.contains_speech_verb", "scripture_purpose", 0,
                    "Contains a speech verb (15.6% of AKJV). Flags the record for reported_speech "
                    "and speaker_role assessment, which is the largest source of "
                    "misleading-if-isolated content. No score nudge.",
                )
            if GENEALOGY_RE.search(text):
                features["genealogy_pattern"] = True
                add(
                    "bible.genealogy_pattern", "standalone_usefulness", -1,
                    "Matches genealogy or measurement patterns (begat / the son of / cubits / "
                    "numbered). 4.9% of AKJV. Such verses are self-contained yet carry nothing to "
                    "reflect on - the case that keeps context_dependency and "
                    "standalone_usefulness separate.",
                )
            if record["location"]["verse_start"] == 1:
                features["chapter_opening"] = True

            shape = xrefs.get(cid)
            if shape:
                features["xref"] = shape
                if shape["contained_in_ranges"] >= RANGE_MEMBERSHIP_THRESHOLD:
                    add(
                        "xref.frequently_inside_ranges", "context_dependency", 1,
                        f"Falls inside {shape['contained_in_ranges']} OpenBible range targets, so "
                        "the community treats it as part of a passage rather than a unit. "
                        "Structure only - vote weights are never read. CORROBORATION ONLY: this "
                        "prior may not originate a context-dependency assessment.",
                    )
                # independent of the range prior, not an elif: a verse can be both
                # heavily range-enclosed and widely referenced, in which case the two
                # nudges cancel to 0, which is the honest outcome.
                if shape["referrer_book_spread"] >= REFERRER_SPREAD_THRESHOLD:
                    add(
                        "xref.referenced_across_canon", "context_dependency", -1,
                        f"Referenced from {shape['referrer_book_spread']} different books, which is "
                        "how a self-contained aphorism behaves. Structure only; corroboration only.",
                    )
            else:
                features["xref"] = {"contained_in_ranges": 0, "referrer_count": 0, "referrer_book_spread": 0}

        else:  # quran
            features["surah"] = record["location"]["chapter_or_surah_number"]
            types: Counter[str] = Counter()
            revelation = "unstated"
            for annotation in mv.independent_annotations(record):
                if annotation["source"] == "QSAC" and annotation["annotation_type"] == "semantic_tag":
                    for tag_type in tag_types.get(annotation["value"], []):
                        types[tag_type] += 1
                if annotation["source"] == "Complete_Quran_data" and annotation["annotation_type"] == "context":
                    if annotation["value"] == "Makki Revelation":
                        revelation = "makki"
                    elif annotation["value"] == "Madani Revelation":
                        revelation = "madani"
            features["qsac_types"] = dict(sorted(types.items()))
            features["revelation_period"] = revelation

            # Bound types (rulings, events, named entities) are tied to a situation
            # the verse does not itself carry; portable types (concepts, moral
            # traits) are not. The nudge follows which group DOMINATES, not which is
            # merely present: quran:94:5 carries concept x2, moral_trait x1 and
            # event x1 and is an excellent standalone reflection. Firing on presence
            # alone penalised it for its single `event` tag.
            bound = types["ruling"] + types["event"] + types["entity"]
            portable = types["concept"] + types["moral_trait"]
            features["qsac_type_balance"] = {"bound": bound, "portable": portable}
            if bound > portable:
                dominant = max(("ruling", "event", "entity"), key=lambda t: types[t])
                add(
                    f"quran.qsac_type.{dominant}", "standalone_usefulness", -1,
                    f"Bound QSAC tag types outnumber portable ones ({bound} vs {portable}); the "
                    f"most common is `{dominant}`. Across the ontology: ruling 61, event 68, "
                    "entity 45 tags versus concept 196, moral_trait 55. Rulings, events and named "
                    "entities are tied to a setting the verse does not carry. The type field is "
                    "structural metadata in a published ontology, so this uses QSAC's shape "
                    "without importing its vocabulary.",
                )
            elif portable > bound:
                add(
                    "quran.qsac_type.concept_or_trait", "standalone_usefulness", 1,
                    f"Portable QSAC tag types outnumber bound ones ({portable} vs {bound}). "
                    "Concepts and moral traits describe ideas that travel without their original "
                    "setting.",
                )
            if record["text"].get("original_variants"):
                features["has_text_variant"] = True
                add(
                    "quran.text_variant", "review_flag", 0,
                    "Sources disagree on this ayah's Arabic (Basmala prefixing on 105 ayat). "
                    "Routes to review until a display decision is recorded.",
                )

        # both religions
        if words <= VERY_SHORT_WORDS:
            features["very_short"] = True
            add(
                "text.very_short", "context_dependency", 1,
                f"{words} words or fewer. Short verses more often depend on their neighbours. "
                "212 AKJV verses and 450 ayat are at or below this threshold.",
            )
        if words >= VERY_LONG_WORDS:
            features["very_long"] = True
            add(
                "text.very_long", "standalone_usefulness", -1,
                f"{words} words. Very long verses are hard to receive as a single reflection.",
            )

        quality = record["data_quality"]["status"]
        if quality != "valid":
            features["phase0_data_quality"] = quality
            add(
                f"phase0.{quality}", "review_flag", 0,
                f"Phase 0 marked this record `{quality}`. Carried forward - records flagged in "
                "Phase 0 deserve review before being served to a user in distress.",
            )

        rows.append(
            {
                "canonical_id": cid,
                "religion": religion,
                "priors_version": PRIORS_VERSION,
                "taxonomy_version": taxonomy.version,
                "features": features,
                "priors": priors,
                "net_nudge": {
                    field: sum(p["nudge"] for p in priors if p["field"] == field)
                    for field in sorted({p["field"] for p in priors})
                },
            }
        )

    stats = {
        "records": len(rows),
        "rules_fired": dict(sorted(fired.items())),
        "records_with_no_prior": sum(1 for r in rows if not r["priors"]),
    }
    return rows, stats


def render_rules_doc(stats: dict) -> str:
    total = stats["records"]
    lines = [
        "# Deterministic priors",
        "",
        f"Version `{PRIORS_VERSION}`. Generated by `processed/enrichment/build_priors.py`.",
        "",
        "Every rule below is a pure function of the Phase 0 corpus. No AI, no network, no",
        "randomness. A prior emits a `nudge` of at most +/-1 ordinal level on one named field.",
        "",
        "**A prior never originates an assessment and never decides a curation status.** It only",
        "shifts an assessment the annotation layer has already made. Every applied nudge is",
        "recorded with its rule id, so it can be traced, measured against the gold set, and",
        "switched off without re-annotating anything.",
        "",
        "## Why both religions get their own prior set",
        "",
        "The Bible has no source annotations and the Quran has no cross-references, so neither",
        "corpus can be given the other's signals. What is held equal is not the *set* of priors",
        "but their *influence*: every rule is capped at one ordinal level, for both religions.",
        "Different prior sets are unavoidable; different prior strength is not acceptable.",
        "",
        "## Cross-reference constraints",
        "",
        "* `votes` is never read - the parser does not extract the field.",
        "* Cross-reference priors are Bible-only and are `null` for all 6,236 Quran records.",
        "  The curation cascade may not reference them.",
        "* They corroborate a context-dependency assessment; they may not originate one.",
        "* Range containment is computed as a statistic over the graph and is never written back",
        "  into the corpus. Phase 0 declined to expand ranges, and that stands.",
        "",
        "## Measured firing rates",
        "",
        "| Rule | Field | Nudge | Records | Share of corpus |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    nudges = {
        "bible.genre.poetry_wisdom": ("context_dependency", -1),
        "bible.genre.law": ("context_dependency", +1),
        "bible.genre.narrative": ("context_dependency", +1),
        "bible.opens_with_connective": ("context_dependency", +1),
        "bible.opens_with_pronoun": ("context_dependency", +1),
        "bible.contains_speech_verb": ("scripture_purpose", 0),
        "bible.genealogy_pattern": ("standalone_usefulness", -1),
        "xref.frequently_inside_ranges": ("context_dependency", +1),
        "xref.referenced_across_canon": ("context_dependency", -1),
        "quran.qsac_type.ruling": ("standalone_usefulness", -1),
        "quran.qsac_type.event": ("standalone_usefulness", -1),
        "quran.qsac_type.entity": ("standalone_usefulness", -1),
        "quran.qsac_type.concept_or_trait": ("standalone_usefulness", +1),
        "quran.text_variant": ("review_flag", 0),
        "text.very_short": ("context_dependency", +1),
        "text.very_long": ("standalone_usefulness", -1),
        "phase0.warning": ("review_flag", 0),
        "phase0.unresolved": ("review_flag", 0),
    }
    for rule_id, count in stats["rules_fired"].items():
        field, nudge = nudges.get(rule_id, ("?", 0))
        lines.append(
            f"| `{rule_id}` | {field} | {nudge:+d} | {count:,} | {100 * count / total:.1f}% |"
        )
    lines += [
        "",
        f"Records with no prior at all: {stats['records_with_no_prior']:,} "
        f"({100 * stats['records_with_no_prior'] / total:.1f}%). An absent prior is not evidence",
        "of anything; those records rely entirely on the annotation layer.",
        "",
        "## Known limitations",
        "",
        "1. **`bible.opens_with_connective` is partly a translation artefact.** KJV renders the",
        "   Hebrew waw-consecutive as 'And', so the 58.2% firing rate overstates genuine syntactic",
        "   dependency. It is a prior, never a verdict, and the annotation layer overrides it.",
        "2. **The connective rule measures syntactic dependency only.** Song of Solomon has the",
        "   canon's lowest connective rate (0.09) and among its highest genuine context",
        "   dependency. Figurative and frame dependency are invisible to this rule.",
        "3. **`bible.genealogy_pattern` is lexical.** It will miss list verses that use none of its",
        "   trigger phrases.",
        "4. **QSAC types are LLM-assigned**, like the tags themselves. The ontology's structure is",
        "   published and validated, but the per-tag type assignment was not human-adjudicated.",
        "5. **No prior exists for the Quran equivalent of genre.** No Phase 0 source supplies one,",
        "   and none was invented.",
        "",
        "Hit rates against the gold set are reported in `validation/agreement_report.json` once a",
        "gold set exists. Until then these are firing rates only - they say how often a rule",
        "applies, not how often it is right.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    mv.setup_stdout()
    before = mv.phase0_digests()
    rows, stats = build()
    mv.write_jsonl(OUT, rows)
    mv.write_text(RULES_DOC, render_rules_doc(stats))
    mv.assert_phase0_unchanged(before, mv.phase0_digests())

    print(f"priors -> {OUT.relative_to(mv.BASE)}")
    print(f"  records              {stats['records']:,}")
    print(f"  records with priors  {stats['records'] - stats['records_with_no_prior']:,}")
    print("  rules fired:")
    for rule_id, count in stats["rules_fired"].items():
        print(f"    {rule_id:38s} {count:7,}  ({100*count/stats['records']:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
