"""Users, reflections, what was recommended, and feedback.

A reflection row records what the user wrote and what the system did with it,
including the retrieval trace. That trace is the only way to answer "why did it
show me this" later, so it is stored rather than recomputed.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.auth import OAuthAccount

# Mirrors app/services/reflection_pipeline.py. A reflection starts pending,
# moves to processing when a worker picks it up, and ends completed or
# failed - the backend never computes this from the presence of results,
# because "no results yet" and "no results ever" must be distinguishable.
REFLECTION_STATUSES = ("pending", "processing", "completed", "failed")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    # Null for an account that has only ever signed in via OIDC. Login with a
    # password must reject a null hash rather than attempt to verify against it.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Default tradition. Retrieval still requires an explicit religion per
    # request; this only seeds the client.
    preferred_religion: Mapped[str | None] = mapped_column(String(16))

    reflections: Mapped[list[Reflection]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "preferred_religion is null or preferred_religion in ('bible', 'quran')",
            name="ck_user_preferred_religion",
        ),
    )


class Reflection(Base):
    """One submitted reflection and the analysis derived from it."""

    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Stored verbatim. Never rewritten, never normalised. Null only while a
    # voice reflection is waiting on transcription - see ck_reflection_text_
    # present_when_completed below.
    text: Mapped[str | None] = mapped_column(Text)
    religion: Mapped[str] = mapped_column(String(16), nullable=False)

    # AI work (analysis, and for voice input, transcription) runs in a Celery
    # worker, never inline in the request - see app/services/reflection_pipeline.py.
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    # The validated provider output. Kept as JSON so a taxonomy revision does
    # not invalidate historical rows.
    analysis: Mapped[dict | None] = mapped_column(JSONB)
    analysis_provider: Mapped[str | None] = mapped_column(String(32))
    analysis_model: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="reflections")
    results: Mapped[list[ReflectionResult]] = relationship(
        back_populates="reflection", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("religion in ('bible', 'quran')", name="ck_reflection_religion"),
        CheckConstraint(f"status in {REFLECTION_STATUSES!r}", name="ck_reflection_status"),
        CheckConstraint(
            "status <> 'completed' or text is not null",
            name="ck_reflection_text_present_when_completed",
        ),
    )


class ReflectionResult(Base):
    """One scripture returned for one reflection, with the reason it ranked."""

    __tablename__ = "reflection_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reflection_id: Mapped[int] = mapped_column(
        ForeignKey("reflections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    canonical_id: Mapped[str] = mapped_column(
        ForeignKey("scriptures.canonical_id"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    similarity: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float | None] = mapped_column(Float)
    # Per-component contributions, so ranking stays explainable after the fact.
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB)

    served_with_context: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    reflection: Mapped[Reflection] = relationship(back_populates="results")
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )


class Feedback(Base):
    """User judgement on one returned scripture."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("reflection_results.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    helpful: Mapped[bool | None] = mapped_column(Boolean)
    # Free-text reason. Feeds curation review; never edits enrichment directly.
    note: Mapped[str | None] = mapped_column(Text)
    reported_harmful: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    result: Mapped[ReflectionResult] = relationship(back_populates="feedback")
