"""MoodVerse API.

Scripture is served from the curated corpus in the database. The runtime model
analyses the user's reflection and nothing else. See docs/backend.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.recommendations import router as recommendations_router
from app.core.eventloop import configure_event_loop
from app.db.session import dispose_engine

# Before uvicorn creates its loop; a no-op off Windows.
configure_event_loop()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Hold the connection pool for the process lifetime, then close it."""
    yield
    await dispose_engine()


app = FastAPI(
    lifespan=lifespan,
    title="MoodVerse API",
    version="0.1.0",
    summary="Curated scripture recommendation for emotional reflection.",
)

app.include_router(recommendations_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
