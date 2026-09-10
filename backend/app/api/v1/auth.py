"""Custom password-based auth: register, login, refresh, logout, me.

Mounted at /auth rather than under /api/v1 - these are cross-cutting identity
endpoints, not versioned business API. api/v1/oidc.py follows the same
convention at /auth/oidc/*.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import (
    EMAIL_VERIFICATION_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TokenError,
    create_email_verification_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_session
from app.models.auth import RefreshToken
from app.models.reflection import User
from app.schemas.auth import (
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
    UserRegister,
    UserPreferencesUpdate,
)
from app.services import auth as auth_service
from app.tasks.email import send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _enqueue_verification_email(user: User, settings: Settings) -> None:
    """Best-effort: a broker hiccup must not fail the registration itself -
    the user can still hit /auth/resend-verification once it recovers."""
    token = create_email_verification_token(user.id, settings)
    verify_url = f"{settings.public_base_url.rstrip('/')}/auth/verify-email?token={token}"
    try:
        send_verification_email.delay(user.email, user.display_name, verify_url)
    except Exception:
        logger.exception("failed to enqueue verification email for user %s", user.id)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegister,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    existing = await auth_service.get_user_by_email(session, payload.email)
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists."
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Closes the race between the check above and this insert.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists."
        ) from exc

    _enqueue_verification_email(user, settings)
    return await auth_service.issue_tokens(session, user, settings)


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    # OAuth2PasswordRequestForm names the identifier field "username"; this
    # app has no separate username, so the client sends the email there.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    user = await auth_service.get_user_by_email(session, form.username)
    if user is None or user.password_hash is None or not verify_password(
        form.password, user.password_hash
    ):
        raise invalid
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled.")

    return await auth_service.issue_tokens(session, user, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token.")
    try:
        claims = decode_token(
            payload.refresh_token, expected_type=REFRESH_TOKEN_TYPE, settings=settings
        )
    except TokenError as exc:
        raise invalid from exc

    result = await session.execute(select(RefreshToken).where(RefreshToken.jti == claims.jti))
    stored = result.scalar_one_or_none()
    if stored is None or not stored.is_active:
        raise invalid

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise invalid

    # Rotation: the presented refresh token is single-use, so a stolen and
    # replayed token is detectable (it will already be revoked).
    stored.revoked_at = datetime.now(timezone.utc)
    return await auth_service.issue_tokens(session, user, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke one refresh token.

    Idempotent by design: revoking an already-revoked or never-valid token is
    not an error, so a client never has to distinguish "logged out" from
    "already logged out."
    """
    try:
        claims = decode_token(payload.refresh_token, expected_type=REFRESH_TOKEN_TYPE)
    except TokenError:
        return None

    result = await session.execute(select(RefreshToken).where(RefreshToken.jti == claims.jti))
    stored = result.scalar_one_or_none()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    return None


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    out = UserOut.model_validate(current_user)
    return out.model_copy(
        update={"linked_providers": [a.provider for a in current_user.oauth_accounts]}
    )


@router.patch("/me/preferences", response_model=UserOut)
async def update_preferences(
    payload: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    current_user.preferred_religion = payload.preferred_religion
    await session.commit()
    await session.refresh(current_user)
    out = UserOut.model_validate(current_user)
    return out.model_copy(
        update={"linked_providers": [a.provider for a in current_user.oauth_accounts]}
    )


@router.get("/verify-email", response_model=None)
async def verify_email(
    token: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict | RedirectResponse:
    """Public - the token itself is the credential, not the caller's session.

    Idempotent: verifying an already-verified account (a stale link clicked
    twice, or an OIDC account that arrived pre-verified) just confirms rather
    than erroring.
    """
    try:
        claims = decode_token(token, expected_type=EMAIL_VERIFICATION_TOKEN_TYPE, settings=settings)
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This verification link is invalid or has expired."
        ) from exc

    user = await session.get(User, claims.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account.")

    if not user.email_verified:
        user.email_verified = True
        await session.commit()

    if settings.email_verification_redirect_url:
        return RedirectResponse(settings.email_verification_redirect_url)
    return {"verified": True, "email": user.email}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    if current_user.email_verified:
        return {"already_verified": True}
    _enqueue_verification_email(current_user, settings)
    return {"sent": True}
