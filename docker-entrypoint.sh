#!/bin/sh
# Migrationen anwenden, bevor der App-Server startet – nur bei Postgres
# (SQLite-Fallback ohne DATABASE_URL nutzt weiterhin db.create_all() beim
# Import von webapp.py, siehe dort). "alembic upgrade head" ist idempotent,
# kann also bei jedem Container-Start gefahrlos erneut laufen.
#
# WICHTIG: Nur GENAU EIN Container darf migrieren. Web- und Worker-Container
# teilen sich dieses Entrypoint-Skript; liefen beide gleichzeitig
# "alembic upgrade head", könnten sie sich beim DDL (Tabellen anlegen/ändern)
# in die Quere kommen. Deshalb migriert standardmäßig nur, wer RUN_MIGRATIONS
# gesetzt hat – der Web-Service tut das (siehe docker-compose.yml), der
# Worker-Service wartet nur, bis das Schema steht.
set -e

if [ -n "$DATABASE_URL" ] && [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "Wende Datenbank-Migrationen an (alembic upgrade head) ..."
    alembic upgrade head
fi

exec "$@"
