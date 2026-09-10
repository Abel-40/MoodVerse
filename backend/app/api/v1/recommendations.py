"""POST /api/v1/recommendations - submit a text reflection.

Creates the `Reflection` row and enqueues app.tasks.reflections.process_reflection
on the heavy queue; it does not itself call the AI provider or retrieval -
that whole pipeline (see app/services/reflection_pipeline.py) now runs in a
Celery worker. Poll GET /api/v1/reflections/{id} (or the history list) for the
outcome once status moves past "pending".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.reflection import Reflection, User
from app.schemas.reflection import ReflectionCreate, ReflectionSubmitResponse
from app.tasks.reflections import process_reflection

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


@router.post(
    "/recommendations",
    response_model=ReflectionSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recommend(
    payload: ReflectionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReflectionSubmitResponse:
    reflection = Reflection(
        user_id=current_user.id,
        text=payload.text,
        religion=payload.religion,
        status="pending",
    )
    session.add(reflection)
    await session.commit()

    process_reflection.delay(reflection.id)

    return ReflectionSubmitResponse(reflection_id=reflection.id, status="pending")
