"""Build mappings/source_label_ledger.json and mappings/quarantine.json.

Turns the declared rules in ledger_rules.py into one ledger row per
(source, annotation_type, source_label), checked against label_inventory.json so
that no label can be silently missed and no rule can name a label that does not
exist in the corpus.

Enforced at build time, as hard failures:
  * No row targets `addressed_states` - nothing in any source measures which
    user state a verse SERVES.
  * No row targets `intent` or any suitability field - those are pastoral
    judgements no source is entitled to make.
  * Every target value exists in the declared taxonomy version.
  * Every independent source label has exactly one row.
  * Derived sources (Only TCEC cols, ELQVv2) get rows for provenance but carry
    weight 0.0 and are excluded from aggregation.

Rows are emitted with status `proposed`. Nothing is `approved` until a human
reviews it; build_enrichment.py refuses to give weight to an unapproved row
unless explicitly run in bootstrap mode.
"""

from __future__ import annotations

import sys
from collections import Counter

import ledger_rules as rules
import mv_common as mv

LEDGER_OUT = mv.ENRICHMENT / "mappings" / "source_label_ledger.json"
QUARANTINE_OUT = mv.ENRICHMENT / "mappings" / "quarantine.json"
INVENTORY = mv.ENRICHMENT / "mappings" / "label_inventory.json"

LEDGER_SCHEMA_VERSION = "1.0.0"

# axes a source label may target
ALLOWED_AXES = {
    "expressed_affect",
    "theme",
    "scripture_purpose_prior",
    "situation",
    "structural",
    "none",
}

# axes a source label may NEVER target. See ledger_rules.py for why.
FORBIDDEN_AXES = {
    "addressed_states",
    "addresses_states",
    "intent",
    "intents",
    "purpose_suitability",
    "standalone_usefulness",
    "emotional_relevance",
    "curation_status",
}

QUARANTINE_CONFIDENCE = 0.1


class LedgerError(SystemExit):
    pass


