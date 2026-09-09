# MoodVerse backend

Phase 2 foundation. See `docs/backend.md` for the binding contract.

## The rule this codebase exists to hold

Scripture comes from the database. Always.

The runtime model analyses what the **user** wrote and nothing else. It has no
access to the corpus, and `ReflectionAnalysis` has no field a verse could be
returned in, so this is structural rather than a matter of prompt discipline. If
retrieval finds nothing eligible, the API says so - it never generates a passage.

Corpus enrichment costs nothing and calls no API: it was done offline and is
committed under `data/processed/enrichment/`.

## Setup

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env          # then fill in DATABASE_URL
```

`AI_PROVIDER=heuristic` runs the whole stack with no key and no cost. Set
`AI_PROVIDER=gemini` and `GEMINI_API_KEY` for real reflection analysis.

## Database

Requires PostgreSQL with pgvector:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The initial migration must be generated against a live database, because
autogenerate needs to inspect one:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

## Ingestion

Loads the committed corpus and enrichment. Idempotent; re-run after any
re-curation.

```bash
python ingest.py --dry-run --only-servable   # inspect
python ingest.py --only-servable             # write
```

It refuses any record whose enrichment digest disagrees with the corpus text.
A non-zero `drifted` count means Phase 1 is stale and must be rebuilt before
serving.

## Run

```bash
uvicorn app.main:app --reload
```

- `POST /api/v1/recommendations` - reflection in, ranked curated verses out
- `GET /health`

## Tests

```bash
pytest
```

23 tests, no database required. They cover the serving constraints:
non-servable statuses are never returned, `INCLUDE_WITH_CONTEXT` without a
resolvable span is refused, `avoid_for_states` blocks the named emotion, crisis
intensity restricts both `crisis_safe` and the permitted intents, and ranking is
deterministic with a breakdown that sums to the final score.

## Layout

| Path | What it is |
| --- | --- |
| `app/core/config.py` | Every credential is read here and nowhere else |
| `app/models/` | SQLAlchemy 2.x. Scripture and enrichment are separate tables on purpose |
| `app/services/ai_provider.py` | `AIProvider` interface, Gemini and heuristic implementations |
| `app/services/embeddings.py` | `EmbeddingProvider` interface; default is free and deterministic |
| `app/services/retrieval.py` | Serving constraints and explainable ranking. `rank()` is pure |
| `app/api/v1/` | Routers |
| `ingest.py` | Corpus and enrichment into the database |

## Known limitations

- The default embedding is a hashed bag-of-words. It approximates lexical
  overlap, not meaning: it matches "weep" to "weep" but not to "mourn". Replace
  it with a sentence encoder before making any claim about retrieval quality.
- Authentication is not implemented. `User` exists; the endpoints are open.
- Only 28 verses are currently servable, because Phase 1 annotation is
  in progress. Retrieval is correct but the corpus behind it is thin.
