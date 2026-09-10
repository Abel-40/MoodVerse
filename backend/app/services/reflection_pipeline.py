"""The reflection processing pipeline: transcribe (voice only) -> analyse ->
embed -> retrieve -> rank -> persist.

Runs inside a Celery task (app/tasks/reflections.py) against the heavy queue,
never inline in an API request - the endpoints in app/api/v1/recommendations.py
and app/api/v1/reflections.py only create the pending `Reflection` row and
enqueue one of the two entry points below. Kept here, independent of Celery,
so the pipeline itself stays testable without a broker or worker.

Flow, and the order matters:

    reflection text -> provider analysis -> validated -> embedding
      -> candidate fetch (religion + curation filtered in SQL)
      -> serving constraints -> ranking -> verses read from the database

The provider never touches the corpus and the corpus never reaches the
provider, so a model cannot supply scripture even if its prompt were subverted.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.reflection import Reflection, ReflectionResult
from app.services import retrieval
from app.services.ai_provider import get_provider
from app.services.embeddings import get_embedding_provider
from app.services.speech_to_text import get_speech_to_text_provider


async def _mark_failed(session: AsyncSession, reflection_id: int, error: str) -> None:
    await session.rollback()
    reflection = await session.get(Reflection, reflection_id)
    if reflection is None:
        return
    reflection.status = "failed"
    reflection.error = error[:2000]
    await session.commit()


async def run_text_reflection(
    session: AsyncSession, reflection_id: int, settings: Settings | None = None
) -> None:
    """Analyse, retrieve, rank and persist. `reflection.text` must already be set."""
    settings = settings or get_settings()
    reflection = await session.get(Reflection, reflection_id)
    if reflection is None:
        return  # deleted between enqueue and execution; nothing to process

    reflection.status = "processing"
    await session.commit()

    try:
        assert reflection.text is not None  # guaranteed by the caller
        provider = get_provider(settings)
        analysis = provider.analyse(reflection.text)

        embedder = get_embedding_provider(settings)
        ranked = await retrieval.recommend(
            session=session,
            religion=reflection.religion,
            analysis=analysis,
            embedder=embedder,
            reflection_text=reflection.text,
            candidate_limit=settings.retrieval_candidate_limit,
            result_limit=settings.retrieval_result_limit,
        )

        reflection.analysis = analysis.model_dump()
        reflection.analysis_provider = provider.name
        reflection.analysis_model = provider.model_id

        for index, item in enumerate(ranked, start=1):
            if item.served_with_context:
                start, end = item.candidate.context_span
                verses = (
                    await retrieval.context_verses(session, start, end)
                    if start and end
                    else []
                )
                if not verses:
                    # Context that cannot be rendered may not be promised.
                    # Drop the result rather than serve a verse known to
                    # mislead alone.
                    continue

            session.add(
                ReflectionResult(
                    reflection_id=reflection.id,
                    canonical_id=item.candidate.canonical_id,
                    rank=index,
                    similarity=item.similarity,
                    final_score=item.final_score,
                    score_breakdown=item.breakdown,
                    served_with_context=item.served_with_context,
                )
            )

        reflection.status = "completed"
        reflection.error = None
        await session.commit()
    except Exception as exc:
        await _mark_failed(session, reflection_id, str(exc))
        raise


async def run_voice_reflection(
    session: AsyncSession,
    reflection_id: int,
    audio_bytes: bytes,
    content_type: str | None,
    settings: Settings | None = None,
) -> None:
    """Transcribe, then hand off to run_text_reflection for the rest."""
    settings = settings or get_settings()
    reflection = await session.get(Reflection, reflection_id)
    if reflection is None:
        return

    reflection.status = "processing"
    await session.commit()

    try:
        stt = get_speech_to_text_provider(settings)
        text = stt.transcribe(audio_bytes, content_type)
        if not text.strip():
            raise RuntimeError("transcription returned empty text")
        reflection.text = text
        await session.commit()
    except Exception as exc:
        await _mark_failed(session, reflection_id, f"transcription failed: {exc}")
        raise

    await run_text_reflection(session, reflection_id, settings)
