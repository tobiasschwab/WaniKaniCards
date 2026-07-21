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

**Architektur (P2-Refactor, siehe README "Migrationsdisziplin"/"Architektur"):**
Storage-/Domänen-Helfer (Settings, Jobs, eigene/Dictionary-Karten, Render-
Worker) leben in `services.py`; die SRS-, Card- und Job-Endpunkte sind als
eigene Blueprints ausgelagert (`srs_api.py`, `cards_api.py`, `jobs_api.py`,
analog zu `auth.py`) – dieses Modul selbst behält nur noch App-Setup,
Auth-Verdrahtung sowie die verbleibenden "Kern"-Endpunkte (Einstellungen,
Sprachen, Auflisten/Resolve, Text-Modus, Wortliste, Frontend-Auslieferung).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any

from flask import Flask, abort, g, jsonify, request, send_from_directory
from flask_login import current_user, login_required
from werkzeug.middleware.proxy_fix import ProxyFix

import cards_api
import jobs_api
import kanji_cards as kc
import crypto
import models
import pdf_import
import srs_api
from auth import bp as auth_bp
from extensions import db, limiter, login_manager
from languages.registry import SUPPORTED_TARGET_LANGS, get_pack
from services import (
    DATA_DIR,
    _already_exported_ids,
    _coerce_known_id,
    _current_pack,
    _current_target_lang,
    _fetch_username,
    _mark_exported,
    _mask,
    _remove_known_word,
    _require_content_provider,
    _resolve_gemini_model,
    _upsert_known_word,
    list_kana,
    load_known,
    load_known_meta,
    load_settings,
    save_settings,
    set_active_language,
    TARGET_LANGS as _TARGET_LANGS,
)

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
# Einstellungen/bekannte Wörter/eigene-/Dictionary-Karten/Jobs liegen seit
# Phase 2 des Multi-User-Umbaus in der Datenbank (siehe models.py) statt als
# Dateien - nur die generierten PDFs/APKGs selbst bleiben dateibasiert
# (Binärdaten, für die eine Objekt-Storage-Anbindung sinnvoller ist als eine
# DB-Spalte, siehe README-Roadmap "Jobs/Dateien SaaS-tauglich machen").
# `DATA_DIR`/`OUTPUT_DIR` selbst leben in services.py (auch vom Render-Worker
# gebraucht) - hier nur für den SQLite-Fallback der DATABASE_URL gebraucht.
WEB_DIR = HERE / "web"
# Gebündelte Fremdbibliotheken (z. B. WanaKana für die Romaji→Kana-Eingabe im
# Review-Screen). Liegen bewusst außerhalb von web/ (werden auch in den Anki-
# Export eingebettet, siehe anki_export.py) und über eine eigene Route
# ausgeliefert.
VENDOR_DIR = HERE / "vendor"

logger = logging.getLogger(__name__)

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
# haben unterschiedliche Rotationsanforderungen/Formate und sollten
# unabhängig voneinander wechselbar sein.
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", f"sqlite:///{DATA_DIR / 'shiori.db'}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("WKCARDS_SESSION_SECRET", "dev-insecure-change-me")

# ---------- Session-Cookie-Härtung ------------------------------------------ #
#
# HTTPONLY: Session-Cookie ist für JavaScript unsichtbar (Schutz gegen
# Cookie-Diebstahl per XSS) - in Flask ohnehin Default, hier explizit.
# SAMESITE=Lax: das Cookie wird bei Cross-Site-POSTs nicht mitgeschickt
# (CSRF-Milderung); "Lax" statt "Strict", damit ein normaler Link auf die App
# von außen die Sitzung nicht verliert.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# SECURE: Cookie nur über HTTPS senden. Standardmäßig AUS, weil die App in der
# lokalen Entwicklung über http://localhost läuft - dort würde ein Secure-
# Cookie gar nicht gesetzt und der Login schlüge fehl. In Produktion (hinter
# HTTPS-Terminierung) per SESSION_COOKIE_SECURE=1 aktivieren (siehe README/
# docker-compose.yml).
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE") == "1"

