#!/usr/bin/env python3
"""srs_api.py – Vokabeltrainer-Endpunkte (SRS, siehe README "Vokabeltrainer").

Als Blueprint ausgelagert aus webapp.py (siehe README "Architektur", P2
"webapp.py in Blueprints aufteilen"), analog zu `auth.py`. Nutzt `srs.py`
(FSRS-Wrapper, NICHT zu verwechseln mit diesem Modul hier) für die eigentliche
Scheduling-Mathematik und `services.py` für geteilte Storage-Helfer.

Dritter Export-Weg neben PDF/Anki: Karten direkt in Shiori mit FSRS lernen.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from . import kanji_cards as kc
from . import models, schemas, srs
from .extensions import db
from .services import (
    _current_target_lang,
    _require_content_provider,
    _strip_html,
    get_subject_overrides,
    load_settings,
    read_custom_for_user,
    read_custom_owned,
    read_kana_for_user,
    read_kana_owned,
)

bp = Blueprint("srs_api", __name__, url_prefix="/api/srs")


def _srs_add_card(
    user_id: int, target_lang: str, card_type: str, card_id: str, item_types: list[str],
) -> int:
    """Für jeden noch NICHT vorhandenen `item_type` eine frische
    `ReviewState`-Zeile anlegen - bereits vorhandene Zeilen (Karte war schon
    einmal hinzugefügt) bleiben unverändert, damit ein erneutes Hinzufügen
    nie den Lernfortschritt zurücksetzt. Gibt die Anzahl NEU angelegter
    Zeilen zurück.

    Committet bewusst NICHT selbst: der Aufrufer (`api_srs_add`) fügt oft viele
    Karten in einer Schleife hinzu und committet EINMAL am Ende (ein
    Transaktions-Roundtrip statt einem pro Karte)."""
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
    return added


@bp.post("/add")
@login_required
def api_srs_add() -> Any:
    """Ausgewählte Karten (dieselbe Auswahl-Form wie `/api/render`) in die
    Lernwarteschlange aufnehmen. Kanji/Vokabel bekommen zwei Zeilen (Meaning
    + Reading, wie WaniKani selbst), Radicals/Custom-Karten nur eine
    (Radicals haben keine Lesung); Dictionary-/KI-Karten bekommen eine
    Reading-Zeile nur, wenn die Karte selbst eine Lesung hat.
    ---
    tags:
      - srs
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            subject_ids: {type: array, items: {type: integer}}
            custom_ids: {type: array, items: {type: string}}
            kana_ids: {type: array, items: {type: string}}
            sample: {type: boolean, default: false}
    responses:
      200:
        description: Anzahl neu hinzugefügter Prüfrichtungen (bereits vorhandene Karten bleiben unverändert).
        schema:
          type: object
          properties:
            ok: {type: boolean}
            added: {type: integer}
      400:
        description: Keine Karten ausgewählt.
      401:
        description: Nicht eingeloggt.
      404:
        description: Eigene/Dictionary-Karte nicht gefunden.
      502:
        description: WaniKani-API-Fehler.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.SrsAddBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400
    subject_ids = data.subject_ids
    custom_ids = data.custom_ids
    kana_ids = data.kana_ids
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
    sample = data.sample
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

    # Einmal committen für ALLE hinzugefügten Karten (siehe _srs_add_card).
    if added:
        db.session.commit()
    return jsonify({"ok": True, "added": added})


def _srs_resolve_fronts(rows: list[models.ReviewState]) -> dict[tuple[str, str], str]:
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


def _today_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _srs_daily_counts(user_id: int, target_lang: str, now: datetime) -> tuple[int, int]:
    """(neue Karten heute bereits beantwortet, Reviews heute insgesamt) –
    Grundlage für die Tageslimits (siehe `api_srs_queue()`) und das
    Statistik-Dashboard (`api_srs_stats()`)."""
    today_logs = models.ReviewLog.query.filter(
        models.ReviewLog.user_id == user_id,
        models.ReviewLog.target_lang == target_lang,
        models.ReviewLog.reviewed_at >= _today_start(now),
    )
    reviews_today = today_logs.count()
    new_today = today_logs.filter(models.ReviewLog.was_new.is_(True)).count()
    return new_today, reviews_today


