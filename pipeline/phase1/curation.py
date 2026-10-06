"""The curation decision cascade.

Gemini never emits a curation status. Status is computed here, by an ordered
rule cascade over the enrichment fields: first match wins, and the id of the
matching rule is stored on the record as `curation.rule_fired`.

Three consequences, and they are the whole point:
  * the decision is reproducible - the same record always yields the same status;
  * it is explainable - `rule_fired` names exactly why;
  * it is re-tunable - changing a threshold re-runs over existing annotations in
    seconds, without re-annotating 37,339 verses.

DEFAULT DENY. A record that matches no INCLUDE rule falls to REVIEW_REQUIRED.
Nothing reaches a user by falling through the bottom of the cascade.
"""

from __future__ import annotations

from typing import Any

# Statuses, from the phases document.
INCLUDE = "INCLUDE"
INCLUDE_WITH_CONTEXT = "INCLUDE_WITH_CONTEXT"
EXCLUDE = "EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS"
REVIEW = "REVIEW_REQUIRED"

# A REVIEW_REQUIRED record older than this is reported as stale by the
# validator, so records cannot sit in review forever unnoticed.
REVIEW_MAX_AGE_DAYS = 90

# Intents permitted at user intensity 4 (crisis). Everything else is hard
# blocked there - notably `warning`, `repentance`, `instruction` and `guidance`.
CRISIS_SAFE_INTENTS = frozenset({"comfort", "lament", "assurance", "peace"})

# Gate 4b (single-pass INCLUDE): whose words may be served on one pass, and
# which speech acts never are.
SINGLE_PASS_SPEAKERS = frozenset({"divine", "prophet_or_apostle", "righteous_figure", "narrator"})
SINGLE_PASS_EXCLUDED_PURPOSES = frozenset(
    {"warning_or_threat", "legal_ruling", "genealogy_or_record"}
)

# Phase 0 warnings a deterministic, documented rule has already settled. A
# cross-source Arabic variant is settled once display policy v1 has chosen the
# reading (implementation_phases.md, "Decided 2026-10-06"); every other warning
# still needs a person.
SETTLED_BY_DISPLAY_POLICY = frozenset({"original_text_variant_across_sources"})


def phase0_open(record: dict[str, Any]) -> bool:
    """True while a Phase 0 flag on this record still needs a person to clear it."""
    quality = record.get("phase0_data_quality") or {}
    status = quality.get("status")
    if status in (None, "valid"):
        return False
    if status != "warning":
        return True
    codes = {w.get("code") for w in quality.get("warnings") or []}
    display_decided = (record.get("display_text_ref") or {}).get("decision") == "display_policy_v1"
    return not (codes <= SETTLED_BY_DISPLAY_POLICY and display_decided)


def _scores(record: dict[str, Any]) -> dict[str, Any]:
    """Pull the decision-relevant fields, tolerating absent annotation."""
    suitability = record.get("purpose_suitability") or {}
    return {
        "confidence": record.get("curation", {}).get("curation_confidence"),
        "standalone": record.get("standalone_usefulness"),
        "context_level": (record.get("context_dependency") or {}).get("level"),
        "isolation_level": (record.get("isolation_risk") or {}).get("level"),
        "purposes": {k: (v or {}).get("score") for k, v in suitability.items()},
        "max_suitability": max(
            [(v or {}).get("score") or 0 for v in suitability.values()] or [None],
            default=None,
        )
        if suitability
        else None,
        "states": record.get("addressed_states") or [],
        "max_relevance": max(
            [s.get("emotional_relevance") or 0 for s in (record.get("addressed_states") or [])],
            default=0,
        ),
        "purpose_ids": [p.get("purpose") for p in (record.get("scripture_purpose") or [])],
        "speaker_roles": [
            p.get("speaker_role")
            for p in (record.get("scripture_purpose") or [])
            if p.get("purpose") == "reported_speech"
        ],
        "promise_conditions": [
            p.get("promise_conditionality")
            for p in (record.get("scripture_purpose") or [])
            if p.get("purpose") == "promise"
        ],
        "advisories": (record.get("safety") or {}).get("content_advisories") or [],
        "crisis_safe": (record.get("safety") or {}).get("crisis_safe"),
        "span": record.get("recommended_context_span"),
        "phase0": (record.get("phase0_data_quality") or {}).get("status"),
        "phase0_open": phase0_open(record),
        "disagreement": record.get("_max_pass_disagreement", 0),
        "low_kappa_fields": record.get("_low_kappa_fields") or [],
        "annotated": bool(record.get("_annotated")),
    }


