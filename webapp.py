#!/usr/bin/env python3
"""Web-Frontend für den WaniKani-Karten-Generator.

Ablauf: Quelle *auflisten* (Level, Suche oder Komposition) → Elemente in einer
Tabelle *auswählen* → ausgewählte Karten als **ein PDF** rendern.

**Multi-User-Umbau (Phase 2):** Accounts, Einstellungen (inkl. API-Token),
bekannte Wörter, eigene/Dictionary-Karten und der Job-Verlauf liegen in der
Datenbank (SQLite lokal, Postgres in Produktion – siehe `models.py`) und sind
pro Nutzer getrennt (`current_user.id`-Scoping + Ownership-Checks, siehe
README-Abschnitt "Multi-User-Architektur"). Generierte PDFs/APKGs liegen
weiterhin als Dateien unter ``WKCARDS_DATA`` (Default: ``./data``), aber
jeder Zugriff prüft vorher das zugehörige `Job`-Datenbank-Objekt auf
Eigentümerschaft.

Der WaniKani-Token des jeweils eingeloggten Nutzers wird dabei explizit als
`token`-Parameter an `kanji_cards.py` durchgereicht (statt – wie noch in
Phase 2 zunächst – über die prozessglobale Umgebungsvariable
`WANIKANI_API_TOKEN`), damit unter echter Nebenläufigkeit mehrerer Nutzer im
selben Worker kein Request versehentlich den Token eines anderen Nutzers
verwendet. `WANIKANI_API_TOKEN` bleibt nur der Fallback fürs CLI
(`python kanji_cards.py <level>`), wo es ohnehin nur einen Nutzer pro
Prozessaufruf gibt.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import redis
from flask import Flask, abort, g, jsonify, redirect, request, send_file, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_required
from rq import Queue
from sqlalchemy.exc import IntegrityError

import anki_export as ae
import crypto
import kanji_cards as kc
import models
import pdf_import
import srs
import storage
from auth import bp as auth_bp
from extensions import db, login_manager
from languages.registry import SUPPORTED_TARGET_LANGS, get_pack

# INFO-Logs (u. a. Gemini-Requests: Start, Dauer, Fehlerursache) landen sonst
# im Nirwana, weil Python ohne explizite Konfiguration nur WARNING+ ausgibt –
# gunicorn/Flask fangen stdout ab, das reicht für `docker logs`.
#
# Jeder Log-Eintrag bekommt zusätzlich den eingeloggten Nutzer angehängt
# (Multi-User-Betrieb: "wessen Request hat das ausgelöst" ist sonst aus den
# Logs allein nicht ersichtlich) - "-" außerhalb eines Requests (z. B. im
# RQ-Worker-Prozess, der Jobs verarbeitet).
class _UserIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import has_request_context
            record.user_id = current_user.id if (has_request_context() and current_user.is_authenticated) else "-"
        except Exception:  # noqa: BLE001 - Logging darf nie selbst crashen
            record.user_id = "-"
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s [user=%(user_id)s]: %(message)s",
)
# Als Filter auf dem Root-Handler (nicht auf dem Root-Logger!) registrieren:
# Logger-Filter laufen nur für Records, die auf GENAU diesem Logger erzeugt
# wurden, nicht für Records, die von Kind-Loggern (z. B. "werkzeug",
# "gunicorn.error") zum Root propagiert werden – die würden sonst ohne
# `user_id`-Attribut beim Root-Handler landen und die Format-String-
# Auswertung mit ValueError crashen.
for _h in logging.getLogger().handlers:
    _h.addFilter(_UserIdLogFilter())

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WKCARDS_DATA", HERE / "data")).resolve()
# Einstellungen/bekannte Wörter/eigene-/Dictionary-Karten/Jobs liegen seit
# Phase 2 des Multi-User-Umbaus in der Datenbank (siehe models.py) statt als
# Dateien - nur die generierten PDFs/APKGs selbst bleiben dateibasiert
# (Binärdaten, für die eine Objekt-Storage-Anbindung sinnvoller ist als eine
# DB-Spalte, siehe README-Roadmap "Jobs/Dateien SaaS-tauglich machen").
OUTPUT_DIR = DATA_DIR / "output"
WEB_DIR = HERE / "web"

for _d in (DATA_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS: dict[str, Any] = {
    "deepl_key": "",
    "gemini_key": "",
    "gemini_model": kc.gemini_client.DEFAULT_MODEL,
    # Zielsprache für DeepL-Übersetzungen (Beispielsätze UND der neue
    # Felder-Übersetzen-Dialog) – DeepL-Sprachcode, z. B. "DE"/"EN"/"FR".
    # NICHT zu verwechseln mit der gelernten Sprache (`active_target_lang`,
    # siehe unten) - dieselbe Terminologie wird hier historisch für zwei
    # unterschiedliche Dinge verwendet.
    "target_lang": "DE",
    "defaults": {
        "level": 1,
        "types": ["kanji"],
        "format": "pdf",
        "layout": "a6",
        "paper": "a4",
        "duplex": "long-edge",
        "cut_marks": True,
        "hole": False,
    },
}

logger = logging.getLogger(__name__)

# DeepL-Zielsprachen zur Auswahl in den Einstellungen (Teilmenge der von
# DeepL unterstützten Sprachen – https://developers.deepl.com/docs/resources/supported-languages,
# nur die "einfachen" Codes ohne Regionalvarianten wie EN-US/PT-BR, die für
# diesen Anwendungsfall (kurze Vokabel-/Satzübersetzungen) nicht relevant sind).
_TARGET_LANGS = (
    "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FI", "FR", "HU", "ID",
    "IT", "JA", "KO", "LT", "LV", "NB", "NL", "PL", "PT", "RO", "RU", "SK",
    "SL", "SV", "TR", "UK", "ZH",
)

app = Flask(__name__, static_folder=None)

# 20 MB reicht für die allermeisten gescannten Lesehefte/Fotos bequem, ohne
# dass ein versehentlich falscher Upload (Video, riesiger Bildband) den
# Server unnötig belastet. Als Flask-Config gesetzt, damit ein zu großer
# Body schon von Werkzeug abgelehnt wird, statt erst komplett in den
# Speicher gelesen zu werden (siehe api_text_extract()).
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = _MAX_UPLOAD_BYTES

# ---------- Multi-User-Fundament: Datenbank + Login (Phase 1) --------------- #
#
# Ohne DATABASE_URL fällt die App auf eine lokale SQLite-Datei unter
# WKCARDS_DATA zurück (Zero-Config für Demo/Entwicklung) - für den
# produktiven Multi-User-Betrieb ist Postgres vorgesehen (siehe README,
# Abschnitt "Multi-User-Architektur"). Bewusst nicht dieselbe Umgebungs-
# variable wie WKCARDS_SECRET_KEY (Fernet-Verschlüsselung der API-Keys,
# siehe crypto.py): Flasks Session-Signing-Key und der Secrets-Master-Key
# haben unterschiedliche Rotationsanforderungen und Formate und sollten
# unabhängig voneinander wechselbar sein.
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", f"sqlite:///{DATA_DIR / 'shiori.db'}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("WKCARDS_SESSION_SECRET", "dev-insecure-change-me")

db.init_app(app)
login_manager.init_app(app)


@login_manager.user_loader
def _load_user(user_id: str) -> "models.User | None":
    return db.session.get(models.User, int(user_id))


@login_manager.unauthorized_handler
def _unauthorized() -> Any:
    """JSON statt Redirect: das Frontend ist eine Single-Page-App, kein
    serverseitig gerendertes Login-Formular, auf das umgeleitet werden könnte."""
    return jsonify({"error": "Nicht angemeldet."}), 401


app.register_blueprint(auth_bp)


@app.before_request
def _reset_login_cache() -> None:
    """Flask-Logins Pro-Request-Cache (`g._login_user`) vor jedem Request
    zurücksetzen, damit `current_user` garantiert aus DIESEM Request-Cookie
    neu aufgelöst wird. Nötig, weil Flask einen bereits aktiven App-Context
    derselben App wiederverwendet (inkl. `g`) statt bei jedem Request einen
    frischen zu erzeugen (siehe `flask.ctx.RequestContext.push()`) – das
    betrifft besonders Tests, die (z. B. für Multi-Tenant-Checks) mehrere
    Test-Clients innerhalb desselben offen gehaltenen App-Contexts benutzen
    (siehe tests/conftest.py `db_session`). In Produktion ein No-Op, da dort
    ohnehin jeder Request einen eigenen, frischen Context bekommt."""
    g.pop("_login_user", None)


# ---------- Multi-User Phase 3: Job-Queue + Rate-Limiting (Redis) ----------- #
#
# REDIS_URL fällt ohne Angabe auf ein lokales Redis zurück (Zero-Config für
# Entwicklung, analog zum SQLite-Fallback bei DATABASE_URL) - für den
# produktiven Multi-User-Betrieb läuft ein eigener Redis-Dienst (siehe
# docker-compose.yml). Dieselbe Verbindung dient sowohl der Job-Queue (RQ)
# als auch dem Rate-Limiting-Zähler (Flask-Limiter) - zwei unterschiedliche
# Nutzungen derselben Infrastruktur, kein zweiter Dienst nötig.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_conn = redis.from_url(REDIS_URL)
render_queue = Queue("renders", connection=redis_conn)

limiter = Limiter(
    key_func=lambda: str(current_user.get_id()) if current_user.is_authenticated else get_remote_address(),
    app=app,
    storage_uri=REDIS_URL,
    # Großzügiger Default für die meisten (billigen) Endpunkte - teure
    # Einzelendpunkte (Rendern, Gemini-Aufrufe) bekommen unten ihr eigenes,
    # strengeres Limit direkt am jeweiligen Endpunkt.
    default_limits=["120 per minute"],
)

# Wie viele gleichzeitig laufende/wartende Render-Jobs ein einzelner Nutzer
# haben darf, bevor /api/render neue Anfragen ablehnt - verhindert, dass ein
# Nutzer die komplette Worker-Kapazität für sich beansprucht (siehe
# api_render()). WaniKanis eigenes Rate-Limit ist schon pro Token isoliert,
# die EIGENE Serverkapazität (Worker-Prozesse) aber nicht.
_MAX_CONCURRENT_JOBS_PER_USER = 3


@app.errorhandler(crypto.SecretCryptoError)
def _handle_secret_crypto_error(exc: crypto.SecretCryptoError) -> Any:
    """Klare JSON-Fehlermeldung statt einer nackten 500 – z. B. wenn
    WKCARDS_SECRET_KEY im Multi-User-Betrieb fehlt (siehe crypto.py)."""
    logger.error("Secrets-Verschlüsselung fehlgeschlagen: %s", exc)
    return jsonify({"error": "Serverkonfigurationsfehler (Secrets-Verschlüsselung). Bitte den Betreiber informieren."}), 500

# Tabellen anlegen, falls sie noch nicht existieren – nur ein Komfort-
# Fallback für SQLite/lokale Entwicklung ohne eingerichtetes Alembic. In
# Produktion (Postgres) übernimmt `alembic upgrade head` das Schema-
# Management (siehe migrations/), db.create_all() dort NICHT verwenden (die
# beiden Mechanismen würden sich sonst gegenseitig ins Gehege kommen).
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
    with app.app_context():
        db.create_all()


# ---------- Einstellungen (pro Nutzer, Postgres/SQLite statt settings.json) - #

def _get_or_create_user_settings(user_id: int) -> models.UserSettings:
    settings = db.session.get(models.UserSettings, user_id)
    if settings is None:
        settings = models.UserSettings(user_id=user_id)
        db.session.add(settings)
        try:
            db.session.commit()
        except IntegrityError:
            # Das Frontend feuert beim Login mehrere Requests parallel ab
            # (loadSettings()/loadLanguages() u. Ä., keiner davon wartet auf
            # den anderen) - zwei können hier gleichzeitig "existiert noch
            # nicht" sehen und beide versuchen anzulegen. Der Verlierer
            # rollt zurück und liest einfach die vom Gewinner erzeugte
            # Zeile - kein Fehler, kein Datenverlust.
            db.session.rollback()
            settings = db.session.get(models.UserSettings, user_id)
    return settings


def _get_or_create_language_secrets(user_id: int, target_lang: str) -> models.UserLanguageSecrets:
    """WaniKani-Token/-Username sind pro Nutzer UND Zielsprache gespeichert
    (siehe models.UserLanguageSecrets-Docstring: nur für "ja" heute relevant,
    aber schon so modelliert, dass eine künftige zweite Sprache mit eigenem
    Content-Provider dieselbe Tabelle nutzen könnte)."""
    row = db.session.get(models.UserLanguageSecrets, (user_id, target_lang))
    if row is None:
        row = models.UserLanguageSecrets(user_id=user_id, target_lang=target_lang)
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            # Gleiches Race wie bei _get_or_create_user_settings() oben.
            db.session.rollback()
            row = db.session.get(models.UserLanguageSecrets, (user_id, target_lang))
    return row


def _settings_to_dict(
    s: models.UserSettings, secrets: models.UserLanguageSecrets, native_lang: str,
) -> dict[str, Any]:
    """`UserSettings`+`UserLanguageSecrets`-Zeilen in ein flaches Dict bringen
    (historisch dieselbe Form wie die alte settings.json). Secrets werden
    hier entschlüsselt (siehe crypto.py) – NIE im Klartext in der DB."""
    return {
        "token": crypto.decrypt_secret(secrets.wanikani_token_enc) or "",
        "username": secrets.wanikani_username or "",
        "deepl_key": crypto.decrypt_secret(s.deepl_key_enc) or "",
        "gemini_key": crypto.decrypt_secret(s.gemini_key_enc) or "",
        "gemini_model": s.gemini_model or kc.gemini_client.DEFAULT_MODEL,
        "target_lang": s.target_lang or "DE",
        "native_lang": native_lang,
        "active_target_lang": s.active_target_lang or "ja",
        "defaults": {**DEFAULT_SETTINGS["defaults"], **(s.defaults or {})},
    }


def load_settings_for_user(user_id: int, target_lang: str | None = None) -> dict[str, Any]:
    """Einstellungen eines bestimmten Nutzers – für Code-Pfade ohne aktiven
    Request-Kontext (z. B. der Render-Worker, der `current_user` nicht kennt,
    aber den `user_id` UND `target_lang` des Jobs). `token`/`username` werden
    für die angegebene Zielsprache geladen (Default: die AKTUELL aktive
    Zielsprache des Nutzers) - ein Job trägt seine eigene `target_lang`,
    unabhängig davon, ob der Nutzer inzwischen die Sprache gewechselt hat."""
    user = db.session.get(models.User, user_id)
    s = _get_or_create_user_settings(user_id)
    lang = target_lang or s.active_target_lang or "ja"
    secrets = _get_or_create_language_secrets(user_id, lang)
    return _settings_to_dict(s, secrets, user.native_lang if user else "de")


def load_settings() -> dict[str, Any]:
    """Einstellungen des aktuell eingeloggten Nutzers für seine AKTUELL
    aktive Zielsprache (nur innerhalb eines Requests aufrufbar, braucht
    `current_user`)."""
    return load_settings_for_user(current_user.id)


def save_settings(data: dict[str, Any]) -> None:
    """Speichert immer für die aktuell aktive Zielsprache (`token`/
    `username`) bzw. nutzerglobal (DeepL-/Gemini-Key, Defaults)."""
    s = _get_or_create_user_settings(current_user.id)
    if "token" in data or "username" in data:
        secrets = _get_or_create_language_secrets(current_user.id, s.active_target_lang or "ja")
        if "token" in data:
            secrets.wanikani_token_enc = crypto.encrypt_secret(data["token"])
        if "username" in data:
            secrets.wanikani_username = data["username"]
    if "deepl_key" in data:
        s.deepl_key_enc = crypto.encrypt_secret(data["deepl_key"])
    if "gemini_key" in data:
        s.gemini_key_enc = crypto.encrypt_secret(data["gemini_key"])
    if "gemini_model" in data:
        s.gemini_model = data["gemini_model"]
    if "target_lang" in data:
        s.target_lang = data["target_lang"]
    if "defaults" in data:
        s.defaults = data["defaults"]
    db.session.commit()


def _current_target_lang() -> str:
    """Aktuell aktive Lernsprache des eingeloggten Nutzers - scoped
    KnownWord/CustomCard/KanaCard/Job (siehe README "Multi-Language-
    Architektur")."""
    return _get_or_create_user_settings(current_user.id).active_target_lang or "ja"


def _current_pack():
    """`LanguagePack` der aktuell aktiven Zielsprache - Capability-Flags wie
    `has_content_provider`/`has_offline_tokenizer` entscheiden, welche Modi
    für diese Sprache überhaupt sinnvoll sind (siehe languages/base.py)."""
    return get_pack(_current_target_lang())


def set_active_language(*, native_lang: str | None = None, active_target_lang: str | None = None) -> dict[str, Any]:
    """Muttersprache und/oder aktive Zielsprache des eingeloggten Nutzers
    ändern (Sprachwechsler im Frontend) - beide sind unabhängig wechselbar."""
    if native_lang is not None:
        current_user.native_lang = native_lang
        db.session.add(current_user)
    if active_target_lang is not None:
        s = _get_or_create_user_settings(current_user.id)
        s.active_target_lang = active_target_lang
    db.session.commit()
    return {
        "native_lang": current_user.native_lang,
        "active_target_lang": _current_target_lang(),
    }


def _coerce_known_id(raw: str) -> int | str:
    """WaniKani-Subject-IDs sind rein numerisch -> int; Dictionary-Wörter
    (`kana_…`/`manual_…`) bleiben str."""
    return int(raw) if raw.isdigit() else raw


def load_known() -> set[int | str]:
    """IDs, die der eingeloggte Nutzer FÜR DIE AKTUELL AKTIVE Zielsprache
    manuell als „bekannt" markiert hat – unabhängig vom Export-/Karten-
    Verlauf, z. B. für Wörter, die man von woanders schon kann.
    WaniKani-Subject-IDs kommen als int zurück, Dictionary-/manuelle Wörter
    (`kana_…`/`manual_…`) als str."""
    rows = models.KnownWord.query.filter_by(
        user_id=current_user.id, target_lang=_current_target_lang(),
    ).all()
    return {_coerce_known_id(r.word_id) for r in rows}


def load_known_meta() -> dict[str, dict[str, Any]]:
    """Anzeige-Metadaten (characters/meaning/kind/level/source) zu den
    eigenen manuell bekannt markierten Wörtern der aktuell aktiven
    Zielsprache – nötig für die Wortliste, u. a. weil rein manuelle
    Einträge (`manual_…`) gar keine Karte/keinen WaniKani-Subject haben, aus
    dem sich die Anzeige sonst herleiten ließe."""
    rows = models.KnownWord.query.filter_by(
        user_id=current_user.id, target_lang=_current_target_lang(),
    ).all()
    return {
        r.word_id: {
            "characters": r.characters, "meaning": r.meaning,
            "kind": r.kind, "level": r.level, "source": r.source,
        }
        for r in rows
    }


def _upsert_known_word(word_id: str, fields: dict[str, Any]) -> None:
    """Einzelnes bekanntes Wort anlegen/aktualisieren (Zeile pro Nutzer+
    Zielsprache+Wort, siehe `KnownWord.uq_known_word_per_user`) – ersetzt das
    bisherige Lade-alles/Mutiere/Speichere-alles-Muster der Datei-Version."""
    lang = _current_target_lang()
    row = models.KnownWord.query.filter_by(
        user_id=current_user.id, target_lang=lang, word_id=word_id,
    ).first()
    if row is None:
        row = models.KnownWord(user_id=current_user.id, target_lang=lang, word_id=word_id)
        db.session.add(row)
    for k, v in fields.items():
        setattr(row, k, v)
    db.session.commit()


def _remove_known_word(word_id: str) -> None:
    models.KnownWord.query.filter_by(
        user_id=current_user.id, target_lang=_current_target_lang(), word_id=word_id,
    ).delete()
    db.session.commit()


def _mask(token: str) -> str:
    return (("•" * max(0, len(token) - 4)) + token[-4:]) if token else ""


def _resolve_gemini_model(settings: dict[str, Any]) -> str:
    """Gespeicherten Modellnamen übernehmen, wenn er wie ein gültiger
    Gemini-Modellname aussieht (`gemini-*`) – sonst der aktuelle Default
    (siehe `api_post_settings()`, dieselbe Validierung)."""
    stored_model = settings.get("gemini_model")
    if isinstance(stored_model, str) and stored_model.strip().startswith("gemini-"):
        return stored_model.strip()
    return kc.gemini_client.DEFAULT_MODEL


def _fetch_username(token: str) -> str:
    """Benutzernamen zum Token holen (best-effort, still bei Fehler)."""
    if not token:
        return ""
    try:
        data = kc.WaniKaniClient(token, use_cache=False)._request("user")  # noqa: SLF001
        return (data.get("data") or {}).get("username", "") or ""
    except kc.WaniKaniError:
        return ""


# ---------- Jobs (pro Nutzer, Postgres/SQLite statt jobs/*.json) ------------ #

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_to_dict(row: models.Job) -> dict[str, Any]:
    """`Job`-Zeile in dieselbe Dict-Form wie das alte jobs/<id>.json bringen,
    damit `_run_render()`/die API-Endpunkte unverändert bleiben."""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "target_lang": row.target_lang,
        "title": row.title,
        "params": row.params or {},
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "filename": row.filename,
        "n_cards": row.n_cards,
        "error": row.error,
    }


