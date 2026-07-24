#!/usr/bin/env python3
"""jobs_api.py – Rendern (PDF/Anki) als asynchrone Jobs + Job-Verlauf.

Als Blueprint ausgelagert aus webapp.py (siehe README "Architektur", P2
"webapp.py in Blueprints aufteilen"), analog zu `auth.py`. Der eigentliche
Render-Worker-Code (`_build_mixed_deck`/`_run_render`) sowie Job-Storage
leben in `services.py`, damit auch der RQ-Worker-Prozess sie importieren
kann, ohne diesen Blueprint (oder webapp.py) zu benötigen."""
from __future__ import annotations

import uuid
from typing import Any

from flask import Blueprint, abort, jsonify, redirect, request, send_file
from flask_login import current_user, login_required

from . import kanji_cards as kc
from . import models
from . import storage
from .extensions import db, limiter
from .services import (
    OUTPUT_DIR,
    MAX_CONCURRENT_JOBS_PER_USER,
    _current_target_lang,
    _now,
    _run_render,
    list_jobs,
    read_custom_owned,
    read_job_owned,
    read_kana_owned,
    render_queue,
    write_job,
)

bp = Blueprint("jobs_api", __name__)


@bp.post("/api/render")
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
    if active_count >= MAX_CONCURRENT_JOBS_PER_USER:
        return jsonify({
            "error": f"Zu viele laufende Render-Jobs (max. {MAX_CONCURRENT_JOBS_PER_USER} gleichzeitig). "
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


@bp.get("/api/jobs")
@login_required
def api_jobs() -> Any:
    return jsonify(list_jobs())


@bp.get("/api/jobs/<job_id>")
@login_required
def api_job(job_id: str) -> Any:
    job = read_job_owned(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@bp.delete("/api/jobs/<job_id>")
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


@bp.get("/api/jobs/<job_id>/pdf")
@login_required
def api_job_pdf(job_id: str) -> Any:
    return _serve_job_output(job_id, suffix=".pdf", mimetype="application/pdf")


@bp.get("/api/jobs/<job_id>/apkg")
@login_required
def api_job_apkg(job_id: str) -> Any:
    return _serve_job_output(job_id, suffix=".apkg", mimetype="application/octet-stream")
