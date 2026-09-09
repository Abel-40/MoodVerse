"""Application settings.

Every credential is read here and nowhere else. Nothing in `api/` or
`services/` reads the environment directly, so there is exactly one place to
audit for secret handling.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/moodverse",
        alias="DATABASE_URL",
    )

    # Runtime AI. Analyses a reflection; never produces scripture.
    ai_provider: str = Field(default="gemini", alias="AI_PROVIDER")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    embedding_provider: str = Field(default="hash", alias="EMBEDDING_PROVIDER")
    embedding_dimension: int = Field(default=768, alias="EMBEDDING_DIMENSION")

    retrieval_candidate_limit: int = Field(default=200, alias="RETRIEVAL_CANDIDATE_LIMIT")
    retrieval_result_limit: int = Field(default=5, alias="RETRIEVAL_RESULT_LIMIT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
