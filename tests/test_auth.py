"""Tests für auth.py – Signup/Login/Logout (Flask-Login-Sessions)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webapp
from models import User, UserSettings


def test_signup_creates_user_and_settings_and_logs_in(db_session):
    client = webapp.app.test_client()
    r = client.post("/api/auth/signup", json={"email": "new@example.com", "password": "supersecret123"})
    assert r.status_code == 201
    assert r.get_json() == {"ok": True, "email": "new@example.com"}

    user = User.query.filter_by(email="new@example.com").first()
    assert user is not None
    assert UserSettings.query.filter_by(user_id=user.id).first() is not None

    me = client.get("/api/auth/me").get_json()
    assert me == {"authenticated": True, "email": "new@example.com"}


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
