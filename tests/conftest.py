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
# Fester Test-Key statt einem echten Secret (siehe crypto.py) - Endpunkte,
# die WaniKani-Token/DeepL-/Gemini-Keys verschlüsseln, brauchen sonst in
# JEDEM Test ein eigenes monkeypatch.setenv().
os.environ.setdefault("WKCARDS_SECRET_KEY", "dN4DNC08zC7HtrKO0MDE7QGp5LLxLb4yFD0fXENHAug=")

import pytest  # noqa: E402
from flask_login import login_user  # noqa: E402

import models  # noqa: E402
import services  # noqa: E402
import webapp  # noqa: E402
from extensions import db  # noqa: E402


@pytest.fixture
def db_session():
    """Frische, leere Tabellen für einen Test – Modelltests/Auth-Tests, die
    tatsächlich Datenbank-Zeilen anlegen, sollen sich nicht gegenseitig
    beeinflussen. Der aktive `app_context()` bleibt für die gesamte
    Testlaufzeit gepusht, sodass auch reine DB-Model-Queries im Testkörper
    (ohne HTTP-Request) funktionieren."""
    with webapp.app.app_context():
        db.drop_all()
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(db_session):
    """Flask-Testclient mit einem frisch registrierten & eingeloggten Nutzer
    (Signup setzt direkt die Session-Cookies) – für Endpunkt-Tests, die jetzt
    `@login_required` sind. `client.test_user_id` gibt die ID des angelegten
    Nutzers für Test-Setup/-Assertions direkt gegen die DB-Modelle."""
    c = webapp.app.test_client()
    r = c.post("/api/auth/signup", json={"email": "test@example.com", "password": "supersecret123"})
    assert r.status_code == 201, r.get_json()
    user = models.User.query.filter_by(email="test@example.com").first()
    c.test_user_id = user.id
    return c


def _synchronous_enqueue(func, *args, **kwargs):
    """Test-Double für `render_queue.enqueue()`: führt das Ziel SOFORT synchron
    aus statt es über Redis an einen echten RQ-Worker-Prozess zu übergeben –
    Tests laufen ohne eine laufende Redis-/Worker-Infrastruktur und ohne
    Wettlauf mit dem Tabellen-Teardown von `db_session`. `job_timeout` u. Ä.
    Keyword-Argumente von `Queue.enqueue()` werden ignoriert (beim direkten
    Aufruf sinnlos)."""
    func(*args)
    return None


@pytest.fixture(autouse=True)
def _synchronous_render_queue(monkeypatch):
    monkeypatch.setattr(services.render_queue, "enqueue", _synchronous_enqueue)


@pytest.fixture(autouse=True)
def _disable_rate_limiting(monkeypatch):
    """Flask-Limiter zählt gegen Redis (`storage_uri=REDIS_URL`) – in Tests
    soll das Limit nie zuschlagen, unabhängig davon, ob/wie schnell Requests
    aufeinanderfolgen oder ob überhaupt ein Redis erreichbar ist."""
    monkeypatch.setattr(webapp.limiter, "enabled", False)


@pytest.fixture
def logged_in_user(db_session):
    """Nutzer anlegen und für die Testlaufzeit als `current_user` verfügbar
    machen (über einen gepushten `test_request_context()`, ohne den Umweg
    über einen echten HTTP-Request) – für Unit-Tests von Funktionen, die
    `current_user` direkt lesen (z. B. `webapp.load_known()`,
    `webapp._already_exported_ids()`)."""
    user = models.User(email="unituser@example.com")
    user.set_password("supersecret123")
    db.session.add(user)
    db.session.commit()
    ctx = webapp.app.test_request_context()
    ctx.push()
    login_user(user)
    yield user
    ctx.pop()