def write_job(job: dict[str, Any], *, user_id: int | None = None) -> None:
    """Job-Zeile anlegen (erster Aufruf, braucht `user_id`) oder aktualisieren
    (Status/Ergebnis, Zeile existiert schon - z. B. aus `_run_render()`, das
    `current_user` im Worker-Thread nicht kennt und deshalb keinen `user_id`
    mitgeben muss)."""
    row = db.session.get(models.Job, job["id"])
    if row is None:
        if user_id is None:
            raise ValueError("write_job(): user_id ist beim erstmaligen Anlegen eines Jobs erforderlich.")
        row = models.Job(id=job["id"], user_id=user_id, target_lang=job.get("target_lang", "ja"))
        db.session.add(row)
    row.title = job.get("title", "")
    row.params = job.get("params") or {}
    row.status = job.get("status", "queued")
    row.filename = job.get("filename")
    row.n_cards = job.get("n_cards")
    row.error = job.get("error")
    if job.get("started_at"):
        row.started_at = datetime.fromisoformat(job["started_at"])
    if job.get("finished_at"):
        row.finished_at = datetime.fromisoformat(job["finished_at"])
    db.session.commit()


def read_job(job_id: str) -> dict[str, Any] | None:
    """OHNE Ownership-Check – nur für interne, vertrauenswürdige Aufrufer
    (den Render-Worker-Thread selbst, der `current_user` nicht kennt). Für
    HTTP-Endpunkte immer `read_job_owned()` verwenden."""
    row = db.session.get(models.Job, job_id)
    return _job_to_dict(row) if row else None


