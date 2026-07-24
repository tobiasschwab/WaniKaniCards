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

from flask import Blueprint, jsonify, request
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_required, login_user, logout_user

from . import schemas
from .extensions import db, limiter
from .models import User, UserSettings
from .services import delete_all_user_data

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/signup")
# Bewusst IMMER nach IP limitiert (key_func=get_remote_address), NICHT der
# App-Standard-key_func (Identität, falls eingeloggt): signup() loggt den
# neu angelegten Nutzer sofort ein (login_user() unten) - mit dem Standard-
# key_func würde ein Angreifer bei jedem Aufruf automatisch einen NEUEN
# Rate-Limit-Bucket bekommen (die jeweils frisch eingeloggte Identität des
# zuvor erzeugten Kontos), das Limit liefe dadurch komplett ins Leere
# (live nachgestellt: Redis-Keys zeigten LIMITS:.../1/, /2/, /3/... statt
# eines gemeinsamen Buckets pro IP).
@limiter.limit("5 per hour", key_func=get_remote_address)
def signup():
    """Neues Konto anlegen + sofort einloggen (Session-Cookie).

    Öffentliche Instanz = offenes Self-Signup (siehe Design-Entscheidung
    "Zielgruppe"); für eine invite-only-Variante würde man hier zusätzlich
    einen Einladungscode prüfen.
    ---
    tags:
      - auth
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [email, password]
          properties:
            email: {type: string, example: du@beispiel.de}
            password: {type: string, format: password, minLength: 8}
            native_lang: {type: string, example: de}
            active_target_lang: {type: string, example: ja}
    responses:
      201:
        description: Konto angelegt, Session-Cookie gesetzt.
      400:
        description: Ungültige E-Mail oder zu kurzes Passwort.
      409:
        description: E-Mail-Adresse bereits vergeben.
      429:
        description: Rate-Limit (5 pro Stunde und IP) überschritten.
    """
    body = request.get_json(silent=True) or {}
    try:
        # native_lang/active_target_lang optional bei der Registrierung
        # mitgegeben (siehe web/index.html Onboarding); ohne Angabe bleiben
        # die Modell-Defaults ("de"/"ja") - lassen sich danach jederzeit in
        # den Einstellungen ändern (siehe /api/settings/language).
        data = schemas.parse_body(schemas.SignupBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400

    if User.query.filter_by(email=data.email).first() is not None:
        return jsonify({"error": "Für diese E-Mail-Adresse existiert bereits ein Konto."}), 409

    user = User(email=data.email, native_lang=data.native_lang)
    user.set_password(data.password)
    db.session.add(user)
    db.session.flush()  # user.id wird für die FK unten gebraucht
    db.session.add(UserSettings(user_id=user.id, active_target_lang=data.active_target_lang))
    db.session.commit()

    login_user(user)
    return jsonify({"ok": True, "email": user.email}), 201


@bp.post("/login")
@limiter.limit("10 per minute;30 per hour")
def login():
    """Mit E-Mail/Passwort einloggen (Session-Cookie).
    ---
    tags:
      - auth
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [email, password]
          properties:
            email: {type: string}
            password: {type: string, format: password}
    responses:
      200:
        description: Eingeloggt, Session-Cookie gesetzt.
      401:
        description: E-Mail oder Passwort falsch.
      429:
        description: Rate-Limit überschritten.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.LoginBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400

    user = User.query.filter_by(email=data.email).first()
    # Bewusst dieselbe Fehlermeldung bei unbekannter E-Mail UND falschem
    # Passwort (keine Rückmeldung, ob eine E-Mail-Adresse überhaupt
    # registriert ist - übliche Praxis gegen Account-Enumeration).
    if user is None or not user.check_password(data.password):
        return jsonify({"error": "E-Mail oder Passwort falsch."}), 401

    login_user(user)
    return jsonify({"ok": True, "email": user.email})


@bp.post("/logout")
@login_required
def logout():
    """Ausloggen (Session-Cookie invalidieren).
    ---
    tags:
      - auth
    responses:
      200:
        description: Ausgeloggt.
      401:
        description: Nicht eingeloggt.
    """
    logout_user()
    return jsonify({"ok": True})


@bp.post("/change-password")
@login_required
@limiter.limit("10 per hour")
def change_password():
    """Passwort des eingeloggten Nutzers ändern – das aktuelle Passwort muss
    korrekt mitgegeben werden (Schutz, falls jemand eine offene Sitzung an
    einem fremden Gerät kapert). Rate-limitiert gegen Brute-Force des alten
    Passworts über eine bestehende Sitzung.
    ---
    tags:
      - auth
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [current_password, new_password]
          properties:
            current_password: {type: string, format: password}
            new_password: {type: string, format: password, minLength: 8}
    responses:
      200:
        description: Passwort geändert.
      400:
        description: Neues Passwort zu kurz oder identisch mit dem alten.
      401:
        description: Nicht eingeloggt.
      403:
        description: Aktuelles Passwort falsch.
      429:
        description: Rate-Limit überschritten.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.ChangePasswordBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400

    if not current_user.check_password(data.current_password):
        return jsonify({"error": "Aktuelles Passwort falsch."}), 403
    if data.new_password == data.current_password:
        return jsonify({"error": "Das neue Passwort muss sich vom aktuellen unterscheiden."}), 400

    current_user.set_password(data.new_password)
    db.session.commit()
    return jsonify({"ok": True})


@bp.delete("/account")
@login_required
def delete_account():
    """Konto und ALLE zugehörigen Daten unwiderruflich löschen (DSGVO-
    „Recht auf Löschung"). Das aktuelle Passwort muss zur Bestätigung
    mitgegeben werden, damit eine gekaperte oder versehentlich offene Sitzung
    nicht das ganze Konto vernichten kann.
    ---
    tags:
      - auth
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [password]
          properties:
            password: {type: string, format: password}
    responses:
      200:
        description: Konto und alle Daten gelöscht.
      401:
        description: Nicht eingeloggt.
      403:
        description: Passwort falsch.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.DeleteAccountBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400
    if not current_user.check_password(data.password):
        return jsonify({"error": "Passwort falsch."}), 403

    user_id = current_user.id
    # Erst ausloggen (Session-Cookie invalidieren), dann die Daten löschen -
    # danach existiert der `current_user` nicht mehr, ein späterer Zugriff
    # darauf würde fehlschlagen.
    logout_user()
    delete_all_user_data(user_id)
    db.session.delete(db.session.get(User, user_id))
    db.session.commit()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    """Aktuellen Login-Status abfragen – fürs Frontend, um beim Laden zu
    entscheiden, ob Login-Formular oder App gezeigt wird.
    ---
    tags:
      - auth
    responses:
      200:
        description: Login-Status (immer 200, auch wenn nicht eingeloggt).
        schema:
          type: object
          properties:
            authenticated: {type: boolean}
            email: {type: string}
            native_lang: {type: string}
            active_target_lang: {type: string}
    """
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    settings = current_user.settings
    return jsonify({
        "authenticated": True,
        "email": current_user.email,
        "native_lang": current_user.native_lang,
        "active_target_lang": settings.active_target_lang if settings else "ja",
    })
