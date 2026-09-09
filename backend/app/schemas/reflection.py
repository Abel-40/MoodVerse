"""Request and response shapes for the V1 API.

The response never contains model-generated scripture. Every `text` field here
is copied from a database row, and `canonical_id` lets the client verify which
row it came from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Religion = Literal["bible", "quran"]


class ReflectionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    religion: Religion


class AnalysisOut(BaseModel):
    primary_emotion: str
    secondary_emotions: list[str]
    intensity: int
    intent: str
    themes: list[str]
    crisis_signals: bool


class VerseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_id: str
    religion: Religion
    reference: str
    text: str


class ScoreBreakdown(BaseModel):
    similarity: float
    addressed_state: float
    intent: float
    standalone: float
    confidence: float


class RecommendationOut(BaseModel):
    """One recommended verse.

    `context` is populated whenever the verse is curated INCLUDE_WITH_CONTEXT.
    A client must render it alongside the verse; the API will not return such a
    verse with an empty context.
    """

    verse: VerseOut
    rank: int
    similarity: float
    final_score: float
    breakdown: ScoreBreakdown
    served_with_context: bool
    context: list[VerseOut] = Field(default_factory=list)
    curation_status: str


class RecommendationResponse(BaseModel):
    reflection_id: int | None = None
    analysis: AnalysisOut
    results: list[RecommendationOut]
    # True when the corpus had nothing eligible. The correct response to an
    # empty result is to say so, never to generate a passage.
    empty_reason: str | None = None


class FeedbackCreate(BaseModel):
    helpful: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    reported_harmful: bool = False


class ReflectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    text: str
    religion: Religion
    analysis: dict | None = None
