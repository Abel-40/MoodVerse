"""Password hashing and the application's own JWTs.

Two different token families exist in this app and they must not be confused:

    this module          issues and verifies MoodVerse's own access/refresh
                          JWTs - the tokens `get_current_user` accepts.
    app/core/oauth.py     drives the *provider's* OIDC handshake (Google). Its
                          id_token is never handed to a client and never
                          accepted by get_current_user; the OIDC callback
                          exchanges it for a MoodVerse token via this module,
                          so one dependency recognises a user regardless of
                          how they signed in.

JWT encode/decode uses joserfc rather than python-jose: Authlib is already a
dependency for OIDC, joserfc is its maintained JOSE implementation (the older
authlib.jose is deprecated), and one JOSE library is enough for the app to
carry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey

from app.core.config import Settings, get_settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
EMAIL_VERIFICATION_TOKEN_TYPE = "email_verification"


class TokenError(Exception):
    """Any invalid, expired, malformed or wrong-type token. Callers map this to 401."""


@dataclass(frozen=True)
class TokenPayload:
    user_id: int
    token_type: str
    jti: str | None
    expires_at: datetime


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, UnicodeEncodeError):
        # A malformed or absent hash (an OIDC-only account has none) must fail
        # closed rather than raise past the caller.
        return False


def _key(settings: Settings) -> OctKey:
    return OctKey.import_key(settings.jwt_secret_key)


def _encode(claims: dict[str, object], settings: Settings) -> str:
    return jwt.encode({"alg": settings.jwt_algorithm}, claims, _key(settings))


def create_access_token(user_id: int, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    claims = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return _encode(claims, settings)


def create_refresh_token(
    user_id: int, settings: Settings | None = None
) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at).

    The caller persists (jti, expires_at) as a `RefreshToken` row - a bare JWT
    cannot be revoked, so revocation is tracked by jti in the database instead.
    """
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.jwt_refresh_token_expire_days)
    jti = str(uuid.uuid4())
    claims = {
        "sub": str(user_id),
        "type": REFRESH_TOKEN_TYPE,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return _encode(claims, settings), jti, expires


def create_email_verification_token(user_id: int, settings: Settings | None = None) -> str:
    """Single-use in effect, not in enforcement: verifying twice is a harmless
    no-op (see /auth/verify-email), so there is no revocation table to check
    here the way refresh tokens need one - only an expiry."""
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=settings.email_verification_token_expire_hours)
    claims = {
        "sub": str(user_id),
        "type": EMAIL_VERIFICATION_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return _encode(claims, settings)


def decode_token(
    token: str, expected_type: str, settings: Settings | None = None
) -> TokenPayload:
    """Verify signature, expiry and token type. Raises TokenError otherwise."""
    settings = settings or get_settings()
    try:
        decoded = jwt.decode(token, _key(settings), algorithms=[settings.jwt_algorithm])
        registry = jwt.JWTClaimsRegistry(
            exp={"essential": True},
            sub={"essential": True},
            type={"essential": True, "values": [expected_type]},
        )
        registry.validate(decoded.claims)
    except JoseError as exc:
        raise TokenError(str(exc)) from exc

    claims = decoded.claims
    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("token subject is not a valid user id") from exc

    return TokenPayload(
        user_id=user_id,
        token_type=claims["type"],
        jti=claims.get("jti"),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
    )
