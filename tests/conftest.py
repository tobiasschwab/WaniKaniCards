"""conftest.py – gemeinsame Test-Konfiguration.

Setzt DATABASE_URL auf eine temporäre SQLite-Datei, BEVOR irgendein Testmodul
`webapp` importiert (webapp.py liest die Variable beim Modul-Import, um
`app.config["SQLALCHEMY_DATABASE_URI"]` zu setzen) – Tests laufen so nie
gegen die echte Entwicklungs-DB unter data/shiori.db.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TEST_DB_DIR = tempfile.mkdtemp(prefix="shiori_test_db_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_DIR}/test_shiori.db")

import pytest  # noqa: E402

import webapp  # noqa: E402
from extensions import db  # noqa: E402


@pytest.fixture
def db_session():
    """Frische, leere Tabellen für einen Test – Modelltests/Auth-Tests, die
    tatsächlich Datenbank-Zeilen anlegen, sollen sich nicht gegenseitig
    beeinflussen (anders als die dateibasierten Endpunkte, die weiterhin über
    `monkeypatch.setattr(webapp, "...")` pro Test isoliert werden)."""
    with webapp.app.app_context():
        db.drop_all()
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()
