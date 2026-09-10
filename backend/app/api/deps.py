"""Shared FastAPI dependencies for authenticated routes.

`get_current_user` is the one place every protected endpoint converges on,
whether the caller signed in with a password or with Google: it only ever
verifies a MoodVerse access token, and by the time one exists the two login
paths are indistinguishable.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_TOKEN_TYPE, TokenError, decode_token
from app.db.session import get_session
from app.models.reflection import User

# tokenUrl only drives Swagger UI's "Authorize" form; the dependency itself
# accepts a bearer token regardless of which endpoint issued it.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise unauthorized

    try:
        payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except TokenError as exc:
        raise unauthorized from exc

    user = await session.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user
