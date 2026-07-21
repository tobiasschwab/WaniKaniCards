#!/usr/bin/env python3
"""services.py – geteilte Storage-/Domänen-Hilfsfunktionen (Settings, Jobs,
eigene/Dictionary-Karten, Render-Worker) für die API-Blueprints.

Ausgelagert aus webapp.py (siehe README "Architektur", P2 "webapp.py in
Blueprints aufteilen"): `webapp.py` registriert die Blueprints `srs_api.py`/
`cards_api.py`/`jobs_api.py`, die wiederum diese Funktionen brauchen – ein
Import von webapp.py selbst aus den Blueprints würde einen Zirkelimport
erzeugen (webapp.py importiert die Blueprints ja gerade, um sie zu
registrieren). Dieses Modul enthält deshalb bewusst KEINE Flask-Routen, nur
die von ihnen genutzte Logik, und wird sowohl von webapp.py selbst als auch
von den drei Blueprints importiert (eine Richtung, kein Zyklus).
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import redis
from flask import jsonify
from flask_login import current_user
from rq import Queue
from sqlalchemy.exc import IntegrityError

import anki_export as ae
import crypto
import kanji_cards as kc
import models
import storage
from extensions import db
from languages.registry import get_pack

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WKCARDS_DATA", HERE / "data")).resolve()
OUTPUT_DIR = DATA_DIR / "output"
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
        # Tageslimits für den Vokabeltrainer (wie Anki-Deck-Optionen) - über
        # den bestehenden generischen "defaults"-Mechanismus einstellbar
        # (POST /api/settings {"defaults": {"srs_new_per_day": ...}}), kein
        # eigenes Schema/Endpunkt nötig (siehe api_srs_queue() in srs_api.py).
        "srs_new_per_day": 20,
        "srs_reviews_per_day": 200,
    },
}

# DeepL-Zielsprachen zur Auswahl in den Einstellungen (Teilmenge der von
# DeepL unterstützten Sprachen – https://developers.deepl.com/docs/resources/supported-languages,
# nur die "einfachen" Codes ohne Regionalvarianten wie EN-US/PT-BR, die für
# diesen Anwendungsfall (kurze Vokabel-/Satzübersetzungen) nicht relevant sind).
TARGET_LANGS = (
    "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FI", "FR", "HU", "ID",
    "IT", "JA", "KO", "LT", "LV", "NB", "NL", "PL", "PT", "RO", "RU", "SK",
    "SL", "SV", "TR", "UK", "ZH",
)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_conn = redis.from_url(REDIS_URL)
render_queue = Queue("renders", connection=redis_conn)

# Wie viele gleichzeitig laufende/wartende Render-Jobs ein einzelner Nutzer
# haben darf, bevor /api/render neue Anfragen ablehnt - verhindert, dass ein
# Nutzer die komplette Worker-Kapazität für sich beansprucht (siehe
# jobs_api.api_render()). WaniKanis eigenes Rate-Limit ist schon pro Token
# isoliert, die EIGENE Serverkapazität (Worker-Prozesse) aber nicht.
MAX_CONCURRENT_JOBS_PER_USER = 3


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


def _require_content_provider() -> Any | None:
    """`None`, wenn die aktuell aktive Zielsprache eine externe Lernstufen-
    Quelle wie WaniKani hat - sonst eine fertige 400-JSON-Response, die der
    Aufrufer direkt zurückgeben kann. Nur Japanisch hat aktuell einen
    `LanguagePack` mit `has_content_provider=True` (siehe languages/japanese.py)."""
    if _current_pack().has_content_provider:
        return None
    return jsonify({"error": "Diese Funktion ist nur für Japanisch (WaniKani) verfügbar."}), 400


# ---------- Bekannte Wörter (pro Nutzer, Postgres/SQLite statt known.json) -- #

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
    (siehe api_post_settings() in webapp.py, dieselbe Validierung)."""
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


def _delete_srs_rows_for_card(user_id: int, card_type: str, card_id: str) -> None:
    """Räumt `ReviewState`/`ReviewLog`-Zeilen einer gelöschten Karte weg.
    Ohne das bliebe der SRS-Lernstand als Datenleiche liegen (`card_id`
    zeigt danach ins Leere) und würde in `/api/srs/queue` als "fällig"
    weitergeführt, obwohl die Karte gar nicht mehr existiert - `/api/srs/
    check`+`/answer` würden für sie außerdem ins Leere greifen (kein Front/
    Back mehr ladbar). `card_id` ist über alle Zielsprachen hinweg eindeutig,
    daher genügt der Filter ohne `target_lang`."""
    models.ReviewState.query.filter_by(user_id=user_id, card_type=card_type, card_id=card_id).delete()
    models.ReviewLog.query.filter_by(user_id=user_id, card_type=card_type, card_id=card_id).delete()


def delete_all_user_data(user_id: int) -> None:
    """Sämtliche Daten eines Nutzers löschen – für die Konto-Löschung
    (DELETE /api/auth/account). Die Fremdschlüssel auf `users.id` haben KEIN
    `ON DELETE CASCADE`, deshalb müssen alle abhängigen Zeilen explizit und
    portabel (SQLite/Postgres) entfernt werden, bevor die User-Zeile selbst
    gelöscht werden kann – sonst schlüge der Delete unter Postgres mit einer
    FK-Verletzung fehl (unter SQLite blieben die Zeilen verwaist).

    Die auf Disk/S3 liegenden Job-Ausgabedateien (PDF/APKG) werden ebenfalls
    weggeräumt, damit kein Nutzer-Inhalt zurückbleibt. Das eigentliche Löschen
    der `User`-Zeile bleibt Aufgabe des Aufrufers (auth.py), inkl. `commit()`."""
    for job in models.Job.query.filter_by(user_id=user_id).all():
        storage.delete_output(OUTPUT_DIR, f"{job.id}.pdf")
        storage.delete_output(OUTPUT_DIR, f"{job.id}.apkg")
    for model in (
        models.ReviewLog, models.ReviewState, models.Job, models.KanaCard,
        models.CustomCard, models.KnownWord, models.UserLanguageSecrets,
        models.UserSettings,
    ):
        model.query.filter_by(user_id=user_id).delete()


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
    nötig (anders als beim früheren `threading.Thread`-Ansatz).

    `app` wird bewusst ERST HIER (zur Laufzeit) aus webapp.py importiert,
    nicht am Modulanfang: webapp.py registriert Blueprints, die dieses Modul
    importieren, ein Import von webapp.py auf Modulebene wäre also ein
    Zirkelimport. Zur Ausführungszeit dieser Funktion (als RQ-Job, lange
    nach dem Start) ist webapp.py garantiert schon vollständig geladen."""
    from webapp import app

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
