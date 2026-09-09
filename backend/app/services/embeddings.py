"""Embedding providers.

The model is configurable because the choice is not settled. What is settled is
the shape: one interface, a dimension that must match the pgvector column, and a
model id recorded on every row so a re-index can tell which vectors are stale.

The default provider costs nothing and calls nothing. It is a deterministic
hashed bag-of-words, which is a real if weak semantic signal - good enough to
develop, test and demo the retrieval stack end to end, and honest about being a
placeholder rather than a sentence encoder.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

from app.core.config import Settings, get_settings

_TOKEN = re.compile(r"[a-z']+")

# Words carrying no discriminative signal for this corpus.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "him", "his", "i", "in", "is", "it",
    "its", "me", "my", "not", "of", "on", "or", "our", "shall", "she", "so",
    "that", "the", "their", "them", "they", "this", "to", "unto", "us", "was",
    "we", "were", "what", "when", "which", "who", "will", "with", "you", "your",
})


def tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


class EmbeddingProvider(ABC):
    """One interface. Swapping the model must not touch retrieval or the schema."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class HashingEmbedding(EmbeddingProvider):
    """Deterministic hashed bag-of-words, L2-normalised.

    Same text always yields the same vector, with no network call and no key,
    so ingestion and retrieval are reproducible and free. Cosine distance over
    these vectors approximates lexical overlap, not meaning: it will match
    "weep" to "weep" but not to "mourn". Replace it with a sentence encoder
    before any quality claim is made about retrieval.
    """

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return f"hash-bow-v1-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in tokenise(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            # Sign from a separate byte so collisions cancel rather than pile up.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Resolve the configured embedding provider."""
    settings = settings or get_settings()
    if settings.embedding_provider == "hash":
        return HashingEmbedding(settings.embedding_dimension)
    raise ValueError(
        f"unknown EMBEDDING_PROVIDER {settings.embedding_provider!r}. "
        "Add a provider class rather than special-casing the caller."
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity for already-normalised vectors, clamped to [-1, 1]."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    return max(-1.0, min(1.0, dot))
