"""Heavy-queue tasks: reflection analysis/retrieval and voice transcription.

Each task opens its own event loop (`asyncio.run`) and its own `AsyncSession` -
a Celery worker is a plain synchronous process with no loop of its own, and
tasks never share a session with the API process or with each other. This
reuses the existing async retrieval/embedding stack unchanged rather than
forking a second, sync copy of it.

Retries are modest (2) and only guard transient failures (a dropped Gemini or
Cartesia connection); app/services/reflection_pipeline.py already marks the
`Reflection` row failed with an error message on every attempt regardless of
whether Celery retries again, so the database is always consistent even if
retries are exhausted.
"""

from __future__ import annotations

import asyncio
import base64

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services import reflection_pipeline


async def _run_text(reflection_id: int) -> None:
    async with SessionLocal() as session:
        await reflection_pipeline.run_text_reflection(session, reflection_id)


async def _run_voice(reflection_id: int, audio_b64: str, content_type: str | None) -> None:
    audio_bytes = base64.b64decode(audio_b64)
    async with SessionLocal() as session:
        await reflection_pipeline.run_voice_reflection(
            session, reflection_id, audio_bytes, content_type
        )


@celery_app.task(
    name="app.tasks.reflections.process_reflection",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def process_reflection(self, reflection_id: int) -> None:
    try:
        asyncio.run(_run_text(reflection_id))
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(
    name="app.tasks.reflections.process_voice_reflection",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def process_voice_reflection(
    self, reflection_id: int, audio_b64: str, content_type: str | None
) -> None:
    try:
        asyncio.run(_run_voice(reflection_id, audio_b64, content_type))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
