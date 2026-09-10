"""V1 recommendation endpoints.

Flow, and the order matters:

    reflection text -> provider analysis -> validated -> embedding
      -> candidate fetch (religion + curation filtered in SQL)
      -> serving constraints -> ranking -> verses read from the database

The provider never touches the corpus and the corpus never reaches the
provider, so a model cannot supply scripture even if its prompt were subverted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.scripture import format_reference
from app.db.session import get_session
from app.schemas.reflection import (
    AnalysisOut,
    RecommendationOut,
    RecommendationResponse,
    ReflectionCreate,
    ScoreBreakdown,
    VerseOut,
)
from app.services import retrieval
from app.services.ai_provider import AIProvider, get_provider
from app.services.embeddings import EmbeddingProvider, get_embedding_provider

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


def provider_dependency(settings: Settings = Depends(get_settings)) -> AIProvider:
    return get_provider(settings)


def embedder_dependency(settings: Settings = Depends(get_settings)) -> EmbeddingProvider:
    return get_embedding_provider(settings)


def _verse_out(scripture) -> VerseOut:
    return VerseOut(
        canonical_id=scripture.canonical_id,
        religion=scripture.religion,
        reference=format_reference(
            scripture.religion, scripture.book_or_surah, scripture.chapter, scripture.verse
        ),
        text=scripture.text,
    )


@router.post("/recommendations", response_model=RecommendationResponse)
async def recommend(
    payload: ReflectionCreate,
    session: AsyncSession = Depends(get_session),
    provider: AIProvider = Depends(provider_dependency),
    embedder: EmbeddingProvider = Depends(embedder_dependency),
    settings: Settings = Depends(get_settings),
) -> RecommendationResponse:
    try:
        analysis = provider.analyse(payload.text)
    except Exception as exc:  # provider failure must not surface as a 500 body
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Reflection analysis is unavailable.",
        ) from exc

    ranked = await retrieval.recommend(
        session=session,
        religion=payload.religion,
        analysis=analysis,
        embedder=embedder,
        reflection_text=payload.text,
        candidate_limit=settings.retrieval_candidate_limit,
        result_limit=settings.retrieval_result_limit,
    )

    results: list[RecommendationOut] = []
    for index, item in enumerate(ranked, start=1):
        context: list[VerseOut] = []
        if item.served_with_context:
            start, end = item.candidate.context_span
            verses = (
                await retrieval.context_verses(session, start, end) if start and end else []
            )
            if not verses:
                # Context that cannot be rendered may not be promised. Drop the
                # result rather than serve a verse known to mislead alone.
                continue
            context = [_verse_out(v) for v in verses]

        results.append(
            RecommendationOut(
                verse=VerseOut(
                    canonical_id=item.candidate.canonical_id,
                    religion=item.candidate.religion,
                    reference=item.candidate.reference,
                    text=item.candidate.text,
                ),
                rank=index,
                similarity=item.similarity,
                final_score=item.final_score,
                breakdown=ScoreBreakdown(**item.breakdown),
                served_with_context=item.served_with_context,
                context=context,
                curation_status=item.candidate.curation_status,
            )
        )

    return RecommendationResponse(
        analysis=AnalysisOut(**analysis.model_dump()),
        results=results,
        empty_reason=(
            None
            if results
            else "No curated verse met the serving constraints for this reflection."
        ),
    )
