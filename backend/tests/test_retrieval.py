"""Retrieval and serving-constraint tests.

These run without a database. Everything they assert is a property of the pure
ranking layer, which is where the rules that protect a reader actually live.
"""

from __future__ import annotations

import pytest

from app.services.ai_provider import (
    HeuristicProvider,
    ReflectionAnalysis,
    get_provider,
)
from app.services.embeddings import HashingEmbedding, cosine_similarity
from app.services.retrieval import Candidate, eligible, rank, score

DIM = 64
EMBEDDER = HashingEmbedding(DIM)


def make_candidate(**overrides) -> Candidate:
    defaults = dict(
        canonical_id="bible:Psalms:4:8",
        religion="bible",
        text="I will both lay me down in peace, and sleep.",
        reference="Psalms 4:8",
        curation_status="INCLUDE",
        curation_confidence=0.6,
        standalone_usefulness=4,
        context_span=(None, None),
        crisis_safe=True,
        embedding=EMBEDDER.embed("peace sleep safety rest"),
        addressed={"anxiety": 3},
        intents={"peace": 4},
        avoid_states=set(),
    )
    defaults.update(overrides)
    return Candidate(**defaults)


def make_analysis(**overrides) -> ReflectionAnalysis:
    defaults = dict(
        primary_emotion="anxiety",
        secondary_emotions=[],
        intensity=2,
        intent="peace",
        themes=[],
        crisis_signals=False,
    )
    defaults.update(overrides)
    return ReflectionAnalysis(**defaults)


# --------------------------------------------------------------------------
# curation is a serving constraint, not a label
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status", ["EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS", "REVIEW_REQUIRED"]
)
def test_non_servable_status_never_returned(status):
    candidate = make_candidate(curation_status=status)
    allowed, reason = eligible(candidate, make_analysis())
    assert not allowed
    assert status in reason

    # and it survives ranking too, at any similarity
    results = rank([candidate], make_analysis(), candidate.embedding, limit=5)
    assert results == []


def test_include_with_context_without_span_is_refused():
    """Context that cannot be rendered may not be promised."""
    candidate = make_candidate(
        curation_status="INCLUDE_WITH_CONTEXT", context_span=(None, None)
    )
    allowed, reason = eligible(candidate, make_analysis())
    assert not allowed
    assert "span" in reason


def test_include_with_context_with_span_is_allowed_and_flagged():
    candidate = make_candidate(
        curation_status="INCLUDE_WITH_CONTEXT",
        context_span=("bible:Psalms:4:7", "bible:Psalms:4:8"),
    )
    results = rank([candidate], make_analysis(), candidate.embedding, limit=5)
    assert len(results) == 1
    assert results[0].served_with_context is True


def test_avoid_for_states_blocks_the_named_emotion():
    candidate = make_candidate(avoid_states={"anxiety"})
    allowed, reason = eligible(candidate, make_analysis(primary_emotion="anxiety"))
    assert not allowed
    assert "avoid_for_states" in reason

    # the same verse remains eligible for a different reader
    allowed_other, _ = eligible(candidate, make_analysis(primary_emotion="grief"))
    assert allowed_other


# --------------------------------------------------------------------------
# crisis constraints, which INCLUDE does not override
# --------------------------------------------------------------------------

def test_crisis_requires_crisis_safe_even_for_include():
    candidate = make_candidate(curation_status="INCLUDE", crisis_safe=False)
    allowed, reason = eligible(candidate, make_analysis(crisis_signals=True, intensity=4))
    assert not allowed
    assert "crisis_safe" in reason


def test_crisis_restricts_intent_to_the_permitted_set():
    candidate = make_candidate(crisis_safe=True, intents={"warning": 4})
    analysis = make_analysis(intent="warning", crisis_signals=True, intensity=4)
    allowed, reason = eligible(candidate, analysis)
    assert not allowed
    assert "not permitted at crisis intensity" in reason


def test_crisis_safe_comfort_verse_still_served_in_crisis():
    candidate = make_candidate(crisis_safe=True, intents={"comfort": 4})
    analysis = make_analysis(intent="comfort", crisis_signals=True, intensity=4)
    allowed, _ = eligible(candidate, analysis)
    assert allowed


def test_intensity_four_alone_triggers_crisis_constraints():
    """Intensity 4 is treated as crisis even without an explicit signal."""
    candidate = make_candidate(crisis_safe=False)
    allowed, _ = eligible(candidate, make_analysis(intensity=4, crisis_signals=False))
    assert not allowed


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

