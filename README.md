# MoodVerse

You write down how you feel. MoodVerse returns scripture that speaks to it —
from the Bible or the Quran, chosen from a **curated corpus in a database**,
never written by a model.

That distinction is the whole point of the project, so it is enforced
structurally rather than by prompt discipline. See
[The AI boundary](#the-ai-boundary).

---

## Table of contents

- [What it does](#what-it-does)
- [The AI boundary](#the-ai-boundary)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API](#api)
- [Web API console](#web-api-console)
- [Repository layout](#repository-layout)
- [Running without Docker](#running-without-docker)
- [Rebuilding the corpus](#rebuilding-the-corpus)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Project status](#project-status)

---

## What it does

1. A signed-in user submits a reflection — typed text, or a voice recording.
2. The API stores it, returns `202 {reflection_id, status: "pending"}` and hands
   the work to a background worker. Nothing analyses anything inside the request.
3. The worker transcribes (voice only), asks Gemini to turn the reflection into
   structured emotions, themes and intent, embeds it, and retrieves candidate
   verses by vector similarity.
4. Serving constraints drop anything unsafe or context-dependent, the survivors
   are ranked with an explainable score, and the result is persisted.
5. The client polls `GET /api/v1/reflections/{id}` until the status moves to
   `completed` or `failed`, then reads the verses and can leave feedback.

```text
client ──POST /api/v1/recommendations──▶ api ──enqueue──▶ Postgres queue
   │                                      │                     │
   │                                      │                worker-heavy
   │                                      │            transcribe → analyse
   │                                      │            → embed → retrieve
   │                                      │            → rank → persist
   └──GET /api/v1/reflections/{id}────────┴─────────────────────┘
```

There is no Redis. Celery's broker is Kombu's SQLAlchemy transport and its
result backend is Celery's SQLAlchemy backend, both pointed at the same
Postgres database as the app — so a fresh clone needs exactly two services:
Postgres, and the image built from `docker/backend.Dockerfile`.

## The AI boundary

Two uses of AI, which must never be merged:

| | Build time — corpus enrichment | Runtime — reflection analysis |
| --- | --- | --- |
| When | Offline, once, committed to the repo | Per request, in a worker |
| Cost | **None.** No paid API | Gemini free tier |
| Output | Taxonomy labels on existing verses | Emotions, themes, intent |
| Can it produce scripture? | No | **No** |

The runtime model reads what the *user* wrote and nothing else. It has no
access to the corpus, and the analysis schema has no field a verse could be
returned in. If retrieval finds nothing eligible, the API says so — it never
generates a passage. `data/raw/` is read-only and digest-checked on every
pipeline run.

## Quickstart

Requires Docker and Docker Compose. Nothing else — no Python, no Postgres.

```bash
git clone <this repo> && cd MoodVerse_bd
cp .env.example .env              # 1. required: Compose and the backend both read it
docker compose up -d              # 2. Postgres + API + both workers; migrations run on start
docker compose run --rm ingest    # 3. load the curated corpus (idempotent)
curl localhost:8080/health        # {"status":"ok"}
```

Interactive API docs: <http://localhost:8080/docs>

| | Host | In-container |
| --- | --- | --- |
| API | <http://127.0.0.1:8080> | `api:8000` |
| Postgres | `127.0.0.1:55433` | `db:5432` |

Both host ports bind to loopback only and avoid 5432/8000, which are commonly
already taken. Move either without editing a file — set `DB_HOST_PORT` /
`API_HOST_PORT` in `.env`.

Out of the box `AI_PROVIDER=gemini` needs a `GEMINI_API_KEY`. Set
`AI_PROVIDER=heuristic` instead to run the whole pipeline with no key and no
cost — retrieval and ranking are unaffected, only the analysis step is cruder.

Useful afterwards:

```bash
docker compose ps                        # what is running, and is it healthy
docker compose logs -f api worker-heavy  # follow the interesting logs
docker compose down                      # stop; the database volume survives
docker compose down -v                   # stop and delete the database too
```

## Configuration

**One file: `.env` at the repository root.** Compose reads it for host ports and
database credentials, hands it to every service via `env_file`, and the backend
reads the same file directly when run outside Docker. `.env.example` documents
every key; copy it and fill in what you need.

The only values Compose sets itself are the ones that genuinely differ inside
the network — `DATABASE_URL` pointing at `db:5432` rather than at your host,
and `RUN_MIGRATIONS` on the `api` service, which owns migrations so no worker
races it.

Everything is optional except `DATABASE_URL`. Unset provider keys degrade
rather than crash:

| Unset | Effect |
| --- | --- |
| `GEMINI_API_KEY` | Set `AI_PROVIDER=heuristic`; no key needed |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | `/auth/oidc/*` reports 503; password login unaffected |
| `SMTP_HOST` | Registration succeeds; the verification mail is logged, not sent |
| `CARTESIA_API_KEY` | Voice reflections fail with a clear `error`; text is unaffected |

`JWT_SECRET_KEY` and `SESSION_SECRET_KEY` ship with insecure dev defaults so a
clone runs immediately. **Replace both before any non-local deployment:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## API

Every `/api/v1/*` route requires `Authorization: Bearer <access_token>`.

### Auth — `/auth`

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register` | Create an account, get a token pair |
| `POST` | `/auth/login` | OAuth2 password form; `username` holds the email |
| `POST` | `/auth/refresh` | Rotate a refresh token for a new pair |
| `POST` | `/auth/logout` | Revoke one refresh token (idempotent) |
| `GET` | `/auth/me` | The current user |
| `GET` | `/auth/verify-email?token=` | Confirm an address (idempotent, public) |
| `POST` | `/auth/resend-verification` | Re-send the verification mail |
| `GET` | `/auth/oidc/login` | Start Google sign-in |
| `GET` | `/auth/oidc/callback` | Exchange Google's code for MoodVerse tokens |
| `GET` | `/auth/oidc/logout` | RP-initiated logout |

Password and Google sign-in converge on the same token pair, so every protected
route verifies one kind of credential and cannot tell the two apart.

### Reflections — `/api/v1`

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/recommendations` | Submit text → `202 {reflection_id, status}` |
| `POST` | `/api/v1/reflections/voice` | Submit audio (multipart: `religion`, `audio`) |
| `GET` | `/api/v1/reflections/{id}` | Poll one reflection's status and results |
| `GET` | `/api/v1/reflections/history` | Paged history (`limit`, `offset`) |
| `POST` | `/api/v1/reflections/{id}/feedback` | Rate a served verse |
| `GET` | `/api/v1/scriptures/{canonical_id}` | Read one curated verse |
| `GET` | `/health` | Liveness, unauthenticated |

Both submit routes return immediately and are processed in the background; poll
the reflection until `status` leaves `pending`.

## Web API console

A Next.js app for exercising every endpoint by hand lives in the sibling
`MoodVerse_fd/` directory — sign in, submit a reflection, watch it move
`pending → processing → completed`, and inspect the raw request and response of
every call. It is a development tool for this API, not the product; the mobile
client is a separate React Native app.

```bash
cd ../MoodVerse_fd
npm install
npm run dev     # http://127.0.0.1:3200
```

It calls the API from the browser, so the API must allow its origin —
`CORS_ALLOWED_ORIGINS` in `.env` already lists `http://localhost:3200` and
`http://127.0.0.1:3200`. Port 3200 avoids the Windows/Hyper-V reserved range
that includes port 3000 on this machine.

## Repository layout

Entries marked *(generated)* are deterministic outputs: git-ignored, rebuilt
from committed sources, never committed.

```text
MoodVerse_bd/
├── .env.example                  # every setting, documented — the only one
├── docker-compose.yml            # the entry point: db, api, 2 workers, ingest
├── docker/
│   ├── backend.Dockerfile        # one image, three roles (api + both workers)
│   ├── backend-entrypoint.sh     # optional migrate, then exec as PID 1
│   └── postgres/initdb/          # enables pgvector on a fresh volume
├── backend/
│   ├── app/
│   │   ├── api/v1/               # routers
│   │   ├── core/                 # config, security, celery, oauth
│   │   ├── models/               # SQLAlchemy 2.x
│   │   ├── schemas/              # request/response shapes
│   │   ├── services/             # retrieval, ranking, providers, pipeline
│   │   └── tasks/                # Celery tasks: reflections (heavy), email (light)
│   ├── alembic/                  # migrations
│   ├── tests/
│   ├── ingest.py                 # corpus + enrichment into the database
│   └── README.md                 # backend internals and design notes
├── data/
│   ├── raw/                      # read-only source inputs, digest-checked
│   └── processed/                # the unified corpus (generated) + enrichment
├── pipeline/
│   ├── phase0/                   # sources → one unified corpus
│   └── phase1/                   # corpus → taxonomy enrichment
└── docs/                         # product, architecture and phase specs
```

## Running without Docker

Postgres 17 with the `pgvector` extension must be reachable. The Compose
database is the easy way to get one:

```bash
docker compose up -d db

cd backend
python -m venv ../.venv
../.venv/Scripts/Activate.ps1     # PowerShell; macOS/Linux: source ../.venv/bin/activate
pip install -e ".[dev]"

# .env at the repository root is picked up automatically.
alembic upgrade head
python ingest.py --only-servable
uvicorn app.main:app --reload --port 8000
```

Background jobs need a worker per queue, each in its own shell:

```bash
celery -A app.core.celery_app worker -Q heavy --concurrency=2   # analysis, transcription
celery -A app.core.celery_app worker -Q light --concurrency=4   # email
```

Without a worker running, every reflection stays `pending` forever — the single
most common "it's broken" report.

## Rebuilding the corpus

Not needed to run the app: the enrichment is committed. Rebuild only after
changing the taxonomy or the sources. The same inputs plus the same pipeline
version produce byte-identical outputs.

```bash
python pipeline/phase0/build_unified_corpus.py
python pipeline/phase1/build_label_inventory.py
python pipeline/phase1/build_ledger.py
python pipeline/phase1/build_priors.py
python pipeline/phase1/build_enrichment.py --bootstrap
python pipeline/phase1/validate.py
```

## Tests

```bash
cd backend && pytest                           # 23 tests, no database required
python pipeline/phase1/tests/test_phase1.py    # 18 pipeline tests
```

The backend tests cover the serving constraints directly: non-servable statuses
are never returned, a verse needing context it cannot resolve is refused,
`avoid_for_states` blocks the named emotion, crisis intensity restricts both
`crisis_safe` and the permitted intents, and ranking is deterministic with a
breakdown that sums to the final score.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| A reflection never leaves `pending` | No worker draining `heavy` — check `docker compose ps` |
| `docker compose up` fails on `.env` | You skipped `cp .env.example .env` |
| Reflections complete but return no verses | Corpus not loaded: `docker compose run --rm ingest` |
| Browser calls fail with a CORS error | Add the origin to `CORS_ALLOWED_ORIGINS`, then `docker compose up -d api` |
| `/auth/oidc/*` returns 503 | `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` unset — by design |
| Port already in use | Change `DB_HOST_PORT` / `API_HOST_PORT` in `.env` |

## Project status

**Phase 0 — complete.** 37,339 records unified (31,103 Bible, 6,236 Quran),
0 errors, 0 unresolved.

**Phase 1 — pipeline complete, annotation in progress.** 14/14 validation checks
and 18/18 tests pass. Annotation is performed offline and committed; no paid API
is involved.

**Phases 2–3 — complete.** Schema, retrieval, ranking, the async API,
persistence, auth (password and Google OIDC), email verification, background
jobs, and voice input pulled forward from Phase 4.

Known limitations are listed in [backend/README.md](backend/README.md). The two
that matter most:

- **Only 28 verses are currently servable**, because Phase 1 annotation is still
  in progress. Retrieval is correct; the corpus behind it is thin. A crisis
  reflection returns nothing at all — default-deny working as designed, but not
  yet a usable product state.
- **The default embedding is a hashed bag-of-words.** It approximates lexical
  overlap, not meaning: it matches "weep" to "weep" but not to "mourn". Replace
  it with a sentence encoder before making any claim about retrieval quality.
