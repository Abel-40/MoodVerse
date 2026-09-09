"""Phase 1 test suite. Standard library only; run with `python tests/test_phase1.py`.

Covers the 18 tests specified in PHASE1A_DESIGN.md section 12.5. Tests that
require a recorded annotation run are marked SKIP until one exists, and say so
rather than silently passing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENRICHMENT = HERE.parent
sys.path.insert(0, str(ENRICHMENT))

import build_ledger  # noqa: E402
import build_priors  # noqa: E402
import curation  # noqa: E402
import mv_common as mv  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, "PASS" if condition else "FAIL", detail))


def skip(name: str, why: str) -> None:
    RESULTS.append((name, "SKIP", why))


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def base_record(**overrides) -> dict:
    """A record that would reach INCLUDE, so each test can break one thing."""
    record = {
        "canonical_id": "bible:Test:1:1",
        "religion": "bible",
        "standalone_usefulness": 4,
        "context_dependency": {"level": 0, "reasons": []},
        "isolation_risk": {"level": 0, "kinds": [], "explanation": None},
        "purpose_suitability": {"comfort": {"score": 4, "basis": "x", "blockers": []}},
        "addressed_states": [{"state": "grief", "emotional_relevance": 4}],
        "scripture_purpose": [{"purpose": "declaration_about_god"}],
        "intents": ["comfort"],
        "safety": {"crisis_safe": True, "avoid_for_states": [], "content_advisories": []},
        "curation": {"curation_confidence": 0.80},
        "phase0_data_quality": {"status": "valid"},
        "recommended_context_span": None,
        "_annotated": True,
        "_max_pass_disagreement": 0,
        "_needs_display_decision": False,
        "_low_kappa_fields": [],
    }
    record.update(overrides)
    return record


SPEAKERS = frozenset({"adversary_or_negative_exemplar", "unattributed"})


def status_of(record: dict) -> tuple[str, str]:
    status, rule, _ = curation.decide(record, SPEAKERS)
    return status, rule


# ---------------------------------------------------------------------------
# 1. corpus immutability
# ---------------------------------------------------------------------------

def test_corpus_immutability() -> None:
    before = mv.phase0_digests()
    subprocess.run(
        [sys.executable, "build_label_inventory.py"], cwd=ENRICHMENT,
        capture_output=True, check=True,
    )
    after = mv.phase0_digests()
    changed = [k for k in before if before[k] != after.get(k)]
    check("1  corpus immutability", not changed, f"changed: {changed}" if changed else
          f"{len(before)} Phase 0 + raw source files unchanged")


# ---------------------------------------------------------------------------
# 2. replay determinism
# ---------------------------------------------------------------------------

def test_replay_determinism() -> None:
    target = ENRICHMENT / "curation" / "enrichment.jsonl"
    if not target.exists():
        skip("2  replay determinism", "enrichment.jsonl not built yet")
        return
    first = mv.sha256_file(target)
    subprocess.run(
        [sys.executable, "build_enrichment.py", "--bootstrap"], cwd=ENRICHMENT,
        capture_output=True, check=True,
    )
    second = mv.sha256_file(target)
    check("2  replay determinism", first == second,
          "byte-identical across two runs, zero API calls" if first == second
          else f"{first[:12]} != {second[:12]}")


# ---------------------------------------------------------------------------
# 3 & 4. ledger round-trip, both directions
# ---------------------------------------------------------------------------

def test_ledger_roundtrip() -> None:
    inventory = mv.read_json(ENRICHMENT / "mappings" / "label_inventory.json")
    ledger = mv.read_json(ENRICHMENT / "mappings" / "source_label_ledger.json")
    inv_keys = {(l["source"], l["annotation_type"], l["label"]) for l in inventory["labels"]}
    led_keys = {(r["source"], r["source_annotation_type"], r["source_label"]) for r in ledger["rows"]}
    check("3  ledger round-trip forward", inv_keys == led_keys,
          f"{len(inv_keys)} inventory labels, {len(led_keys)} ledger rows, "
          f"{len(inv_keys ^ led_keys)} unmatched")

    # backward: every row names the source, file and verbatim label it came from
    complete = [
        r for r in ledger["rows"]
        if r["source"] and r["source_label"] is not None and r["mapping_id"]
        and "source_file" in r and r["rationale"]
    ]
    check("4  ledger round-trip backward", len(complete) == len(ledger["rows"]),
          f"{len(complete)}/{len(ledger['rows'])} rows carry source, file, verbatim label, "
          "mapping_id and rationale")


# ---------------------------------------------------------------------------
# 5. direction rule
# ---------------------------------------------------------------------------

def test_direction_rule() -> None:
    taxonomy = mv.Taxonomy()
    blocked = []
    for axis in ("addressed_states", "intent", "purpose_suitability", "standalone_usefulness"):
        try:
            build_ledger.make_targets([(axis, "comfort", "exact", 0.9)], taxonomy)
        except SystemExit:
            blocked.append(axis)
    check("5  direction rule blocks forbidden axes", len(blocked) == 4,
          f"blocked {blocked}")

    # and taxonomy closure on the allowed axes
    closed = []
    for axis, bad in (("theme", "not_a_theme"), ("expressed_affect", "bereavement")):
        try:
            build_ledger.make_targets([(axis, bad, "exact", 0.9)], taxonomy)
        except SystemExit:
            closed.append(axis)
    check("14 taxonomy closure on ledger targets", len(closed) == 2, f"rejected {closed}")


# ---------------------------------------------------------------------------
# 6. vote independence
# ---------------------------------------------------------------------------

def test_vote_independence() -> None:
    """No enrichment field may be a function of cross-reference votes.

    Structural check rather than a 95 MB graph permutation: assert that neither
    the priors builder nor the enrichment builder ever reads the `votes` key.
    """
    offenders = []
    for name in ("build_priors.py", "build_enrichment.py", "curation.py"):
        text = (ENRICHMENT / name).read_text(encoding="utf-8")
        for marker in ('"votes"', "'votes'", "[\"votes\"]", "get('votes'"):
            if marker in text and "never read" not in text.split(marker)[0][-200:]:
                offenders.append(f"{name}:{marker}")
    check("6  vote independence", not offenders,
          "no builder reads the votes field" if not offenders else str(offenders))


# ---------------------------------------------------------------------------
# 7. derived-source exclusion
# ---------------------------------------------------------------------------

def test_derived_exclusion() -> None:
    ledger = mv.read_json(ENRICHMENT / "mappings" / "source_label_ledger.json")
    derived = [r for r in ledger["rows"] if not r["independent_annotation_source"]]
    weighted = [r for r in derived if r["evidence_weight"] != 0.0]
    check("7  derived sources carry zero weight", derived and not weighted,
          f"{len(derived)} derived rows (Only TCEC cols, ELQVv2), all weight 0.0")


# ---------------------------------------------------------------------------
# 8, 9, 10. cascade
# ---------------------------------------------------------------------------

CASES = [
    ("include", base_record(), curation.INCLUDE, "gate4.include"),
    ("unannotated", base_record(_annotated=False), curation.REVIEW, "gate1.not_annotated"),
    ("phase0 unresolved", base_record(phase0_data_quality={"status": "unresolved"}),
     curation.REVIEW, "gate1.phase0_data_quality"),
    ("low confidence", base_record(curation={"curation_confidence": 0.20}),
     curation.REVIEW, "gate1.low_confidence"),
    ("self-contradictory", base_record(isolation_risk={"level": 2}, standalone_usefulness=4),
     curation.REVIEW, "gate1.self_contradictory"),
    ("speech without speaker",
     base_record(scripture_purpose=[{"purpose": "reported_speech"}]),
     curation.REVIEW, "gate1.reported_speech_without_speaker"),
    ("relevance/suitability tension",
     base_record(scripture_purpose=[{"purpose": "warning_or_threat"}]),
     curation.REVIEW, "gate1.relevance_suitability_tension"),
    ("crisis safety unknown",
     base_record(safety={"crisis_safe": None, "avoid_for_states": [], "content_advisories": []}),
     curation.REVIEW, "gate1.crisis_safety_undetermined"),
    ("pass disagreement", base_record(_max_pass_disagreement=2),
     curation.REVIEW, "gate1.pass_disagreement"),
    ("undecided display text", base_record(_needs_display_decision=True),
     curation.REVIEW, "gate1.undecided_display_text"),
    ("low kappa field", base_record(_low_kappa_fields=["situations"]),
     curation.REVIEW, "gate1.field_below_agreement_threshold"),
    ("useless alone", base_record(standalone_usefulness=1),
     curation.EXCLUDE, "gate2.not_useful_alone"),
    ("severe isolation", base_record(isolation_risk={"level": 3}, standalone_usefulness=2),
     curation.EXCLUDE, "gate2.severe_isolation_risk"),
    ("frame dependent",
     base_record(context_dependency={"level": 4}, standalone_usefulness=2,
                 isolation_risk={"level": 1}),
     curation.EXCLUDE, "gate2.frame_dependent"),
    ("genealogy only",
     base_record(scripture_purpose=[{"purpose": "genealogy_or_record"}], standalone_usefulness=2),
     curation.EXCLUDE, "gate2.record_only"),
    ("adversary speaker",
     base_record(scripture_purpose=[
         {"purpose": "reported_speech", "speaker_role": "adversary_or_negative_exemplar"}],
         standalone_usefulness=3),
     curation.EXCLUDE, "gate2.negative_or_unattributed_speaker"),
    ("no suitable purpose",
     base_record(purpose_suitability={"comfort": {"score": 1, "blockers": ["could_increase_distress"]}}),
     curation.EXCLUDE, "gate2.no_suitable_purpose"),
    ("advisory without purpose",
     base_record(purpose_suitability={"comfort": {"score": 2}},
                 safety={"crisis_safe": True, "avoid_for_states": [],
                         "content_advisories": ["violence"]}),
     curation.EXCLUDE, "gate2.advisory_without_strong_purpose"),
    ("no state, weak purpose",
     base_record(addressed_states=[], purpose_suitability={"wisdom": {"score": 2}}),
     curation.EXCLUDE, "gate2.no_state_and_weak_purpose"),
    ("include with context",
     base_record(context_dependency={"level": 2, "reasons": ["referent_named_earlier"]},
                 standalone_usefulness=3,
                 recommended_context_span={"start_canonical_id": "bible:Test:1:1",
                                           "end_canonical_id": "bible:Test:1:3"}),
     curation.INCLUDE_WITH_CONTEXT, "gate3.include_with_context"),
    ("context span missing",
     base_record(context_dependency={"level": 3, "reasons": ["narrative_setup_required"]},
                 standalone_usefulness=3),
     curation.REVIEW, "gate3.context_span_missing"),
]


def test_cascade() -> None:
    failures = []
    for label, record, want_status, want_rule in CASES:
        got_status, got_rule = status_of(record)
        if (got_status, got_rule) != (want_status, want_rule):
            failures.append(f"{label}: got {got_status}/{got_rule}, want {want_status}/{want_rule}")
    check("8  cascade determinism", not failures,
          f"{len(CASES)} fixtures produce the expected status and rule"
          if not failures else "; ".join(failures))

    fired = {rule for _, record, _, _ in CASES for rule in [status_of(record)[1]]}
    gates = {r.split(".")[0] for r in fired}
    check("9  cascade coverage", gates >= {"gate1", "gate2", "gate3", "gate4"},
          f"gates exercised: {sorted(gates)}; {len(fired)} distinct rules")

    empty = {"canonical_id": "x", "religion": "bible", "curation": {}, "_annotated": False}
    status, rule = status_of(empty)
    check("10 default deny", status == curation.REVIEW,
          f"all-null record -> {status} via {rule}")


# ---------------------------------------------------------------------------
# 11, 12. response guards (exercised against the validator's own checks)
# ---------------------------------------------------------------------------

def test_response_guards() -> None:
    try:
        import annotate
    except ImportError:
        skip("11 hallucination guard", "annotate.py not present")
        skip("12 invented-reference guard", "annotate.py not present")
        return

    verse = "The LORD is nigh unto them that are of a broken heart."
    good = {
        "canonical_id": "bible:Psalms:34:18",
        "addressed_states": [{"state": "grief", "emotional_relevance": 4,
                              "evidence_span": "nigh unto them that are of a broken heart"}],
        "model_rationale": "Speaks directly to the brokenhearted.",
    }
    bad_span = json.loads(json.dumps(good))
    bad_span["addressed_states"][0]["evidence_span"] = "God will wipe away every tear"
    bad_ref = json.loads(json.dumps(good))
    bad_ref["model_rationale"] = "Compare John 3:16 for the same idea."

    ok_good = annotate.validate_response(good, "bible:Psalms:34:18", verse)
    ok_span = annotate.validate_response(bad_span, "bible:Psalms:34:18", verse)
    ok_ref = annotate.validate_response(bad_ref, "bible:Psalms:34:18", verse)

    check("11 hallucination guard", not ok_good and ok_span,
          f"verbatim span accepted, fabricated span rejected ({ok_span[:1]})")
    check("12 invented-reference guard", bool(ok_ref),
          f"rejected: {ok_ref[:1]}")


# ---------------------------------------------------------------------------
# 13, 16, 17. schema, asymmetry guard, encoding
# ---------------------------------------------------------------------------

def test_enrichment_records() -> None:
    path = ENRICHMENT / "curation" / "enrichment.jsonl"
    if not path.exists():
        skip("13 schema conformance", "enrichment.jsonl not built yet")
        skip("16 Quran xref nullity", "enrichment.jsonl not built yet")
        return
    taxonomy = mv.Taxonomy()
    required = {
        "canonical_id", "religion", "enrichment_schema_version", "taxonomy_version",
        "corpus_text_sha256", "evidence", "provenance", "curation", "phase0_data_quality",
    }
    corpus_ids = {r["canonical_id"] for r in mv.iter_corpus()}
    seen, missing, bad_status, quran_xref, orphans = set(), 0, 0, 0, 0
    for item in mv.read_jsonl(path):
        if not required <= set(item):
            missing += 1
        if item["curation"]["status"] not in taxonomy.curation_statuses:
            bad_status += 1
        if item["canonical_id"] not in corpus_ids:
            orphans += 1
        if item["religion"] == "quran" and item["evidence"]["cross_reference_context"] is not None:
            quran_xref += 1
        seen.add(item["canonical_id"])

    check("13 schema conformance",
          missing == 0 and bad_status == 0 and orphans == 0 and len(seen) == len(corpus_ids),
          f"{len(seen):,} records, {missing} missing required keys, {bad_status} bad statuses, "
          f"{orphans} orphans")
    check("16 Quran cross-reference nullity", quran_xref == 0,
          f"{6236 - quran_xref}/6236 Quran records have cross_reference_context = null")


def test_utf8_safety() -> None:
    """The pipeline must survive Arabic on a cp1252 console."""
    script = (
        "import sys; sys.path.insert(0, r'%s');"
        "import mv_common as mv; mv.setup_stdout();"
        "r=next(x for x in mv.iter_corpus() if x['religion']=='quran');"
        "print(r['text']['original'][:40])" % ENRICHMENT
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=ENRICHMENT,
        capture_output=True, env={"PYTHONIOENCODING": "cp1252", "PATH": ""},
    )
    check("17 UTF-8 safety on cp1252 console", proc.returncode == 0,
          "Arabic printed without UnicodeEncodeError"
          if proc.returncode == 0 else proc.stderr.decode("utf-8", "replace")[-200:])


# ---------------------------------------------------------------------------
# 15, 18. provenance monotonicity, parity gate
# ---------------------------------------------------------------------------

def test_provenance_monotonicity() -> None:
    taxonomy = mv.Taxonomy()
    ranks = taxonomy.method_rank
    ordered = [m for m, _ in sorted(ranks.items(), key=lambda kv: kv[1])]
    check("15 provenance ladder is ordered", ordered == [
        "source_derived", "deterministic_rule", "ai_generated", "ai_reviewed",
        "human_reviewed", "approved_production",
    ], f"ladder: {ordered}")


def test_parity_report() -> None:
    path = ENRICHMENT / "validation" / "parity_report.json"
    if not path.exists():
        skip("18 parity gate", "parity_report.json not generated yet")
        return
    report = mv.read_json(path)
    check("18 parity gate reports gaps", "purpose_coverage" in report and "gaps" in report,
          f"{len(report.get('gaps', []))} coverage gaps reported")


# ---------------------------------------------------------------------------

def main() -> int:
    mv.setup_stdout()
    for fn in (
        test_corpus_immutability,
        test_replay_determinism,
        test_ledger_roundtrip,
        test_direction_rule,
        test_vote_independence,
        test_derived_exclusion,
        test_cascade,
        test_response_guards,
        test_enrichment_records,
        test_utf8_safety,
        test_provenance_monotonicity,
        test_parity_report,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a crashing test is a failing test
            RESULTS.append((fn.__name__, "FAIL", f"{type(exc).__name__}: {exc}"))

    width = max(len(name) for name, _, _ in RESULTS)
    failed = skipped = 0
    print()
    for name, outcome, detail in RESULTS:
        if outcome == "FAIL":
            failed += 1
        elif outcome == "SKIP":
            skipped += 1
        print(f"  [{outcome}] {name:<{width}}  {detail}")
    passed = len(RESULTS) - failed - skipped
    print(f"\n  {passed} passed, {failed} failed, {skipped} skipped\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