def read_job_owned(job_id: str) -> dict[str, Any] | None:
    """Wie `read_job()`, aber nur wenn der Job dem eingeloggten Nutzer gehört
    – sonst `None`, bewusst identisch zur Antwort für „existiert nicht",
    damit kein HTTP-Endpunkt verrät, ob eine fremde Job-ID existiert (IDOR-
    Schutz, siehe README "Multi-User-Architektur")."""
    row = db.session.get(models.Job, job_id)
    if row is None or row.user_id != current_user.id:
        return None
    return _job_to_dict(row)


def list_jobs() -> list[dict[str, Any]]:
    """Jobs des eingeloggten Nutzers FÜR DIE AKTUELL AKTIVE Zielsprache,
    neueste zuerst - Job-Verlauf/„bereits exportiert"-Status sind pro
    Sprache getrennt (siehe README "Multi-Language-Architektur"), sonst
    würde z. B. ein Sprachwechsel scheinbar fremde Exporte in der eigenen
    Historie zeigen."""
    rows = models.Job.query.filter_by(
        user_id=current_user.id, target_lang=_current_target_lang(),
    ).order_by(models.Job.created_at.desc()).all()
    return [_job_to_dict(r) for r in rows]


def _already_exported_ids() -> set[int]:
    """Subject-IDs, die der eingeloggte Nutzer schon einmal erfolgreich
    exportiert hat (PDF oder Anki).

    Liest den eigenen Job-Verlauf statt einer separaten Tabelle – ein Job ist
    bereits die vollständige Aufzeichnung, was wann gerendert wurde.
    """
    ids: set[int] = set()
    for job in list_jobs():
        if job.get("status") != "done":
            continue
        for sid in (job.get("params") or {}).get("subject_ids") or []:
            try:
                ids.add(int(sid))
            except (TypeError, ValueError):
                continue
    return ids


