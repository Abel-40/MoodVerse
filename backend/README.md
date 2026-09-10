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

## Running it

Everything is driven from `docker-compose.yml` at the repository root. The
Dockerfile only describes how the image is built; Compose is the entry point,
and adding a service means appending a block that reuses its anchors.

```bash
docker compose up -d              # database + API, migrations run on start
docker compose run --rm ingest    # load the curated corpus
curl localhost:8080/health
```

| | Host | In-container |
| --- | --- | --- |
| API | http://127.0.0.1:8080 | 8000 |
| Postgres | 127.0.0.1:55433 | db:5432 |

Both host ports avoid 5432 and 8000, which are already taken on this machine by
another stack, and both bind to loopback only. Move either without editing any
file:

```bash
DB_HOST_PORT=55555 API_HOST_PORT=8090 docker compose up -d
```

`AI_PROVIDER` defaults to `heuristic`, which needs no key and costs nothing. Set
`AI_PROVIDER=gemini` and `GEMINI_API_KEY` for real reflection analysis.

## Async

Async end to end: FastAPI endpoints, SQLAlchemy `AsyncSession`, psycopg3 in
async mode, and Alembic migrating through `connection.run_sync`.

`rank`, `score` and `eligible` stay synchronous and pure on purpose - they touch
no I/O, so they are the layer worth testing directly and the tests need no
event loop.

One Windows note: psycopg's async mode cannot run on the default
`ProactorEventLoop` and fails on the first connection. `app/core/eventloop.py`
selects the selector loop on Windows and does nothing elsewhere, so the same
entry points work locally and in the Linux container.

## Local development without Docker

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env
export DATABASE_URL=postgresql+psycopg://moodverse:moodverse@127.0.0.1:55433/moodverse
alembic upgrade head
python ingest.py --only-servable
```

## Migrations

Async, through `connection.run_sync`. The pgvector extension is created before
migrating, so a fresh database needs no manual setup.

```bash
alembic revision --autogenerate -m "what changed"
alembic upgrade head
```

Autogenerate renders `Vector` columns but does not emit the `pgvector` import;
`script.py.mako` adds it to every revision so this cannot bite again.

## Ingestion

Loads the committed corpus and enrichment. Calls no AI provider and costs
nothing. Idempotent - re-run after any re-curation.

```bash
docker compose run --rm ingest          # or: python ingest.py --only-servable
```

`--only-servable` also loads the verses each `INCLUDE_WITH_CONTEXT` record needs
to render its context span, even though those neighbours are not servable
themselves. Without them the API would correctly drop every such verse for
missing context, and nothing would ever be returned.

It refuses any record whose enrichment digest disagrees with the corpus text. A
non-zero `drifted` count means Phase 1 is stale and must be rebuilt before
serving.

## Run

- `POST /api/v1/recommendations` - reflection in, ranked curated verses out
- `GET /health`

Locally without Docker: `uvicorn app.main:app --reload`

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
- Only 28 verses are currently servable, because Phase 1 annotation is in
  progress. Retrieval is correct but the corpus behind it is thin. A crisis
  reflection currently returns nothing at all, which is default-deny working
  as designed rather than a fault, but it is not a usable product state.
