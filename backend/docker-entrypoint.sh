#!/bin/sh
# Entrypoint. Optionally migrates, then execs the given command as PID 1 so
# signals reach uvicorn and the container stops cleanly.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "running database migrations..."
  alembic upgrade head
fi

exec "$@"
