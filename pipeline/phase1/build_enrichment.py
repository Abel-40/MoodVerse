"""Assemble the enrichment layer.

REPLAY DETERMINISM is the contract this file exists to honour:

    build_enrichment.py is a PURE FUNCTION of
        (corpus + taxonomy + ledger + priors + recorded annotation runs + overrides)
    producing a byte-identical enrichment.jsonl on every re-run,
    WITHOUT issuing a single API call.

Annotation runs are recorded once by annotate.py and replayed here. That splits
the phase into a deterministic half and a recorded half, so everything except
the model calls is reproducible in the way Phase 0 is.

Nothing in processed/ outside enrichment/ is ever written. Phase 0 artefacts are
hashed before and after and the run fails if any digest moved.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import curation
import mv_common as mv

ENRICHMENT_SCHEMA_VERSION = "phase1-1"
PIPELINE_VERSION = "1.0.0"

LEDGER = mv.ENRICHMENT / "mappings" / "source_label_ledger.json"
PRIORS = mv.ENRICHMENT / "priors" / "deterministic_priors.jsonl"
RUNS_DIR = mv.ENRICHMENT / "annotation" / "runs"
OVERRIDES = mv.ENRICHMENT / "curation" / "overrides.jsonl"

OUT_ENRICHMENT = mv.ENRICHMENT / "curation" / "enrichment.jsonl"
OUT_DECISIONS = mv.ENRICHMENT / "curation" / "decisions.jsonl"
OUT_QUEUE = mv.ENRICHMENT / "curation" / "review_queue.json"

# Priors may shift an assessed field by at most this many ordinal levels, in
# total, for either religion. Different prior SETS are unavoidable; different
# prior STRENGTH is not acceptable.
MAX_PRIOR_SHIFT = 1


def load_ledger(taxonomy: mv.Taxonomy, bootstrap: bool) -> dict[tuple[str, str, str], dict]:
    """Ledger rows keyed by (source, annotation_type, label).

    Only `approved` rows carry evidence weight. `--bootstrap` additionally
    accepts `proposed` rows so the pipeline can be exercised end to end before a
    human has reviewed 501 mapping decisions; it is recorded on every affected
    record so no bootstrap value can be mistaken for a reviewed one.
    """
    ledger = mv.read_json(LEDGER)
    accepted = {"approved"} | ({"proposed"} if bootstrap else set())
    rows: dict[tuple[str, str, str], dict] = {}
    for row in ledger["rows"]:
        if row["status"] not in accepted:
            continue
        if not row["independent_annotation_source"]:
            continue  # derived duplicates never contribute
        rows[(row["source"], row["source_annotation_type"], row["source_label"])] = row
    return rows


def load_priors() -> dict[str, dict]:
    return {row["canonical_id"]: row for row in mv.read_jsonl(PRIORS)}


def load_annotations() -> tuple[dict[str, list[dict]], list[str]]:
    """Every recorded model response, grouped by canonical_id, in run order."""
    by_id: dict[str, list[dict]] = defaultdict(list)
    run_ids: list[str] = []
    if not RUNS_DIR.exists():
        return by_id, run_ids
    for run_dir in sorted(p for p in RUNS_DIR.iterdir() if p.is_dir()):
        responses = run_dir / "responses.jsonl"
        if not responses.exists():
            continue
        run_ids.append(run_dir.name)
        for response in mv.read_jsonl(responses):
            cid = response.get("canonical_id")
            if cid:
                response["_run_id"] = run_dir.name
                by_id[cid].append(response)
    return by_id, run_ids


def load_overrides() -> dict[str, dict[str, Any]]:
    """Human overrides, append-only; the last entry per (id, field) wins.

    Overrides are stored ALONGSIDE the AI value, never replacing it, so the pair
    is a free per-field error measurement and every edit stays reversible.
    """
    overrides: dict[str, dict[str, Any]] = defaultdict(dict)
    if OVERRIDES.exists():
        for entry in mv.read_jsonl(OVERRIDES):
            overrides[entry["canonical_id"]][entry["field"]] = entry
    return overrides


def apply_ledger(record: dict, rows: dict, taxonomy: mv.Taxonomy) -> dict[str, Any]:
    """Source-derived evidence for one record. Read-time join; corpus untouched."""
    affect: Counter[str] = Counter()
    themes: Counter[str] = Counter()
    purpose_priors: Counter[str] = Counter()
    revelation = "unstated"
    evidence: list[dict] = []

    for annotation in mv.independent_annotations(record):
        key = (annotation["source"], annotation["annotation_type"], annotation["value"])
        row = rows.get(key)
        if not row:
            continue
        weight = row["evidence_weight"]
        for target in row["targets"]:
            axis, value = target["axis"], target["value"]
            contribution = weight * target["confidence"]
            if axis == "expressed_affect":
                affect[value] += contribution
            elif axis == "theme":
                themes[value] += contribution
            elif axis == "scripture_purpose_prior":
                purpose_priors[value] += contribution
            elif axis == "structural" and value and value.startswith("revelation_period="):
                revelation = value.split("=", 1)[1]
        evidence.append(
            {
                "source": row["source"],
                "annotation_type": row["source_annotation_type"],
                "label": row["source_label"],
                "mapping_id": row["mapping_id"],
                "tier": row["source_evidence_tier"],
                "weight": weight,
                "status": row["status"],
            }
        )

    return {
        "expressed_affect_evidence": [k for k, _ in affect.most_common()],
        "theme_evidence": [k for k, _ in themes.most_common(8)],
        "purpose_prior_evidence": [k for k, _ in purpose_priors.most_common(3)],
        "revelation_period": revelation,
        "source_labels": evidence,
    }


def clamp_nudges(priors: list[dict]) -> dict[str, int]:
    """Net prior shift per field, capped at +/-MAX_PRIOR_SHIFT."""
    net: Counter[str] = Counter()
    for prior in priors:
        net[prior["field"]] += prior["nudge"]
    return {
        field: max(-MAX_PRIOR_SHIFT, min(MAX_PRIOR_SHIFT, value))
        for field, value in sorted(net.items())
        if value
    }


def reconcile(responses: list[dict]) -> tuple[dict, int, list[str]]:
    """Merge >=1 annotation passes. Disagreement is recorded, never averaged.

    The first pass is authoritative for values; later passes are compared
    against it. The largest ordinal disagreement on any score is returned and
    routes the record to review at >=2.
    """
    if not responses:
        return {}, 0, []
    primary = responses[0]
    if len(responses) == 1:
        return primary, 0, [primary.get("_run_id", "")]

    def score_map(response: dict) -> dict[str, int]:
        out = {
            "standalone_usefulness": response.get("standalone_usefulness"),
            "context_dependency": (response.get("context_dependency") or {}).get("level"),
            "isolation_risk": (response.get("isolation_risk") or {}).get("level"),
        }
        for intent, block in (response.get("purpose_suitability") or {}).items():
            out[f"purpose:{intent}"] = (block or {}).get("score")
        for state in response.get("addressed_states") or []:
            out[f"state:{state.get('state')}"] = state.get("emotional_relevance")
        return {k: v for k, v in out.items() if isinstance(v, int)}

    base = score_map(primary)
    worst = 0
    for other in responses[1:]:
        for field, value in score_map(other).items():
            if field in base:
                worst = max(worst, abs(base[field] - value))
    return primary, worst, [r.get("_run_id", "") for r in responses]


def build(bootstrap: bool) -> tuple[list[dict], list[dict], dict]:
    taxonomy = mv.Taxonomy()
    rows = load_ledger(taxonomy, bootstrap)
    priors_by_id = load_priors()
    annotations, run_ids = load_annotations()
    overrides = load_overrides()

    enrichment: list[dict] = []
    decisions: list[dict] = []
    status_counts: Counter[tuple[str, str]] = Counter()
    rule_counts: Counter[str] = Counter()

    for record in mv.iter_corpus():
        cid = record["canonical_id"]
        religion = record["religion"]
        text, text_source = mv.display_text(record)
        prior_row = priors_by_id.get(cid, {"priors": [], "features": {}})
        derived = apply_ledger(record, rows, taxonomy)
        responses = annotations.get(cid, [])
        annotation, disagreement, used_runs = reconcile(responses)

        needs_display_decision = bool(record["text"].get("original_variants"))

        item: dict[str, Any] = {
            "canonical_id": cid,
            "religion": religion,
            "enrichment_schema_version": ENRICHMENT_SCHEMA_VERSION,
            "taxonomy_version": taxonomy.version,
            "pipeline_version": PIPELINE_VERSION,
            "corpus_text_sha256": mv.sha256_text(text),
            "display_text_ref": {
                "text_source": text_source,
                "original_source": record["text"].get("original_source", record["text"].get("source")),
                "decision": "deterministic_default" if not needs_display_decision else "undecided",
                "decided_by": "deterministic_rule",
                "note": (
                    "Sources disagree on this verse's original text; which reading is displayed is "
                    "a content decision that has not been made."
                    if needs_display_decision
                    else None
                ),
            },
            # ---- annotation-layer fields (empty until a run exists) ----
            "expressed_affect": annotation.get("expressed_affect"),
            "addressed_states": annotation.get("addressed_states"),
            "primary_addressed_state": (
                (annotation.get("addressed_states") or [{}])[0].get("state")
                if annotation.get("addressed_states")
                else None
            ),
            "serves_intensity": annotation.get("serves_intensity"),
            "nuance_terms": annotation.get("nuance_terms") or [],
            "themes": annotation.get("themes"),
            "intents": annotation.get("intents"),
            "scripture_purpose": annotation.get("scripture_purpose"),
            "situations": annotation.get("situations"),
            "revelation_period": derived["revelation_period"],
            "standalone_usefulness": annotation.get("standalone_usefulness"),
            "context_dependency": annotation.get("context_dependency"),
            "requires_context": (
                (annotation.get("context_dependency") or {}).get("level", 0) >= 2
                if annotation
                else None
            ),
            "recommended_context_span": annotation.get("recommended_context_span"),
            "isolation_risk": annotation.get("isolation_risk"),
            "purpose_suitability": annotation.get("purpose_suitability"),
            "safety": annotation.get("safety"),
            # ---- provenance, evidence, review ----
            "prior_nudges": clamp_nudges(prior_row["priors"]),
            "prior_rules_applied": [p["rule_id"] for p in prior_row["priors"]],
            "evidence": {
                "source_labels": derived["source_labels"],
                "expressed_affect_evidence": derived["expressed_affect_evidence"],
                "theme_evidence": derived["theme_evidence"],
                "purpose_prior_evidence": derived["purpose_prior_evidence"],
                "deterministic_priors": [p["rule_id"] for p in prior_row["priors"]],
                "source_disagreements": annotation.get("source_disagreements") or [],
                # Bible-only by construction. Null for every Quran record, and the
                # cascade may not read it - see priors/prior_rules.md.
                "cross_reference_context": (
                    prior_row["features"].get("xref") if religion == "bible" else None
                ),
            },
            "provenance": {},
            "model_rationale": annotation.get("model_rationale"),
            "notes": None,
            "review": {"state": "unreviewed", "reviewer": None, "notes": None},
            "phase0_data_quality": record["data_quality"],
            "curation": {},
            # internal, stripped before writing
            "_annotated": bool(annotation),
            "_max_pass_disagreement": disagreement,
            "_needs_display_decision": needs_display_decision,
            "_low_kappa_fields": [],
        }

        # provenance per field group
        if derived["source_labels"]:
            item["provenance"]["evidence"] = {
                "method": "source_derived",
                "ledger_rows": len(derived["source_labels"]),
                "bootstrap": bootstrap,
            }
        if prior_row["priors"]:
            item["provenance"]["prior_nudges"] = {
                "method": "deterministic_rule",
                "rules": [p["rule_id"] for p in prior_row["priors"]],
            }
        if annotation:
            method = "ai_reviewed" if len(responses) >= 2 else "ai_generated"
            for field in (
                "expressed_affect", "addressed_states", "themes", "intents",
                "scripture_purpose", "situations", "standalone_usefulness",
                "context_dependency", "isolation_risk", "purpose_suitability", "safety",
            ):
                item["provenance"][field] = {"method": method, "run_ids": used_runs}

        # confidence band, from pipeline evidence only
        item["curation"]["curation_confidence"] = confidence_band(
            item, responses, derived, taxonomy
        )

        # human overrides, applied last, recorded not replacing
        applied = overrides.get(cid, {})
        if applied:
            item["review"]["state"] = "human_reviewed"
            item["_overrides"] = []
            for field, entry in sorted(applied.items()):
                item["_overrides"].append(
                    {"field": field, "ai_value": item.get(field), "human_value": entry["value"]}
                )
                item[field] = entry["value"]
                item["provenance"][field] = {
                    "method": "human_reviewed",
                    "reviewer": entry.get("reviewer"),
                    "reviewed_at": entry.get("reviewed_at"),
                    "supersedes": entry.get("supersedes"),
                }
            item["curation"]["curation_confidence"] = max(
                item["curation"]["curation_confidence"] or 0, 0.80
            )

        status, rule_id, explanation = curation.decide(item, taxonomy.hard_exclusion_speakers)
        item["curation"].update(
            {
                "status": status,
                "rule_fired": rule_id,
                "explanation": explanation,
                "decided_at": None,  # set only on release, keeps rebuilds byte-identical
            }
        )
        item["serving_constraints"] = curation.serving_constraints(item)

        decisions.append(
            {
                "canonical_id": cid,
                "religion": religion,
                "status": status,
                "rule_fired": rule_id,
                "explanation": explanation,
                "curation_confidence": item["curation"]["curation_confidence"],
                "annotated": item["_annotated"],
            }
        )
        status_counts[(religion, status)] += 1
        rule_counts[rule_id] += 1

        for key in list(item):
            if key.startswith("_"):
                item.pop(key)
        enrichment.append(item)

    stats = {
        "records": len(enrichment),
        "run_ids": run_ids,
        "bootstrap_mode": bootstrap,
        "ledger_rows_active": len(rows),
        "status_by_religion": {
            religion: {
                status: status_counts[(religion, status)]
                for status in sorted({s for r, s in status_counts if r == religion})
            }
            for religion in ("bible", "quran")
        },
        "rules_fired": dict(sorted(rule_counts.items())),
    }
    return enrichment, decisions, stats


def confidence_band(
    item: dict, responses: list[dict], derived: dict, taxonomy: mv.Taxonomy
) -> float | None:
    """Confidence from PIPELINE evidence, deliberately near-blind to sources.

    A model's self-reported certainty never reaches this value. The one
    source-dependent band is capped: expert-tier (ELQV) agreement may raise
    confidence by a single band, and only on expressed_affect, because that is
    the only axis ELQV measures. Every other axis ignores sources entirely -
    otherwise the Quran's richer annotation would buy it higher confidence than
    the Bible can ever earn, which is the asymmetry this design exists to stop.
    """
    if not responses:
        return None
    if len(responses) >= 2:
        band = 0.60
    else:
        corroborated = bool(item["prior_nudges"]) or bool(derived["source_labels"])
        band = 0.40 if corroborated else 0.20
        expert = any(
            label["tier"] == "expert_human" for label in derived["source_labels"]
        )
        affect = (responses[0].get("expressed_affect") or {}).get("primary")
        if expert and affect and affect in derived["expressed_affect_evidence"]:
            band = 0.60
    return band


def build_review_queue(enrichment: list[dict]) -> dict:
    """Prioritised review worklist. Highest user exposure first."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for item in enrichment:
        if item["curation"]["status"] != curation.REVIEW:
            continue
        rule = item["curation"]["rule_fired"]
        states = {s.get("state") for s in (item.get("addressed_states") or [])}
        if rule in ("gate1.relevance_suitability_tension", "gate1.self_contradictory"):
            buckets["p1_would_otherwise_be_included"].append(item["canonical_id"])
        elif states & {"despair", "grief"}:
            buckets["p2_crisis_relevant"].append(item["canonical_id"])
        elif item["evidence"]["source_disagreements"]:
            buckets["p3_source_disagreement"].append(item["canonical_id"])
        elif item["phase0_data_quality"]["status"] != "valid":
            buckets["p4_phase0_flagged"].append(item["canonical_id"])
        else:
            buckets["p5_awaiting_annotation"].append(item["canonical_id"])

    return {
        "review_queue_version": "1.0.0",
        "generated_by": "processed/enrichment/build_enrichment.py",
        "max_age_days": curation.REVIEW_MAX_AGE_DAYS,
        "priority_order": [
            "p1_would_otherwise_be_included",
            "p2_crisis_relevant",
            "p3_source_disagreement",
            "p4_phase0_flagged",
            "p5_awaiting_annotation",
        ],
        "counts": {k: len(v) for k, v in sorted(buckets.items())},
        "total": sum(len(v) for v in buckets.values()),
        # ids are capped per bucket so the file stays reviewable at 37k records
        "sample_ids": {k: sorted(v)[:200] for k, v in sorted(buckets.items())},
    }


def main() -> int:
    mv.setup_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="accept `proposed` ledger rows as well as `approved`, so the pipeline can be "
             "exercised before a human has reviewed all 501 mapping rows. Recorded on every "
             "affected record.",
    )
    args = parser.parse_args()

    before = mv.phase0_digests()
    enrichment, decisions, stats = build(args.bootstrap)
    mv.write_jsonl(OUT_ENRICHMENT, enrichment)
    mv.write_jsonl(OUT_DECISIONS, decisions)
    mv.write_json(OUT_QUEUE, build_review_queue(enrichment))
    mv.assert_phase0_unchanged(before, mv.phase0_digests())

    print(f"enrichment -> {OUT_ENRICHMENT.relative_to(mv.BASE)}")
    print(f"  records              {stats['records']:,}")
    print(f"  annotation runs      {stats['run_ids'] or '(none yet)'}")
    print(f"  ledger rows active   {stats['ledger_rows_active']}"
          f"{'  [BOOTSTRAP]' if args.bootstrap else ''}")
    for religion, counts in stats["status_by_religion"].items():
        print(f"  {religion}: {counts}")
    print("  rules fired:")
    for rule_id, count in stats["rules_fired"].items():
        print(f"    {rule_id:44s} {count:7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
