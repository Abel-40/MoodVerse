"""Hybrid retrieval and explainable ranking.

Vector similarity narrows; metadata and curation decide. Similarity alone is
never allowed to select a verse, because two texts about grief can be lexically
close while one consoles the grieving and the other blames them.

Ranking is scored from named components and the breakdown is returned with every
result, so "why did it show me this" has an answer that does not require
re-running anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.scripture import (
    AddressedState,
    ContentAdvisory,
    Scripture,
    ScriptureEnrichment,
    format_reference,
)
from app.services.ai_provider import ReflectionAnalysis
from app.services.embeddings import EmbeddingProvider, cosine_similarity

logger = logging.getLogger(__name__)

# Ranking weights. Deliberately explicit and summing to 1.0 so a change is
# visible in review. These are a starting point to be evaluated, not truth.
WEIGHTS = {
    "similarity": 0.30,
    "addressed_state": 0.30,
    "intent": 0.25,
    "standalone": 0.10,
    "confidence": 0.05,
}

# Intents that may be served at intensity 4. Mirrors curation.CRISIS_SAFE_INTENTS.
CRISIS_SAFE_INTENTS = frozenset({"comfort", "lament", "assurance", "peace"})
# At crisis intensity a verse must itself do one of those well, not merely be
# tagged crisis-safe.
CRISIS_MIN_INTENT_SCORE = 3


def is_crisis(analysis: ReflectionAnalysis) -> bool:
    return analysis.crisis_signals or analysis.intensity >= 4


def effective_intent(analysis: ReflectionAnalysis) -> str:
    """The intent ranking serves.

    At crisis intensity only the crisis-safe intents may be served. Despair
    reads naturally as needing `hope`, and refusing every verse because of that
    would leave someone in crisis with no passage at all, so a non-crisis-safe
    intent is served as `comfort` there instead.
    """
    if is_crisis(analysis) and analysis.intent not in CRISIS_SAFE_INTENTS:
        return "comfort"
    return analysis.intent


@dataclass
class Candidate:
    """One verse considered for a response, with everything ranking needs."""

    canonical_id: str
    religion: str
    text: str
    reference: str
    curation_status: str
    curation_confidence: float | None
    standalone_usefulness: int | None
    context_span: tuple[str | None, str | None]
    crisis_safe: bool | None
    embedding: list[float] | None
    addressed: dict[str, int] = field(default_factory=dict)
    embedding_model: str | None = None
    intents: dict[str, int] = field(default_factory=dict)
    avoid_states: set[str] = field(default_factory=set)


@dataclass
class RankedResult:
    candidate: Candidate
    similarity: float
    final_score: float
    breakdown: dict[str, float]
    served_with_context: bool

    @property
    def requires_context(self) -> bool:
        return self.candidate.curation_status == "INCLUDE_WITH_CONTEXT"


def eligible(candidate: Candidate, analysis: ReflectionAnalysis) -> tuple[bool, str]:
    """Serving constraints. Returns (allowed, reason_if_not).

    These are hard gates, applied before ranking. An INCLUDE status does not
    override any of them: curation says a verse may be served at all, not that
    it may be served to this person right now.
    """
    if candidate.curation_status not in ("INCLUDE", "INCLUDE_WITH_CONTEXT"):
        return False, f"curation_status {candidate.curation_status}"

    # Context that cannot be rendered may not be promised.
    if candidate.curation_status == "INCLUDE_WITH_CONTEXT":
        start, end = candidate.context_span
        if not start or not end:
            return False, "INCLUDE_WITH_CONTEXT without a resolvable span"

    # The annotation named states this verse must not be served for. Any state
    # the person reports counts, not only the primary one: a verse that could
    # worsen shame is wrong for someone lonely and ashamed.
    for state in (analysis.primary_emotion, *analysis.secondary_emotions):
        if state in candidate.avoid_states:
            return False, f"avoid_for_states contains {state}"

    if is_crisis(analysis):
        if candidate.crisis_safe is not True:
            return False, "not crisis_safe at crisis intensity"
        if effective_intent(analysis) not in CRISIS_SAFE_INTENTS:
            return False, f"intent {analysis.intent} is not permitted at crisis intensity"
        if not any(
            candidate.intents.get(intent, 0) >= CRISIS_MIN_INTENT_SCORE
            for intent in CRISIS_SAFE_INTENTS
        ):
            return False, "does not perform a crisis-safe intent well enough for crisis intensity"

    return True, ""


def score(
    candidate: Candidate,
    analysis: ReflectionAnalysis,
    reflection_vector: list[float],
) -> tuple[float, dict[str, float]]:
    """Explainable score in [0, 1] plus the per-component contributions."""
    similarity = 0.0
    if candidate.embedding:
        # Map cosine from [-1, 1] into [0, 1]; negative similarity is no signal.
        similarity = max(0.0, cosine_similarity(reflection_vector, candidate.embedding))

    # How strongly this verse addresses what the person is actually feeling.
    wanted = [analysis.primary_emotion, *analysis.secondary_emotions]
    relevances = [candidate.addressed.get(state, 0) for state in wanted]
    # Primary counts double: a verse for the secondary emotion only is a weaker match.
    if relevances:
        weighted = (relevances[0] * 2 + sum(relevances[1:])) / (2 + len(relevances) - 1)
    else:
        weighted = 0.0
    addressed = weighted / 4.0

    intent = candidate.intents.get(effective_intent(analysis), 0) / 4.0
    standalone = (candidate.standalone_usefulness or 0) / 4.0
    confidence = candidate.curation_confidence or 0.0

    breakdown = {
        "similarity": round(WEIGHTS["similarity"] * similarity, 6),
        "addressed_state": round(WEIGHTS["addressed_state"] * addressed, 6),
        "intent": round(WEIGHTS["intent"] * intent, 6),
        "standalone": round(WEIGHTS["standalone"] * standalone, 6),
        "confidence": round(WEIGHTS["confidence"] * confidence, 6),
    }
    return round(sum(breakdown.values()), 6), breakdown


def rank(
    candidates: list[Candidate],
    analysis: ReflectionAnalysis,
    reflection_vector: list[float],
    limit: int,
) -> list[RankedResult]:
    """Filter by the serving constraints, then order by score.

    Pure: no database, no provider. This is the function to test ranking with.
    """
    results: list[RankedResult] = []
    for candidate in candidates:
        allowed, _reason = eligible(candidate, analysis)
        if not allowed:
            continue
        similarity = (
            max(0.0, cosine_similarity(reflection_vector, candidate.embedding))
            if candidate.embedding
            else 0.0
        )
        final, breakdown = score(candidate, analysis, reflection_vector)
        results.append(
            RankedResult(
                candidate=candidate,
                similarity=round(similarity, 6),
                final_score=final,
                breakdown=breakdown,
                served_with_context=candidate.curation_status == "INCLUDE_WITH_CONTEXT",
            )
        )

    # canonical_id breaks ties so ordering is deterministic across runs.
    results.sort(key=lambda r: (-r.final_score, r.candidate.canonical_id))
    return results[:limit]


def _to_candidate(scripture: Scripture, enrichment: ScriptureEnrichment) -> Candidate:
    return Candidate(
        canonical_id=scripture.canonical_id,
        religion=scripture.religion,
        text=scripture.text,
        reference=format_reference(
            scripture.religion, scripture.book_or_surah, scripture.chapter, scripture.verse
        ),
        curation_status=enrichment.curation_status,
        curation_confidence=enrichment.curation_confidence,
        standalone_usefulness=enrichment.standalone_usefulness,
        context_span=(enrichment.context_span_start, enrichment.context_span_end),
        crisis_safe=enrichment.crisis_safe,
        embedding=list(enrichment.embedding) if enrichment.embedding is not None else None,
        embedding_model=enrichment.embedding_model,
        addressed={s.state: s.emotional_relevance for s in enrichment.addressed_states},
        intents={i.intent: i.score for i in enrichment.intent_scores},
        avoid_states={
            a.value for a in enrichment.advisories if a.kind == "avoid_state"
        },
    )


async def fetch_candidates(
    session: AsyncSession,
    religion: str,
    reflection_vector: list[float],
    limit: int,
    states: tuple[str, ...] = (),
) -> list[Candidate]:
    """Pull the nearest servable verses for one tradition.

    Religion is a hard SQL filter, never a ranking signal. A Bible reader must
    not receive a Quran verse because it scored well, and the reverse.
    Curation status is filtered in SQL too, so excluded records never enter the
    candidate pool at any similarity. With `states`, only verses annotated as
    addressing one of them are pulled.
    """
    statement = (
        select(Scripture, ScriptureEnrichment)
        .join(ScriptureEnrichment, Scripture.canonical_id == ScriptureEnrichment.canonical_id)
        .options(
            selectinload(ScriptureEnrichment.addressed_states),
            selectinload(ScriptureEnrichment.intent_scores),
            selectinload(ScriptureEnrichment.advisories),
        )
        .where(Scripture.religion == religion)
        .where(ScriptureEnrichment.curation_status.in_(("INCLUDE", "INCLUDE_WITH_CONTEXT")))
    )
    if states:
        statement = statement.where(
            ScriptureEnrichment.canonical_id.in_(
                select(AddressedState.canonical_id).where(AddressedState.state.in_(states))
            )
        )
    if reflection_vector:
        statement = statement.order_by(
            ScriptureEnrichment.embedding.cosine_distance(reflection_vector)
        )
    statement = statement.limit(limit)

    rows = (await session.execute(statement)).all()
    return [_to_candidate(s, e) for s, e in rows]


async def context_verses(
    session: AsyncSession, start_canonical_id: str, end_canonical_id: str
) -> list[Scripture]:
    """The passage an INCLUDE_WITH_CONTEXT verse must be shown with.

    Returned from the database, never reconstructed. If this comes back empty
    the caller must drop the result rather than serve the verse bare.
    """
    start = await session.get(Scripture, start_canonical_id)
    end = await session.get(Scripture, end_canonical_id)
    if start is None or end is None or start.religion != end.religion:
        return []

    statement = (
        select(Scripture)
        .where(Scripture.religion == start.religion)
        .where(Scripture.book_or_surah == start.book_or_surah)
        .where(Scripture.chapter >= start.chapter)
        .where(Scripture.chapter <= end.chapter)
        .order_by(Scripture.chapter, Scripture.verse)
    )
    rows = list((await session.execute(statement)).scalars())
    return [
        verse
        for verse in rows
        if (verse.chapter, verse.verse) >= (start.chapter, start.verse)
        and (verse.chapter, verse.verse) <= (end.chapter, end.verse)
    ]


async def recommend(
    session: AsyncSession,
    religion: str,
    analysis: ReflectionAnalysis,
    embedder: EmbeddingProvider,
    reflection_text: str,
    candidate_limit: int,
    result_limit: int,
) -> list[RankedResult]:
    """End to end: embed the reflection, fetch candidates, rank them.

    Similarity is one ranking signal, not a gate. If the reflection cannot be
    embedded (a rate-limited encoder), or a verse was embedded by a different
    model than the one embedding the reflection, that similarity is unknown
    rather than noise, and ranking proceeds on the curated fields alone.
    """
    try:
        vector = embedder.embed_query(reflection_text)
    except Exception as exc:  # noqa: BLE001 - any encoder failure degrades the same way
        logger.warning("reflection not embedded, ranking without similarity: %s", exc)
        vector = []
    candidates = await fetch_candidates(session, religion, vector, candidate_limit)
    # The nearest verses by vector need not include the ones annotated for what
    # the person feels, so those are always in the pool as well.
    wanted = (analysis.primary_emotion, *analysis.secondary_emotions)
    seen = {c.canonical_id for c in candidates}
    for candidate in await fetch_candidates(session, religion, vector, candidate_limit, wanted):
        if candidate.canonical_id not in seen:
            candidates.append(candidate)
            seen.add(candidate.canonical_id)
    for candidate in candidates:
        if candidate.embedding_model != embedder.model_id:
            candidate.embedding = None
    return rank(candidates, analysis, vector, result_limit)