def _mark_exported(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`already_exported` an jede Tabellenzeile anhängen (Default-Auswahl im Frontend)."""
    exported = _already_exported_ids()
    for c in cards:
        try:
            c["already_exported"] = int(c["id"]) in exported
        except (TypeError, ValueError):
            c["already_exported"] = False
    return cards


# ---------- Eigene Karten (pro Nutzer, Postgres/SQLite statt customcards/) -- #

def _custom_card_to_dict(row: models.CustomCard) -> dict[str, Any]:
    return {
        "id": row.id,
        "front_html": row.front_html,
        "back_html": row.back_html,
        "tags": row.tags or [],
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def read_custom_for_user(user_id: int, cid: str) -> dict[str, Any] | None:
    """Explizit nach `user_id` gefiltert – für den Render-Worker-Thread (kennt
    `current_user` nicht, aber den `user_id` des Jobs) UND als Basis für
    `read_custom_owned()`."""
    row = models.CustomCard.query.filter_by(id=cid, user_id=user_id).first()
    return _custom_card_to_dict(row) if row else None


def read_custom_owned(cid: str) -> dict[str, Any] | None:
    """Wie `read_custom_for_user()`, aber für den eingeloggten Nutzer –
    `None` sowohl wenn die Karte nicht existiert als auch wenn sie einem
    anderen Nutzer gehört (IDOR-Schutz, siehe `read_job_owned()`)."""
    return read_custom_for_user(current_user.id, cid)


def write_custom(card: dict[str, Any], *, user_id: int, target_lang: str | None = None) -> None:
    """Neu anlegen oder aktualisieren. Der Aufrufer (`api_save_customcard()`)
    hat Ownership bei einer bestehenden ID bereits per `read_custom_owned()`
    geprüft, bevor diese Funktion aufgerufen wird. `target_lang` nur beim
    erstmaligen Anlegen relevant (Default: die aktuell aktive Zielsprache) -
    eine bestehende Karte wechselt beim Bearbeiten nicht die Sprache."""
    row = db.session.get(models.CustomCard, card["id"])
    if row is None:
        row = models.CustomCard(id=card["id"], user_id=user_id, target_lang=target_lang or "ja")
        db.session.add(row)
    row.front_html = card.get("front_html", "")
    row.back_html = card.get("back_html", "")
    row.tags = card.get("tags") or []
    db.session.commit()


def list_customs() -> list[dict[str, Any]]:
    """Eigene Karten der aktuell aktiven Zielsprache - "Frei erstellen" ist
    für jede Sprache nutzbar, der Verlauf bleibt aber pro Sprache getrennt."""
    rows = models.CustomCard.query.filter_by(
        user_id=current_user.id, target_lang=_current_target_lang(),
    ).order_by(models.CustomCard.updated_at.desc()).all()
    return [_custom_card_to_dict(r) for r in rows]


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _custom_descriptor(card: dict[str, Any]) -> dict[str, Any]:
    front = _strip_html(card.get("front_html", ""))
    back = _strip_html(card.get("back_html", ""))
    has_img = "<img" in (card.get("front_html", "") or "")
    return {
        "id": card["id"],
        "object": "custom",
        "kind": "Frei",
        "characters": (front[:6] or ("🖼" if has_img else "—")),
        "meaning": back[:48],
        "level": None,
        "has_image": has_img,
    }


# ---------- Dictionary-Karten (pro Nutzer, Postgres/SQLite statt kanacards/) #
#
# Zusammengesetzter Schlüssel (user_id, id): die ID selbst ist ein reiner
# Wort-Hash (kc.kana_card_id()), nutzerunabhängig – zwei Nutzer, die dasselbe
# Wort als Karte anlegen, brauchen trotzdem je eine eigene Zeile (siehe
# models.KanaCard-Docstring).

def _kana_card_to_dict(row: models.KanaCard) -> dict[str, Any]:
    return {
        "id": row.id,
        "word": row.word,
        "kanji_hint": row.kanji_hint,
        "reading": row.reading,
        "meaning": row.meaning,
        "meaning_extra": row.meaning_extra,
        "sentence_ja": row.sentence_ja,
        "sentence_translation": row.sentence_translation,
        "sentence_audio_url": row.sentence_audio_url,
        "source": row.source,
        "tags": row.tags or [],
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _get_kana_row(user_id: int, target_lang: str, kid: str) -> "models.KanaCard | None":
    return models.KanaCard.query.filter_by(user_id=user_id, target_lang=target_lang, id=kid).first()


def read_kana_for_user(user_id: int, kid: str, target_lang: str) -> dict[str, Any] | None:
    """Explizit nach `user_id`+`target_lang` gefiltert (Teil des
    zusammengesetzten Primärschlüssels seit dem Multi-Language-Umbau) – für
    den Render-Worker (kennt `current_user` nicht, aber `user_id`/
    `target_lang` des Jobs) UND als Basis für `read_kana_owned()`."""
    row = _get_kana_row(user_id, target_lang, kid)
    return _kana_card_to_dict(row) if row else None


def read_kana_owned(kid: str) -> dict[str, Any] | None:
    """Wie `read_kana_for_user()`, aber für den eingeloggten Nutzer in dessen
    aktuell aktiver Zielsprache (IDOR-Schutz, siehe `read_job_owned()`)."""
    return read_kana_for_user(current_user.id, kid, _current_target_lang())


def write_kana(card: dict[str, Any], *, user_id: int, target_lang: str | None = None) -> None:
    lang = target_lang or "ja"
    row = _get_kana_row(user_id, lang, card["id"])
    if row is None:
        row = models.KanaCard(id=card["id"], user_id=user_id, target_lang=lang)
        db.session.add(row)
    row.word = card.get("word", "")
    row.kanji_hint = card.get("kanji_hint")
    row.reading = card.get("reading")
    row.meaning = card.get("meaning", "")
    row.meaning_extra = card.get("meaning_extra")
    row.sentence_ja = card.get("sentence_ja")
    row.sentence_translation = card.get("sentence_translation")
    row.sentence_audio_url = card.get("sentence_audio_url")
    row.source = card.get("source", "dictionary")
    row.tags = card.get("tags") or []
    db.session.commit()


def list_kana() -> list[dict[str, Any]]:
    """Dictionary-/KI-Karten der aktuell aktiven Zielsprache."""
    rows = models.KanaCard.query.filter_by(
        user_id=current_user.id, target_lang=_current_target_lang(),
    ).order_by(models.KanaCard.updated_at.desc()).all()
    return [_kana_card_to_dict(r) for r in rows]


def _kana_descriptor(card: dict[str, Any]) -> dict[str, Any]:
    is_ai = card.get("source") == "ai"
    return {
        "id": card["id"],
        "object": "ai" if is_ai else "dictionary",
        "kind": "KI" if is_ai else "Dict",
        "characters": card.get("word", ""),
        "reading": card.get("reading"),
        "meaning": card.get("meaning", ""),
        "meaning_extra": card.get("meaning_extra"),
        "level": None,
        "has_image": False,
    }


# ---------- Render-Worker ---------------------------------------------------- #

def _build_mixed_deck(
    p: dict[str, Any], user_id: int, token: str | None = None, target_lang: str = "ja",
) -> list[Any]:
    """Kombinierten Stapel aus WaniKani-Subjects, eigenen und Dictionary-
    Karten bauen – alle drei Quellen können in einem Export landen (z. B.
    Text-Modus: WaniKani-Vokabel + Dictionary-Wort zusammen ausgewählt).
    `user_id` explizit statt `current_user`, da auch vom Render-Worker-Thread
    (kein Request-Kontext) aus aufgerufen; `token` ebenso explizit an
    kanji_cards.py durchgereicht statt über die Prozessumgebung. `target_lang`
    kommt vom Job (nicht vom evtl. inzwischen gewechselten `current_user`),
    weil `KanaCard`-Lookups seit dem Multi-Language-Umbau danach scopen."""
    deck: list[Any] = []
    if p.get("subject_ids"):
        deck.extend(
            kc.resolve_subject_deck(
                p["subject_ids"],
                use_cache=p.get("use_cache", True),
                sample=p.get("sample", False),
                sentence_overrides=p.get("sentence_overrides"),
                field_overrides=p.get("field_overrides"),
                token=token,
            )
        )
    if p.get("custom_ids"):
        datas = [read_custom_for_user(user_id, cid) for cid in p["custom_ids"]]
        deck.extend(kc.build_custom_card(d) for d in datas if d)
    if p.get("kana_ids"):
        datas = [read_kana_for_user(user_id, kid, target_lang) for kid in p["kana_ids"]]
        deck.extend(kc.build_kana_card_from_dict(d) for d in datas if d)
    return deck


def _run_render(job_id: str) -> None:
    """Der eigentliche Render-Worker – läuft als RQ-Job in einem separaten
    Worker-Prozess OHNE Flask-Request-Kontext, braucht deshalb
    `app.app_context()` für DB-Zugriffe (`current_user` ist hier nicht
    verfügbar, alle Lookups laufen über den im Job gespeicherten `user_id`
    statt über den eingeloggten Nutzer). Da RQ jeden Job in einer eigenen
    Job-Ausführung verarbeitet (keine parallelen Threads im selben Prozess,
    die sich hier in die Quere kommen könnten), ist kein eigenes Lock mehr
    nötig (anders als beim früheren `threading.Thread`-Ansatz)."""
    with app.app_context():
        job = read_job(job_id)
        if job is None:
            return
        user_id = job["user_id"]
        target_lang = job.get("target_lang", "ja")
        p = job["params"]
        job["status"] = "running"
        job["started_at"] = _now()
        write_job(job)

        anki = p.get("format") == "anki"
        out_key = f"{job_id}.apkg" if anki else f"{job_id}.pdf"
        try:
            settings = load_settings_for_user(user_id, target_lang)
            # Token nur nötig, wenn WaniKani-Subjects (keine reinen Custom-/
            # Dictionary-Karten, kein Demo-Modus) gerendert werden.
            needs_token = bool(p.get("subject_ids")) and not p.get("sample")
            if needs_token and not settings.get("token"):
                raise kc.WaniKaniError(
                    "Kein API-Token gespeichert. Bitte in den Einstellungen setzen."
                )

            deck = _build_mixed_deck(p, user_id, token=settings.get("token"), target_lang=target_lang)
            if not deck:
                raise kc.WaniKaniError("Keine Karten für die Auswahl gefunden.")

            # Erst in eine lokale Temp-Datei rendern (WeasyPrint/genanki
            # schreiben direkt auf einen Dateipfad), danach die fertigen Bytes
            # über die Storage-Abstraktion sichern (lokales Disk ODER S3/MinIO
            # - siehe storage.py). Der Zwischenschritt kostet bei lokalem
            # Disk eine zusätzliche Kopie, hält den Rendering-Code aber
            # unabhängig davon, wo das Ergebnis am Ende landet.
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir) / out_key
                if anki:
                    deck_name = job.get("title") or "Shiori"
                    root_deck_name = get_pack(target_lang).display_name("de")
                    _, n = ae.export_deck(deck, tmp_path, deck_name=deck_name, root_deck_name=root_deck_name)
                else:
                    username = settings.get("username", "")
                    if not p.get("sample") and not username:
                        username = ""  # kein Token → kein Name
                    kc.render_deck(
                        deck,
                        tmp_path,
                        layout=p.get("layout", "a6"),
                        paper=p.get("paper", "a4"),
                        duplex=p.get("duplex", "long-edge"),
                        cut_marks=p.get("cut_marks", True),
                        hole=p.get("hole", False),
                        username=username,
                    )
                    n = len(deck)
                storage.save_output(OUTPUT_DIR, out_key, tmp_path.read_bytes())
            job["status"] = "done"
            job["n_cards"] = n
            job["filename"] = out_key
        except kc.WaniKaniError as exc:
            job["status"], job["error"] = "error", str(exc)
        except Exception as exc:  # noqa: BLE001
            job["status"], job["error"] = "error", f"Unerwarteter Fehler: {exc}"
        finally:
            job["finished_at"] = _now()
            write_job(job)


# ---------- API: Konfig & Einstellungen ------------------------------------- #

@app.get("/api/config")
@login_required
def api_config() -> Any:
    return jsonify(
        {
            "layouts": list(kc.LAYOUTS),
            "types": ["radicals", "kanji", "vocabulary"],
            "formats": ["pdf", "anki"],
            "papers": ["a4", "letter", "a6"],
            "duplex": ["long-edge", "short-edge"],
            "defaults": load_settings()["defaults"],
        }
    )


@app.get("/api/settings")
@login_required
def api_get_settings() -> Any:
    s = load_settings()
    token = s.get("token", "")
    deepl_key = s.get("deepl_key", "")
    gemini_key = s.get("gemini_key", "")
    return jsonify(
        {
            "token_set": bool(token),
            "token_hint": _mask(token),
            "deepl_key_set": bool(deepl_key),
            "deepl_key_hint": _mask(deepl_key),
            "gemini_key_set": bool(gemini_key),
            "gemini_key_hint": _mask(gemini_key),
            "gemini_model": s.get("gemini_model", kc.gemini_client.DEFAULT_MODEL),
            "gemini_models": list(kc.gemini_client.AVAILABLE_MODELS),
            "target_lang": s.get("target_lang", "DE"),
            "target_langs": list(_TARGET_LANGS),
            "native_lang": s.get("native_lang", "de"),
            "active_target_lang": s.get("active_target_lang", "ja"),
            "defaults": s["defaults"],
        }
    )


@app.post("/api/settings")
@login_required
def api_post_settings() -> Any:
    body = request.get_json(silent=True) or {}
    s = load_settings()
    if isinstance(body.get("token"), str):
        s["token"] = body["token"].strip()
        s["username"] = _fetch_username(s["token"])  # für den Kartenaufdruck
    if isinstance(body.get("deepl_key"), str):
        s["deepl_key"] = body["deepl_key"].strip()
    if isinstance(body.get("gemini_key"), str):
        s["gemini_key"] = body["gemini_key"].strip()
    if isinstance(body.get("gemini_model"), str) and body["gemini_model"].strip().startswith("gemini-"):
        s["gemini_model"] = body["gemini_model"].strip()
    if isinstance(body.get("target_lang"), str) and body["target_lang"].strip().upper() in _TARGET_LANGS:
        s["target_lang"] = body["target_lang"].strip().upper()
    if isinstance(body.get("defaults"), dict):
        s["defaults"] = {**s["defaults"], **body["defaults"]}
    save_settings(s)
    return jsonify({"ok": True, "token_set": bool(s.get("token")), "username": s.get("username", "")})


# ---------- API: Sprachen (Muttersprache/aktive Zielsprache) ---------------- #

@app.get("/api/languages/public")
def api_languages_public() -> Any:
    """Wie `/api/languages`, aber OHNE Login - für die Sprachwahl im
    Registrierungsformular (vor dem ersten Login gibt es noch keinen
    `current_user`, dessen Muttersprache/Zielsprache abfragbar wäre).
    Liefert bewusst keine nutzerspezifischen Daten, nur die statische Liste
    unterstützter Zielsprachen - `?native_lang=` steuert nur die
    Anzeigesprache der Namen (Default Deutsch)."""
    native_lang = (request.args.get("native_lang") or "de").strip().lower()[:10]
    return jsonify({
        "supported_target_langs": [
            {"code": code, "display_name": get_pack(code).display_name(native_lang)}
            for code in SUPPORTED_TARGET_LANGS
        ],
    })


@app.get("/api/languages")
@login_required
def api_languages() -> Any:
    """Verfügbare Zielsprachen + Capabilities des jeweiligen `LanguagePack`
    (siehe languages/base.py) - treibt den Sprachwechsler und blendet im
    Frontend Modi ein/aus, die für die aktive Sprache keinen Sinn ergeben
    (z. B. „Level-Stapel"/„Suche" nur bei `has_content_provider`)."""
    s = load_settings()
    return jsonify({
        "native_lang": s.get("native_lang", "de"),
        "active_target_lang": s.get("active_target_lang", "ja"),
        "active_capabilities": _current_pack().capabilities(),
        "supported_target_langs": [
            {"code": code, "display_name": get_pack(code).display_name(s.get("native_lang", "de"))}
            for code in SUPPORTED_TARGET_LANGS
        ],
    })


@app.post("/api/settings/language")
@login_required
def api_post_language() -> Any:
    """Muttersprache und/oder aktive Zielsprache wechseln (Sprachwechsler) -
    unabhängig voneinander, beide optional im Body."""
    body = request.get_json(silent=True) or {}
    native_lang = body.get("native_lang")
    active_target_lang = body.get("active_target_lang")
    if native_lang is not None and not isinstance(native_lang, str):
        return jsonify({"error": "Ungültige Muttersprache."}), 400
    if active_target_lang is not None and not isinstance(active_target_lang, str):
        return jsonify({"error": "Ungültige Zielsprache."}), 400
    result = set_active_language(
        native_lang=native_lang.strip().lower()[:10] if native_lang else None,
        active_target_lang=active_target_lang.strip().lower()[:10] if active_target_lang else None,
    )
    return jsonify({"ok": True, **result})


@app.post("/api/gemini/models")
@login_required
@limiter.limit("20 per minute")
def api_gemini_models() -> Any:
    """Verfügbare Gemini-Modelle live per API abrufen (ListModels), statt eine
    hartcodierte Liste zu pflegen – akzeptiert optional einen noch nicht
    gespeicherten Key aus dem Formular (analog zu /api/test-token), sonst den
    in den Einstellungen hinterlegten."""
    key = (request.get_json(silent=True) or {}).get("key") or load_settings().get("gemini_key", "")
    if not key:
        return jsonify({"error": "Kein Gemini-API-Key angegeben."}), 400
    models = kc.gemini_client.list_models(key)
    if models is None:
        return jsonify({"error": "Modell-Liste konnte nicht abgerufen werden (ungültiger Key oder Netzwerkfehler)."}), 502
    if not models:
        return jsonify({"error": "Keine passenden Modelle gefunden."}), 502
    return jsonify({"models": models, "default": kc.gemini_client.DEFAULT_MODEL})


@app.post("/api/gemini/tts")
@login_required
@limiter.limit("20 per minute")
def api_gemini_tts() -> Any:
    """Text (Original-Satz im KI-Modus) per Gemini vorlesen lassen – gibt
    eine data-URI zurück, die sich sowohl direkt im Browser abspielen als
    auch beim Erstellen einer KI-Karte einbetten lässt (siehe
    `gemini_client.synthesize_speech()`, nutzt denselben Gemini-Key wie die
    Satzanalyse statt einen separaten Google-Cloud-TTS-Zugang zu brauchen)."""
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Kein Text angegeben."}), 400
    gemini_key = load_settings().get("gemini_key") or None
    if not gemini_key:
        return jsonify({"error": "Kein Gemini-API-Key in den Einstellungen hinterlegt."}), 400
    wav = kc.gemini_client.synthesize_speech(text, gemini_key)
    if wav is None:
        return jsonify({"error": "Sprachausgabe fehlgeschlagen (Netzwerk, Quota oder ungültiger Key)."}), 502
    audio_data_uri = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
    return jsonify({"audio_data_uri": audio_data_uri})


@app.post("/api/gemini/generate-image")
@login_required
@limiter.limit("20 per minute")
def api_gemini_generate_image() -> Any:
    """Bildkarten-Feature: ein einfaches Clipart-Bild für eine Vokabel per
    Gemini generieren lassen (siehe `gemini_client.generate_image()`) – gibt
    eine data-URI zurück, die im Frontend direkt als Vorschau angezeigt und
    bei „Übernehmen" als `field_overrides[id].image_data_uri` gespeichert
    wird (siehe FIELD_SCHEMAS in web/app.js). Bewusst pro Klick ein neuer,
    ungecachter Request – „Neu generieren" soll ein anderes Ergebnis liefern."""
    body = request.get_json(silent=True) or {}
    word = str(body.get("word", "")).strip()
    if not word:
        return jsonify({"error": "Kein Wort angegeben."}), 400
    meaning = str(body.get("meaning", "")).strip()
    gemini_key = load_settings().get("gemini_key") or None
    if not gemini_key:
        return jsonify({"error": "Kein Gemini-API-Key in den Einstellungen hinterlegt."}), 400
    result = kc.gemini_client.generate_image(word, meaning, gemini_key)
    if result is None:
        return jsonify({"error": "Bildgenerierung fehlgeschlagen (Netzwerk, Quota, ungültiger Key oder kein Bild in der Antwort)."}), 502
    image_bytes, mime_type = result
    image_data_uri = f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
    return jsonify({"image_data_uri": image_data_uri})


def _require_content_provider() -> Any | None:
    """`None`, wenn die aktuell aktive Zielsprache eine externe Lernstufen-
    Quelle wie WaniKani hat - sonst eine fertige 400-JSON-Response, die der
    Aufrufer direkt zurückgeben kann. Nur Japanisch hat aktuell einen
    `LanguagePack` mit `has_content_provider=True` (siehe languages/japanese.py)."""
    if _current_pack().has_content_provider:
        return None
    return jsonify({"error": "Diese Funktion ist nur für Japanisch (WaniKani) verfügbar."}), 400


@app.post("/api/test-token")
@login_required
def api_test_token() -> Any:
    if (blocked := _require_content_provider()) is not None:
        return blocked
    token = (request.get_json(silent=True) or {}).get("token") or load_settings().get(
        "token", ""
    )
    if not token:
        return jsonify({"ok": False, "error": "Kein Token angegeben."}), 400
    try:
        data = kc.WaniKaniClient(token, use_cache=False)._request("user")  # noqa: SLF001
        d = data.get("data") or {}
        # Benutzernamen für den Kartenaufdruck merken.
        s = load_settings()
        s["username"] = d.get("username", "") or ""
        save_settings(s)
        return jsonify({"ok": True, "username": d.get("username", "?"), "level": d.get("level")})
    except kc.WaniKaniError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


# ---------- API: Auflisten (resolve) ---------------------------------------- #

@app.post("/api/resolve")
@login_required
def api_resolve() -> Any:
    """Quelle in eine Kartenliste (Tabelle) auflösen.

    body.mode: "level" | "search" | "compose"
    """
    if (blocked := _require_content_provider()) is not None:
        return blocked
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    sample = bool(body.get("sample"))
    token = None if sample else load_settings().get("token")
    try:
        if mode == "level":
            level = int(body.get("level"))
            deck_types = body.get("types") or [body.get("type", "kanji")]
            cards = kc.resolve_level(level, deck_types, sample=sample, token=token)
        elif mode == "search":
            cards = kc.search_subjects(str(body.get("q", "")), sample=sample, token=token)
        elif mode == "compose":
            ids = body.get("subject_ids") or []
            cards = kc.resolve_composition(ids, sample=sample, token=token)
        else:
            return jsonify({"error": "Unbekannter Modus."}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Eingabe."}), 400
    except kc.WaniKaniError as exc:
        return jsonify({"error": str(exc)}), 502
    cards = _mark_exported(cards)
    return jsonify({"cards": cards})


@app.post("/api/card-detail")
@login_required
def api_card_detail() -> Any:
    """Volle Karten-Felder (alle Dataclass-Felder) für die gegebenen Subject-
    IDs liefern – Grundlage für den „Felder manuell anpassen"-Dialog in der
    Kartentabelle. Die Tabelle selbst (`/api/resolve`) zeigt nur eine
    Kurzfassung (Zeichen/Bedeutung/Level), zum Bearbeiten braucht das
    Frontend aber alle Felder (Lesungen, Beispielvokabel/-satz, Merkhilfen …).
    """
    if (blocked := _require_content_provider()) is not None:
        return blocked
    body = request.get_json(silent=True) or {}
    ids = body.get("subject_ids") or []
    sample = bool(body.get("sample"))
    token = None if sample else load_settings().get("token")
    try:
        details = kc.card_details_for_ids(ids, sample=sample, token=token)
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Eingabe."}), 400
    except kc.WaniKaniError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"cards": {str(k): v for k, v in details.items()}})