def test_ranking_is_deterministic_and_ordered():
    weak = make_candidate(
        canonical_id="bible:A:1:1", addressed={"anxiety": 1}, intents={"peace": 1}
    )
    strong = make_candidate(
        canonical_id="bible:B:1:1", addressed={"anxiety": 4}, intents={"peace": 4}
    )
    analysis = make_analysis()
    vector = EMBEDDER.embed("anxious cannot sleep")

    first = rank([weak, strong], analysis, vector, limit=5)
    second = rank([strong, weak], analysis, vector, limit=5)

    assert [r.candidate.canonical_id for r in first] == ["bible:B:1:1", "bible:A:1:1"]
    assert [r.candidate.canonical_id for r in first] == [
        r.candidate.canonical_id for r in second
    ]
    assert first[0].final_score > first[0 + 1].final_score


def test_score_breakdown_sums_to_final_score():
    candidate = make_candidate()
    analysis = make_analysis()
    vector = EMBEDDER.embed("anxious and cannot rest")
    final, breakdown = score(candidate, analysis, vector)
    assert final == pytest.approx(sum(breakdown.values()), abs=1e-6)
    assert set(breakdown) == {
        "similarity", "addressed_state", "intent", "standalone", "confidence"
    }


def test_score_stays_within_unit_interval():
    best = make_candidate(
        addressed={"anxiety": 4}, intents={"peace": 4},
        standalone_usefulness=4, curation_confidence=1.0,
    )
    vector = best.embedding
    final, _ = score(best, make_analysis(), vector)
    assert 0.0 <= final <= 1.0


def test_primary_emotion_outweighs_secondary():
    primary_match = make_candidate(canonical_id="bible:A:1:1", addressed={"anxiety": 4})
    secondary_match = make_candidate(canonical_id="bible:B:1:1", addressed={"grief": 4})
    analysis = make_analysis(primary_emotion="anxiety", secondary_emotions=["grief"])
    vector = EMBEDDER.embed("worried and sad")

    primary_score, _ = score(primary_match, analysis, vector)
    secondary_score, _ = score(secondary_match, analysis, vector)
    assert primary_score > secondary_score


def test_limit_is_respected():
    candidates = [make_candidate(canonical_id=f"bible:X:1:{i}") for i in range(10)]
    assert len(rank(candidates, make_analysis(), candidates[0].embedding, limit=3)) == 3


# --------------------------------------------------------------------------
# embeddings
# --------------------------------------------------------------------------

def test_embedding_is_deterministic():
    assert EMBEDDER.embed("grief and loss") == EMBEDDER.embed("grief and loss")


def test_embedding_is_normalised():
    vector = EMBEDDER.embed("comfort for the mourning")
    assert sum(v * v for v in vector) == pytest.approx(1.0, abs=1e-9)


def test_embedding_handles_empty_and_stopword_only_text():
    assert EMBEDDER.embed("") == [0.0] * DIM
    assert EMBEDDER.embed("the and of to") == [0.0] * DIM


def test_similar_text_scores_above_unrelated_text():
    query = EMBEDDER.embed("weeping and mourning in grief")
    close = EMBEDDER.embed("grief and mourning")
    far = EMBEDDER.embed("commerce taxation harvest census")
    assert cosine_similarity(query, close) > cosine_similarity(query, far)


# --------------------------------------------------------------------------
# provider contract
# --------------------------------------------------------------------------

def test_heuristic_provider_returns_validated_analysis():
    analysis = HeuristicProvider().analyse("I feel so lonely since my father died.")
    assert analysis.primary_emotion in {"grief", "loneliness"}
    assert 1 <= analysis.intensity <= 4


def test_provider_flags_crisis_language():
    analysis = HeuristicProvider().analyse("I do not want to live any more.")
    assert analysis.crisis_signals is True
    assert analysis.intensity == 4


def test_analysis_rejects_values_outside_the_taxonomy():
    with pytest.raises(ValueError):
        ReflectionAnalysis(
            primary_emotion="melancholia", secondary_emotions=[], intensity=2,
            intent="comfort", themes=[], crisis_signals=False,
        )
    with pytest.raises(ValueError):
        ReflectionAnalysis(
            primary_emotion="grief", secondary_emotions=[], intensity=9,
            intent="comfort", themes=[], crisis_signals=False,
        )


def test_provider_exposes_no_way_to_supply_scripture():
    """The provider interface has one method and it takes only user text.

    Structural, not a matter of prompt discipline: there is no parameter through
    which corpus text could be passed in, and no return field through which a
    verse could come back.
    """
    analysis = HeuristicProvider().analyse("anything at all")
    assert not hasattr(analysis, "verse")
    assert not hasattr(analysis, "scripture")
    assert set(analysis.model_dump()) == {
        "primary_emotion", "secondary_emotions", "intensity",
        "intent", "themes", "crisis_signals",
    }


def test_unknown_provider_is_rejected():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        get_provider(Settings(AI_PROVIDER="not-a-provider"))
