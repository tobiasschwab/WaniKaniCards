#!/bin/sh
# Migrationen anwenden, bevor der App-Server startet – nur bei Postgres
# (SQLite-Fallback ohne DATABASE_URL nutzt weiterhin db.create_all() beim
# Import von webapp.py, siehe dort). "alembic upgrade head" ist idempotent,
# kann also bei jedem Container-Start gefahrlos erneut laufen.
set -e

if [ -n "$DATABASE_URL" ]; then
    echo "Wende Datenbank-Migrationen an (alembic upgrade head) ..."
    alembic upgrade head
fi

exec "$@"
