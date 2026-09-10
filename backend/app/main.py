"""MoodVerse API.

Scripture is served from the curated corpus in the database. The runtime model
analyses the user's reflection and nothing else. See docs/backend.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.oidc import router as oidc_router
from app.api.v1.recommendations import router as recommendations_router
from app.api.v1.reflections import router as reflections_router
from app.api.v1.scriptures import router as scriptures_router
from app.core.config import get_settings
from app.core.eventloop import configure_event_loop
from app.db.session import dispose_engine

# Before uvicorn creates its loop; a no-op off Windows.
configure_event_loop()

_settings = get_settings()


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

# Signs the session cookie Authlib's OIDC flow uses to carry state/nonce
# between /auth/oidc/login and /auth/oidc/callback. Unrelated to the app's
# own JWTs, which are stateless bearer tokens and touch no cookie.
app.add_middleware(SessionMiddleware, secret_key=_settings.session_secret_key)

# Added last, so it wraps everything above and can answer a preflight without
# the request reaching a route. Only browser clients need it - see
# CORS_ALLOWED_ORIGINS; an empty list leaves cross-origin requests blocked.
if _settings.cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(oidc_router)
app.include_router(recommendations_router)
app.include_router(reflections_router)
app.include_router(scriptures_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