@bp.get("/queue")
@login_required
def api_srs_queue() -> Any:
    """Fällige Karten für die aktuell aktive Zielsprache, älteste Fälligkeit
    zuerst – Grundlage für den Review-Screen. `limit` deckelt zusätzlich die
    Antwortgröße (Default 50, max. 200). `due_total` ist die volle Anzahl
    unabhängig von Limit/Tageslimits (fürs „X Karten fällig"-Badge im
    Frontend).

    Tageslimits (wie bei Anki-Deck-Optionen, siehe `DEFAULT_SETTINGS`
    `srs_new_per_day`/`srs_reviews_per_day`) begrenzen, wie viele NEUE
    Karten (`reps == 0`) und wie viele Reviews insgesamt heute noch
    ausgeliefert werden – bereits Fällige, die das Tageslimit sprengen,
    bleiben einfach für morgen liegen (kein Datenverlust, nur Verzögerung).
    ---
    tags:
      - srs
    parameters:
      - name: limit
        in: query
        type: integer
        default: 50
        description: Max. Anzahl gelieferter Karten (1-200).
    responses:
      200:
        description: Fällige Karten (nach Tageslimit gedeckelt) + Gesamtzahl.
        schema:
          type: object
          properties:
            due_total: {type: integer}
            items:
              type: array
              items:
                type: object
                properties:
                  card_type: {type: string, enum: [wanikani, custom, kana]}
                  card_id: {type: string}
                  item_type: {type: string, enum: [meaning, reading, front]}
                  front: {type: string}
                  due_at: {type: string, format: date-time}
                  is_new: {type: boolean}
      401:
        description: Nicht eingeloggt.
    """
    lang = _current_target_lang()
    now = datetime.now(UTC)
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

    defaults = load_settings()["defaults"]
    new_done_today, reviews_done_today = _srs_daily_counts(current_user.id, lang, now)

    def _safe_int(value: Any, fallback: int) -> int:
        # Einstellungen kommen aus einem generischen JSON-Merge (POST
        # /api/settings {"defaults": {...}}) ohne Typ-Validierung - ein
        # ungültiger Wert (String, null, ...) darf die Warteschlange nicht
        # mit einem 500er abschießen, sondern fällt auf den Default zurück.
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    new_budget = max(0, _safe_int(defaults.get("srs_new_per_day", 20), 20) - new_done_today)
    review_budget = max(0, _safe_int(defaults.get("srs_reviews_per_day", 200), 200) - reviews_done_today)

    new_rows = base_query.filter(models.ReviewState.reps == 0).order_by(
        models.ReviewState.due_at.asc()
    ).limit(new_budget).all() if new_budget else []
    review_rows = base_query.filter(models.ReviewState.reps > 0).order_by(
        models.ReviewState.due_at.asc()
    ).limit(review_budget).all() if review_budget else []
    rows = sorted(new_rows + review_rows, key=lambda r: r.due_at)[:limit]

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


def _get_review_row(card_type: str, card_id: str, item_type: str) -> models.ReviewState | None:
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


def _match_quality(typed: str, accepted: list[str]) -> str | None:
    """Qualität eines Eingabe-Treffers gegen die akzeptierten Antworten:

    - `"exact"`  – nach Normalisierung exakt gleich einer Antwort.
    - `"fuzzy"`  – kein exakter Treffer, aber innerhalb der Tippfehler-Toleranz
      (1 Editierschritt, nur ab 4 normalisierten Zeichen – bei kürzeren
      Antworten würde ein einzelner Fehler die Bedeutung verändern).
    - `None`     – kein Treffer.

    Die Unterscheidung exact/fuzzy treibt den Bewertungs-VORSCHLAG (siehe
    `api_srs_check`): ein exakter Treffer schlägt „good" vor, ein nur mit
    Tippfehler-Toleranz akzeptierter „hard" (ehrlicher – man wusste es nicht
    ganz sicher), ein Fehltreffer „again"."""
    typed_norm = _normalize_answer(typed)
    if not typed_norm:
        return None
    fuzzy_hit = False
    for candidate in accepted:
        cand_norm = _normalize_answer(candidate)
        if not cand_norm:
            continue
        if typed_norm == cand_norm:
            return "exact"
        threshold = 1 if len(cand_norm) >= 4 else 0
        if threshold and _levenshtein(typed_norm, cand_norm) <= threshold:
            fuzzy_hit = True
    return "fuzzy" if fuzzy_hit else None