def slug(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_")[:60]


def qsac_tag_index() -> dict[str, dict]:
    """tag name -> {category, domain, types} from the verbatim QSAC ontology."""
    ontology = mv.read_json(mv.QSAC_ONTOLOGY)
    index: dict[str, dict] = {}
    for domain in ontology["domains"]:
        for category in domain["categories"]:
            for tag in category["tags"]:
                index[tag["name"]] = {
                    "domain": domain["name"],
                    "category": category["name"],
                    "types": tag.get("types", []),
                }
    return index


def make_targets(specs, taxonomy: mv.Taxonomy) -> list[dict]:
    targets = []
    for axis, value, relation, confidence in specs:
        if axis in FORBIDDEN_AXES:
            raise LedgerError(
                f"DIRECTION RULE VIOLATION: a source label may never target `{axis}`. "
                "Source annotations describe the text; they do not certify what it serves."
            )
        if axis not in ALLOWED_AXES:
            raise LedgerError(f"unknown target axis `{axis}`")
        if axis == "theme" and value not in taxonomy.themes:
            raise LedgerError(f"theme `{value}` is not in taxonomy {taxonomy.version}")
        if axis == "expressed_affect" and value not in taxonomy.emotions:
            raise LedgerError(f"emotion `{value}` is not in taxonomy {taxonomy.version}")
        if axis == "scripture_purpose_prior" and value not in taxonomy.scripture_purposes:
            raise LedgerError(f"scripture purpose `{value}` is not in taxonomy {taxonomy.version}")
        if axis == "situation" and value not in taxonomy.situations:
            raise LedgerError(f"situation `{value}` is not in taxonomy {taxonomy.version}")
        targets.append(
            {
                "axis": axis,
                "value": value,
                "relation": relation,
                "confidence": confidence,
            }
        )
    return targets


def default_rationale(targets: list[dict]) -> str:
    if not targets or targets[0]["axis"] == "none":
        return "Carries nothing usable into the MoodVerse taxonomy. Recorded as a decision, not a gap."
    parts = []
    for target in targets:
        parts.append(f"{target['relation']} match to {target['axis']} `{target['value']}`")
    return "Declared mapping: " + "; ".join(parts) + "."


def build() -> tuple[dict, dict]:
    taxonomy = mv.Taxonomy()
    inventory = mv.read_json(INVENTORY)
    tags = qsac_tag_index()

    inv_rows = {
        (row["source"], row["annotation_type"], row["label"]): row
        for row in inventory["labels"]
    }

    rows: list[dict] = []
    quarantined: list[dict] = []
    unmapped: list[str] = []
    method_counts: Counter[str] = Counter()

    for (source, atype, label), inv in sorted(inv_rows.items()):
        tier = inv["evidence_tier"]
        independent = inv["independent_annotation_source"]
        specs = None
        rationale = None
        method = "deterministic"
        variant_of = None

        if source in ("ELQV", "ELQVv2") and atype == "emotion":
            specs = rules.ELQV_EMOTION.get(label)
            rationale = rules.ELQV_RATIONALE.get(label)
            method = "human_reviewed"

        elif source in ("Complete_Quran_data", "Only TCEC cols"):
            if atype == "emotion":
                specs = rules.CQD_EMOTION.get(label)
                rationale = rules.CQD_EMOTION_RATIONALE.get(label)
                method = "human_reviewed"
            elif atype == "category":
                variant_of = rules.CQD_CATEGORY_VARIANTS.get(label)
                lookup = variant_of or label
                specs = rules.CQD_CATEGORY.get(lookup)
                rationale = rules.CQD_CATEGORY_RATIONALE.get(label)
                method = "human_reviewed"
            elif atype == "context":
                variant_of = rules.CQD_CONTEXT_VARIANTS.get(label)
                specs = rules.CQD_CONTEXT.get(label)
                rationale = rules.CQD_CONTEXT_RATIONALE.get(label)
                method = "human_reviewed"
            elif atype == "theme_tag":
                theme = rules.CQD_THEME.get(label, ...)
                if theme is ...:
                    specs = None
                elif theme is None:
                    specs = [("none", None, "none", 0.1)]
                else:
                    confidence = 0.3 if label in rules.CQD_THEME_LOW_CONFIDENCE else 0.5
                    relation = "related" if label in rules.CQD_THEME_LOW_CONFIDENCE else "exact"
                    specs = [("theme", theme, relation, confidence)]
                rationale = rules.CQD_THEME_RATIONALE.get(label)
                method = "human_reviewed"

        elif source == "QSAC" and atype == "semantic_tag":
            meta = tags.get(label)
            override = rules.QSAC_TAG_OVERRIDE.get(label)
            if override:
                specs = [("theme", override, "exact", 0.6)]
                rationale = (
                    f"Tag-level override. Ontology category `{meta['category']}` "
                    f"(domain `{meta['domain']}`) maps elsewhere; this tag's own meaning is closer "
                    f"to `{override}`."
                ) if meta else None
                method = "human_reviewed"
            elif meta:
                theme = rules.QSAC_CATEGORY_THEME.get(meta["category"], ...)
                if theme is ...:
                    specs = None
                elif theme is None:
                    specs = [("none", None, "none", 0.2)]
                    rationale = (
                        f"Ontology category `{meta['category']}` describes literary form rather "
                        "than subject matter, so it carries nothing onto a MoodVerse theme."
                    )
                else:
                    specs = [("theme", theme, "broader", 0.5)]
                    rationale = (
                        f"Inherited from QSAC ontology category `{meta['category']}` "
                        f"(domain `{meta['domain']}`), which is the declared mapping unit. "
                        f"Tag types: {', '.join(meta['types']) or 'none'}."
                    )
                method = "deterministic"
                # purpose prior from the tag's own ontology types
                for tag_type in meta["types"]:
                    purpose = rules.QSAC_TYPE_PURPOSE_PRIOR.get(tag_type)
                    if purpose and specs and specs[0][0] != "none":
                        specs = list(specs) + [
                            ("scripture_purpose_prior", purpose, "related", 0.3)
                        ]
                        break

        if specs is None:
            unmapped.append(f"{source}/{atype}/{label}")
            continue

        targets = make_targets(specs, taxonomy)
        is_quarantined = "low_frequency" in inv["anomalies"]

        if is_quarantined:
            for target in targets:
                target["confidence"] = QUARANTINE_CONFIDENCE

        row = {
            "mapping_id": f"{slug(source)}.{slug(atype)}.{slug(label)}",
            "source": source,
            "source_file": inv["source_file"],
            "source_annotation_type": atype,
            "source_label": label,
            "source_label_occurrences": inv["occurrences"],
            "source_evidence_tier": tier,
            "independent_annotation_source": independent,
            "evidence_weight": 0.0 if not independent else taxonomy.tier_weight(tier),
            "targets": targets,
            "relation_summary": sorted({t["relation"] for t in targets}),
            "rationale": rationale or default_rationale(targets),
            "method": method,
            "status": "quarantined" if is_quarantined else "proposed",
            "anomalies": inv["anomalies"],
            "variant_of_label": variant_of,
            "evidence_verse_ids": inv["example_verses"],
            "taxonomy_version": taxonomy.version,
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": None,
        }
        if not independent:
            row["derived_note"] = (
                f"Verified duplicate of {source}. Row kept for provenance; evidence_weight is "
                "0.0 and it is excluded from every aggregate."
            )
        rows.append(row)
        method_counts[row["method"]] += 1
        if is_quarantined:
            quarantined.append(
                {
                    "mapping_id": row["mapping_id"],
                    "source": source,
                    "annotation_type": atype,
                    "label": label,
                    "occurrences": inv["occurrences"],
                    "anomalies": inv["anomalies"],
                    "spelling_variants": inv["spelling_variants"],
                    "canonical_spelling": inv["canonical_spelling"],
                    "variant_of_label": variant_of,
                    "reason": "low_frequency",
                    "effect": "Preserved and visible; contributes nothing to any aggregate.",
                    "example_verses": inv["example_verses"],
                }
            )

    if unmapped:
        raise LedgerError(
            "UNMAPPED LABELS - every label in the inventory needs a ledger row.\n  "
            + "\n  ".join(unmapped[:40])
            + (f"\n  ... and {len(unmapped) - 40} more" if len(unmapped) > 40 else "")
        )

    independent_rows = [r for r in rows if r["independent_annotation_source"]]
    axis_counts: Counter[str] = Counter()
    for row in rows:
        for target in row["targets"]:
            axis_counts[target["axis"]] += 1

    ledger = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "generated_by": "processed/enrichment/build_ledger.py",
        "taxonomy_version": taxonomy.version,
        "policy": {
            "reversibility": (
                "Every row preserves the source label verbatim alongside its mapping, so the "
                "corpus can be re-derived forward and any enrichment value can be traced back to "
                "the labels that contributed to it."
            ),
            "corpus_untouched": (
                "Applying this ledger is a join at read time. No value in "
                "unified_scripture_corpus.jsonl is altered, and spelling variants keep the "
                "source's own spelling."
            ),
            "forbidden_axes": sorted(FORBIDDEN_AXES),
            "forbidden_axes_reason": (
                "Source annotations describe what the text expresses. None of them measures which "
                "user state a verse serves, and none is entitled to certify pastoral suitability. "
                "Both prohibitions are asserted at build time."
            ),
            "approval": (
                "Rows are emitted as `proposed`. A row carries evidence weight only once a human "
                "reviewer sets status to `approved`."
            ),
        },
        "totals": {
            "rows": len(rows),
            "rows_independent_sources": len(independent_rows),
            "rows_derived_sources": len(rows) - len(independent_rows),
            "quarantined": len(quarantined),
            "targets_by_axis": dict(sorted(axis_counts.items())),
            "rows_by_method": dict(sorted(method_counts.items())),
            "rows_by_status": dict(sorted(Counter(r["status"] for r in rows).items())),
            "rows_by_tier": dict(sorted(Counter(r["source_evidence_tier"] for r in rows).items())),
        },
        "rows": rows,
    }

    quarantine = {
        "quarantine_version": LEDGER_SCHEMA_VERSION,
        "generated_by": "processed/enrichment/build_ledger.py",
        "policy": (
            "Labels here are preserved and visible but contribute nothing to any aggregate. "
            "Nothing is deleted or corrected in the corpus. Quarantine is a decision recorded "
            "for review, not a repair."
        ),
        "low_frequency_threshold": inventory["anomaly_summary"]["low_frequency_threshold"],
        "count": len(quarantined),
        "entries": quarantined,
    }
    return ledger, quarantine


def main() -> int:
    mv.setup_stdout()
    before = mv.phase0_digests()
    ledger, quarantine = build()
    mv.write_json(LEDGER_OUT, ledger)
    mv.write_json(QUARANTINE_OUT, quarantine)
    mv.assert_phase0_unchanged(before, mv.phase0_digests())

    totals = ledger["totals"]
    print(f"ledger -> {LEDGER_OUT.relative_to(mv.BASE)}")
    print(f"  rows                 {totals['rows']}")
    print(f"  independent sources  {totals['rows_independent_sources']}")
    print(f"  derived (weight 0)   {totals['rows_derived_sources']}")
    print(f"  quarantined          {totals['quarantined']}")
    print(f"  by status            {totals['rows_by_status']}")
    print(f"  by method            {totals['rows_by_method']}")
    print(f"  targets by axis      {totals['targets_by_axis']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
