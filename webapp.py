#!/usr/bin/env python3
"""Web-Frontend für den WaniKani-Karten-Generator.

Ablauf: Quelle *auflisten* (Level, Suche oder Komposition) → Elemente in einer
Tabelle *auswählen* → ausgewählte Karten als **ein PDF** rendern. Keine
Datenbank – Einstellungen (inkl. API-Token), Jobs und PDFs liegen als Dateien
unter ``WKCARDS_DATA`` (Default: ``./data``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import anki_export as ae
import kanji_cards as kc

# INFO-Logs (u. a. Gemini-Requests: Start, Dauer, Fehlerursache) landen sonst
# im Nirwana, weil Python ohne explizite Konfiguration nur WARNING+ ausgibt –
# gunicorn/Flask fangen stdout ab, das reicht für `docker logs`.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WKCARDS_DATA", HERE / "data")).resolve()
SETTINGS_FILE = DATA_DIR / "settings.json"
KNOWN_FILE = DATA_DIR / "known.json"
KNOWN_META_FILE = DATA_DIR / "known_meta.json"
OUTPUT_DIR = DATA_DIR / "output"
JOBS_DIR = DATA_DIR / "jobs"
CUSTOM_DIR = DATA_DIR / "customcards"
KANA_DIR = DATA_DIR / "kanacards"
WEB_DIR = HERE / "web"

for _d in (DATA_DIR, OUTPUT_DIR, JOBS_DIR, CUSTOM_DIR, KANA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_export_lock = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "token": "",
    "username": "",
    "deepl_key": "",
    "gemini_key": "",
    "gemini_model": kc.gemini_client.DEFAULT_MODEL,
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

app = Flask(__name__, static_folder=None)


# ---------- Einstellungen ---------------------------------------------------- #

def load_settings() -> dict[str, Any]:
    if SETTINGS_FILE.is_file():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    else:
        data = {}
    merged = {**DEFAULT_SETTINGS, **data}
    merged["defaults"] = {**DEFAULT_SETTINGS["defaults"], **(data.get("defaults") or {})}
    return merged


def save_settings(data: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_known() -> set[int | str]:
    """IDs, die manuell als „bekannt" markiert wurden (Text-Modus) – unabhängig
    vom Export-/Karten-Verlauf, z. B. für Wörter, die man von woanders schon
    kann. WaniKani-Subject-IDs bleiben int, Dictionary-Wörter (`kana_…`) sind
    str – beide zusammen in derselben Datei, da beide „bekannt" bedeuten."""
    if not KNOWN_FILE.is_file():
        return set()
    try:
        data = json.loads(KNOWN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("ids") if isinstance(data, dict) else None
    out: set[int | str] = set()
    for i in ids or []:
        if isinstance(i, bool):
            continue
        if isinstance(i, int) or (isinstance(i, str) and i):
            out.add(i)
    return out


def save_known(ids: set[int | str]) -> None:
    KNOWN_FILE.write_text(
        json.dumps({"ids": sorted(ids, key=str)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_known_meta() -> dict[str, dict[str, Any]]:
    """Anzeige-Metadaten (characters/meaning/kind/level/source) zu manuell
    bekannt markierten IDs – nötig für die Wortliste, u. a. weil rein manuelle
    Einträge (`manual_…`) gar keine Karte/keinen WaniKani-Subject haben, aus
    dem sich die Anzeige sonst herleiten ließe."""
    if not KNOWN_META_FILE.is_file():
        return {}
    try:
        data = json.loads(KNOWN_META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_known_meta(meta: dict[str, dict[str, Any]]) -> None:
    KNOWN_META_FILE.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _mask(token: str) -> str:
    return (("•" * max(0, len(token) - 4)) + token[-4:]) if token else ""


def _apply_token_env() -> str:
    token = load_settings().get("token", "")
    os.environ["WANIKANI_API_TOKEN"] = token or ""
    return token


def _fetch_username(token: str) -> str:
    """Benutzernamen zum Token holen (best-effort, still bei Fehler)."""
    if not token:
        return ""
    try:
        data = kc.WaniKaniClient(token, use_cache=False)._request("user")  # noqa: SLF001
        return (data.get("data") or {}).get("username", "") or ""
    except kc.WaniKaniError:
        return ""


# ---------- Jobs (ein JSON pro Job) ----------------------------------------- #

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def write_job(job: dict[str, Any]) -> None:
    _job_path(job["id"]).write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_job(job_id: str) -> dict[str, Any] | None:
    p = _job_path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_jobs() -> list[dict[str, Any]]:
    jobs = []
    for p in JOBS_DIR.glob("*.json"):
        try:
            jobs.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs


def _already_exported_ids() -> set[int]:
    """Subject-IDs, die schon einmal erfolgreich exportiert wurden (PDF oder Anki).

    Liest den Job-Verlauf statt einer eigenen Datenbank – ein Job ist bereits
    die vollständige Aufzeichnung, was wann gerendert wurde.
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


# ---------- Eigene Karten (customcards/) ------------------------------------ #

def _custom_path(cid: str) -> Path:
    safe = "".join(c for c in cid if c.isalnum())
    return CUSTOM_DIR / f"{safe}.json"


def read_custom(cid: str) -> dict[str, Any] | None:
    p = _custom_path(cid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_custom(card: dict[str, Any]) -> None:
    _custom_path(card["id"]).write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_customs() -> list[dict[str, Any]]:
    out = []
    for p in CUSTOM_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return out


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


# ---------- Dictionary-Karten (kanacards/) – Text-Modus, kein WaniKani-Treffer #

def _kana_path(kid: str) -> Path:
    safe = "".join(c for c in kid if c.isalnum() or c == "_")
    return KANA_DIR / f"{safe}.json"


def read_kana(kid: str) -> dict[str, Any] | None:
    p = _kana_path(kid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_kana(card: dict[str, Any]) -> None:
    _kana_path(card["id"]).write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_kana() -> list[dict[str, Any]]:
    out = []
    for p in KANA_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return out


def _kana_descriptor(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card["id"],
        "object": "dictionary",
        "kind": "Dict",
        "characters": card.get("word", ""),
        "meaning": card.get("meaning", ""),
        "meaning_extra": card.get("meaning_extra"),
        "level": None,
        "has_image": False,
    }


# ---------- Render-Worker ---------------------------------------------------- #

def _build_mixed_deck(p: dict[str, Any]) -> list[Any]:
    """Kombinierten Stapel aus WaniKani-Subjects, eigenen und Dictionary-
    Karten bauen – alle drei Quellen können in einem Export landen (z. B.
    Text-Modus: WaniKani-Vokabel + Dictionary-Wort zusammen ausgewählt)."""
    deck: list[Any] = []
    if p.get("subject_ids"):
        deck.extend(
            kc.resolve_subject_deck(
                p["subject_ids"],
                use_cache=p.get("use_cache", True),
                sample=p.get("sample", False),
                sentence_overrides=p.get("sentence_overrides"),
            )
        )
    if p.get("custom_ids"):
        datas = [read_custom(cid) for cid in p["custom_ids"]]
        deck.extend(kc.build_custom_card(d) for d in datas if d)
    if p.get("kana_ids"):
        datas = [read_kana(kid) for kid in p["kana_ids"]]
        deck.extend(kc.build_kana_card_from_dict(d) for d in datas if d)
    return deck


def _run_render(job_id: str) -> None:
    job = read_job(job_id)
    if job is None:
        return
    p = job["params"]
    with _export_lock:
        job = read_job(job_id) or job
        job["status"] = "running"
        job["started_at"] = _now()
        write_job(job)

        anki = p.get("format") == "anki"
        out_path = OUTPUT_DIR / (f"{job_id}.apkg" if anki else f"{job_id}.pdf")
        try:
            # Token nur nötig, wenn WaniKani-Subjects (keine reinen Custom-/
            # Dictionary-Karten, kein Demo-Modus) gerendert werden.
            needs_token = bool(p.get("subject_ids")) and not p.get("sample")
            if needs_token and not _apply_token_env():
                raise kc.WaniKaniError(
                    "Kein API-Token gespeichert. Bitte in den Einstellungen setzen."
                )
            _apply_token_env()

            deck = _build_mixed_deck(p)
            if not deck:
                raise kc.WaniKaniError("Keine Karten für die Auswahl gefunden.")

            if anki:
                deck_name = job.get("title") or "Shiori"
                _, n = ae.export_deck(deck, out_path, deck_name=deck_name)
            else:
                username = load_settings().get("username", "")
                if not p.get("sample") and not username:
                    username = ""  # kein Token → kein Name
                kc.render_deck(
                    deck,
                    out_path,
                    layout=p.get("layout", "a6"),
                    paper=p.get("paper", "a4"),
                    duplex=p.get("duplex", "long-edge"),
                    cut_marks=p.get("cut_marks", True),
                    hole=p.get("hole", False),
                    username=username,
                )
                n = len(deck)
            job["status"] = "done"
            job["n_cards"] = n
            job["filename"] = out_path.name
        except kc.WaniKaniError as exc:
            job["status"], job["error"] = "error", str(exc)
        except Exception as exc:  # noqa: BLE001
            job["status"], job["error"] = "error", f"Unerwarteter Fehler: {exc}"
        finally:
            job["finished_at"] = _now()
            write_job(job)


# ---------- API: Konfig & Einstellungen ------------------------------------- #

@app.get("/api/config")
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
            "defaults": s["defaults"],
        }
    )


@app.post("/api/settings")
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
    if isinstance(body.get("defaults"), dict):
        s["defaults"] = {**s["defaults"], **body["defaults"]}
    save_settings(s)
    return jsonify({"ok": True, "token_set": bool(s.get("token")), "username": s.get("username", "")})


@app.post("/api/gemini/models")
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


@app.post("/api/test-token")
def api_test_token() -> Any:
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
def api_resolve() -> Any:
    """Quelle in eine Kartenliste (Tabelle) auflösen.

    body.mode: "level" | "search" | "compose"
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    sample = bool(body.get("sample"))
    try:
        if not sample:
            _apply_token_env()
        if mode == "level":
            level = int(body.get("level"))
            deck_types = body.get("types") or [body.get("type", "kanji")]
            cards = kc.resolve_level(level, deck_types, sample=sample)
        elif mode == "search":
            cards = kc.search_subjects(str(body.get("q", "")), sample=sample)
        elif mode == "compose":
            ids = body.get("subject_ids") or []
            cards = kc.resolve_composition(ids, sample=sample)
        else:
            return jsonify({"error": "Unbekannter Modus."}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Eingabe."}), 400
    except kc.WaniKaniError as exc:
        return jsonify({"error": str(exc)}), 502
    cards = _mark_exported(cards)
    return jsonify({"cards": cards})


# ---------- API: Text-Modus (lemmatisieren, annotieren, bekannt markieren) -- #

@app.post("/api/text-annotate")
def api_text_annotate() -> Any:
    """Text lemmatisieren und zeilenweise annotieren (kein Auto-Hinzufügen).

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

    `use_gemini` (bool): Sätze zusätzlich per Gemini analysieren (bessere
    Wortgrenzen, grammatikalische Funktion, Grammatik-Erklärung + deutsche
    Übersetzung pro Satz) – braucht einen in den Einstellungen hinterlegten
    Gemini-Key, sonst Fehler. Wörter ohne WaniKani-/Dictionary-Treffer, die
    Gemini aber grammatikalisch erklären kann (`source: "gemini"`), haben
    `id: null` und fließen NICHT in `known`/`total` ein (keine Vokabel zum
    Lernen, nur eine Grammatik-Info).
    """
    body = request.get_json(silent=True) or {}
    text = str(body.get("text", ""))
    sample = bool(body.get("sample"))
    use_gemini = bool(body.get("use_gemini"))
    gemini_key = None
    gemini_model = kc.gemini_client.DEFAULT_MODEL
    if use_gemini:
        s = load_settings()
        gemini_key = s.get("gemini_key") or None
        stored_model = s.get("gemini_model")
        if isinstance(stored_model, str) and stored_model.strip().startswith("gemini-"):
            gemini_model = stored_model.strip()
        elif stored_model:
            # Kein gültiger Gemini-Modellname (z. B. leere/kaputte Einstellung) ->
            # auf den aktuellen Default ausweichen statt an Google zu senden.
            logger.warning(
                "Gespeichertes Gemini-Modell %r ist ungültig, verwende Default %r.",
                stored_model, gemini_model,
            )
        if not gemini_key:
            return jsonify({"error": "Kein Gemini-API-Key in den Einstellungen hinterlegt."}), 400
    logger.info(
        "text-annotate: %d Zeichen, use_gemini=%s, sample=%s …", len(text), use_gemini, sample,
    )
    t0 = time.monotonic()
    try:
        if not sample:
            _apply_token_env()
        lines = kc.annotate_text(
            text, sample=sample, gemini_key=gemini_key, gemini_model=gemini_model
        )
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
            if seg.get("id") is None:
                seg["manually_known"] = False
                seg["ready"] = False
                seg["status"] = "info"
                seg["known"] = False
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


def _coerce_known_id(raw: str) -> int | str:
    """WaniKani-Subject-IDs sind rein numerisch -> int; Dictionary-Wörter
    (`kana_…`) bleiben str."""
    return int(raw) if raw.isdigit() else raw


_KNOWN_META_FIELDS = ("characters", "meaning", "kind", "level", "source")


@app.post("/api/known/<string:word_id>")
def api_mark_known(word_id: str) -> Any:
    coerced = _coerce_known_id(word_id)
    ids = load_known()
    ids.add(coerced)
    save_known(ids)
    body = request.get_json(silent=True) or {}
    fields = {k: body[k] for k in _KNOWN_META_FIELDS if k in body}
    if fields:
        meta = load_known_meta()
        meta[str(coerced)] = {**meta.get(str(coerced), {}), **fields}
        save_known_meta(meta)
    return jsonify({"ok": True, "id": coerced, "known": True})


@app.delete("/api/known/<string:word_id>")
def api_unmark_known(word_id: str) -> Any:
    coerced = _coerce_known_id(word_id)
    ids = load_known()
    ids.discard(coerced)
    save_known(ids)
    meta = load_known_meta()
    if str(coerced) in meta:
        del meta[str(coerced)]
        save_known_meta(meta)
    return jsonify({"ok": True, "id": coerced, "known": False})


# ---------- API: Wortliste (alle bekannten Wörter, gefiltert/entfernbar) ---- #

@app.get("/api/wortliste")
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
            if not sample:
                _apply_token_env()
            by_id = {d["id"]: d for d in kc.resolve_subject_ids(wk_ids, sample=sample)}
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

    dict_ids = sorted(set(kana_records) | {i for i in manual if isinstance(i, str) and i.startswith("kana_")})
    for wid in dict_ids:
        card = kana_records.get(wid) or {}
        m = meta.get(wid, {})
        entries.append(
            {
                "id": wid,
                "source": "dictionary",
                "characters": card.get("word") or m.get("characters") or wid,
                "meaning": card.get("meaning") or m.get("meaning", ""),
                "meaning_extra": card.get("meaning_extra"),
                "kind": "Dict",
                "level": None,
                "card_created": wid in kana_records,
                "manually_known": wid in manual,
                "removable": True,
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
def api_wortliste_add_manual() -> Any:
    """Rein manuellen Eintrag (ohne WaniKani-Subject/Dictionary-Treffer) zur
    Wortliste hinzufügen – z. B. ein Wort, das man von woanders schon kann."""
    body = request.get_json(silent=True) or {}
    characters = str(body.get("characters", "")).strip()
    meaning = str(body.get("meaning", "")).strip()
    if not characters:
        return jsonify({"error": "Bitte ein Wort angeben."}), 400
    wid = "manual_" + hashlib.sha1(characters.encode("utf-8")).hexdigest()[:16]
    ids = load_known()
    ids.add(wid)
    save_known(ids)
    meta = load_known_meta()
    meta[wid] = {"characters": characters, "meaning": meaning, "kind": "Manuell", "level": None, "source": "manual"}
    save_known_meta(meta)
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

    sentence_overrides = body.get("sentence_overrides")
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
    }
    n = len(params["custom_ids"]) + len(params["subject_ids"]) + len(params["kana_ids"])
    title = body.get("title") or f"{n} Karten"

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "title": title,
        "params": params,
        "status": "queued",
        "created_at": _now(),
    }
    write_job(job)
    threading.Thread(target=_run_render, args=(job_id,), daemon=True).start()
    return jsonify(job), 202


# ---------- API: Jobs -------------------------------------------------------- #

@app.get("/api/customcards")
def api_customcards() -> Any:
    return jsonify([_custom_descriptor(c) for c in list_customs()])


@app.get("/api/customcards/<cid>")
def api_customcard(cid: str) -> Any:
    card = read_custom(cid)
    if card is None:
        abort(404)
    return jsonify(card)


@app.post("/api/customcards")
def api_save_customcard() -> Any:
    body = request.get_json(silent=True) or {}
    cid = body.get("id") or uuid.uuid4().hex[:12]
    card = {
        "id": cid,
        "front_html": str(body.get("front_html", "")),
        "back_html": str(body.get("back_html", "")),
        "tags": [str(t).strip() for t in (body.get("tags") or []) if str(t).strip()],
        "updated_at": _now(),
    }
    write_custom(card)
    return jsonify(card)


@app.delete("/api/customcards/<cid>")
def api_delete_customcard(cid: str) -> Any:
    if read_custom(cid) is None:
        abort(404)
    _custom_path(cid).unlink(missing_ok=True)
    return jsonify({"ok": True})


# ---------- API: Dictionary-Karten (kanacards) ------------------------------- #

@app.get("/api/kanacards")
def api_kanacards() -> Any:
    return jsonify([_kana_descriptor(c) for c in list_kana()])


@app.post("/api/kanacards")
def api_create_kanacard() -> Any:
    """Wort (aus dem Text-Modus, ohne WaniKani-Treffer) als Dictionary-Karte
    anlegen. Bedeutung kommt aus JMdict; Satzübersetzung optional per DeepL,
    wenn ein Key hinterlegt ist (sonst bleibt die Karte trotzdem gültig)."""
    body = request.get_json(silent=True) or {}
    word = str(body.get("word", "")).strip()
    sentence_raw = body.get("sentence")
    sentence = sentence_raw.strip() if isinstance(sentence_raw, str) and sentence_raw.strip() else None
    if not word:
        return jsonify({"error": "Kein Wort angegeben."}), 400
    deepl_key = load_settings().get("deepl_key") or None
    card_obj = kc.build_kana_card(word, sentence, deepl_key=deepl_key)
    if card_obj is None:
        return jsonify({"error": f"„{word}“ wurde im Wörterbuch nicht gefunden."}), 404
    record = {
        "id": card_obj.card_id,
        "word": card_obj.word,
        "kanji_hint": card_obj.kanji_hint,
        "meaning": card_obj.meaning,
        "meaning_extra": card_obj.meaning_extra,
        "sentence_ja": card_obj.sentence_ja,
        "sentence_translation": card_obj.sentence_translation,
        "tags": card_obj.tags,
        "updated_at": _now(),
    }
    write_kana(record)
    return jsonify(_kana_descriptor(record))


@app.delete("/api/kanacards/<kid>")
def api_delete_kanacard(kid: str) -> Any:
    if read_kana(kid) is None:
        abort(404)
    _kana_path(kid).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.get("/api/jobs")
def api_jobs() -> Any:
    return jsonify(list_jobs())


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str) -> Any:
    job = read_job(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.delete("/api/jobs/<job_id>")
def api_delete_job(job_id: str) -> Any:
    if read_job(job_id) is None:
        abort(404)
    (OUTPUT_DIR / f"{job_id}.pdf").unlink(missing_ok=True)
    (OUTPUT_DIR / f"{job_id}.apkg").unlink(missing_ok=True)
    _job_path(job_id).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.get("/api/jobs/<job_id>/pdf")
def api_job_pdf(job_id: str) -> Any:
    job = read_job(job_id)
    if job is None or job.get("status") != "done":
        abort(404)
    pdf = OUTPUT_DIR / f"{job_id}.pdf"
    if not pdf.is_file():
        abort(404)
    download = request.args.get("download") == "1"
    safe = "".join(c for c in job.get("title", "cards") if c.isalnum() or c in " -_")
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=download,
        download_name=f"wanikani-{safe.strip() or 'cards'}.pdf",
        max_age=0,
    )


@app.get("/api/jobs/<job_id>/apkg")
def api_job_apkg(job_id: str) -> Any:
    job = read_job(job_id)
    if job is None or job.get("status") != "done":
        abort(404)
    apkg = OUTPUT_DIR / f"{job_id}.apkg"
    if not apkg.is_file():
        abort(404)
    download = request.args.get("download") == "1"
    safe = "".join(c for c in job.get("title", "cards") if c.isalnum() or c in " -_")
    return send_file(
        apkg,
        mimetype="application/octet-stream",
        as_attachment=download,
        download_name=f"wanikani-{safe.strip() or 'cards'}.apkg",
        max_age=0,
    )


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