@app.post("/api/translate")
@login_required
def api_translate() -> Any:
    """Einen einzelnen Text (z. B. eine WaniKani-Bedeutung/Merkhilfe auf
    Englisch) per DeepL in die in den Einstellungen hinterlegte Zielsprache
    übersetzen – für den „Felder manuell anpassen"-Dialog (dortiger
    🌐-Button). `source_lang` per Default "EN", da WaniKani-Texte englisch
    sind; für japanische Beispielsätze übergibt das Frontend "JA"."""
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Kein Text angegeben."}), 400
    source_lang = str(body.get("source_lang") or "EN").strip().upper()
    s = load_settings()
    deepl_key = s.get("deepl_key") or None
    if not deepl_key:
        return jsonify({"error": "Kein DeepL-API-Key in den Einstellungen hinterlegt."}), 400
    target_lang = s.get("target_lang", "DE")
    translation = kc.dictionary.translate_sentence(
        text, deepl_key, target_lang=target_lang, source_lang=source_lang,
    )
    if translation is None:
        return jsonify({"error": "Übersetzung fehlgeschlagen (Netzwerk, Quota oder ungültiger Key)."}), 502
    return jsonify({"translation": translation, "target_lang": target_lang})


# ---------- API: Text-Modus (lemmatisieren, annotieren, bekannt markieren) -- #

@app.post("/api/text-annotate")
@login_required
def api_text_annotate() -> Any:
    """Text lemmatisieren und zeilenweise annotieren (kein Auto-Hinzufügen).

    Reine Janome-Lemmatisierung + WaniKani-/JMdict-Abgleich, kein Gemini
    (dafür siehe `/api/text-annotate-ai`, der eigenständige „KI"-Modus).

    Jedes erkannte Wort bekommt zwei rohe Signale (fürs clientseitige
    Umschalten von „bekannt" ohne Server-Roundtrip):
    - `manually_known` (bool) – manuell als bekannt markiert (`/api/known`).
    - `ready`          (bool) – Karte dafür existiert bereits
                                 (WaniKani exportiert bzw. Dictionary-Karte erstellt).
    Daraus abgeleitet (bereits serverseitig berechnet, zur Bequemlichkeit):
    - `status` – nur noch `known` / `unknown` (treibt die Farbcodierung im
                 Text-Modus: grün/blau, unabhängig von Quelle oder Grund –
                 Details wie „manuell markiert" vs. „Karte erstellt" bzw.
                 die Quelle (`source`: `wanikani`/`dictionary`) zeigt das
                 Wort-Popup).
    - `known`  – `manually_known or ready`, treibt die „Prozent bekannt"-Statistik
                 (Vorkommen-basiert, nicht nur eindeutige Wörter).

    Nur verfügbar, wenn die aktive Zielsprache einen Offline-Tokenizer hat
    (aktuell nur Japanisch/Janome) - für andere Sprachen siehe
    `/api/text-annotate-ai` (Gemini-gestützt, funktioniert sprachunabhängig).
    """
    if not _current_pack().has_offline_tokenizer:
        return jsonify({"error": "Dieser Modus ist nur für Japanisch verfügbar. Bitte „Mit KI“ verwenden."}), 400
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", ""))
    sample = bool(body.get("sample"))
    token = None if sample else load_settings().get("token")
    logger.info("text-annotate: %d Zeichen, sample=%s …", len(text), sample)
    t0 = time.monotonic()
    try:
        lines = kc.annotate_text(text, sample=sample, token=token)
    except kc.WaniKaniError as exc:
        return jsonify({"error": str(exc)}), 502
    logger.info("text-annotate: fertig in %.1fs (%d Zeilen)", time.monotonic() - t0, len(lines))

    exported = _already_exported_ids()
    known_manual = load_known()
    created_kana = {c["id"] for c in list_kana()}
    total = 0
    known_count = 0
    for line in lines:
        for seg in line:
            if seg.get("type") != "word":
                continue
            is_dict = seg.get("source") == "dictionary"
            sid: int | str = str(seg["id"]) if is_dict else int(seg["id"])
            is_manual = sid in known_manual
            is_ready = sid in (created_kana if is_dict else exported)
            seg["manually_known"] = is_manual
            seg["ready"] = is_ready
            seg["status"] = "known" if (is_manual or is_ready) else "unknown"
            seg["known"] = is_manual or is_ready
            total += 1
            if seg["known"]:
                known_count += 1
    percent = round(known_count / total * 100, 1) if total else 0.0
    return jsonify(
        {
            "lines": lines,
            "stats": {"known": known_count, "total": total, "percent": percent},
        }
    )


