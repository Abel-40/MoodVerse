# MoodVerse backend

Phase 2 foundation, Phase 3 API/persistence/auth, and voice input pulled
forward from Phase 4. See `docs/backend.md` for the binding contract.

## The rule this codebase exists to hold

Scripture comes from the database. Always.

The runtime model analyses what the **user** wrote and nothing else. It has no
access to the corpus, and `ReflectionAnalysis` has no field a verse could be
returned in, so this is structural rather than a matter of prompt discipline. If
retrieval finds nothing eligible, the API says so - it never generates a passage.

Corpus enrichment costs nothing and calls no API: it was done offline and is
committed under `data/processed/enrichment/`.

## Running it

See the [root README](../README.md) for installation. In short, from the
repository root:

```bash
cp .env.example .env
docker compose up -d              # database + API + both Celery workers; migrations run on start
docker compose run --rm ingest    # load the curated corpus
curl localhost:8080/health
```

`docker-compose.yml` is the entry point; `docker/backend.Dockerfile` only
describes how the image is built. That one image serves three roles - the API
and both workers - which is why they can never drift apart. Each service reads
its configuration from the single root `.env` via `env_file`; the only values
Compose sets inline are the ones that must differ inside the network
(`DATABASE_URL` pointing at `db:5432`, and `RUN_MIGRATIONS` on `api`).

Set `AI_PROVIDER=heuristic` to run with no key and no cost; `gemini` plus
`GEMINI_API_KEY` gives real reflection analysis.

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

Configuration comes from `.env` at the repository root - the same file
Compose uses - so there is nothing to copy into this directory. A `.env` in the
working directory, if one exists, takes precedence over it.

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
python ingest.py --only-servable
uvicorn app.main:app --reload --port 8000
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

- `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`
- `GET /auth/verify-email`, `POST /auth/resend-verification`
- `GET /auth/oidc/login`, `GET /auth/oidc/callback`, `GET /auth/oidc/logout` - Google OIDC via Authlib
- `POST /api/v1/recommendations` - submit a text reflection (requires auth). Returns
  `202 {reflection_id, status: "pending"}` immediately; analysis and retrieval run in
  a background worker - see **Background jobs** below.
- `POST /api/v1/reflections/voice` - submit an audio reflection (multipart form
  fields `religion` and `audio`; requires auth). Same pending/poll contract as
  above, with transcription ahead of it.
- `GET /api/v1/reflections/{id}` - poll one reflection's status/results (requires auth)
- `GET /api/v1/scriptures/{canonical_id}` (requires auth)
- `GET /api/v1/reflections/history` (requires auth)
- `POST /api/v1/reflections/{id}/feedback` (requires auth)
- `GET /health`

Locally without Docker: `uvicorn app.main:app --reload`, plus a worker per queue -
see **Background jobs**.

## Auth

Two ways in, one token type out: every `/api/v1/*` endpoint sits behind
`get_current_user`, which only ever verifies a MoodVerse-issued access token -
it cannot tell whether the user originally registered with a password or
signed in with Google.

**Password.** `POST /auth/register` and `POST /auth/login` (the latter is an
OAuth2 password-form endpoint - `username` holds the email, for Swagger's
"Authorize" button to work) both return `{access_token, refresh_token,
token_type, expires_in}`. Send `Authorization: Bearer <access_token>` on every
protected request. `POST /auth/refresh` rotates a refresh token for a new
pair; `POST /auth/logout` revokes one. Passwords are hashed with bcrypt;
tokens are signed JWTs via `joserfc` (`JWT_SECRET_KEY` in the environment -
change it before any non-local deployment).

**Google OIDC.** `GET /auth/oidc/login` redirects to Google
(`authlib.integrations.starlette_client`, scopes `openid profile email`);
`GET /auth/oidc/callback` verifies the returned ID token, finds or creates the
matching `User` (linked through `oauth_accounts` by Google's `sub`, or by
verified email for an existing password account), and issues the same
token pair as `/auth/login`. Disabled - and reporting 503 - unless
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are set. `GET /auth/oidc/logout`
performs RP-Initiated Logout via Authlib's `logout_redirect`; Google does not
publish an `end_session_endpoint` (it does not implement that part of the
OIDC spec), so for Google this only clears the local session and says so -
the same route works unchanged against a provider that does implement it.

A caller-supplied `redirect_uri` (for handing tokens back to a mobile app via
deep link after `/auth/oidc/callback`) is only honoured if it exactly matches
`OIDC_ALLOWED_APP_REDIRECTS`; otherwise the callback returns the tokens as
JSON. This is not optional - redirecting to an arbitrary caller-supplied URL
after issuing a token is an open redirect that leaks it.