# ---------- ProxyFix (Rate-Limiting/Client-IP hinter Reverse-Proxy) --------- #
#
# Hinter einem Reverse-Proxy (nginx/Traefik/Cloud-LB) sieht Flask sonst immer
# die Proxy-IP als Absender - alle Nutzer teilten sich dann EINEN Rate-Limit-
# Bucket (nach 5 Signups/Stunde wäre die Registrierung für ALLE gesperrt,
# siehe auth.py). TRUST_PROXY = Anzahl vertrauenswürdiger Proxy-Hops davor
# (meist "1"). NUR setzen, wenn wirklich ein Proxy davor steht, der
# X-Forwarded-For korrekt setzt - sonst könnte ein Client die Header selbst
# fälschen und das per-IP-Limit umgehen. Default AUS (0), sicher für den
# Direktbetrieb ohne Proxy.
_trusted_proxy_hops = 0
try:
    _trusted_proxy_hops = max(0, int(os.environ.get("TRUST_PROXY", "0")))
except ValueError:
    _trusted_proxy_hops = 0
if _trusted_proxy_hops:
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=_trusted_proxy_hops, x_proto=_trusted_proxy_hops,
        x_host=_trusted_proxy_hops, x_port=_trusted_proxy_hops,
    )

db.init_app(app)
login_manager.init_app(app)