@app.post("/api/text-annotate-ai")
@login_required
@limiter.limit("20 per minute")
def api_text_annotate_ai() -> Any:
    """Text per Gemini satzweise analysieren (eigener „KI"-Modus, siehe
    `kc.annotate_text_ai()`): pro Satz Original, deutsche Übersetzung,
    Grammatik-Notizen und anklickbare Wort-Segmente – ohne Fallback auf
    Janome, ein Satz bekommt bei einem Fehler stattdessen `error` gesetzt.

    Braucht einen in den Einstellungen hinterlegten Gemini-Key. Jedes
    Wort-Segment bekommt zusätzlich `manually_known`/`ready`/`status`/`known`
    wie bei `/api/text-annotate` – `source: "ai"`-Wörter zählen dabei genau
    wie `source: "dictionary"` über `kanacards/` (dieselbe Karten-
    Infrastruktur, nur mit KI- statt JMdict-Bedeutung; eine Karte entsteht
    aber erst, wenn der Nutzer sie manuell über `/api/kanacards` anlegt).
    """
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", ""))
    sample = bool(body.get("sample"))
    s = load_settings()
    gemini_key = s.get("gemini_key") or None
    if not gemini_key:
        return jsonify({"error": "Kein Gemini-API-Key in den Einstellungen hinterlegt."}), 400
    gemini_model = _resolve_gemini_model(s)

    token = None if sample else s.get("token")
    lang = _current_target_lang()
    pack = _current_pack()
    # Ausgeschriebene Sprachnamen für den Gemini-Prompt (siehe
    # gemini_client._batch_prompt()) - der Prompt-Text selbst ist auf
    # Deutsch verfasst, die Namen daher immer auf Deutsch ausgeschrieben
    # (nicht in der jeweiligen Sprache selbst).
    native_lang_name = get_pack(current_user.native_lang).display_name("de")
    logger.info("text-annotate-ai: %d Zeichen, sample=%s, Modell=%s …", len(text), sample, gemini_model)
    t0 = time.monotonic()
    try:
        rows = kc.annotate_text_ai(
            text, gemini_key=gemini_key, gemini_model=gemini_model, sample=sample, token=token,
            target_lang=lang, target_lang_name=pack.display_name("de"),
            native_lang_name=native_lang_name, has_reading=pack.has_furigana,
        )
    except kc.WaniKaniError as exc:
        return jsonify({"error": str(exc)}), 502
    logger.info("text-annotate-ai: fertig in %.1fs (%d Sätze)", time.monotonic() - t0, len(rows))

    exported = _already_exported_ids()
    known_manual = load_known()
    created_kana = {c["id"] for c in list_kana()}
    total = 0
    known_count = 0
    for row in rows:
        for seg in row["segments"]:
            if seg.get("type") != "word":
                continue
            is_wk = seg.get("source") == "wanikani"
            sid: int | str = int(seg["id"]) if is_wk else str(seg["id"])
            is_manual = sid in known_manual
            is_ready = sid in (exported if is_wk else created_kana)
            seg["manually_known"] = is_manual
            seg["ready"] = is_ready
            seg["status"] = "known" if (is_manual or is_ready) else "unknown"
            seg["known"] = is_manual or is_ready
            total += 1
            if seg["known"]:
                known_count += 1
    percent = round(known_count / total * 100, 1) if total else 0.0
    return jsonify(
        {
            "rows": rows,
            "stats": {"known": known_count, "total": total, "percent": percent},
        }
    )


