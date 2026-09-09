"""MoodVerse API.

Scripture is served from the curated corpus in the database. The runtime model
analyses the user's reflection and nothing else. See docs/backend.md.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.recommendations import router as recommendations_router

app = FastAPI(
    title="MoodVerse API",
    version="0.1.0",
    summary="Curated scripture recommendation for emotional reflection.",
)

app.include_router(recommendations_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