def _fuzzy_correct(typed: str, accepted: list[str]) -> bool:
    """Ob die Eingabe als richtig gilt (exakt ODER innerhalb der Tippfehler-
    Toleranz) – dünner Wrapper um `_match_quality()`."""
    return _match_quality(typed, accepted) is not None


def _srs_load_card_data(row: models.ReviewState) -> dict[str, Any] | None:
    """Lädt den zugrundeliegenden Karteninhalt EINER `ReviewState`-Zeile –
    der gemeinsame Ort für das `card_type`-Dispatch (wanikani/custom/kana)
    bei Einzelkarten-Lookups. Bewusst getrennt von `_srs_resolve_fronts()`
    (das dieselbe Fallunterscheidung für einen ganzen Batch von Zeilen macht,
    um WaniKani-Requests zu bündeln) und von `services._build_mixed_deck()`
    (das für Render/Anki-Export volle Karten-Objekte inkl. Beispielsätzen
    baut, nicht nur die für die SRS-Prüfung nötigen Bedeutungen/Lesungen)."""
    if row.card_type == "custom":
        return read_custom_for_user(row.user_id, row.card_id)
    if row.card_type == "kana":
        return read_kana_for_user(row.user_id, row.card_id, row.target_lang)
    if row.card_type == "wanikani":
        token = load_settings().get("token")
        try:
            details = kc.card_details_for_ids([int(row.card_id)], sample=not token, token=token)
        except kc.WaniKaniError:
            return None
        data = details.get(int(row.card_id))
        if data is not None:
            data.update(get_subject_overrides(row.user_id, [int(row.card_id)]).get(int(row.card_id), {}))
        return data
    return None


def _split_answer_synonyms(text: str) -> list[str]:
    """Ein Bedeutungsfeld wie "Kuchen; Torte; Biskuit; Backwerk" (JMdict/
    Gemini trennen mehrere gültige Übersetzungen/Glossen mit "; ", siehe
    dictionary.build_reading_index()) in EINZELNE akzeptierte Antworten
    auftrennen - sonst müsste der Nutzer die komplette Aufzählung wortgleich
    eintippen, um als richtig zu gelten."""
    return [part.strip() for part in text.split(";") if part.strip()]


def _srs_accepted_answers(row: models.ReviewState) -> list[str] | None:
    """Akzeptierte Antworten für eine Prüfrichtung, oder `None`, wenn die
    Karte nicht automatisch prüfbar ist (Custom-Karten: freies HTML auf
    beiden Seiten, kein sinnvoller Textvergleich möglich – dort bewertet
    sich der Nutzer wie bei Anki rein selbst, ohne Auto-Check/Vorschlag)."""
    if row.card_type == "custom":
        return None
    data = _srs_load_card_data(row)
    if not data:
        return None
    if row.card_type == "kana":
        if row.item_type == "reading":
            return [data["reading"]] if data.get("reading") else None
        answers = [
            syn
            for field in (data.get("meaning"), data.get("meaning_extra"))
            if field
            for syn in _split_answer_synonyms(field)
        ]
        return answers or None
    if row.card_type == "wanikani":
        if row.item_type == "reading":
            if data.get("kind") == "VocabCard":
                return data.get("readings") or None
            readings = (data.get("onyomi") or []) + (data.get("kunyomi") or [])
            return readings or None
        return data.get("meanings") or None
    return None


