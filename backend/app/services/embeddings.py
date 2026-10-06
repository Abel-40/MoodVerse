"""Embedding providers.

The model is configurable because the choice is not settled. What is settled is
the shape: one interface, a dimension that must match the pgvector column, and a
model id recorded on every row so a re-index can tell which vectors are stale.

The default provider costs nothing and calls nothing. It is a deterministic
hashed bag-of-words, which is a real if weak semantic signal - good enough to
develop, test and demo the retrieval stack end to end, and honest about being a
placeholder rather than a sentence encoder. `gemini` is the sentence encoder.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
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

    # Asymmetric encoders embed a short question and a stored passage
    # differently. Symmetric ones need not care, hence the defaults.
    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_batch(texts)


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


class GeminiEmbedding(EmbeddingProvider):
    """Gemini sentence embeddings, truncated to the column's dimension.

    Passages are embedded as RETRIEVAL_DOCUMENT and reflections as
    RETRIEVAL_QUERY, which is what lets "I can't stop worrying about money"
    land near "take no thought for your life" without sharing a word.
    Truncated vectors are not unit length, so every vector is renormalised.
    """

    _API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
    # The batch endpoint accepts up to 100 requests; smaller batches stay
    # under the free tier's per-minute token budget.
    BATCH_SIZE = 50
    RETRIES = 5
    BACKOFF_SECONDS = 15.0

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise ValueError("EMBEDDING_PROVIDER=gemini needs GEMINI_API_KEY")
        self._settings = settings
        self._model = settings.gemini_embedding_model
        self._dimension = settings.embedding_dimension

    @property
    def model_id(self) -> str:
        return f"{self._model}-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        return self.embed_query(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        # One attempt: a reflection must not wait a minute on a rate limit.
        # The caller ranks without similarity instead.
        return self._request([text], "RETRIEVAL_QUERY", retries=0)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            chunk = texts[start:start + self.BATCH_SIZE]
            vectors.extend(self._request(chunk, "RETRIEVAL_DOCUMENT", retries=self.RETRIES))
        return vectors

    def _request(self, texts: list[str], task: str, retries: int) -> list[list[float]]:
        payload = {
            "requests": [
                {
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task,
                    "outputDimensionality": self._dimension,
                }
                for text in texts
            ]
        }
        request = urllib.request.Request(
            f"{self._API_ROOT}/{self._model}:batchEmbedContents",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._settings.gemini_api_key or "",
            },
        )
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 503) and attempt < retries:
                    time.sleep(self.BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise RuntimeError(f"embedding failed: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < retries:
                    time.sleep(self.BACKOFF_SECONDS)
                    continue
                raise RuntimeError(f"embedding failed: {exc}") from exc
        vectors = [_normalise(e["values"]) for e in body["embeddings"]]
        if len(vectors) != len(texts) or any(len(v) != self._dimension for v in vectors):
            raise RuntimeError("embedding failed: response does not match the request")
        return vectors


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Resolve the configured embedding provider."""
    settings = settings or get_settings()
    if settings.embedding_provider == "hash":
        return HashingEmbedding(settings.embedding_dimension)
    if settings.embedding_provider == "gemini":
        return GeminiEmbedding(settings)
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
