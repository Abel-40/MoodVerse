"""Request/response shapes for auth - custom password login and OIDC alike.

Both paths converge on TokenResponse. get_current_user only ever verifies a
MoodVerse-issued access token; it has no notion of how the user originally
signed in.
"""

from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    # Seconds until access_token expires, so a client knows when to refresh
    # without decoding the JWT itself.
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserPreferencesUpdate(BaseModel):
    preferred_religion: Literal["bible", "quran"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    is_active: bool
    email_verified: bool
    preferred_religion: str | None
    created_at: datetime
    linked_providers: list[str] = Field(default_factory=list)
