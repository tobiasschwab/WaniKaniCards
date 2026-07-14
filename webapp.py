#!/usr/bin/env python3
"""Web-Frontend für den WaniKani-Karten-Generator.

Ablauf: Quelle *auflisten* (Level, Suche oder Komposition) → Elemente in einer
Tabelle *auswählen* → ausgewählte Karten als **ein PDF** rendern. Keine
Datenbank – Einstellungen (inkl. API-Token), Jobs und PDFs liegen als Dateien
unter ``WKCARDS_DATA`` (Default: ``./data``).
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

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WKCARDS_DATA", HERE / "data")).resolve()
SETTINGS_FILE = DATA_DIR / "settings.json"
OUTPUT_DIR = DATA_DIR / "output"
JOBS_DIR = DATA_DIR / "jobs"
WEB_DIR = HERE / "web"

for _d in (DATA_DIR, OUTPUT_DIR, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_export_lock = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "token": "",
    "username": "",
    "defaults": {
        "level": 1,
        "type": "kanji",
        "layout": "a6",
        "paper": "a4",
        "duplex": "long-edge",
        "cut_marks": True,
        "hole": False,
    },
}

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


# ---------- Render-Worker ---------------------------------------------------- #

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

        pdf_path = OUTPUT_DIR / f"{job_id}.pdf"
        try:
            if not p.get("sample"):
                if not _apply_token_env():
                    raise kc.WaniKaniError(
                        "Kein API-Token gespeichert. Bitte in den Einstellungen setzen."
                    )
            _, n = kc.render_subjects(
                p["subject_ids"],
                pdf_path,
                layout=p.get("layout", "a4-4up"),
                paper=p.get("paper", "a4"),
                duplex=p.get("duplex", "long-edge"),
                cut_marks=p.get("cut_marks", True),
                hole=p.get("hole", False),
                username=load_settings().get("username", "") if not p.get("sample") else "",
                use_cache=p.get("use_cache", True),
                sample=p.get("sample", False),
            )
            job["status"] = "done"
            job["n_cards"] = n
            job["filename"] = pdf_path.name
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
        {"token_set": bool(token), "token_hint": _mask(token), "defaults": s["defaults"]}
    )


@app.post("/api/settings")
def api_post_settings() -> Any:
    body = request.get_json(silent=True) or {}
    s = load_settings()
    if isinstance(body.get("token"), str):
        s["token"] = body["token"].strip()
        s["username"] = _fetch_username(s["token"])  # für den Kartenaufdruck
    if isinstance(body.get("defaults"), dict):
        s["defaults"] = {**s["defaults"], **body["defaults"]}
    save_settings(s)
    return jsonify({"ok": True, "token_set": bool(s.get("token")), "username": s.get("username", "")})


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
            deck_type = body.get("type", "kanji")
            cards = kc.resolve_level(level, deck_type, sample=sample)
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
    return jsonify({"cards": cards})


# ---------- API: Rendern (by ids) ------------------------------------------- #

@app.post("/api/render")
def api_render() -> Any:
    body = request.get_json(silent=True) or {}
    ids = body.get("subject_ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Keine Karten ausgewählt."}), 400
    layout = body.get("layout", "a4-4up")
    if layout not in kc.LAYOUTS:
        return jsonify({"error": "Ungültiges Layout."}), 400

    params = {
        "subject_ids": [int(i) for i in ids],
        "layout": layout,
        "paper": body.get("paper", "a4"),
        "duplex": body.get("duplex", "long-edge"),
        "cut_marks": bool(body.get("cut_marks", True)),
        "hole": bool(body.get("hole", True)),
        "use_cache": not bool(body.get("no_cache", False)),
        "sample": bool(body.get("sample", False)),
    }
    title = body.get("title") or f"{len(params['subject_ids'])} Karten"

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
