"""Auth business logic: user lookup/creation and token issuance.

Kept out of the routers so the password-login path and the OIDC-callback path
issue tokens exactly the same way - the whole point being that
`get_current_user` cannot tell afterwards which one a caller used.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, create_refresh_token
from app.models.auth import MagicLinkToken, OAuthAccount, RefreshToken
from app.models.reflection import User
from app.schemas.auth import TokenResponse


async def issue_tokens(
    session: AsyncSession, user: User, settings: Settings | None = None
) -> TokenResponse:
    """Issue and persist a fresh access/refresh pair for `user`.

    Commits: the refresh token must be durable before it is handed out, or a
    crash between issuing and persisting it would hand a client a refresh
    token /refresh can never recognise.
    """
    settings = settings or get_settings()
    access_token = create_access_token(user.id, settings)
    refresh_token, jti, expires_at = create_refresh_token(user.id, settings)
    session.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    await session.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def find_or_create_oidc_user(
    session: AsyncSession,
    *,
    provider: str,
    provider_user_id: str,
    email: str | None,
    email_verified: bool,
    display_name: str | None,
) -> User:
    """Find-or-create for the OIDC callback.

    Resolution order:
      1. An OAuthAccount already linked to this (provider, subject) - the
         common case on every login after the first.
      2. An existing User with this email, but only if the provider reports
         the email verified. An unverified provider email must never silently
         take over an existing password account - that would let anyone with
         a throwaway "verify later" OIDC account claim someone else's inbox.
      3. Otherwise, a brand new User with no password, since this account has
         never had one to set.
    """
    existing = await session.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    account = existing.scalar_one_or_none()
    if account is not None:
        user = await session.get(User, account.user_id)
        if user is None:  # not reachable while the FK constraint holds
            raise RuntimeError(f"oauth_accounts row {account.id} references a missing user")
        return user

    user = await get_user_by_email(session, email) if email and email_verified else None

    if user is None:
        user = User(
            email=email or f"{provider}:{provider_user_id}@no-email.invalid",
            password_hash=None,
            display_name=display_name,
            email_verified=email_verified,
        )
        session.add(user)
        await session.flush()  # assigns user.id before the OAuthAccount FK below
    elif email_verified and not user.email_verified:
        user.email_verified = True

    session.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
        )
    )
    await session.commit()
    await session.refresh(user)
    return user


def _hash_magic_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_magic_link_token(
    session: AsyncSession, email: str, settings: Settings | None = None
) -> str | None:
    """Store a new single-use sign-in token for `email` and return it raw.

    Returns None, storing nothing, when a link went to this address within
    `magic_link_resend_seconds`: the caller still answers 202, so a burst of
    requests can't flood an inbox or reveal anything.
    """
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    recent = await session.execute(
        select(MagicLinkToken.id)
        .where(
            MagicLinkToken.email == email,
            MagicLinkToken.created_at
            > now - timedelta(seconds=settings.magic_link_resend_seconds),
        )
        .limit(1)
    )
    if recent.scalar_one_or_none() is not None:
        return None

    token = secrets.token_urlsafe(32)
    session.add(
        MagicLinkToken(
            email=email,
            token_hash=_hash_magic_token(token),
            expires_at=now + timedelta(minutes=settings.magic_link_expire_minutes),
        )
    )
    await session.commit()
    return token


async def redeem_magic_link_token(session: AsyncSession, token: str) -> User | None:
    """Spend a sign-in token and return its user, creating the account if this
    is the address's first sign-in. None if the token is unknown, expired or
    already used.

    The claim is a single conditional UPDATE, so two simultaneous clicks on
    the same link cannot both succeed. Opening the link proves control of the
    inbox, so the account's email counts as verified from here on.
    """
    now = datetime.now(timezone.utc)
    claimed = await session.execute(
        update(MagicLinkToken)
        .where(
            MagicLinkToken.token_hash == _hash_magic_token(token),
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(MagicLinkToken.email)
    )
    email = claimed.scalar_one_or_none()
    if email is None:
        await session.rollback()
        return None

    user = await get_user_by_email(session, email)
    if user is None:
        user = User(email=email, password_hash=None, email_verified=True)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            # A simultaneous first sign-in for this address created the
            # account first. The rollback undid this token's claim too, so
            # spend it again and use the account that won.
            await session.rollback()
            await session.execute(
                update(MagicLinkToken)
                .where(MagicLinkToken.token_hash == _hash_magic_token(token))
                .values(used_at=now)
            )
            user = await get_user_by_email(session, email)
            if user is None:
                raise
    elif not user.email_verified:
        user.email_verified = True

    await session.commit()
    await session.refresh(user)
    return user