@bp.post("/check")
@login_required
def api_srs_check() -> Any:
    """Getippte Antwort gegen die akzeptierten Antworten prüfen (Fuzzy-
    Match, siehe `_fuzzy_correct()`) und eine Bewertung VORSCHLAGEN – ändert
    NICHTS am FSRS-Lernstand (das passiert erst in `/api/srs/answer`, wenn
    der Nutzer den Vorschlag bestätigt oder überschrieben hat). Bei nicht
    automatisch prüfbaren Karten (Custom) bleibt `correct`/`suggested_rating`
    `None` – der Nutzer bewertet sich dort rein selbst.
    ---
    tags:
      - srs
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [card_type, card_id, item_type, answer]
          properties:
            card_type: {type: string, enum: [wanikani, custom, kana]}
            card_id: {type: string}
            item_type: {type: string, enum: [meaning, reading, front]}
            answer: {type: string}
    responses:
      200:
        description: Prüfergebnis + Bewertungs-Vorschlag (ändert nichts am Lernstand).
        schema:
          type: object
          properties:
            correct: {type: boolean}
            accepted_answers: {type: array, items: {type: string}}
            suggested_rating: {type: string, enum: [again, hard, good]}
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht in der Lernwarteschlange.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.SrsCheckBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400

    row = _get_review_row(data.card_type, data.card_id, data.item_type)
    if row is None:
        return jsonify({"error": "Karte nicht in der Lernwarteschlange gefunden."}), 404

    accepted = _srs_accepted_answers(row)
    if accepted is None:
        return jsonify({"correct": None, "accepted_answers": [], "suggested_rating": None})

    quality = _match_quality(data.answer, accepted)
    # exact -> "good" (sicher gewusst), fuzzy (nur mit Tippfehler-Toleranz
    # akzeptiert) -> "hard" (ehrlicher Vorschlag), kein Treffer -> "again".
    suggested = {"exact": "good", "fuzzy": "hard"}.get(quality or "", "again")
    return jsonify({
        "correct": quality is not None,
        "accepted_answers": accepted,
        "suggested_rating": suggested,
    })


@bp.post("/answer")
@login_required
def api_srs_answer() -> Any:
    """Bewertung (`"again"`/`"hard"`/`"good"`/`"easy"`, wie bei Anki) für
    eine Karte übernehmen und den FSRS-Lernstand fortschreiben. Der Nutzer
    hat die Bewertung ggf. gegenüber dem Vorschlag aus `/api/srs/check`
    überschrieben – dieser Endpunkt vertraut der übergebenen Bewertung,
    ohne selbst nochmal zu prüfen.
    ---
    tags:
      - srs
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [card_type, card_id, item_type, rating]
          properties:
            card_type: {type: string, enum: [wanikani, custom, kana]}
            card_id: {type: string}
            item_type: {type: string, enum: [meaning, reading, front]}
            rating: {type: string, enum: [again, hard, good, easy]}
    responses:
      200:
        description: FSRS-Lernstand fortgeschrieben, Log-Eintrag erstellt.
      400:
        description: Ungültige Bewertung.
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht in der Lernwarteschlange.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.SrsAnswerBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400

    row = _get_review_row(data.card_type, data.card_id, data.item_type)
    if row is None:
        return jsonify({"error": "Karte nicht in der Lernwarteschlange gefunden."}), 404

    was_new = row.reps == 0
    try:
        updated = srs.review(srs.state_from_row(row), data.rating)
    except srs.SrsError as exc:
        return jsonify({"error": str(exc)}), 400
    srs.apply_state_to_row(row, updated)
    # Log-Eintrag für Tageslimits/Statistik-Dashboard (siehe models.ReviewLog-
    # Docstring) - ReviewState selbst hält nur den AKTUELLEN Zustand, keine
    # Historie.
    db.session.add(models.ReviewLog(
        user_id=current_user.id, target_lang=row.target_lang, card_type=data.card_type,
        card_id=data.card_id, item_type=data.item_type, rating=data.rating, was_new=was_new,
    ))
    db.session.commit()

    return jsonify({"ok": True, "due_at": row.due_at.isoformat(), "reps": row.reps, "lapses": row.lapses})


def _daily_review_counts(user_id: int, target_lang: str) -> dict[str, int]:
    """Reviews pro Kalendertag (UTC, konsistent mit den Tageslimits in
    `_today_start()`) über die GESAMTE Historie – ein `GROUP BY date(...)`
    serverseitig statt alle Log-Zeilen zu laden (`date()` existiert in
    SQLite UND Postgres). SQLite liefert den Tag als 'YYYY-MM-DD'-String,
    Postgres als `date`-Objekt – deshalb die `str()[:10]`-Normalisierung."""
    day = db.func.date(models.ReviewLog.reviewed_at)
    rows = (
        db.session.query(day, db.func.count())
        .filter(
            models.ReviewLog.user_id == user_id,
            models.ReviewLog.target_lang == target_lang,
        )
        .group_by(day)
        .all()
    )
    return {str(d)[:10]: int(n) for d, n in rows}