@app.post("/api/text-extract")
@login_required
@limiter.limit("20 per minute")
def api_text_extract() -> Any:
    """Text aus einer hochgeladenen PDF-Datei oder einem Bild extrahieren
    (siehe `pdf_import.py`) – liefert reinen Text zurück, der dann genauso
    wie manuell eingefügter Text durch „Aus Text"/„Mit KI" läuft.

    PDF-Seiten mit Textlayer werden kostenlos direkt ausgelesen; Seiten ohne
    Textlayer (Scans) und Bilder brauchen für die Texterkennung einen in
    den Einstellungen hinterlegten Gemini-Key.
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Keine Datei hochgeladen."}), 400
    data = file.read()
    if not data:
        return jsonify({"error": "Datei ist leer."}), 400
    if len(data) > _MAX_UPLOAD_BYTES:
        return jsonify({"error": f"Datei zu groß (max. {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)."}), 400

    s = load_settings()
    gemini_key = s.get("gemini_key") or None
    gemini_model = _resolve_gemini_model(s)
    pack = _current_pack()

    logger.info("text-extract: %s (%d Bytes) …", file.filename, len(data))
    t0 = time.monotonic()
    try:
        text = pdf_import.extract_text_from_upload(
            data, file.filename, file.mimetype, gemini_key=gemini_key, gemini_model=gemini_model,
            target_lang_name=pack.display_name("de"), has_furigana=pack.has_furigana,
        )
    except pdf_import.ExtractionError as exc:
        return jsonify({"error": str(exc)}), 400
    logger.info("text-extract: fertig in %.1fs (%d Zeichen)", time.monotonic() - t0, len(text))

    if not text.strip():
        return jsonify(
            {"error": "Kein Text gefunden – bei gescannten Seiten/Bildern wird ein Gemini-Key benötigt."}
        ), 422
    return jsonify({"text": text})


_KNOWN_META_FIELDS = ("characters", "meaning", "kind", "level", "source")


@app.post("/api/known/<string:word_id>")
@login_required
def api_mark_known(word_id: str) -> Any:
    coerced = _coerce_known_id(word_id)
    body = request.get_json(silent=True) or {}
    fields = {k: body[k] for k in _KNOWN_META_FIELDS if k in body}
    _upsert_known_word(str(coerced), fields)
    return jsonify({"ok": True, "id": coerced, "known": True})


@app.delete("/api/known/<string:word_id>")
@login_required
def api_unmark_known(word_id: str) -> Any:
    coerced = _coerce_known_id(word_id)
    _remove_known_word(str(coerced))
    return jsonify({"ok": True, "id": coerced, "known": False})


# ---------- API: Wortliste (alle bekannten Wörter, gefiltert/entfernbar) ---- #

@app.get("/api/wortliste")
@login_required
def api_wortliste() -> Any:
    """Vereinigte Liste aller bekannten Wörter: WaniKani (exportiert oder
    manuell markiert), Dictionary (Karte erstellt oder manuell markiert) und
    rein manuelle Einträge ohne Karte/Subject. Volltextsuche/Filter passiert
    clientseitig (Liste ist überschaubar, keine Server-Roundtrips nötig)."""
    sample = request.args.get("sample") in ("1", "true", "True")
    exported = _already_exported_ids()
    manual = load_known()
    meta = load_known_meta()
    kana_records = {c["id"]: c for c in list_kana()}

    entries: list[dict[str, Any]] = []

    wk_ids = sorted(exported | {i for i in manual if isinstance(i, int)})
    by_id: dict[int, dict[str, Any]] = {}
    if wk_ids:
        try:
            token = None if sample else load_settings().get("token")
            by_id = {d["id"]: d for d in kc.resolve_subject_ids(wk_ids, sample=sample, token=token)}
        except kc.WaniKaniError:
            by_id = {}
    for sid in wk_ids:
        d = by_id.get(sid) or {}
        m = meta.get(str(sid), {})
        entries.append(
            {
                "id": sid,
                "source": "wanikani",
                "object": d.get("object", ""),
                "characters": d.get("characters") or m.get("characters") or f"#{sid}",
                "meaning": d.get("meaning") or m.get("meaning", ""),
                "kind": d.get("kind") or m.get("kind", "?"),
                "level": d.get("level", m.get("level")),
                "already_exported": sid in exported,
                "manually_known": sid in manual,
                "removable": sid in manual,
            }
        )

    dict_ids = sorted(
        set(kana_records)
        | {i for i in manual if isinstance(i, str) and (i.startswith("kana_") or i.startswith("aikana_"))}
    )
    for wid in dict_ids:
        card = kana_records.get(wid) or {}
        m = meta.get(wid, {})
        is_ai = card.get("source") == "ai"
        entries.append(
            {
                "id": wid,
                "source": "ai" if is_ai else "dictionary",
                "characters": card.get("word") or m.get("characters") or wid,
                "reading": card.get("reading"),
                "meaning": card.get("meaning") or m.get("meaning", ""),
                "meaning_extra": card.get("meaning_extra"),
                "kind": "KI" if is_ai else "Dict",
                "level": None,
                "card_created": wid in kana_records,
                "manually_known": wid in manual,
                "removable": True,
                "sentence_ja": card.get("sentence_ja"),
                "sentence_translation": card.get("sentence_translation"),
                "sentence_audio_url": card.get("sentence_audio_url"),
            }
        )

    manual_ids = sorted(i for i in manual if isinstance(i, str) and i.startswith("manual_"))
    for wid in manual_ids:
        m = meta.get(wid, {})
        entries.append(
            {
                "id": wid,
                "source": "manual",
                "characters": m.get("characters", wid),
                "meaning": m.get("meaning", ""),
                "kind": "Manuell",
                "level": None,
                "manually_known": True,
                "removable": True,
            }
        )

    return jsonify({"entries": entries, "total": len(entries)})


@app.post("/api/wortliste")
@login_required
def api_wortliste_add_manual() -> Any:
    """Rein manuellen Eintrag (ohne WaniKani-Subject/Dictionary-Treffer) zur
    Wortliste hinzufügen – z. B. ein Wort, das man von woanders schon kann."""
    body = request.get_json(silent=True) or {}
    characters = str(body.get("characters", "")).strip()
    meaning = str(body.get("meaning", "")).strip()
    if not characters:
        return jsonify({"error": "Bitte ein Wort angeben."}), 400
    wid = "manual_" + hashlib.sha1(characters.encode("utf-8")).hexdigest()[:16]
    _upsert_known_word(
        wid, {"characters": characters, "meaning": meaning, "kind": "Manuell", "level": None, "source": "manual"},
    )
    return jsonify(
        {
            "id": wid,
            "source": "manual",
            "characters": characters,
            "meaning": meaning,
            "kind": "Manuell",
            "level": None,
            "manually_known": True,
            "removable": True,
        }
    )


# ---------- API: Rendern (by ids) ------------------------------------------- #

@app.post("/api/render")
@login_required
@limiter.limit("10 per minute")
def api_render() -> Any:
    body = request.get_json(silent=True) or {}
    subject_ids = body.get("subject_ids") or []
    custom_ids = body.get("custom_ids") or []
    kana_ids = body.get("kana_ids") or []
    if not (subject_ids or custom_ids or kana_ids):
        return jsonify({"error": "Keine Karten ausgewählt."}), 400
    fmt = body.get("format", "pdf")
    if fmt not in ("pdf", "anki"):
        return jsonify({"error": "Ungültiges Format."}), 400
    layout = body.get("layout", "a6")
    if fmt == "pdf" and layout not in kc.LAYOUTS:
        return jsonify({"error": "Ungültiges Layout."}), 400

    # Ownership vor dem Rendern prüfen (IDOR-Schutz): sonst könnte ein Nutzer
    # eine fremde custom_id/kana_id angeben und deren Inhalt in sein EIGENES
    # Export mitrendern lassen. WaniKani-Subjects brauchen das nicht (öffentliche
    # WaniKani-Daten, kein privater Nutzer-Inhalt).
    for cid in custom_ids:
        if read_custom_owned(str(cid)) is None:
            return jsonify({"error": f"Eigene Karte „{cid}“ nicht gefunden."}), 404
    for kid in kana_ids:
        if read_kana_owned(str(kid)) is None:
            return jsonify({"error": f"Dictionary-Karte „{kid}“ nicht gefunden."}), 404

    sentence_overrides = body.get("sentence_overrides")
    field_overrides = body.get("field_overrides")
    params = {
        "subject_ids": [int(i) for i in subject_ids] if subject_ids else [],
        "custom_ids": [str(i) for i in custom_ids] if custom_ids else [],
        "kana_ids": [str(i) for i in kana_ids] if kana_ids else [],
        "format": fmt,
        "layout": layout,
        "paper": body.get("paper", "a4"),
        "duplex": body.get("duplex", "long-edge"),
        "cut_marks": bool(body.get("cut_marks", True)),
        "hole": bool(body.get("hole", False)),
        "use_cache": not bool(body.get("no_cache", False)),
        "sample": bool(body.get("sample", False)),
        "sentence_overrides": sentence_overrides if isinstance(sentence_overrides, dict) else {},
        "field_overrides": field_overrides if isinstance(field_overrides, dict) else {},
    }
    n = len(params["custom_ids"]) + len(params["subject_ids"]) + len(params["kana_ids"])
    title = body.get("title") or f"{n} Karten"

    # Ein Nutzer soll nicht die gesamte Worker-Kapazität (gemeinsame
    # Infrastruktur, im Gegensatz zum WaniKani-Rate-Limit, das ja bereits pro
    # Token/Nutzer gilt) durch beliebig viele parallele Render-Jobs blockieren.
    active_count = models.Job.query.filter(
        models.Job.user_id == current_user.id,
        models.Job.status.in_(("queued", "running")),
    ).count()
    if active_count >= _MAX_CONCURRENT_JOBS_PER_USER:
        return jsonify({
            "error": f"Zu viele laufende Render-Jobs (max. {_MAX_CONCURRENT_JOBS_PER_USER} gleichzeitig). "
                     "Bitte warte, bis ein Job fertig ist.",
        }), 429

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "title": title,
        "params": params,
        "status": "queued",
        "created_at": _now(),
        "target_lang": _current_target_lang(),
    }
    write_job(job, user_id=current_user.id)
    render_queue.enqueue(_run_render, job_id, job_timeout=600)
    return jsonify(job), 202


# ---------- API: Jobs -------------------------------------------------------- #

@app.get("/api/customcards")
@login_required
def api_customcards() -> Any:
    return jsonify([_custom_descriptor(c) for c in list_customs()])


@app.get("/api/customcards/<cid>")
@login_required
def api_customcard(cid: str) -> Any:
    card = read_custom_owned(cid)
    if card is None:
        abort(404)
    return jsonify(card)


@app.post("/api/customcards")
@login_required
def api_save_customcard() -> Any:
    body = request.get_json(silent=True) or {}
    cid = body.get("id")
    if cid:
        # Bearbeiten einer bestehenden Karte: nur wenn sie dem eingeloggten
        # Nutzer gehört - sonst würde ein untergeschobenes Fremd-Id die Karte
        # eines anderen Nutzers überschreiben (IDOR).
        if read_custom_owned(str(cid)) is None:
            return jsonify({"error": "Karte nicht gefunden."}), 404
    else:
        cid = uuid.uuid4().hex[:12]
    card = {
        "id": cid,
        "front_html": str(body.get("front_html", "")),
        "back_html": str(body.get("back_html", "")),
        "tags": [str(t).strip() for t in (body.get("tags") or []) if str(t).strip()],
    }
    write_custom(card, user_id=current_user.id, target_lang=_current_target_lang())
    return jsonify(read_custom_owned(cid))


@app.delete("/api/customcards/<cid>")
@login_required
def api_delete_customcard(cid: str) -> Any:
    if read_custom_owned(cid) is None:
        abort(404)
    models.CustomCard.query.filter_by(id=cid, user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


# ---------- API: Dictionary-Karten (kanacards) ------------------------------- #

@app.get("/api/kanacards")
@login_required
def api_kanacards() -> Any:
    return jsonify([_kana_descriptor(c) for c in list_kana()])


@app.post("/api/kanacards")
@login_required
def api_create_kanacard() -> Any:
    """Wort (aus dem Text-Modus, ohne WaniKani-Treffer) als Dictionary- oder
    KI-Karte anlegen.

    Default (`source` fehlt/`"dictionary"`): bei Japanisch kommt die
    Bedeutung aus JMdict (`kc.build_kana_card`). Für jede andere Zielsprache
    (kein JMdict-Äquivalent) übernimmt Gemini die Nachschlage-Funktion
    (`kc.build_generic_dictionary_card`, siehe README "Multi-Language-
    Architektur", Entscheidung 3) – braucht dafür einen hinterlegten
    Gemini-Key.

    `source: "ai"` (aus dem KI-Modus, siehe `annotate_text_ai()`): Bedeutung
    kommt direkt von Gemini (`meaning`/`reading` im Request), kein weiterer
    Lookup nötig – der Nutzer hat das Wort bewusst im KI-Modus angeklickt, es
    wird nie automatisch für alle KI-erkannten Wörter eine Karte erzeugt.

    Satzübersetzung in beiden Fällen optional per DeepL, wenn ein Key
    hinterlegt ist (sonst bleibt die Karte trotzdem gültig)."""
    body = request.get_json(silent=True) or {}
    word = str(body.get("word", "")).strip()
    sentence_raw = body.get("sentence")
    sentence = sentence_raw.strip() if isinstance(sentence_raw, str) and sentence_raw.strip() else None
    source = str(body.get("source") or "dictionary").strip()
    if not word:
        return jsonify({"error": "Kein Wort angegeben."}), 400
    s = load_settings()
    deepl_key = s.get("deepl_key") or None
    sentence_audio = body.get("sentence_audio_url") or None
    if source == "ai":
        meaning = str(body.get("meaning") or "").strip()
        if not meaning:
            return jsonify({"error": "Keine KI-Bedeutung angegeben."}), 400
        card_obj = kc.build_ai_kana_card(
            word, meaning=meaning, reading=body.get("reading"), sentence=sentence,
            sentence_audio_url=sentence_audio, deepl_key=deepl_key,
        )
    elif _current_pack().has_furigana:  # aktuell gleichbedeutend mit "hat JMdict", siehe JapanesePack
        card_obj = kc.build_kana_card(word, sentence, deepl_key=deepl_key)
        if card_obj is None:
            return jsonify({"error": f"„{word}“ wurde im Wörterbuch nicht gefunden."}), 404
    else:
        pack = _current_pack()
        gemini_key = s.get("gemini_key") or None
        if not gemini_key:
            return jsonify({"error": "Kein Gemini-API-Key in den Einstellungen hinterlegt (nötig für das Wörterbuch dieser Sprache)."}), 400
        card_obj = kc.build_generic_dictionary_card(
            word, sentence, gemini_key=gemini_key, gemini_model=_resolve_gemini_model(s),
            target_lang_name=pack.display_name("de"), native_lang_name=get_pack(current_user.native_lang).display_name("de"),
            has_reading=pack.has_furigana, deepl_key=deepl_key,
        )
        if card_obj is None:
            return jsonify({"error": f"„{word}“ wurde nicht als gültiges Wort erkannt."}), 404
    record = {
        "id": card_obj.card_id,
        "word": card_obj.word,
        "kanji_hint": card_obj.kanji_hint,
        "reading": card_obj.reading,
        "meaning": card_obj.meaning,
        "meaning_extra": card_obj.meaning_extra,
        "sentence_ja": card_obj.sentence_ja,
        "sentence_translation": card_obj.sentence_translation,
        "sentence_audio_url": card_obj.sentence_audio_url,
        "source": card_obj.source,
        "tags": card_obj.tags,
    }
    write_kana(record, user_id=current_user.id, target_lang=_current_target_lang())
    return jsonify(_kana_descriptor(read_kana_owned(record["id"])))


@app.delete("/api/kanacards/<kid>")
@login_required
def api_delete_kanacard(kid: str) -> Any:
    if read_kana_owned(kid) is None:
        abort(404)
    models.KanaCard.query.filter_by(id=kid, user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


@app.get("/api/jobs")
@login_required
def api_jobs() -> Any:
    return jsonify(list_jobs())


@app.get("/api/jobs/<job_id>")
@login_required
def api_job(job_id: str) -> Any:
    job = read_job_owned(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.delete("/api/jobs/<job_id>")
@login_required
def api_delete_job(job_id: str) -> Any:
    if read_job_owned(job_id) is None:
        abort(404)
    storage.delete_output(OUTPUT_DIR, f"{job_id}.pdf")
    storage.delete_output(OUTPUT_DIR, f"{job_id}.apkg")
    models.Job.query.filter_by(id=job_id, user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


def _serve_job_output(job_id: str, *, suffix: str, mimetype: str) -> Any:
    """Gemeinsame Auslieferung für PDF/APKG: bei S3/MinIO per Redirect auf eine
    signierte URL (kein Umweg über den App-Server nötig), sonst lokal per
    `send_file()` (siehe storage.py: `generate_download_url()` liefert `None`,
    solange kein Object Storage konfiguriert ist)."""
    job = read_job_owned(job_id)
    if job is None or job.get("status") != "done":
        abort(404)
    key = f"{job_id}{suffix}"
    download = request.args.get("download") == "1"
    safe = "".join(c for c in job.get("title", "cards") if c.isalnum() or c in " -_")
    download_name = f"wanikani-{safe.strip() or 'cards'}{suffix}"

    url = storage.generate_download_url(key, filename=download_name)
    if url is not None:
        return redirect(url)

    if not storage.output_exists(OUTPUT_DIR, key):
        abort(404)
    return send_file(
        OUTPUT_DIR / key,
        mimetype=mimetype,
        as_attachment=download,
        download_name=download_name,
        max_age=0,
    )


@app.get("/api/jobs/<job_id>/pdf")
@login_required
def api_job_pdf(job_id: str) -> Any:
    return _serve_job_output(job_id, suffix=".pdf", mimetype="application/pdf")


@app.get("/api/jobs/<job_id>/apkg")
@login_required
def api_job_apkg(job_id: str) -> Any:
    return _serve_job_output(job_id, suffix=".apkg", mimetype="application/octet-stream")


# ---------- Vokabeltrainer (SRS, Fundament) ---------------------------------- #
#
# Dritter Export-Weg neben PDF/Anki: Karten direkt in Shiori mit FSRS lernen
# (siehe srs.py, models.ReviewState, README "Vokabeltrainer"). Phase 2:
# Karten in die Warteschlange aufnehmen + auflisten - der eigentliche
# Review-Screen (Eingabe/Bewertung, `/api/srs/answer`) ist eine spätere
# Phase.

def _srs_add_card(
    user_id: int, target_lang: str, card_type: str, card_id: str, item_types: list[str],
) -> int:
    """Für jeden noch NICHT vorhandenen `item_type` eine frische
    `ReviewState`-Zeile anlegen - bereits vorhandene Zeilen (Karte war schon
    einmal hinzugefügt) bleiben unverändert, damit ein erneutes Hinzufügen
    nie den Lernfortschritt zurücksetzt. Gibt die Anzahl NEU angelegter
    Zeilen zurück."""
    added = 0
    for item_type in item_types:
        existing = db.session.get(
            models.ReviewState, (user_id, target_lang, card_type, card_id, item_type),
        )
        if existing is not None:
            continue
        row = models.ReviewState(
            user_id=user_id, target_lang=target_lang, card_type=card_type,
            card_id=card_id, item_type=item_type,
        )
        srs.apply_state_to_row(row, srs.new_review_state())
        db.session.add(row)
        added += 1
    if added:
        db.session.commit()
    return added


@app.post("/api/srs/add")
@login_required
def api_srs_add() -> Any:
    """Ausgewählte Karten (dieselbe Auswahl-Form wie `/api/render`) in die
    Lernwarteschlange aufnehmen. Kanji/Vokabel bekommen zwei Zeilen (Meaning
    + Reading, wie WaniKani selbst), Radicals/Custom-Karten nur eine
    (Radicals haben keine Lesung); Dictionary-/KI-Karten bekommen eine
    Reading-Zeile nur, wenn die Karte selbst eine Lesung hat."""
    body = request.get_json(silent=True) or {}
    subject_ids = [int(i) for i in (body.get("subject_ids") or [])]
    custom_ids = [str(i) for i in (body.get("custom_ids") or [])]
    kana_ids = [str(i) for i in (body.get("kana_ids") or [])]
    if not (subject_ids or custom_ids or kana_ids):
        return jsonify({"error": "Keine Karten ausgewählt."}), 400

    # Ownership vor dem Hinzufügen prüfen (IDOR-Schutz, siehe api_render()).
    for cid in custom_ids:
        if read_custom_owned(cid) is None:
            return jsonify({"error": f"Eigene Karte „{cid}“ nicht gefunden."}), 404
    for kid in kana_ids:
        if read_kana_owned(kid) is None:
            return jsonify({"error": f"Dictionary-Karte „{kid}“ nicht gefunden."}), 404

    lang = _current_target_lang()
    sample = bool(body.get("sample"))
    added = 0

    if subject_ids:
        if (blocked := _require_content_provider()) is not None:
            return blocked
        token = None if sample else load_settings().get("token")
        try:
            details = kc.resolve_subject_ids(subject_ids, sample=sample, token=token)
        except kc.WaniKaniError as exc:
            return jsonify({"error": str(exc)}), 502
        for d in details:
            item_types = ["meaning", "reading"] if d.get("object") in ("kanji", "vocabulary") else ["meaning"]
            added += _srs_add_card(current_user.id, lang, "wanikani", str(d["id"]), item_types)

    for cid in custom_ids:
        added += _srs_add_card(current_user.id, lang, "custom", cid, ["front"])

    for kid in kana_ids:
        record = read_kana_owned(kid)
        item_types = ["meaning", "reading"] if record and record.get("reading") else ["meaning"]
        added += _srs_add_card(current_user.id, lang, "kana", kid, item_types)

    return jsonify({"ok": True, "added": added})


def _srs_resolve_fronts(rows: list["models.ReviewState"]) -> dict[tuple[str, str], str]:
    """Kurzer Vorschautext ("Vorderseite") je `(card_type, card_id)` für die
    Warteschlangen-Ansicht – WaniKani-Subjects gebündelt in einem Request
    aufgelöst (nutzt den bestehenden Disk-Cache aus kanji_cards.py, kein
    Request pro Karte), Custom-/Dictionary-Karten direkt aus der DB."""
    fronts: dict[tuple[str, str], str] = {}
    wk_ids = sorted({int(r.card_id) for r in rows if r.card_type == "wanikani"})
    if wk_ids:
        token = load_settings().get("token")
        try:
            # Ohne gespeicherten Token auf die Sample-Registry zurückfallen
            # (Demo-Modus, gleiche Konvention wie überall sonst in der App,
            # z. B. /api/text-annotate) - sonst bliebe die Vorschau für jede
            # Demo-Karte leer, weil der echte WaniKani-Request ohne Token
            # fehlschlägt.
            for d in kc.resolve_subject_ids(wk_ids, sample=not token, token=token):
                fronts[("wanikani", str(d["id"]))] = d["characters"]
        except kc.WaniKaniError:
            pass
    for r in rows:
        key = (r.card_type, r.card_id)
        if key in fronts:
            continue
        if r.card_type == "custom":
            card = read_custom_for_user(r.user_id, r.card_id)
            fronts[key] = _strip_html(card["front_html"])[:80] if card else "?"
        elif r.card_type == "kana":
            card = read_kana_for_user(r.user_id, r.card_id, r.target_lang)
            fronts[key] = (card.get("word") if card else None) or "?"
    return fronts


@app.get("/api/srs/queue")
@login_required
def api_srs_queue() -> Any:
    """Fällige Karten für die aktuell aktive Zielsprache, älteste Fälligkeit
    zuerst – Grundlage für den (späteren) Review-Screen. `limit` deckelt die
    Antwortgröße (Default 50, max. 200), `due_total` ist die volle Anzahl
    unabhängig vom Limit (fürs „X Karten fällig"-Badge im Frontend)."""
    lang = _current_target_lang()
    now = datetime.now(timezone.utc)
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except (TypeError, ValueError):
        limit = 50

    base_query = models.ReviewState.query.filter(
        models.ReviewState.user_id == current_user.id,
        models.ReviewState.target_lang == lang,
        models.ReviewState.due_at <= now,
    )
    due_total = base_query.count()
    rows = base_query.order_by(models.ReviewState.due_at.asc()).limit(limit).all()

    fronts = _srs_resolve_fronts(rows)
    items = [
        {
            "card_type": r.card_type,
            "card_id": r.card_id,
            "item_type": r.item_type,
            "front": fronts.get((r.card_type, r.card_id), "?"),
            "due_at": r.due_at.isoformat(),
            "is_new": r.reps == 0,
        }
        for r in rows
    ]
    return jsonify({"items": items, "due_total": due_total})


def _get_review_row(card_type: str, card_id: str, item_type: str) -> "models.ReviewState | None":
    """Wie die anderen `*_owned()`-Helfer (siehe `read_job_owned()`): `None`
    sowohl wenn die Zeile nicht existiert als auch wenn sie einem anderen
    Nutzer gehört – der zusammengesetzte Primärschlüssel enthält bereits
    `target_lang`, aber NICHT implizit `user_id`, daher der explizite
    Vergleich danach."""
    row = db.session.get(
        models.ReviewState, (current_user.id, _current_target_lang(), card_type, card_id, item_type),
    )
    return row


def _levenshtein(a: str, b: str) -> int:
    """Klassische Editierdistanz (Einfügen/Löschen/Ersetzen) – für die
    kurzen Wörter/Bedeutungen hier reicht die einfache O(n·m)-DP-Variante,
    keine externe Bibliothek nötig."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _normalize_answer(text: str) -> str:
    return re.sub(r"[^\w]", "", text.strip().lower(), flags=re.UNICODE)


def _fuzzy_correct(typed: str, accepted: list[str]) -> bool:
    """Eingabe-Prüfung mit Tippfehler-Toleranz (1 Editierschritt erlaubt ab
    4 normalisierten Zeichen, sonst exakt) – wie bei WaniKani, das
    Tippfehler bei längeren Antworten großzügig verzeiht, bei kurzen
    Antworten (wo ein einzelner Fehler die Bedeutung verändert) aber streng
    bleibt."""
    typed_norm = _normalize_answer(typed)
    if not typed_norm:
        return False
    for candidate in accepted:
        cand_norm = _normalize_answer(candidate)
        if not cand_norm:
            continue
        if typed_norm == cand_norm:
            return True
        threshold = 1 if len(cand_norm) >= 4 else 0
        if _levenshtein(typed_norm, cand_norm) <= threshold:
            return True
    return False


def _srs_accepted_answers(row: "models.ReviewState") -> list[str] | None:
    """Akzeptierte Antworten für eine Prüfrichtung, oder `None`, wenn die
    Karte nicht automatisch prüfbar ist (Custom-Karten: freies HTML auf
    beiden Seiten, kein sinnvoller Textvergleich möglich – dort bewertet
    sich der Nutzer wie bei Anki rein selbst, ohne Auto-Check/Vorschlag)."""
    if row.card_type == "custom":
        return None
    if row.card_type == "kana":
        card = read_kana_for_user(row.user_id, row.card_id, row.target_lang)
        if not card:
            return None
        if row.item_type == "reading":
            return [card["reading"]] if card.get("reading") else None
        answers = [a for a in (card.get("meaning"), card.get("meaning_extra")) if a]
        return answers or None
    if row.card_type == "wanikani":
        token = load_settings().get("token")
        try:
            details = kc.card_details_for_ids([int(row.card_id)], sample=not token, token=token)
        except kc.WaniKaniError:
            return None
        detail = details.get(int(row.card_id))
        if not detail:
            return None
        if row.item_type == "reading":
            if detail.get("kind") == "VocabCard":
                return detail.get("readings") or None
            readings = (detail.get("onyomi") or []) + (detail.get("kunyomi") or [])
            return readings or None
        return detail.get("meanings") or None
    return None


@app.post("/api/srs/check")
@login_required
def api_srs_check() -> Any:
    """Getippte Antwort gegen die akzeptierten Antworten prüfen (Fuzzy-
    Match, siehe `_fuzzy_correct()`) und eine Bewertung VORSCHLAGEN – ändert
    NICHTS am FSRS-Lernstand (das passiert erst in `/api/srs/answer`, wenn
    der Nutzer den Vorschlag bestätigt oder überschrieben hat). Bei nicht
    automatisch prüfbaren Karten (Custom) bleibt `correct`/`suggested_rating`
    `None` – der Nutzer bewertet sich dort rein selbst."""
    body = request.get_json(silent=True) or {}
    card_type = str(body.get("card_type", ""))
    card_id = str(body.get("card_id", ""))
    item_type = str(body.get("item_type", ""))
    answer = str(body.get("answer", ""))

    row = _get_review_row(card_type, card_id, item_type)
    if row is None:
        return jsonify({"error": "Karte nicht in der Lernwarteschlange gefunden."}), 404

    accepted = _srs_accepted_answers(row)
    if accepted is None:
        return jsonify({"correct": None, "accepted_answers": [], "suggested_rating": None})

    correct = _fuzzy_correct(answer, accepted)
    return jsonify({
        "correct": correct,
        "accepted_answers": accepted,
        "suggested_rating": "good" if correct else "again",
    })


@app.post("/api/srs/answer")
@login_required
def api_srs_answer() -> Any:
    """Bewertung (`"again"`/`"hard"`/`"good"`/`"easy"`, wie bei Anki) für
    eine Karte übernehmen und den FSRS-Lernstand fortschreiben. Der Nutzer
    hat die Bewertung ggf. gegenüber dem Vorschlag aus `/api/srs/check`
    überschrieben – dieser Endpunkt vertraut der übergebenen Bewertung,
    ohne selbst nochmal zu prüfen."""
    body = request.get_json(silent=True) or {}
    card_type = str(body.get("card_type", ""))
    card_id = str(body.get("card_id", ""))
    item_type = str(body.get("item_type", ""))
    rating = str(body.get("rating", ""))

    row = _get_review_row(card_type, card_id, item_type)
    if row is None:
        return jsonify({"error": "Karte nicht in der Lernwarteschlange gefunden."}), 404

    try:
        updated = srs.review(srs.state_from_row(row), rating)
    except srs.SrsError as exc:
        return jsonify({"error": str(exc)}), 400
    srs.apply_state_to_row(row, updated)
    db.session.commit()

    return jsonify({"ok": True, "due_at": row.due_at.isoformat(), "reps": row.reps, "lapses": row.lapses})


# ---------- Frontend --------------------------------------------------------- #

@app.get("/")
def index() -> Any:
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path: str) -> Any:
    target = (WEB_DIR / path).resolve()
    if not str(target).startswith(str(WEB_DIR)) or not target.is_file():
        abort(404)
    return send_from_directory(WEB_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
