#!/usr/bin/env python3
"""cleanup_worker.py – periodisch alte Job-Verlaufseinträge (samt PDF-/APKG-
Datei in `data/output/`) löschen (siehe README "Aufräum-Job").

Läuft als EIGENER Prozess/Container, analog zum RQ-Render-Worker, NICHT als
Teil des Webservers: sonst würde jeder Gunicorn-Worker-Prozess seinen
eigenen Timer starten und dieselbe Bereinigung mehrfach parallel ausführen
(harmlos, da `cleanup_old_jobs()` idempotent ist, aber unnötig).

Bewusst ein simpler Sleep-Loop statt APScheduler/Cron: eine einzelne
"alle X Sekunden"-Schleife deckt den Anwendungsfall vollständig ab, ohne
eine weitere Abhängigkeit ins Projekt zu ziehen (siehe CLAUDE.md "schlank
halten").
"""
from __future__ import annotations

import logging
import os
import time

from .services import cleanup_old_jobs
from .webapp import app

logger = logging.getLogger(__name__)

RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", "30"))
INTERVAL_SECONDS = int(os.environ.get("JOB_CLEANUP_INTERVAL_SECONDS", str(24 * 60 * 60)))


def run_once() -> int:
    with app.app_context():
        return cleanup_old_jobs(RETENTION_DAYS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "Cleanup-Worker gestartet (JOB_RETENTION_DAYS=%d, JOB_CLEANUP_INTERVAL_SECONDS=%d).",
        RETENTION_DAYS, INTERVAL_SECONDS,
    )
    while True:
        try:
            removed = run_once()
            if removed:
                logger.info("%d alte Job(s) samt Ausgabedatei(en) bereinigt.", removed)
        except Exception:
            logger.exception("Fehler beim Aufräum-Durchlauf, versuche es beim nächsten Intervall erneut.")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
