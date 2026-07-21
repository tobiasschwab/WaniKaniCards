#!/usr/bin/env python3
"""auth.py – Signup/Login/Logout für den Multi-User-Betrieb.

E-Mail/Passwort statt WaniKani-Token als Login-Credential (siehe README,
Design-Entscheidung "Auth-Methode"): der WaniKani-Token bleibt ein
Nutzungs-Detail, das erst NACH dem Login in den Einstellungen hinterlegt
wird – identisch zum bisherigen Verhalten, nur jetzt pro Account statt
global.

Kein serverseitig gerendertes Login-Formular: das Frontend ist eine
SPA-artige Single-Page-App, alle Routen hier liefern JSON.
"""
from __future__ import annotations

import re

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import User, UserSettings

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LEN = 8


@bp.post("/signup")
def signup():
    """Neues Konto anlegen + sofort einloggen (Session-Cookie).

    Öffentliche Instanz = offenes Self-Signup (siehe Design-Entscheidung
    "Zielgruppe"); für eine invite-only-Variante würde man hier zusätzlich
    einen Einladungscode prüfen."""
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    # Optional bei der Registrierung mitgegeben (siehe web/index.html
    # Onboarding); ohne Angabe bleiben die Modell-Defaults ("de"/"ja") -
    # Muttersprache/Zielsprache lassen sich danach jederzeit in den
    # Einstellungen ändern (siehe /api/settings/language).
    native_lang = str(body.get("native_lang") or "de").strip().lower()[:10]
    active_target_lang = str(body.get("active_target_lang") or "ja").strip().lower()[:10]

    if not _EMAIL_RE.match(email):
        return jsonify({"error": "Ungültige E-Mail-Adresse."}), 400
    if len(password) < _MIN_PASSWORD_LEN:
        return jsonify({"error": f"Passwort muss mindestens {_MIN_PASSWORD_LEN} Zeichen haben."}), 400
    if User.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "Für diese E-Mail-Adresse existiert bereits ein Konto."}), 409

    user = User(email=email, native_lang=native_lang)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()  # user.id wird für die FK unten gebraucht
    db.session.add(UserSettings(user_id=user.id, active_target_lang=active_target_lang))
    db.session.commit()

    login_user(user)
    return jsonify({"ok": True, "email": user.email}), 201


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))

    user = User.query.filter_by(email=email).first()
    # Bewusst dieselbe Fehlermeldung bei unbekannter E-Mail UND falschem
    # Passwort (keine Rückmeldung, ob eine E-Mail-Adresse überhaupt
    # registriert ist - übliche Praxis gegen Account-Enumeration).
    if user is None or not user.check_password(password):
        return jsonify({"error": "E-Mail oder Passwort falsch."}), 401

    login_user(user)
    return jsonify({"ok": True, "email": user.email})


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    """Aktuellen Login-Status abfragen – fürs Frontend, um beim Laden zu
    entscheiden, ob Login-Formular oder App gezeigt wird."""
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    settings = current_user.settings
    return jsonify({
        "authenticated": True,
        "email": current_user.email,
        "native_lang": current_user.native_lang,
        "active_target_lang": settings.active_target_lang if settings else "ja",
    })
