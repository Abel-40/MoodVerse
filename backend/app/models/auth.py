"""Federated identities and refresh-token revocation.

Two tables, both existing only to make auth work, neither touched by the
recommendation/retrieval domain:

    OAuthAccount    links a provider identity (e.g. Google's `sub`) to a User,
                    so "log in with Google" and "log in with a password" can
                    resolve to the same account.
    RefreshToken    one row per issued refresh token, tracked by its JWT `jti`.
                    A bare JWT cannot be revoked; this is what makes /logout
                    and refresh-token rotation actually work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.reflection import User


class OAuthAccount(Base):
    """One provider identity linked to one MoodVerse user."""

    __tablename__ = "oauth_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # "google" today; the column is a plain string so a second provider needs
    # no migration, only a new authlib.register() call in app/core/oauth.py.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # The provider's stable subject identifier (Google's `sub` claim) - never
    # the email, which a provider account can change.
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="oauth_accounts")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_account_identity"),
    )


class RefreshToken(Base):
    """One issued refresh token. Existence + `revoked_at` is the source of
    truth for whether it is still usable; the JWT's own `exp` is a ceiling on
    top of that, not a substitute for it."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    jti: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(timezone.utc)