def _compute_streak(active_days: set[str], today: date) -> int:
    """Anzahl aufeinanderfolgender Lerntage bis heute. Der heutige Tag zählt
    mit, sobald mindestens ein Review gemacht wurde – ist heute (noch) nichts
    passiert, bricht der Streak aber nicht ab, solange gestern gelernt wurde
    (der Tag ist ja noch nicht vorbei; übliche Streak-Semantik, wie bei
    Duolingo/WaniKani)."""
    start = today if today.isoformat() in active_days else today - timedelta(days=1)
    streak = 0
    day = start
    while day.isoformat() in active_days:
        streak += 1
        day -= timedelta(days=1)
    return streak


@bp.get("/stats")
@login_required
def api_srs_stats() -> Any:
    """Statistik-Dashboard für die aktuell aktive Zielsprache: Reviews/neue
    Karten heute, Retention der letzten 7 Tage (Anteil NICHT "again"
    bewerteter Reviews – Standarddefinition bei Anki/FSRS), die Anzahl
    Karten je Lernstufe, der aktuelle Lern-Streak sowie die Tagesaktivität
    der letzten ~26 Wochen (Kalender-Heatmap im Frontend).
    ---
    tags:
      - srs
    responses:
      200:
        description: Statistik-Dashboard-Daten.
        schema:
          type: object
          properties:
            reviews_today: {type: integer}
            new_today: {type: integer}
            retention_7d: {type: number, description: "Prozent, null ohne Reviews in den letzten 7 Tagen"}
            total_cards: {type: integer}
            by_stage: {type: object}
            streak_days: {type: integer}
            activity: {type: object, description: "Reviews je Kalendertag (YYYY-MM-DD -> Anzahl)"}
      401:
        description: Nicht eingeloggt.
    """
    lang = _current_target_lang()
    now = datetime.now(UTC)

    new_today, reviews_today = _srs_daily_counts(current_user.id, lang, now)

    week_logs = models.ReviewLog.query.filter(
        models.ReviewLog.user_id == current_user.id,
        models.ReviewLog.target_lang == lang,
        models.ReviewLog.reviewed_at >= now - timedelta(days=7),
    )
    week_total = week_logs.count()
    week_again = week_logs.filter(models.ReviewLog.rating == "again").count()
    retention_7d = round((week_total - week_again) / week_total * 100, 1) if week_total else None

    states = models.ReviewState.query.filter_by(user_id=current_user.id, target_lang=lang).all()
    # fsrs.State: 1=Learning, 2=Review, 3=Relearning (siehe srs.py) - "new"
    # ist kein eigener FSRS-State, sondern unsere eigene Definition
    # (reps == 0, noch nie beantwortet).
    by_stage = {"new": 0, "learning": 0, "review": 0, "relearning": 0}
    stage_names = {1: "learning", 2: "review", 3: "relearning"}
    for s in states:
        if s.reps == 0:
            by_stage["new"] += 1
        else:
            fsrs_stage = int((s.fsrs_state or {}).get("state") or 0)
            by_stage[stage_names.get(fsrs_stage, "learning")] += 1

    daily_counts = _daily_review_counts(current_user.id, lang)
    today = now.date()
    streak_days = _compute_streak(set(daily_counts), today)
    # Nur die letzten ~26 Wochen für die Heatmap mitschicken (ältere Tage
    # zeigt sie ohnehin nicht); nur Tage MIT Aktivität, das Frontend füllt
    # die Lücken mit 0-Zellen auf.
    cutoff = (today - timedelta(days=181)).isoformat()
    activity = {d: n for d, n in daily_counts.items() if d >= cutoff}

    return jsonify({
        "reviews_today": reviews_today,
        "new_today": new_today,
        "retention_7d": retention_7d,
        "by_stage": by_stage,
        "total_cards": len(states),
        "streak_days": streak_days,
        "activity": activity,
    })


