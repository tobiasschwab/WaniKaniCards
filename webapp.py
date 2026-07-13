#!/usr/bin/env python3
"""Web-Frontend für den WaniKani-Karten-Generator.

Leichtgewichtige Flask-App ohne Datenbank: Einstellungen (inkl. API-Token),
Export-Jobs und die erzeugten PDFs werden als Dateien unter ``WKCARDS_DATA``
(Default: ``./data``) abgelegt. Dieselbe Export-Logik wie das CLI (`kanji_cards`).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import kanji_cards as kc

# --------------------------------------------------------------------------- #
# Pfade & Verzeichnisse (alles im Datei-Volume)
# --------------------------------------------------------------------------- #

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WKCARDS_DATA", HERE / "data")).resolve()
SETTINGS_FILE = DATA_DIR / "settings.json"
OUTPUT_DIR = DATA_DIR / "output"
JOBS_DIR = DATA_DIR / "jobs"
WEB_DIR = HERE / "web"

for _d in (DATA_DIR, OUTPUT_DIR, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Exporte werden serialisiert (Env-Token-Sicherheit + CPU schonen).
_export_lock = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "token": "",
    "defaults": {
        "level": 1,
        "type": "kanji",
        "layout": "a4-4up",
        "paper": "a4",
        "duplex": "long-edge",
        "cover": True,
        "cut_marks": True,
    },
}

app = Flask(__name__, static_folder=None)


# --------------------------------------------------------------------------- #
# Einstellungen (settings.json)
# --------------------------------------------------------------------------- #

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


def _mask(token: str) -> str:
    if not token:
        return ""
    return ("•" * max(0, len(token) - 4)) + token[-4:]


# --------------------------------------------------------------------------- #
# Job-Speicher (ein JSON pro Job)
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Export-Worker
# --------------------------------------------------------------------------- #

def _run_export(job_id: str) -> None:
    job = read_job(job_id)
    if job is None:
        return
    params = job["params"]
    with _export_lock:
        job = read_job(job_id) or job
        job["status"] = "running"
        job["started_at"] = _now()
        write_job(job)

        settings = load_settings()
        token = settings.get("token", "")
        pdf_path = OUTPUT_DIR / f"{job_id}.pdf"
        try:
            if not params.get("sample") and not token:
                raise kc.WaniKaniError(
                    "Kein API-Token gespeichert. Bitte in den Einstellungen setzen."
                )
            os.environ["WANIKANI_API_TOKEN"] = token or ""
            deck = kc.build_deck(
                params.get("level"),
                params.get("type", "kanji"),
                use_cache=params.get("use_cache", True),
                with_cover=params.get("cover", True),
                sample=params.get("sample", False),
            )
            if not deck:
                raise kc.WaniKaniError("Keine Karten für diese Auswahl gefunden.")
            kc.render_deck(
                deck,
                pdf_path,
                layout=params.get("layout", "a4-4up"),
                paper=params.get("paper", "a4"),
                duplex=params.get("duplex", "long-edge"),
                cut_marks=params.get("cut_marks", True),
            )
            job["status"] = "done"
            job["n_cards"] = len(deck)
            job["filename"] = pdf_path.name
        except kc.WaniKaniError as exc:
            job["status"] = "error"
            job["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 – Fehler sichtbar machen
            job["status"] = "error"
            job["error"] = f"Unerwarteter Fehler: {exc}"
        finally:
            job["finished_at"] = _now()
            write_job(job)


# --------------------------------------------------------------------------- #
# API-Routen
# --------------------------------------------------------------------------- #

@app.get("/api/config")
def api_config() -> Any:
    return jsonify(
        {
            "layouts": list(kc.LAYOUTS),
            "types": ["kanji", "radicals"],
            "papers": ["a4", "letter"],
            "duplex": ["long-edge", "short-edge"],
            "defaults": load_settings()["defaults"],
        }
    )


@app.get("/api/settings")
def api_get_settings() -> Any:
    s = load_settings()
    token = s.get("token", "")
    return jsonify(
        {
            "token_set": bool(token),
            "token_hint": _mask(token),
            "defaults": s["defaults"],
        }
    )


@app.post("/api/settings")
def api_post_settings() -> Any:
    body = request.get_json(silent=True) or {}
    s = load_settings()
    if "token" in body and isinstance(body["token"], str):
        s["token"] = body["token"].strip()
    if isinstance(body.get("defaults"), dict):
        s["defaults"] = {**s["defaults"], **body["defaults"]}
    save_settings(s)
    return jsonify({"ok": True, "token_set": bool(s.get("token"))})


@app.post("/api/test-token")
def api_test_token() -> Any:
    """Token gegen die WaniKani-API prüfen (GET /user)."""
    token = (request.get_json(silent=True) or {}).get("token")
    if not token:
        token = load_settings().get("token", "")
    if not token:
        return jsonify({"ok": False, "error": "Kein Token angegeben."}), 400
    try:
        client = kc.WaniKaniClient(token, use_cache=False)
        data = client._request("user")  # noqa: SLF001 – interner Helfer genügt
        username = (data.get("data") or {}).get("username", "?")
        level = (data.get("data") or {}).get("level")
        return jsonify({"ok": True, "username": username, "level": level})
    except kc.WaniKaniError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/export")
def api_export() -> Any:
    body = request.get_json(silent=True) or {}
    sample = bool(body.get("sample"))

    level = body.get("level")
    if not sample:
        try:
            level = int(level)
        except (TypeError, ValueError):
            return jsonify({"error": "Bitte ein gültiges Level (1–60) angeben."}), 400
        if not 1 <= level <= 60:
            return jsonify({"error": "Level muss zwischen 1 und 60 liegen."}), 400

    deck_type = body.get("type", "kanji")
    if deck_type not in ("kanji", "radicals"):
        return jsonify({"error": "Ungültiger Typ."}), 400
    layout = body.get("layout", "a4-4up")
    if layout not in kc.LAYOUTS:
        return jsonify({"error": "Ungültiges Layout."}), 400

    params = {
        "level": level,
        "type": deck_type,
        "layout": layout,
        "paper": body.get("paper", "a4"),
        "duplex": body.get("duplex", "long-edge"),
        "cover": bool(body.get("cover", True)),
        "cut_marks": bool(body.get("cut_marks", True)),
        "use_cache": not bool(body.get("no_cache", False)),
        "sample": sample,
    }
    kind = "Radicals" if deck_type == "radicals" else "Kanji"
    title = f"{'Demo' if sample else 'Level ' + str(level)} · {kind}"

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "title": title,
        "params": params,
        "status": "queued",
        "created_at": _now(),
    }
    write_job(job)
    threading.Thread(target=_run_export, args=(job_id,), daemon=True).start()
    return jsonify(job), 202


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
    job = read_job(job_id)
    if job is None:
        abort(404)
    pdf = OUTPUT_DIR / f"{job_id}.pdf"
    pdf.unlink(missing_ok=True)
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
    fname = f"wanikani-{job['title'].replace(' · ', '-').replace(' ', '')}.pdf"
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=download,
        download_name=fname,
        max_age=0,
    )


# --------------------------------------------------------------------------- #
# Frontend ausliefern
# --------------------------------------------------------------------------- #

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
