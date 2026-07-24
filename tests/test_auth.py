"""Tests für auth.py – Signup/Login/Logout (Flask-Login-Sessions)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shiori import models, webapp
from shiori.models import User, UserSettings


def test_signup_creates_user_and_settings_and_logs_in(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/signup", json={"email": "new@example.com", "password": "supersecret123"})
    assert r.status_code == 201
    assert r.get_json() == {"ok": True, "email": "new@example.com"}

    user = User.query.filter_by(email="new@example.com").first()
    assert user is not None
    assert UserSettings.query.filter_by(user_id=user.id).first() is not None

    me = client.get("/api/auth/me").get_json()
    assert me == {
        "authenticated": True, "email": "new@example.com",
        "native_lang": "de", "active_target_lang": "ja",
    }


def test_signup_accepts_native_lang_and_active_target_lang(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/signup", json={
        "email": "lang@example.com", "password": "supersecret123",
        "native_lang": "EN", "active_target_lang": "ES",
    })
    assert r.status_code == 201

    me = client.get("/api/auth/me").get_json()
    assert me["native_lang"] == "en"
    assert me["active_target_lang"] == "es"


def test_api_languages_public_works_without_login(db_session):
    client = webapp.app.test_client()
    r = client.get("/api/languages/public")
    assert r.status_code == 200
    codes = {lang["code"] for lang in r.get_json()["supported_target_langs"]}
    assert {"ja", "en", "es"}.issubset(codes)


def test_signup_rejects_invalid_email(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/signup", json={"email": "not-an-email", "password": "supersecret123"})
    assert r.status_code == 400


def test_signup_rejects_short_password(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/signup", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 400


def test_signup_rejects_duplicate_email(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "dup@example.com", "password": "supersecret123"})
    r = client.post("/api/auth/signup", json={"email": "dup@example.com", "password": "anotherpass123"})
    assert r.status_code == 409


def test_login_with_correct_credentials(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "login@example.com", "password": "supersecret123"})
    client.post("/api/auth/logout")

    r = client.post("/api/auth/login", json={"email": "login@example.com", "password": "supersecret123"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_login_rejects_wrong_password(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "login2@example.com", "password": "supersecret123"})
    client.post("/api/auth/logout")

    r = client.post("/api/auth/login", json={"email": "login2@example.com", "password": "wrongpass"})
    assert r.status_code == 401


def test_login_rejects_unknown_email(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "whatever123"})
    assert r.status_code == 401


def test_logout_requires_login(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/logout")
    assert r.status_code == 401


def test_me_reports_unauthenticated_without_session(db_session):
    client = webapp.app.test_client()
    r = client.get("/api/auth/me")
    assert r.get_json() == {"authenticated": False}


def test_logout_ends_session(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "out@example.com", "password": "supersecret123"})
    assert client.get("/api/auth/me").get_json()["authenticated"] is True

    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert client.get("/api/auth/me").get_json() == {"authenticated": False}


def test_login_is_rate_limited(db_session, monkeypatch):
    """Regressionstest für einen im Sicherheitsreview gefundenen Bug: Login/
    Signup hatten kein eigenes Rate-Limit (nur das großzügige globale
    120/min), was Brute-Force/Credential-Stuffing kaum bremst."""
    monkeypatch.setattr(webapp.limiter, "enabled", True)
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "ratelimit@example.com", "password": "supersecret123"})
    client.post("/api/auth/logout")

    responses = [
        client.post("/api/auth/login", json={"email": "ratelimit@example.com", "password": "wrong"})
        for _ in range(11)
    ]
    assert any(r.status_code == 429 for r in responses)


def test_signup_is_rate_limited(db_session, monkeypatch):
    monkeypatch.setattr(webapp.limiter, "enabled", True)
    client = webapp.app.test_client()
    responses = [
        client.post("/api/auth/signup", json={"email": f"spam{i}@example.com", "password": "supersecret123"})
        for i in range(6)
    ]
    assert any(r.status_code == 429 for r in responses)


# --------------------------------------------------------------------------- #
# Passwort ändern
# --------------------------------------------------------------------------- #

def test_change_password_success(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "pw@example.com", "password": "supersecret123"})

    r = client.post("/api/auth/change-password", json={
        "current_password": "supersecret123", "new_password": "brandnewpass456",
    })
    assert r.status_code == 200

    # Altes Passwort funktioniert nicht mehr, neues schon.
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "pw@example.com", "password": "supersecret123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "pw@example.com", "password": "brandnewpass456"}).status_code == 200


def test_change_password_rejects_wrong_current(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "pw2@example.com", "password": "supersecret123"})
    r = client.post("/api/auth/change-password", json={
        "current_password": "wrongwrong", "new_password": "brandnewpass456",
    })
    assert r.status_code == 403


def test_change_password_rejects_short_new(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "pw3@example.com", "password": "supersecret123"})
    r = client.post("/api/auth/change-password", json={
        "current_password": "supersecret123", "new_password": "short",
    })
    assert r.status_code == 400


def test_change_password_requires_login(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/change-password", json={
        "current_password": "x", "new_password": "brandnewpass456",
    })
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Konto löschen
# --------------------------------------------------------------------------- #

def test_delete_account_success_removes_user_and_data(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "del@example.com", "password": "supersecret123"})
    user = User.query.filter_by(email="del@example.com").first()
    uid = user.id
    # Etwas Nutzer-Inhalt anlegen, damit die Daten-Aufräumung geprüft wird.
    client.post("/api/customcards", json={"front_html": "x", "back_html": "y", "tags": []})
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})

    r = client.delete("/api/auth/account", json={"password": "supersecret123"})
    assert r.status_code == 200

    assert User.query.filter_by(email="del@example.com").first() is None
    assert models.CustomCard.query.filter_by(user_id=uid).count() == 0
    assert models.ReviewState.query.filter_by(user_id=uid).count() == 0
    assert models.UserSettings.query.filter_by(user_id=uid).count() == 0
    # Sitzung ist beendet.
    assert client.get("/api/auth/me").get_json() == {"authenticated": False}


def test_delete_account_rejects_wrong_password(db_session):
    client = webapp.app.test_client()
    client.post("/api/auth/signup", json={"email": "del2@example.com", "password": "supersecret123"})
    r = client.delete("/api/auth/account", json={"password": "nope"})
    assert r.status_code == 403
    assert User.query.filter_by(email="del2@example.com").first() is not None


def test_delete_account_requires_login(db_session):
    client = webapp.app.test_client()
    r = client.delete("/api/auth/account", json={"password": "x"})
    assert r.status_code == 401