@bp.get("/cards")
@login_required
def api_srs_cards() -> Any:
    """Übersicht aller Karten in der Lernwarteschlange der aktiven Zielsprache
    (Karten-Browser im Review-Screen) – gruppiert je `(card_type, card_id)`,
    mit Vorschautext, Anzahl Prüfrichtungen, Summe der Wiederholungen, ob
    gerade fällig und der nächsten Fälligkeit. Grundlage, um eine
    versehentlich hinzugefügte Karte gezielt wieder zu entfernen (siehe
    `/api/srs/remove`).
    ---
    tags:
      - srs
    responses:
      200:
        description: Alle Karten der Lernwarteschlange, gruppiert je Karte.
        schema:
          type: object
          properties:
            total: {type: integer}
            cards:
              type: array
              items:
                type: object
                properties:
                  card_type: {type: string}
                  card_id: {type: string}
                  front: {type: string}
                  items: {type: integer}
                  reps: {type: integer}
                  due_now: {type: boolean}
                  next_due: {type: string, format: date-time}
      401:
        description: Nicht eingeloggt.
    """
    lang = _current_target_lang()
    now = datetime.now(UTC)
    rows = models.ReviewState.query.filter_by(user_id=current_user.id, target_lang=lang).all()
    fronts = _srs_resolve_fronts(rows)

    def _aware(dt: datetime) -> datetime:
        # SQLite liefert `due_at` zeitzonennaiv zurück (Postgres bewusst) -
        # für den Vergleich/die Sortierung mit dem tz-bewussten `now`
        # einheitlich als UTC interpretieren.
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r.card_type, r.card_id)
        entry = grouped.setdefault(key, {
            "card_type": r.card_type, "card_id": r.card_id,
            "front": fronts.get(key, "?"), "items": 0, "reps": 0,
            "due_now": False, "next_due": None,
        })
        due = _aware(r.due_at)
        entry["items"] += 1
        entry["reps"] += r.reps
        if due <= now:
            entry["due_now"] = True
        if entry["next_due"] is None or due < entry["next_due"]:
            entry["next_due"] = due

    # Fällige zuerst, dann nach nächster Fälligkeit.
    cards = sorted(grouped.values(), key=lambda c: (not c["due_now"], c["next_due"]))
    for c in cards:
        c["next_due"] = c["next_due"].isoformat() if c["next_due"] else None
    return jsonify({"cards": cards, "total": len(cards)})


@bp.post("/remove")
@login_required
def api_srs_remove() -> Any:
    """Eine Karte (alle ihre Prüfrichtungen) aus der Lernwarteschlange der
    aktiven Zielsprache entfernen – inklusive Lern-Log. Das Kartenobjekt
    selbst (WaniKani-Subject bzw. Custom-/Dictionary-Karte) bleibt bestehen;
    nur der SRS-Lernstand wird verworfen, die Karte kann später erneut
    hinzugefügt werden.
    ---
    tags:
      - srs
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [card_type, card_id]
          properties:
            card_type: {type: string, enum: [wanikani, custom, kana]}
            card_id: {type: string}
    responses:
      200:
        description: Karte aus der Lernwarteschlange entfernt.
      400:
        description: card_type/card_id fehlt.
      401:
        description: Nicht eingeloggt.
    """
    body = request.get_json(silent=True) or {}
    try:
        data = schemas.parse_body(schemas.SrsRemoveBody, body)
    except schemas.ValidationFailed as exc:
        return jsonify({"error": exc.message}), 400

    lang = _current_target_lang()
    removed = models.ReviewState.query.filter_by(
        user_id=current_user.id, target_lang=lang, card_type=data.card_type, card_id=data.card_id,
    ).delete()
    models.ReviewLog.query.filter_by(
        user_id=current_user.id, target_lang=lang, card_type=data.card_type, card_id=data.card_id,
    ).delete()
    db.session.commit()

    if not removed:
        return jsonify({"error": "Karte nicht in der Lernwarteschlange gefunden."}), 404
    return jsonify({"ok": True, "removed": removed})