Requires `SESSION_SECRET_KEY` (signs the cookie Authlib uses to carry OIDC
`state`/`nonce` between the login redirect and the callback - unrelated to the
app's own JWTs) via `SessionMiddleware` on the app.

**Email verification.** `POST /auth/register` enqueues a verification email in
the background (failure to enqueue does not fail registration - see
`_enqueue_verification_email` in `app/api/v1/auth.py`). `GET /auth/verify-email
?token=...` marks the account verified (idempotent - a stale or repeated click
is a no-op success, never an error) and, if `EMAIL_VERIFICATION_REDIRECT_URL`
is set, redirects there; otherwise it returns a small JSON confirmation.
`POST /auth/resend-verification` (protected) re-sends it. Nothing currently
gates login or `/api/v1/*` on `email_verified` - registering and using the API
both work before a link is ever clicked. An OIDC sign-in whose provider
reports `email_verified: true` skips this entirely; its `User` row already
carries `email_verified = true` from the callback.

## Background jobs

Celery, with **no Redis**: the broker is Kombu's SQLAlchemy transport
(`sqla+<DATABASE_URL>`, polling two tables it creates itself,
`kombu_message`/`kombu_queue`) and the result backend is Celery's own
SQLAlchemy backend (`db+<DATABASE_URL>`, `celery_taskmeta`/
`celery_tasksetmeta`) - see `app/core/celery_app.py`. Neither table set is
part of `Base.metadata`; `alembic/env.py` excludes them by name from
autogenerate so they never show up as a phantom `drop_table`.

Two queues, two worker processes, so a burst of Gemini/Cartesia calls can
never delay a verification email behind it:

```bash
celery -A app.core.celery_app worker -Q heavy --concurrency=2   # reflection analysis, voice transcription
celery -A app.core.celery_app worker -Q light --concurrency=4   # email only
```

(`docker compose up -d` runs both as `worker-heavy`/`worker-light`.) A
reflection's `status` moves `pending -> processing -> completed`/`failed`,
written directly by the pipeline on every attempt - see
`app/services/reflection_pipeline.py` - independently of whatever Celery's own
retry/result bookkeeping is doing, so polling `GET /api/v1/reflections/{id}`
never has to wait out a task's retries to learn it already failed.

`celery inspect ping` does not work against this broker - the SQLAlchemy
transport does not implement the fanout exchange Celery's control/inspect
commands rely on, confirmed against this exact setup (it hangs until "No
nodes replied within time constraint"). The worker healthchecks in
`docker-compose.yml` check broker connectivity directly instead
(`celery_app.connection().ensure_connection(...)`), not worker liveness via
`inspect`.

Task result rows (`celery_taskmeta`) are not currently pruned - there is no
Celery beat scheduler running the periodic cleanup task, since nothing else
here needs a scheduler yet. They will accumulate; add `celery beat` plus its
own queue if that becomes worth solving.

## Voice reflections (Cartesia)

`POST /api/v1/reflections/voice` accepts `flac, m4a, mp4, mpeg, mpga, ogg, wav,
webm` up to `VOICE_MAX_UPLOAD_BYTES` (default ~10 MB). The audio travels to the
worker as base64 inside the Celery task's own row (no shared file volume, no
Redis) - that cap exists to keep one upload from bloating `kombu_message`, not
because of any Cartesia limit. `app/services/speech_to_text.py` implements
`CartesiaSpeechToTextProvider` against Cartesia's documented batch `/stt`
endpoint (`X-API-Key` + `Cartesia-Version` headers, `ink-whisper` model) -
**implemented without a live Cartesia account to test against**, so
`CARTESIA_STT_MODEL`/`CARTESIA_API_VERSION`/`CARTESIA_BASE_URL` are all
settings rather than constants in case their contract has moved on since. Unset
`CARTESIA_API_KEY` fails a voice reflection with a clear `error` rather than
rejecting the upload - the same tolerance every other optional provider key
gets.

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
| `app/core/celery_app.py` | The Celery app: Postgres broker/backend, heavy/light queue routing |
| `app/models/` | SQLAlchemy 2.x. Scripture and enrichment are separate tables on purpose |
| `app/services/ai_provider.py` | `AIProvider` interface, Gemini and heuristic implementations |
| `app/services/embeddings.py` | `EmbeddingProvider` interface; default is free and deterministic |
| `app/services/speech_to_text.py` | `SpeechToTextProvider` interface, Cartesia implementation |
| `app/services/retrieval.py` | Serving constraints and explainable ranking. `rank()` is pure |
| `app/services/reflection_pipeline.py` | The actual transcribe/analyse/retrieve/rank/persist pipeline - runs inside a Celery task, not a request |
| `app/tasks/` | Celery tasks: `reflections.py` (heavy), `email.py` (light) |
| `app/api/v1/` | Routers |
| `ingest.py` | Corpus and enrichment into the database |
| `../docker/` | Every Docker build asset: the Dockerfile, the entrypoint, the Postgres init script |
| `../.env.example` | Every setting, documented - the only env template in the repository |

## Known limitations

- The default embedding is a hashed bag-of-words. It approximates lexical
  overlap, not meaning: it matches "weep" to "weep" but not to "mourn". Replace
  it with a sentence encoder before making any claim about retrieval quality.
- Only 28 verses are currently servable, because Phase 1 annotation is in
  progress. Retrieval is correct but the corpus behind it is thin. A crisis
  reflection currently returns nothing at all, which is default-deny working
  as designed rather than a fault, but it is not a usable product state.
- `JWT_SECRET_KEY` and `SESSION_SECRET_KEY` ship with insecure dev defaults
  (like `database_url` does) so the app runs out of the box. Both must be
  replaced with a random value before any non-local deployment; nothing
  currently enforces that at startup.
- OIDC account linking trusts the provider's `email_verified` claim to decide
  whether a Google sign-in may attach to an existing password account. That is
  standard practice, but it means a compromised Google account with a verified
  matching email can reach a MoodVerse account that was never linked to it.
- Registering and using the API are not gated on `email_verified`. The
  verification flow exists and works end to end (confirmed against a real
  SMTP send); nothing currently *requires* it.
- Retrying a voice/text reflection blindly (2 attempts, 15s apart) does not
  distinguish a transient failure (a dropped connection) from a permanent one
  (a missing API key, a malformed upload) - a permanent failure still costs
  two wasted retries before the reflection is marked failed. Confirmed via a
  live run against an intentionally-unset `CARTESIA_API_KEY`.
- `CartesiaSpeechToTextProvider` was implemented from Cartesia's documentation
  without a live account to test against - the request/response shape has not
  been exercised against the real API.
- `celery_taskmeta`/`kombu_message` rows are not pruned (no Celery beat
  scheduler is running); they will grow unbounded over time.
