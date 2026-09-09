"""Validate the enrichment layer and emit the four reports.

    validation/enrichment_validation_report.json   structural + integrity checks
    validation/parity_report.json                  Bible/Quran asymmetry metrics
    validation/coverage_report.json                (state x intent x religion) matrix
    validation/agreement_report.json               gold-set kappa, when a gold set exists

Structural checks are pass/fail. Parity and coverage are REPORTED, not enforced:
a gap is surfaced as a gap rather than silently passing, because the remedy is
targeted annotation, never a lowered bar for the scarce side.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import curation
import mv_common as mv

ENRICH = mv.ENRICHMENT / "curation" / "enrichment.jsonl"
LEDGER = mv.ENRICHMENT / "mappings" / "source_label_ledger.json"
GOLD = mv.ENRICHMENT / "curation" / "gold_set.jsonl"

OUT_VALIDATION = mv.ENRICHMENT / "validation" / "enrichment_validation_report.json"
OUT_PARITY = mv.ENRICHMENT / "validation" / "parity_report.json"
OUT_COVERAGE = mv.ENRICHMENT / "validation" / "coverage_report.json"
OUT_AGREEMENT = mv.ENRICHMENT / "validation" / "agreement_report.json"

# Minimum INCLUDE-status verses each religion must supply for each product
# purpose before the corpus is fit to serve. A failing cell is a gap to fill,
# not a threshold to lower.
PARITY_MIN_PER_PURPOSE = 20

PRODUCT_PURPOSES = [
    "comfort", "hope", "encouragement", "peace", "guidance", "strength",
    "patience", "gratitude", "praise", "repentance", "forgiveness", "wisdom",
    "perseverance",
]


def validate() -> dict:
    taxonomy = mv.Taxonomy()
    ledger = mv.read_json(LEDGER)
    corpus_ids = {r["canonical_id"]: r for r in mv.iter_corpus()}

    checks: dict[str, dict] = {}
    seen: set[str] = set()
    duplicates: list[str] = []
    orphans: list[str] = []
    missing_keys: list[str] = []
    bad_enum: list[str] = []
    bad_ordinal: list[str] = []
    bad_confidence: list[str] = []
    text_drift: list[str] = []
    bad_span: list[str] = []
    quran_xref: list[str] = []
    derived_leak: list[str] = []
    conditional: list[str] = []
    unreviewed_flagged: list[str] = []

    required = {
        "canonical_id", "religion", "enrichment_schema_version", "taxonomy_version",
        "pipeline_version", "corpus_text_sha256", "evidence", "provenance", "curation",
        "phase0_data_quality", "serving_constraints",
    }

    for item in mv.read_jsonl(ENRICH):
        cid = item["canonical_id"]
        if cid in seen:
            duplicates.append(cid)
        seen.add(cid)

        record = corpus_ids.get(cid)
        if record is None:
            orphans.append(cid)
            continue
        if not required <= set(item):
            missing_keys.append(cid)

        # 4. corpus text drift
        text, _ = mv.display_text(record)
        if item["corpus_text_sha256"] != mv.sha256_text(text):
            text_drift.append(cid)

        # 2. enum closure
        for theme in item.get("themes") or []:
            if theme not in taxonomy.themes:
                bad_enum.append(f"{cid}:theme:{theme}")
        for intent in item.get("intents") or []:
            if intent not in taxonomy.intents:
                bad_enum.append(f"{cid}:intent:{intent}")
        for situation in item.get("situations") or []:
            if situation not in taxonomy.situations:
                bad_enum.append(f"{cid}:situation:{situation}")
        if item["curation"].get("status") not in taxonomy.curation_statuses:
            bad_enum.append(f"{cid}:status:{item['curation'].get('status')}")
        if item.get("revelation_period") not in taxonomy.revelation_periods:
            bad_enum.append(f"{cid}:revelation_period:{item.get('revelation_period')}")

        # 3. ordinal ranges and confidence bands
        standalone = item.get("standalone_usefulness")
        if standalone is not None and standalone not in taxonomy.score_levels:
            bad_ordinal.append(f"{cid}:standalone:{standalone}")
        level = (item.get("context_dependency") or {}).get("level")
        if level is not None and level not in taxonomy.context_levels:
            bad_ordinal.append(f"{cid}:context:{level}")
        isolation = (item.get("isolation_risk") or {}).get("level")
        if isolation is not None and isolation not in taxonomy.isolation_levels:
            bad_ordinal.append(f"{cid}:isolation:{isolation}")
        confidence = item["curation"].get("curation_confidence")
        if confidence is not None and confidence not in taxonomy.confidence_bands:
            bad_confidence.append(f"{cid}:{confidence}")

        # 5. conditional requirements on the assembled record
        if level is not None and level >= 2 and not (item.get("context_dependency") or {}).get("reasons"):
            conditional.append(f"{cid}:context>=2 without reasons")
        if isolation is not None and isolation >= 2 and not (item.get("isolation_risk") or {}).get("explanation"):
            conditional.append(f"{cid}:isolation>=2 without explanation")
        for purpose in item.get("scripture_purpose") or []:
            if purpose.get("purpose") == "reported_speech" and not purpose.get("speaker_role"):
                conditional.append(f"{cid}:reported_speech without speaker_role")

        # 6. context span resolves to real ids in the same book/surah
        span = item.get("recommended_context_span")
        if span:
            for endpoint in ("start_canonical_id", "end_canonical_id"):
                value = span.get(endpoint)
                if value not in corpus_ids:
                    bad_span.append(f"{cid}:{endpoint}:{value}")
                elif value.rsplit(":", 2)[0] != cid.rsplit(":", 2)[0]:
                    bad_span.append(f"{cid}:{endpoint} crosses book/surah")

        # 13. Bible-only xref feature must be null for every Quran record
        if item["religion"] == "quran" and item["evidence"]["cross_reference_context"] is not None:
            quran_xref.append(cid)

        # 9. derived sources contribute nothing
        for label in item["evidence"]["source_labels"]:
            if label["source"] in ("Only TCEC cols", "ELQVv2") or label["weight"] == 0.0:
                if label["weight"] != 0.0:
                    derived_leak.append(f"{cid}:{label['source']}")

        # 14. Phase 0 flagged records must be routed to review
        if item["phase0_data_quality"]["status"] != "valid":
            if item["curation"]["status"] != curation.REVIEW and item["review"]["state"] == "unreviewed":
                unreviewed_flagged.append(cid)

    missing_records = sorted(set(corpus_ids) - seen)

    def result(name: str, failures: list, note: str) -> None:
        checks[name] = {
            "passed": not failures,
            "failures": len(failures),
            "examples": sorted(failures)[:10],
            "note": note,
        }

    result("all_corpus_records_present", missing_records, "Every Phase 0 record has an enrichment record.")
    result("no_duplicates", duplicates, "No canonical_id appears twice.")
    result("no_orphans", orphans, "No enrichment record lacks a corpus record.")
    result("required_keys_present", missing_keys, "Every record carries the required top-level keys.")
    result("enum_closure", bad_enum, f"Every value exists in taxonomy {taxonomy.version}.")
    result("ordinal_ranges", bad_ordinal, "Every ordinal is within its declared scale.")
    result("confidence_banded", bad_confidence, f"Confidence is one of {taxonomy.confidence_bands}.")
    result("corpus_text_not_drifted", text_drift, "corpus_text_sha256 matches the Phase 0 text.")
    result("context_spans_resolve", bad_span, "Every context span endpoint is a real id in the same book/surah.")
    result("conditional_requirements", conditional, "Reasons, explanations and speaker roles present where required.")
    result("quran_cross_reference_null", quran_xref, "cross_reference_context is null for all 6,236 Quran records.")
    result("derived_sources_zero_weight", derived_leak, "Only TCEC cols and ELQVv2 contribute nothing.")
    result("phase0_flagged_routed_to_review", unreviewed_flagged, "Phase 0 warning/unresolved records are reviewed before serving.")

    # ledger-level integrity
    bad_axis = [
        r["mapping_id"] for r in ledger["rows"]
        for t in r["targets"]
        if t["axis"] in {"addressed_states", "addresses_states", "intent", "purpose_suitability"}
    ]
    result("no_source_label_targets_forbidden_axis", bad_axis,
           "No source label maps to addressed_states, intent or any suitability field.")

    return {
        "validation_report_version": "1.0.0",
        "generated_by": "processed/enrichment/validate.py",
        "taxonomy_version": taxonomy.version,
        "enrichment_records": len(seen),
        "corpus_records": len(corpus_ids),
        "all_passed": all(c["passed"] for c in checks.values()),
        "checks": checks,
    }


def parity_and_coverage() -> tuple[dict, dict]:
    """Bible/Quran parity metrics and the (state x intent x religion) matrix."""
    by_religion: dict[str, Counter] = defaultdict(Counter)
    confidence: dict[str, list[float]] = defaultdict(list)
    scores: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    purpose_include: dict[str, Counter] = defaultdict(Counter)
    matrix: dict[str, Counter] = defaultdict(Counter)
    annotated: Counter = Counter()
    totals: Counter = Counter()

    for item in mv.read_jsonl(ENRICH):
        religion = item["religion"]
        totals[religion] += 1
        status = item["curation"]["status"]
        by_religion[religion][status] += 1
        value = item["curation"].get("curation_confidence")
        if value is not None:
            confidence[religion].append(value)
            annotated[religion] += 1
        if item.get("standalone_usefulness") is not None:
            scores[religion]["standalone_usefulness"].append(item["standalone_usefulness"])
        if (item.get("context_dependency") or {}).get("level") is not None:
            scores[religion]["context_dependency"].append(item["context_dependency"]["level"])
        if status in (curation.INCLUDE, curation.INCLUDE_WITH_CONTEXT):
            for intent, block in (item.get("purpose_suitability") or {}).items():
                if (block or {}).get("score", 0) >= 3:
                    purpose_include[religion][intent] += 1
            for state in item.get("addressed_states") or []:
                if (state.get("emotional_relevance") or 0) >= 3:
                    for intent in item.get("intents") or []:
                        matrix[religion][f"{state['state']}|{intent}"] += 1

    gaps = []
    coverage_table = {}
    for purpose in PRODUCT_PURPOSES:
        row = {r: purpose_include[r].get(purpose, 0) for r in ("bible", "quran")}
        coverage_table[purpose] = row
        for religion, count in row.items():
            if count < PARITY_MIN_PER_PURPOSE:
                gaps.append(
                    {
                        "purpose": purpose,
                        "religion": religion,
                        "include_verses": count,
                        "required": PARITY_MIN_PER_PURPOSE,
                        "shortfall": PARITY_MIN_PER_PURPOSE - count,
                    }
                )

    def mean(values: list) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    parity = {
        "parity_report_version": "1.0.0",
        "generated_by": "processed/enrichment/validate.py",
        "why": (
            "If enrichment quality tracked source-annotation density, Quran verses would win "
            "retrieval slots because they are better documented, not because they are better "
            "answers. These metrics exist to detect that, and a failing cell is filled by "
            "targeted annotation - never by lowering the bar for the scarce side."
        ),
        "minimum_include_per_purpose": PARITY_MIN_PER_PURPOSE,
        "records": dict(totals),
        "annotated": dict(annotated),
        "annotation_coverage": {
            r: round(annotated[r] / totals[r], 4) if totals[r] else 0.0 for r in totals
        },
        "status_distribution": {r: dict(c) for r, c in by_religion.items()},
        "mean_curation_confidence": {r: mean(v) for r, v in confidence.items()},
        "mean_scores": {
            r: {field: mean(values) for field, values in fields.items()}
            for r, fields in scores.items()
        },
        "purpose_coverage": coverage_table,
        "gaps": gaps,
        "gate_passed": not gaps,
        "note": (
            "gate_passed is false while the corpus is unannotated. That is the correct reading of "
            "an empty corpus, not a failure of the metric."
        ),
    }

    coverage = {
        "coverage_report_version": "1.0.0",
        "generated_by": "processed/enrichment/validate.py",
        "description": "(user state x reflection intent x religion) cells with >=1 eligible verse.",
        "cells": {r: dict(sorted(c.items())) for r, c in matrix.items()},
        "cells_populated": {r: len(c) for r, c in matrix.items()},
    }
    return parity, coverage


def agreement() -> dict:
    """Gold-set agreement. Reports honestly that it cannot be measured yet."""
    if not GOLD.exists():
        return {
            "agreement_report_version": "1.0.0",
            "generated_by": "processed/enrichment/validate.py",
            "gold_set_present": False,
            "measurable": False,
            "weighted_kappa": {},
            "note": (
                "No gold set exists, so per-field agreement cannot be measured. Until it can, no "
                "field's reliability is known, and the trust threshold in the cascade "
                "(gate1.field_below_agreement_threshold) has nothing to act on. Building the gold "
                "set requires human annotators - decision 12 in PHASE1A_DESIGN.md."
            ),
            "required_before_production": True,
        }
    return {
        "agreement_report_version": "1.0.0",
        "gold_set_present": True,
        "measurable": False,
        "note": "Gold set present but scoring is not implemented until annotations exist.",
    }


def main() -> int:
    mv.setup_stdout()
    before = mv.phase0_digests()
    report = validate()
    parity, coverage = parity_and_coverage()
    mv.write_json(OUT_VALIDATION, report)
    mv.write_json(OUT_PARITY, parity)
    mv.write_json(OUT_COVERAGE, coverage)
    mv.write_json(OUT_AGREEMENT, agreement())
    mv.assert_phase0_unchanged(before, mv.phase0_digests())

    print(f"validation -> {OUT_VALIDATION.relative_to(mv.BASE)}")
    print(f"  records checked   {report['enrichment_records']:,} / {report['corpus_records']:,}")
    failed = [name for name, c in report["checks"].items() if not c["passed"]]
    for name, check in report["checks"].items():
        mark = "ok  " if check["passed"] else "FAIL"
        print(f"    [{mark}] {name}"
              + (f"  ({check['failures']} failures, e.g. {check['examples'][:2]})"
                 if not check["passed"] else ""))
    print(f"  all passed: {report['all_passed']}")
    print(f"parity -> annotation coverage {parity['annotation_coverage']}, "
          f"{len(parity['gaps'])} purpose gaps, gate_passed={parity['gate_passed']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
