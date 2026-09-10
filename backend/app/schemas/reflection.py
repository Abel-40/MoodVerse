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


class VerseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_id: str
    religion: Religion
    reference: str
    text: str


class ReflectionSubmitResponse(BaseModel):
    """Returned immediately by POST /api/v1/recommendations and
    POST /api/v1/reflections/voice - analysis and retrieval run in a Celery
    worker, never inline in the request. Poll GET /api/v1/reflections/{id}
    (or the history list) for the outcome."""

    reflection_id: int
    status: Literal["pending"] = "pending"


class FeedbackCreate(BaseModel):
    # Which served verse this feedback is about. Optional only when the
    # reflection has exactly one result - required and validated against the
    # reflection's own results otherwise.
    canonical_id: str | None = None
    helpful: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    reported_harmful: bool = False


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    canonical_id: str
    helpful: bool | None
    note: str | None
    reported_harmful: bool


class ReflectionHistoryResult(BaseModel):
    verse: VerseOut
    rank: int
    similarity: float | None
    final_score: float | None
    served_with_context: bool


class ReflectionHistoryItem(BaseModel):
    """Also the shape GET /api/v1/reflections/{id} returns for one reflection -
    polling for a single item and listing history are the same read, so they
    share a schema rather than drifting into two shapes for one row."""

    id: int
    created_at: datetime
    # Null only while a voice reflection is still waiting on transcription.
    text: str | None
    religion: Religion
    status: str
    error: str | None
    analysis: dict | None
    results: list[ReflectionHistoryResult]


class ReflectionHistoryResponse(BaseModel):
    items: list[ReflectionHistoryItem]
    limit: int
    offset: int
