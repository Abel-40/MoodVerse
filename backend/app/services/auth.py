"""Auth business logic: user lookup/creation and token issuance.

Kept out of the routers so the password-login path and the OIDC-callback path
issue tokens exactly the same way - the whole point being that
`get_current_user` cannot tell afterwards which one a caller used.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, create_refresh_token
from app.models.auth import OAuthAccount, RefreshToken
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
