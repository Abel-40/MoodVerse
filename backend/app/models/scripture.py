"""Scripture and its curated enrichment.

Two tables deliberately, not one. `scriptures` holds Phase 0 output:
source-faithful text that application code must never edit. `scripture_enrichment`
holds the Phase 1 curation layer joined to it. Keeping them apart means a
re-curation replaces enrichment rows without ever touching a verse.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base

EMBEDDING_DIM = get_settings().embedding_dimension

# Mirrors pipeline/phase1/curation.py. The backend never recomputes a status;
# it reads what the cascade decided and enforces it at serving time.
CURATION_STATUSES = (
    "INCLUDE",
    "INCLUDE_WITH_CONTEXT",
    "EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS",
    "REVIEW_REQUIRED",
)
SERVABLE_STATUSES = ("INCLUDE", "INCLUDE_WITH_CONTEXT")


class Scripture(Base):
    """One verse. Source-faithful; never written by application code."""

    __tablename__ = "scriptures"

    canonical_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    religion: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    book_or_surah: Mapped[str] = mapped_column(String(128), nullable=False)
    chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    verse: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_source: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 of the Phase 0 text. Ingestion refuses any enrichment row whose
    # recorded digest disagrees with this, which is how corpus drift is caught.
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    enrichment: Mapped[ScriptureEnrichment] = relationship(
        back_populates="scripture", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "religion in ('bible', 'quran')", name="ck_scripture_religion"
        ),
        Index("ix_scriptures_location", "religion", "book_or_surah", "chapter", "verse"),
    )


class ScriptureEnrichment(Base):
    """The Phase 1 curation layer for one verse."""

    __tablename__ = "scripture_enrichment"

    canonical_id: Mapped[str] = mapped_column(
        ForeignKey("scriptures.canonical_id", ondelete="CASCADE"), primary_key=True
    )
    taxonomy_version: Mapped[str] = mapped_column(String(16), nullable=False)

    curation_status: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    curation_confidence: Mapped[float | None] = mapped_column(Float)
    rule_fired: Mapped[str | None] = mapped_column(String(64))

    expressed_primary: Mapped[str | None] = mapped_column(String(32))
    text_intensity: Mapped[int | None] = mapped_column(Integer)
    standalone_usefulness: Mapped[int | None] = mapped_column(Integer)
    context_dependency: Mapped[int | None] = mapped_column(Integer)
    isolation_risk: Mapped[int | None] = mapped_column(Integer)

    crisis_safe: Mapped[bool | None] = mapped_column(Boolean)

    # Required whenever curation_status is INCLUDE_WITH_CONTEXT, enforced by the
    # check constraint below and again in retrieval. Context that cannot be
    # rendered may not be promised.
    context_span_start: Mapped[str | None] = mapped_column(String(128))
    context_span_end: Mapped[str | None] = mapped_column(String(128))

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))

    scripture: Mapped[Scripture] = relationship(back_populates="enrichment")
    addressed_states: Mapped[list[AddressedState]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    intent_scores: Mapped[list[IntentScore]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    themes: Mapped[list[ScriptureTheme]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    advisories: Mapped[list[ContentAdvisory]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "curation_status <> 'INCLUDE_WITH_CONTEXT' "
            "or (context_span_start is not null and context_span_end is not null)",
            name="ck_enrichment_context_span_present",
        ),
    )


class AddressedState(Base):
    """A user emotion this verse speaks to, and how strongly.

    Distinct from expressed_primary, which is what the text itself sounds like.
    The Phase 1 design treats conflating the two as its primary failure mode: a
    verse can sound fearful while serving someone who is afraid, or sound
    comforting while addressing nobody in distress at all.
    """

    __tablename__ = "scripture_addressed_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_id: Mapped[str] = mapped_column(
        ForeignKey("scripture_enrichment.canonical_id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    emotional_relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_span: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("canonical_id", "state", name="uq_addressed_state"),
    )


class IntentScore(Base):
    """How well this verse performs one reflection intent."""

    __tablename__ = "scripture_intent_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_id: Mapped[str] = mapped_column(
        ForeignKey("scripture_enrichment.canonical_id", ondelete="CASCADE"), index=True
    )
    intent: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("canonical_id", "intent", name="uq_intent_score"),
    )


class ScriptureTheme(Base):
    __tablename__ = "scripture_themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_id: Mapped[str] = mapped_column(
        ForeignKey("scripture_enrichment.canonical_id", ondelete="CASCADE"), index=True
    )
    theme: Mapped[str] = mapped_column(String(48), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("canonical_id", "theme", name="uq_scripture_theme"),
    )


class ContentAdvisory(Base):
    """Advisories, and states to avoid serving this verse for.

    Applied per request. An INCLUDE status does not override them.
    """

    __tablename__ = "scripture_advisories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_id: Mapped[str] = mapped_column(
        ForeignKey("scripture_enrichment.canonical_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(48), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint(
            "kind in ('advisory', 'avoid_state')", name="ck_advisory_kind"
        ),
        UniqueConstraint("canonical_id", "kind", "value", name="uq_advisory"),
    )


class IngestionRun(Base):
    """One ingestion of the enrichment layer, so ingestion stays auditable."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    taxonomy_version: Mapped[str] = mapped_column(String(16), nullable=False)
    pipeline_version: Mapped[str | None] = mapped_column(String(16))
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
