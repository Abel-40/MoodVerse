"""GET /api/v1/scriptures/{id} - read one curated verse.

Protected like every other v1 route: the phase 3 goal is that every business
endpoint sits behind auth, and treating that as one consistent rule is
simpler and safer than judging per-route which content "counts" as sensitive.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.reflection import User
from app.models.scripture import Scripture, format_reference
from app.schemas.reflection import VerseOut

router = APIRouter(prefix="/api/v1", tags=["scriptures"])


@router.get("/scriptures/{canonical_id}", response_model=VerseOut)
async def get_scripture(
    canonical_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> VerseOut:
    scripture = await session.get(Scripture, canonical_id)
    if scripture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No scripture with that id.")

    return VerseOut(
        canonical_id=scripture.canonical_id,
        religion=scripture.religion,
        reference=format_reference(
            scripture.religion, scripture.book_or_surah, scripture.chapter, scripture.verse
        ),
        text=scripture.text,
    )
