"""Embedding provider tests. No network: the Gemini endpoint is stubbed."""

from __future__ import annotations

import io
import json
import math
import urllib.error

import pytest

from app.core.config import Settings
from app.services import embeddings
from app.services.embeddings import GeminiEmbedding, get_embedding_provider


def gemini_settings(**overrides) -> Settings:
    values = {
        "EMBEDDING_PROVIDER": "gemini",
        "EMBEDDING_DIMENSION": 4,
        "GEMINI_API_KEY": "test-key",
    }
    values.update(overrides)
    return Settings(**values)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_gemini_is_selected_by_config():
    provider = get_embedding_provider(gemini_settings())
    assert isinstance(provider, GeminiEmbedding)
    assert provider.model_id == "gemini-embedding-001-4"


def test_gemini_requires_a_key():
    with pytest.raises(ValueError):
        GeminiEmbedding(gemini_settings(GEMINI_API_KEY=None))


def test_documents_and_queries_use_their_task_types_and_come_back_unit_length(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        sent.append(body)
        # Truncated Gemini vectors are not unit length.
        values = [[3.0, 4.0, 0.0, 0.0] for _ in body["requests"]]
        return _Response(json.dumps({"embeddings": [{"values": v} for v in values]}).encode())

    monkeypatch.setattr(embeddings.urllib.request, "urlopen", fake_urlopen)
    provider = GeminiEmbedding(gemini_settings())

    documents = provider.embed_documents(["a", "b", "c"])
    query = provider.embed_query("how do I stop worrying")

    assert {r["taskType"] for r in sent[0]["requests"]} == {"RETRIEVAL_DOCUMENT"}
    assert sent[1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    assert all(r["outputDimensionality"] == 4 for r in sent[0]["requests"])
    for vector in [*documents, query]:
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)


def test_a_rate_limited_query_fails_fast_instead_of_waiting(monkeypatch):
    calls = []

    def limited(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(embeddings.urllib.request, "urlopen", limited)
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: pytest.fail("query must not back off"))
    with pytest.raises(RuntimeError):
        GeminiEmbedding(gemini_settings()).embed_query("I feel alone")
    assert len(calls) == 1


def test_a_short_response_is_rejected_rather_than_misaligned(monkeypatch):
    def short(request, timeout):
        return _Response(json.dumps({"embeddings": [{"values": [1.0, 0, 0, 0]}]}).encode())

    monkeypatch.setattr(embeddings.urllib.request, "urlopen", short)
    with pytest.raises(RuntimeError):
        GeminiEmbedding(gemini_settings()).embed_documents(["a", "b"])
