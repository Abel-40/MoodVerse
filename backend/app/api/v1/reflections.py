"""GET /api/v1/reflections/history, GET /api/v1/reflections/{id},
POST /api/v1/reflections/voice and POST /api/v1/reflections/{id}/feedback.

All scoped to the caller: a reflection (and any feedback on it) belongs to
whoever submitted it, enforced by filtering on user_id server-side rather
than trusting the path - a reflection id from someone else's history 404s
the same way a nonexistent one would, so its existence is never revealed.

Voice submission mirrors POST /api/v1/recommendations: it creates a pending
`Reflection` (text is null until transcribed) and enqueues a heavy-queue
Celery task - see app/services/reflection_pipeline.py for the actual
transcribe -> analyse -> retrieve -> rank -> persist pipeline.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.reflection import Feedback, Reflection, User
from app.models.scripture import Scripture, ScriptureEnrichment
from app.schemas.reflection import (
    FeedbackCreate,
    FeedbackOut,
    Religion,
    ReflectionHistoryItem,
    ReflectionHistoryResponse,
    ReflectionHistoryResult,
    ReflectionSubmitResponse,
    VerseOut,
)
from app.services.retrieval import context_verses
from app.tasks.reflections import process_voice_reflection

router = APIRouter(prefix="/api/v1/reflections", tags=["reflections"])

# Matches what Cartesia's batch STT endpoint documents accepting.
_ALLOWED_VOICE_CONTENT_TYPES = {
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/mpga",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
}


async def _fetch_scriptures(
    session: AsyncSession, canonical_ids: set[str]
) -> dict[str, Scripture]:
    if not canonical_ids:
        return {}
    rows = await session.execute(
        select(Scripture).where(Scripture.canonical_id.in_(canonical_ids))
    )
    return {s.canonical_id: s for s in rows.scalars()}


async def _fetch_contexts(
    session: AsyncSession, reflections: list[Reflection]
) -> dict[str, list[Scripture]]:
    """The passage each served-with-context verse belongs inside.

    Read from the enrichment span, the same one ranking required to exist
    before it would serve the verse.
    """
    wanted = {
        r.canonical_id for refl in reflections for r in refl.results if r.served_with_context
    }
    if not wanted:
        return {}
    rows = await session.execute(
        select(ScriptureEnrichment).where(ScriptureEnrichment.canonical_id.in_(wanted))
    )
    contexts: dict[str, list[Scripture]] = {}
    for enrichment in rows.scalars():
        start, end = enrichment.context_span_start, enrichment.context_span_end
        if start and end:
            contexts[enrichment.canonical_id] = await context_verses(session, start, end)
    return contexts


def _to_history_item(
    reflection: Reflection,
    scriptures: dict[str, Scripture],
    contexts: dict[str, list[Scripture]],
) -> ReflectionHistoryItem:
    results: list[ReflectionHistoryResult] = []
    for r in sorted(reflection.results, key=lambda x: x.rank):
        scripture = scriptures.get(r.canonical_id)
        if scripture is None:
            # Should not happen (scriptures are never deleted once ingested)
            # but a missing verse must not break the whole page.
            continue
        results.append(
            ReflectionHistoryResult(
                verse=VerseOut.from_scripture(scripture),
                rank=r.rank,
                similarity=r.similarity,
                final_score=r.final_score,
                served_with_context=r.served_with_context,
                context=[
                    VerseOut.from_scripture(v)
                    for v in (contexts.get(r.canonical_id, []) if r.served_with_context else [])
                ],
            )
        )
    return ReflectionHistoryItem(
        id=reflection.id,
        created_at=reflection.created_at,
        text=reflection.text,
        religion=reflection.religion,
        status=reflection.status,
        error=reflection.error,
        analysis=reflection.analysis,
        results=results,
    )


@router.get("/history", response_model=ReflectionHistoryResponse)
async def history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReflectionHistoryResponse:
    statement = (
        select(Reflection)
        .where(Reflection.user_id == current_user.id)
        .options(selectinload(Reflection.results))
        .order_by(Reflection.created_at.desc(), Reflection.id.desc())
        .limit(limit)
        .offset(offset)
    )
    reflections = list((await session.execute(statement)).scalars())

    canonical_ids = {r.canonical_id for refl in reflections for r in refl.results}
    scriptures = await _fetch_scriptures(session, canonical_ids)

    contexts = await _fetch_contexts(session, reflections)
    items = [_to_history_item(refl, scriptures, contexts) for refl in reflections]
    return ReflectionHistoryResponse(items=items, limit=limit, offset=offset)


@router.get("/{reflection_id}", response_model=ReflectionHistoryItem)
async def get_reflection(
    reflection_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReflectionHistoryItem:
    """Poll target for both submission routes - status moves
    pending -> processing -> completed/failed as the worker processes it."""
    statement = (
        select(Reflection)
        .where(Reflection.id == reflection_id, Reflection.user_id == current_user.id)
        .options(selectinload(Reflection.results))
    )
    reflection = (await session.execute(statement)).scalar_one_or_none()
    if reflection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No reflection with that id.")

    scriptures = await _fetch_scriptures(
        session, {r.canonical_id for r in reflection.results}
    )
    contexts = await _fetch_contexts(session, [reflection])
    return _to_history_item(reflection, scriptures, contexts)


@router.post(
    "/voice",
    response_model=ReflectionSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_voice_reflection(
    religion: Religion = Form(...),
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ReflectionSubmitResponse:
    if audio.content_type not in _ALLOWED_VOICE_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported audio type {audio.content_type!r}.",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty audio upload.")
    if len(audio_bytes) > settings.voice_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audio file is too large."
        )

    # text is null until the worker transcribes it - see
    # ck_reflection_text_present_when_completed on the Reflection model.
    reflection = Reflection(user_id=current_user.id, religion=religion, status="pending")
    session.add(reflection)
    await session.commit()

    process_voice_reflection.delay(
        reflection.id, base64.b64encode(audio_bytes).decode("ascii"), audio.content_type
    )

    return ReflectionSubmitResponse(reflection_id=reflection.id, status="pending")


@router.post(
    "/{reflection_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    reflection_id: int,
    payload: FeedbackCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FeedbackOut:
    statement = (
        select(Reflection)
        .where(Reflection.id == reflection_id, Reflection.user_id == current_user.id)
        .options(selectinload(Reflection.results))
    )
    reflection = (await session.execute(statement)).scalar_one_or_none()
    if reflection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No reflection with that id.")

    if not reflection.results:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This reflection has no results to give feedback on."
        )

    if payload.canonical_id is not None:
        result = next(
            (r for r in reflection.results if r.canonical_id == payload.canonical_id), None
        )
        if result is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "That verse was not served for this reflection."
            )
    elif len(reflection.results) == 1:
        result = reflection.results[0]
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "canonical_id is required when a reflection has more than one result.",
        )

    feedback = Feedback(
        result_id=result.id,
        helpful=payload.helpful,
        note=payload.note,
        reported_harmful=payload.reported_harmful,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)

    return FeedbackOut(
        id=feedback.id,
        created_at=feedback.created_at,
        canonical_id=result.canonical_id,
        helpful=feedback.helpful,
        note=feedback.note,
        reported_harmful=feedback.reported_harmful,
    )
