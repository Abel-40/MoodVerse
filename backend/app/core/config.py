"""Application settings.

Every credential is read here and nowhere else. Nothing in `api/` or
`services/` reads the environment directly, so there is exactly one place to
audit for secret handling.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# There is one .env, at the repository root next to docker-compose.yml, so the
# container and a developer running uvicorn from backend/ read the same file.
_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    # A .env in the working directory wins over the repository one, which is
    # what makes a per-checkout override possible without editing either.
    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV_FILE, ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # psycopg3 serves both sync and async through this one scheme, so the
    # application, Alembic and ingestion all read the same string.
    database_url: str = Field(
        default="postgresql+psycopg://moodverse:moodverse@localhost:55433/moodverse",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")

    # Runtime AI. Analyses a reflection; never produces scripture.
    ai_provider: str = Field(default="gemini", alias="AI_PROVIDER")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    embedding_provider: str = Field(default="hash", alias="EMBEDDING_PROVIDER")
    embedding_dimension: int = Field(default=768, alias="EMBEDDING_DIMENSION")

    retrieval_candidate_limit: int = Field(default=200, alias="RETRIEVAL_CANDIDATE_LIMIT")
    retrieval_result_limit: int = Field(default=5, alias="RETRIEVAL_RESULT_LIMIT")

    # --- browser clients ----------------------------------------------------
    # Exact origins, comma-separated. Only a browser needs this: the React
    # Native client sends no Origin header and is unaffected either way. An
    # empty value disables CORS entirely rather than falling back to "*".
    cors_allowed_origins_raw: str = Field(
        default="http://localhost:3000", alias="CORS_ALLOWED_ORIGINS"
    )

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins_raw.split(",") if o.strip()]

    # --- auth: custom JWT -------------------------------------------------
    # Insecure defaults so the app runs out of the box in dev, the same way
    # database_url does. Both MUST be overridden with a random value before
    # any non-local deployment; nothing here can enforce that at import time
    # because Settings has no concept of "environment".
    jwt_secret_key: str = Field(
        default="dev-insecure-jwt-secret-change-me", alias="JWT_SECRET_KEY"
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=30, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # Signs the Starlette session cookie Authlib uses to hold OIDC state/nonce
    # between the /login redirect and the /callback request. Unrelated to the
    # app's own JWTs.
    session_secret_key: str = Field(
        default="dev-insecure-session-secret-change-me", alias="SESSION_SECRET_KEY"
    )

    # --- auth: Google OIDC --------------------------------------------------
    # Both unset means OIDC login is disabled; the oidc router reports 503
    # rather than the app failing to start, the same tolerance gemini_api_key
    # gets.
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    oidc_google_discovery_url: str = Field(
        default="https://accounts.google.com/.well-known/openid-configuration",
        alias="OIDC_GOOGLE_DISCOVERY_URL",
    )
    # Backend callback URL registered with the provider's console. If unset it
    # is derived from the incoming request at redirect time.
    oidc_redirect_uri: str | None = Field(default=None, alias="OIDC_REDIRECT_URI")

    # Exact-match allow-list, comma-separated. A caller-supplied redirect_uri
    # on /auth/oidc/login is only honoured if it appears here verbatim -
    # otherwise the callback would be an open redirect that can exfiltrate a
    # freshly issued token to any URL an attacker asks the login link to send
    # a victim through.
    oidc_allowed_app_redirects_raw: str = Field(
        default="", alias="OIDC_ALLOWED_APP_REDIRECTS"
    )

    @property
    def oidc_allowed_app_redirects(self) -> frozenset[str]:
        return frozenset(
            uri.strip()
            for uri in self.oidc_allowed_app_redirects_raw.split(",")
            if uri.strip()
        )

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    # --- background jobs: Celery, no Redis ---------------------------------
    # Broker and result backend both default to database_url itself (Kombu's
    # SQLAlchemy transport / Celery's SQLAlchemy result backend), so a fresh
    # clone needs no second service. Override either independently only if
    # background jobs should use a different database than the app.
    celery_broker_url_override: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend_url_override: str | None = Field(
        default=None, alias="CELERY_RESULT_BACKEND_URL"
    )
    # Two queues so a burst of Gemini/Cartesia calls can never delay a
    # verification email behind it, and vice versa - not two priorities on one
    # queue, two independently-drained ones with their own worker process.
    celery_queue_heavy: str = Field(default="heavy", alias="CELERY_QUEUE_HEAVY")
    celery_queue_light: str = Field(default="light", alias="CELERY_QUEUE_LIGHT")

    @property
    def celery_broker_url(self) -> str:
        return self.celery_broker_url_override or f"sqla+{self.database_url}"

    @property
    def celery_result_backend_url(self) -> str:
        return self.celery_result_backend_url_override or f"db+{self.database_url}"

    # --- email: signup verification -----------------------------------------
    # Unset smtp_host means "don't send" rather than "fail" - send_verification_
    # email raises clearly when a task actually tries, the same tolerance
    # gemini_api_key/google_client_id get, so registration itself never breaks
    # because mail isn't configured yet.
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    # STARTTLS on the given port (587 is the common case). Implicit TLS/SSL
    # (port 465) is not supported - use a STARTTLS-capable relay/port instead.
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_from_email: str = Field(default="noreply@moodverse.app", alias="SMTP_FROM_EMAIL")

    email_verification_token_expire_hours: int = Field(
        default=24, alias="EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS"
    )
    # Where /auth/verify-email sends the browser after a successful verify.
    # Unset returns a small JSON confirmation instead of redirecting - this is
    # a server-configured constant, never caller-supplied, so it carries none
    # of the open-redirect risk oidc_allowed_app_redirects guards against.
    email_verification_redirect_url: str | None = Field(
        default=None, alias="EMAIL_VERIFICATION_REDIRECT_URL"
    )
    # Used to build the absolute link inside the verification email itself
    # (and nowhere else) - built from this trusted setting rather than an
    # inbound Host header, since the link is composed inside a background
    # task with no request to read a header from, and because trusting a
    # client-supplied Host to build a link mailed to someone is exactly the
    # kind of host-header trust an attacker can abuse.
    public_base_url: str = Field(default="http://localhost:8080", alias="PUBLIC_BASE_URL")

    # --- voice: speech-to-text ----------------------------------------------
    stt_provider: str = Field(default="cartesia", alias="STT_PROVIDER")
    cartesia_api_key: str | None = Field(default=None, alias="CARTESIA_API_KEY")
    cartesia_stt_model: str = Field(default="ink-whisper", alias="CARTESIA_STT_MODEL")
    cartesia_api_version: str = Field(default="2026-08-14", alias="CARTESIA_API_VERSION")
    cartesia_base_url: str = Field(default="https://api.cartesia.ai", alias="CARTESIA_BASE_URL")
    # Audio flows through the database-backed task queue as base64 in a task's
    # row, not a shared file volume, so this cap keeps a single voice upload
    # from bloating kombu_message. ~10 MB covers several minutes of compressed
    # speech audio.
    voice_max_upload_bytes: int = Field(default=10_000_000, alias="VOICE_MAX_UPLOAD_BYTES")


@lru_cache
def get_settings() -> Settings:
    return Settings()
