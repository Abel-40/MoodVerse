"""The Celery application: two Postgres-backed queues, no Redis.

Broker: Kombu's SQLAlchemy transport (`sqla+<database_url>`), which polls two
tables it creates itself on first connect (`kombu_message`, `kombu_queue`)
rather than requiring a separate message-broker service. Result backend:
Celery's own SQLAlchemy backend (`db+<database_url>`, tables
`celery_taskmeta`/`celery_tasksetmeta`). Both default to the app's own
database_url - see Settings.celery_broker_url / .celery_result_backend_url -
so a fresh clone needs no second service to run background jobs.

None of those four tables are part of Base.metadata; alembic/env.py excludes
them by name from autogenerate so they never show up as a phantom drop_table.

Two queues, not one, so a burst of Gemini/Cartesia calls (`heavy`) can never
delay a verification email (`light`) behind it, and vice versa - run as two
separate worker processes, each draining only its own queue:

    celery -A app.core.celery_app worker -Q heavy --concurrency=2
    celery -A app.core.celery_app worker -Q light --concurrency=4

(docker-compose.yml wires these up as the worker-heavy / worker-light services.)
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.eventloop import configure_event_loop

# Same Windows ProactorEventLoop fix app/main.py applies - a worker process
# started locally on Windows needs it too; a no-op everywhere else.
configure_event_loop()

_settings = get_settings()

celery_app = Celery(
    "moodverse",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend_url,
    include=["app.tasks.reflections", "app.tasks.email"],
)

celery_app.conf.update(
    task_default_queue=_settings.celery_queue_light,
    task_routes={
        "app.tasks.reflections.*": {"queue": _settings.celery_queue_heavy},
        "app.tasks.email.*": {"queue": _settings.celery_queue_light},
    },
    task_track_started=True,
    # Ack after the task finishes, not on receipt, so a worker that crashes
    # mid-task (a Gemini/Cartesia call that hangs, a killed container) gets
    # its task redelivered rather than silently losing it.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