def decide(record: dict[str, Any], hard_exclusion_speakers: frozenset[str]) -> tuple[str, str, str]:
    """Return (status, rule_id, explanation) for one enrichment record."""
    s = _scores(record)

    # ---------------------------------------------------------------- Gate 1
    # REVIEW_REQUIRED. Evaluated first: these say the record cannot be trusted
    # to be judged automatically at all, whatever its scores look like.

    if not s["annotated"]:
        return (
            REVIEW,
            "gate1.not_annotated",
            "No annotation exists for this record yet, so no automatic status can be earned.",
        )

    if s["phase0_open"]:
        return (
            REVIEW,
            "gate1.phase0_data_quality",
            f"Phase 0 marked this record `{s['phase0']}`. Records flagged upstream are reviewed "
            "before they can be served to a user in distress.",
        )

    if s["confidence"] is None or s["confidence"] < 0.40:
        return (
            REVIEW,
            "gate1.low_confidence",
            f"Curation confidence {s['confidence']} is below the 0.40 floor for any automatic "
            "decision.",
        )

    if s["isolation_level"] is not None and s["standalone"] is not None:
        if s["isolation_level"] >= 2 and s["standalone"] >= 3:
            return (
                REVIEW,
                "gate1.self_contradictory",
                f"The annotation contradicts itself: isolation_risk {s['isolation_level']} says the "
                f"verse is misread alone, while standalone_usefulness {s['standalone']} says it "
                "reads well alone. One of the two is wrong.",
            )

    if "reported_speech" in s["purpose_ids"] and not any(s["speaker_roles"]):
        return (
            REVIEW,
            "gate1.reported_speech_without_speaker",
            "Marked as reported speech with no speaker_role. Whether the words belong to a prophet "
            "or to an adversary changes the meaning entirely, and it is the largest single source "
            "of misleading-if-isolated content.",
        )

    if (
        s["max_relevance"] >= 3
        and (s["max_suitability"] or 0) >= 3
        and "warning_or_threat" in s["purpose_ids"]
    ):
        return (
            REVIEW,
            "gate1.relevance_suitability_tension",
            "Scored as both emotionally relevant and pastorally suitable while its speech-act is a "
            "warning or threat. That combination is exactly the failure this system exists to "
            "prevent, so it is never granted automatically.",
        )

    if s["crisis_safe"] is None:
        return (
            REVIEW,
            "gate1.crisis_safety_undetermined",
            "crisis_safe was not determined. A record whose crisis safety is unknown cannot be "
            "cleared for recommendation.",
        )

    if s["disagreement"] >= 2:
        return (
            REVIEW,
            "gate1.pass_disagreement",
            f"Two independent annotation passes differ by {s['disagreement']} ordinal levels on at "
            "least one score. Disagreement is recorded, never averaged away.",
        )

    if record.get("_theologically_contested"):
        return (
            REVIEW,
            "gate1.theologically_contested",
            "The annotation marks the reading as genuinely contested between traditions. The "
            "annotator may not resolve that, so a person must.",
        )
    if record.get("_needs_display_decision"):
        return (
            REVIEW,
            "gate1.undecided_display_text",
            "Sources disagree on this verse's original text and no display decision has been "
            "recorded. Which reading is shown is a content decision, not a default.",
        )

    if s["low_kappa_fields"]:
        return (
            REVIEW,
            "gate1.field_below_agreement_threshold",
            "Depends on "
            + ", ".join(sorted(s["low_kappa_fields"]))
            + ", whose measured gold-set agreement is below 0.40. A score nobody can reproduce may "
            "not drive an automatic INCLUDE.",
        )

    # ---------------------------------------------------------------- Gate 2
    # EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS. Not deletion: these verses stay
    # fully present and searchable in study, browse and reference modes.

    if s["standalone"] is not None and s["standalone"] <= 1:
        return (
            EXCLUDE,
            "gate2.not_useful_alone",
            f"standalone_usefulness {s['standalone']}: read by itself the verse carries nothing to "
            "reflect on. Theological or narrative weight has no path into this decision.",
        )

    if s["isolation_level"] == 3:
        return (
            EXCLUDE,
            "gate2.severe_isolation_risk",
            "The plain isolated reading contradicts the passage's meaning.",
        )

    if s["context_level"] == 4:
        return (
            EXCLUDE,
            "gate2.frame_dependent",
            "Needs a frame the text does not supply - who is speaking, the historical occasion, or "
            "a legal system - which cannot be delivered by showing adjacent verses.",
        )

    if s["purpose_ids"] and set(s["purpose_ids"]) == {"genealogy_or_record"}:
        return (
            EXCLUDE,
            "gate2.record_only",
            "A list, census, measurement or register.",
        )

    bad_speakers = [r for r in s["speaker_roles"] if r in hard_exclusion_speakers]
    if bad_speakers:
        return (
            EXCLUDE,
            "gate2.negative_or_unattributed_speaker",
            f"Reported speech whose speaker is `{bad_speakers[0]}`. The verse may accurately record "
            "what an adversary or a fool said; served alone it reads as the text's own claim.",
        )

    if s["max_suitability"] is not None and s["max_suitability"] <= 1:
        return (
            EXCLUDE,
            "gate2.no_suitable_purpose",
            "No reflection intent scores above 1. The verse may be entirely accurate and still "
            "perform no pastoral act.",
        )

    if s["advisories"] and (s["max_suitability"] or 0) < 3:
        return (
            EXCLUDE,
            "gate2.advisory_without_strong_purpose",
            f"Carries content advisories ({', '.join(sorted(s['advisories']))}) without any intent "
            "scoring 3 or above to justify showing it.",
        )

    if not s["states"] and (s["max_suitability"] or 0) <= 2:
        return (
            EXCLUDE,
            "gate2.no_state_and_weak_purpose",
            "Speaks to no user emotional state and performs no intent above 2.",
        )

    # ---------------------------------------------------------------- Gate 3
    # INCLUDE_WITH_CONTEXT.

    if s["context_level"] in (2, 3):
        span_ok = bool(s["span"] and s["span"].get("start_canonical_id") and s["span"].get("end_canonical_id"))
        if (
            s["standalone"] is not None
            and s["standalone"] >= 2
            and s["isolation_level"] is not None
            and s["isolation_level"] <= 2
            and (s["max_suitability"] or 0) >= 3
            and span_ok
        ):
            return (
                INCLUDE_WITH_CONTEXT,
                "gate3.include_with_context",
                f"Needs its surrounding passage (context_dependency {s['context_level']}) but does "
                "real pastoral work once shown with it, and a resolvable span exists.",
            )
        if not span_ok:
            return (
                REVIEW,
                "gate3.context_span_missing",
                f"context_dependency {s['context_level']} requires a context span, and none that "
                "resolves to real verse ids was recorded. Context that cannot be rendered may not "
                "be promised.",
            )

    # ---------------------------------------------------------------- Gate 4
    # INCLUDE. Every condition must hold.

    if (
        s["context_level"] is not None
        and s["context_level"] <= 1
        and s["standalone"] is not None
        and s["standalone"] >= 3
        and s["isolation_level"] is not None
        and s["isolation_level"] <= 1
        and (s["max_suitability"] or 0) >= 3
        and s["crisis_safe"] is not None
        and s["confidence"] is not None
        and s["confidence"] >= 0.60
    ):
        best = max(
            ((k, v) for k, v in s["purposes"].items() if v is not None),
            key=lambda kv: (kv[1], kv[0]),
            default=("unknown", 0),
        )
        return (
            INCLUDE,
            "gate4.include",
            f"Self-contained (context {s['context_level']}), reads well alone "
            f"(standalone {s['standalone']}), low isolation risk, and performs `{best[0]}` at "
            f"{best[1]}.",
        )

    # ---------------------------------------------------------------- Gate 4b
    # INCLUDE on a single corroborated pass, for the safest profile only.
    #
    # This resolves the "confidence ceiling" decision in
    # docs/implementation_phases.md, deliberately and narrowly (2026-10-06).
    # One annotation pass caps confidence at 0.40, so gate 4 could never fire,
    # while gate 3 admitted context-dependent verses at 0.40. The product shows
    # a single passage, so that served exactly the verses that most need their
    # surroundings and withheld the self-contained ones that need none.
    #
    # The bar is not lowered across the board: everything in gates 1-3 still
    # applies, and on top of gate 4's own conditions the verse must need no
    # context at all, carry no isolation risk, no advisory, no warning, no
    # addressee-specific promise, and no words but God's, a prophet's, a
    # righteous figure's or the narrator's. Records admitted here are queued
    # for a second pass or human confirmation (review_queue p0).
    if (
        s["confidence"] is not None
        and s["confidence"] >= 0.40
        and s["context_level"] is not None
        and s["context_level"] <= 1
        and s["standalone"] is not None
        and s["standalone"] >= 3
        and s["isolation_level"] == 0
        and (s["max_suitability"] or 0) >= 3
        and s["crisis_safe"] is not None
        and s["states"]
        and not s["advisories"]
        and not set(s["purpose_ids"]) & SINGLE_PASS_EXCLUDED_PURPOSES
        and all(role in SINGLE_PASS_SPEAKERS for role in s["speaker_roles"])
        and "addressee_specific" not in s["promise_conditions"]
    ):
        best = max(
            ((k, v) for k, v in s["purposes"].items() if v is not None),
            key=lambda kv: (kv[1], kv[0]),
            default=("unknown", 0),
        )
        return (
            INCLUDE,
            "gate4.include_single_pass",
            f"One corroborated annotation pass. Self-contained, reads well alone (standalone "
            f"{s['standalone']}), no isolation risk, and performs `{best[0]}` at {best[1]}. "
            "Awaiting a second pass or human confirmation.",
        )

    # ------------------------------------------------------------ default deny
    return (
        REVIEW,
        "default.deny",
        "Met no INCLUDE rule. Nothing reaches a user by falling through the cascade.",
    )


def serving_constraints(record: dict[str, Any]) -> dict[str, Any]:
    """Constraints applied per request, which INCLUDE does not override.

    Inclusion is global; appropriateness is per-request. Job 1:21 is genuinely
    INCLUDE-worthy and still wrong for someone freshly bereaved.
    """
    safety = record.get("safety") or {}
    intents = record.get("intents") or []
    crisis_eligible = bool(
        safety.get("crisis_safe")
        and set(intents) & CRISIS_SAFE_INTENTS
        and (record.get("isolation_risk") or {}).get("level") == 0
        and (record.get("context_dependency") or {}).get("level", 99) <= 1
    )
    return {
        "avoid_for_states": safety.get("avoid_for_states") or [],
        "crisis_eligible": crisis_eligible,
        "crisis_intents_allowed": sorted(set(intents) & CRISIS_SAFE_INTENTS),
        "note": (
            "avoid_for_states vetoes this verse for those states even at INCLUDE. "
            "crisis_eligible gates intensity-4 requests."
        ),
    }
