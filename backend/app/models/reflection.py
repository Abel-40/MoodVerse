"""Users, reflections, what was recommended, and feedback.

A reflection row records what the user wrote and what the system did with it,
including the retrieval trace. That trace is the only way to answer "why did it
show me this" later, so it is stored rather than recomputed.
"""

from __future__ import annotations

from datetime import datetime

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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
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

    # Stored verbatim. Never rewritten, never normalised.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    religion: Mapped[str] = mapped_column(String(16), nullable=False)

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