@app.after_request
def _security_headers(response: Any) -> Any:
    """Defensive Standard-Header auf jeder Antwort (auch statische Dateien):
    - nosniff: Browser darf den Content-Type nicht "erraten" (MIME-Sniffing-
      Schutz).
    - X-Frame-Options DENY: die App darf nicht in einen fremden <iframe>
      eingebettet werden (Clickjacking-Schutz) - sie ist eine eigenständige
      SPA, kein Widget.
    - Referrer-Policy: bei Navigation zu externen Zielen nur die Origin (nicht
      den vollen Pfad mit evtl. IDs) als Referrer senden.
    Bewusst KEINE strenge Content-Security-Policy hier: das Frontend nutzt
    Inline-Skripte/-Styles, eine CSP müsste sorgfältig auf das gesamte
    Frontend abgestimmt und getestet werden (eigener Schritt)."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@login_manager.user_loader
def _load_user(user_id: str) -> "models.User | None":
    return db.session.get(models.User, int(user_id))


@login_manager.unauthorized_handler
def _unauthorized() -> Any:
    """JSON statt Redirect: das Frontend ist eine Single-Page-App, kein
    serverseitig gerendertes Login-Formular, auf das umgeleitet werden könnte."""
    return jsonify({"error": "Nicht angemeldet."}), 401


app.register_blueprint(auth_bp)
app.register_blueprint(srs_api.bp)
app.register_blueprint(cards_api.bp)
app.register_blueprint(jobs_api.bp)


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
# REDIS_URL/redis_conn/render_queue leben in services.py (auch vom Render-
# Worker-Modul gebraucht) - hier nur für die Flask-Limiter-Konfiguration
# erneut gelesen (dieselbe Umgebungsvariable, aber eigenständig, damit
# webapp.py services.py nicht wegen einer einzelnen Konstante importieren muss).
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# `limiter` selbst lebt in extensions.py (App-Factory-Pattern: ohne `app=`
# konstruiert), damit auch auth.py eigene @limiter.limit(...)-Dekoratoren auf
# seine Routen anwenden kann, ohne webapp.py importieren zu müssen (Zirkel-
# import). Storage-URI/Default-Limit werden hier per Flask-Config gesetzt,
# bevor `init_app()` läuft - das ist der von Flask-Limiter vorgesehene Weg
# für den Fall, dass Limiter-Instanz und Flask-App in unterschiedlichen
# Modulen entstehen.
app.config["RATELIMIT_STORAGE_URI"] = REDIS_URL
# Großzügiger Default für die meisten (billigen) Endpunkte - teure
# Einzelendpunkte (Rendern, Gemini-Aufrufe, Login/Signup) bekommen unten ihr
# eigenes, strengeres Limit direkt am jeweiligen Endpunkt.
app.config["RATELIMIT_DEFAULT"] = "120 per minute"
# Wenn Redis kurzzeitig nicht erreichbar ist, soll das Rate-Limiting auf einen
# prozesslokalen In-Memory-Zähler ausweichen, statt jeden Request mit einem
# Fehler abzulehnen (Redis-Ausfall darf nicht die ganze App lahmlegen). Der
# In-Memory-Zähler ist pro Worker-Prozess und übersteht keinen Neustart - als
# Notnagel für einen kurzen Redis-Ausfall aber völlig ausreichend; sobald
# Redis zurück ist, zählt der Limiter wieder zentral.
app.config["RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"] = True
limiter.init_app(app)


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


_KNOWN_META_FIELDS = ("characters", "meaning", "kind", "level", "source")


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
        incoming_defaults = dict(body["defaults"])
        # Tageslimits müssen positive Ganzzahlen sein - ungültige Werte hier
        # abzuweisen statt sie blind zu übernehmen verhindert, dass sie erst
        # später beim Abruf der Review-Queue (api_srs_queue) auffallen.
        for key in ("srs_new_per_day", "srs_reviews_per_day"):
            if key in incoming_defaults:
                try:
                    incoming_defaults[key] = max(0, int(incoming_defaults[key]))
                except (TypeError, ValueError):
                    return jsonify({"error": f"'{key}' muss eine ganze Zahl sein."}), 400
        s["defaults"] = {**s["defaults"], **incoming_defaults}
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
    available_models = kc.gemini_client.list_models(key)
    if available_models is None:
        return jsonify({"error": "Modell-Liste konnte nicht abgerufen werden (ungültiger Key oder Netzwerkfehler)."}), 502
    if not available_models:
        return jsonify({"error": "Keine passenden Modelle gefunden."}), 502
    return jsonify({"models": available_models, "default": kc.gemini_client.DEFAULT_MODEL})


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


# ---------- Frontend --------------------------------------------------------- #

@app.get("/")
def index() -> Any:
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/vendor/<path:path>")
def vendor_files(path: str) -> Any:
    """Gebündelte Fremdbibliotheken (z. B. WanaKana) ausliefern – gleiche
    Path-Traversal-Härtung wie `static_files()` (nur Dateien unterhalb von
    VENDOR_DIR). Eigene Route statt web/, weil dieselben Dateien auch in den
    Anki-Export eingebettet werden und deshalb außerhalb von web/ liegen."""
    target = (VENDOR_DIR / path).resolve()
    if not target.is_relative_to(VENDOR_DIR.resolve()) or not target.is_file():
        abort(404)
    return send_from_directory(VENDOR_DIR, path)


@app.get("/<path:path>")
def static_files(path: str) -> Any:
    # `is_relative_to` statt `startswith(str(WEB_DIR))`: Ein reiner
    # String-Präfix-Vergleich hätte auch ein Verzeichnis wie "web-secret"
    # (Geschwister von WEB_DIR, gleicher String-Präfix) fälschlich als
    # "innerhalb von WEB_DIR" durchgehen lassen.
    target = (WEB_DIR / path).resolve()
    if not target.is_relative_to(WEB_DIR.resolve()) or not target.is_file():
        abort(404)
    return send_from_directory(WEB_DIR, path)


if __name__ == "__main__":
    # In Produktion läuft die App über gunicorn (siehe docker-entrypoint.sh),
    # dieser Block wird dort nie erreicht. debug=True nur bei explizit
    # gesetztem FLASK_DEBUG statt hartcodiert, damit ein versehentlicher
    # direkter Aufruf (`python webapp.py`) nicht automatisch den Werkzeug-
    # Debugger (interaktive Traceback-Konsole mit Code-Ausführung) aktiviert.
    app.run(
        host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
