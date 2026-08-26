#!/bin/sh
# Migrate, then start. Alembic runs here rather than in the application:
# `alembic upgrade head` is idempotent and finishes before the first request,
# and a failed migration then stops the container instead of leaving it up
# against a schema it does not match.
set -e

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> starting: $*"
exec "$@"
