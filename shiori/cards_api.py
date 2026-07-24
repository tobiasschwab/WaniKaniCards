#!/usr/bin/env python3
"""cards_api.py – CRUD für eigene Karten (CustomCard) und Dictionary-/KI-
Karten (KanaCard).

Als Blueprint ausgelagert aus webapp.py (siehe README "Architektur", P2
"webapp.py in Blueprints aufteilen"), analog zu `auth.py`. Storage-Helfer
kommen aus `services.py`."""
from __future__ import annotations

import uuid
from typing import Any

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from . import kanji_cards as kc
from . import models
from .extensions import db
from .languages.registry import get_pack
from .services import (
    _current_pack,
    _current_target_lang,
    _custom_descriptor,
    _delete_srs_rows_for_card,
    _kana_descriptor,
    _resolve_gemini_model,
    list_customs,
    list_kana,
    load_settings,
    read_custom_owned,
    read_kana_owned,
    write_custom,
    write_kana,
)

bp = Blueprint("cards_api", __name__)


# ---------- Eigene Karten (CustomCard) --------------------------------------- #

@bp.get("/api/customcards")
@login_required
def api_customcards() -> Any:
    """Kurzfassungen aller eigenen ("Frei erstellen") Karten der aktiven Zielsprache.
    ---
    tags:
      - cards
    responses:
      200:
        description: Liste der Kartenbeschreibungen.
      401:
        description: Nicht eingeloggt.
    """
    return jsonify([_custom_descriptor(c) for c in list_customs()])


@bp.get("/api/customcards/<cid>")
@login_required
def api_customcard(cid: str) -> Any:
    """Volle Felder (front_html/back_html/tags) einer eigenen Karte.
    ---
    tags:
      - cards
    parameters:
      - name: cid
        in: path
        type: string
        required: true
    responses:
      200:
        description: Karten-Felder.
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht gefunden oder gehört einem anderen Nutzer.
    """
    card = read_custom_owned(cid)
    if card is None:
        abort(404)
    return jsonify(card)


@bp.post("/api/customcards")
@login_required
def api_save_customcard() -> Any:
    """Eigene Karte anlegen (ohne `id`) oder aktualisieren (mit `id`).
    ---
    tags:
      - cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            id: {type: string, description: "weglassen zum Neuanlegen"}
            front_html: {type: string}
            back_html: {type: string}
            tags: {type: array, items: {type: string}}
    responses:
      200:
        description: Gespeicherte Karte.
      401:
        description: Nicht eingeloggt.
      404:
        description: "id gesetzt, aber Karte nicht gefunden/fremd (IDOR-Schutz)."
    """
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


@bp.delete("/api/customcards/<cid>")
@login_required
def api_delete_customcard(cid: str) -> Any:
    """Eigene Karte löschen (inkl. SRS-Lernstand, falls im Vokabeltrainer).
    ---
    tags:
      - cards
    parameters:
      - name: cid
        in: path
        type: string
        required: true
    responses:
      200:
        description: Gelöscht.
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht gefunden oder gehört einem anderen Nutzer.
    """
    if read_custom_owned(cid) is None:
        abort(404)
    models.CustomCard.query.filter_by(id=cid, user_id=current_user.id).delete()
    _delete_srs_rows_for_card(current_user.id, "custom", cid)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Dictionary-Karten (kanacards) ------------------------------------ #

@bp.get("/api/kanacards")
@login_required
def api_kanacards() -> Any:
    """Kurzfassungen aller Dictionary-/KI-Karten der aktiven Zielsprache.
    ---
    tags:
      - cards
    responses:
      200:
        description: Liste der Kartenbeschreibungen.
      401:
        description: Nicht eingeloggt.
    """
    return jsonify([_kana_descriptor(c) for c in list_kana()])


@bp.get("/api/kanacards/<kid>")
@login_required
def api_kanacard(kid: str) -> Any:
    """Volle Felder EINER Dictionary-/KI-Karte – Grundlage für den vollen
    Rückseiten-Reveal und den Editiermodus im Vokabeltrainer-Review (analog
    zu `/api/customcards/<cid>`).
    ---
    tags:
      - cards
    parameters:
      - name: kid
        in: path
        type: string
        required: true
    responses:
      200:
        description: Karten-Felder.
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht gefunden oder gehört einem anderen Nutzer.
    """
    card = read_kana_owned(kid)
    if card is None:
        abort(404)
    return jsonify(card)


@bp.post("/api/kanacards")
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
    hinterlegt ist (sonst bleibt die Karte trotzdem gültig).
    ---
    tags:
      - cards
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [word]
          properties:
            word: {type: string}
            sentence: {type: string}
            sentence_audio_url: {type: string}
            source: {type: string, enum: [dictionary, ai], default: dictionary}
            meaning: {type: string, description: "nur bei source=ai"}
            reading: {type: string, description: "nur bei source=ai"}
    responses:
      200:
        description: Angelegte Karte.
      400:
        description: Kein Wort/keine KI-Bedeutung angegeben, oder kein Gemini-Key hinterlegt.
      401:
        description: Nicht eingeloggt.
      404:
        description: Wort im Wörterbuch/von der KI nicht erkannt.
    """
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


@bp.post("/api/kanacards/<kid>/edit")
@login_required
def api_edit_kanacard(kid: str) -> Any:
    """Bestehende Dictionary-/KI-Karte direkt überschreiben (Editiermodus im
    Vokabeltrainer-Review, siehe README-Feature-Feedback) – anders als
    `POST /api/kanacards` wird hier NICHTS neu aus dem Wörterbuch/der KI
    hergeleitet, sondern nur die übergebenen Felder 1:1 übernommen.
    ---
    tags:
      - cards
    parameters:
      - name: kid
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [fields]
          properties:
            fields:
              type: object
              description: "Teilmenge von word/kanji_hint/reading/meaning/meaning_extra/sentence_ja/sentence_translation"
    responses:
      200:
        description: Aktualisierte Kartenbeschreibung.
      400:
        description: fields fehlt oder ist kein Objekt.
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht gefunden oder gehört einem anderen Nutzer.
    """
    card = read_kana_owned(kid)
    if card is None:
        abort(404)
    body = request.get_json(silent=True) or {}
    fields = body.get("fields")
    if not isinstance(fields, dict):
        return jsonify({"error": "Ungültige fields."}), 400
    allowed = {
        "word", "kanji_hint", "reading", "meaning", "meaning_extra",
        "sentence_ja", "sentence_translation",
    }
    card.update({k: v for k, v in fields.items() if k in allowed})
    write_kana(card, user_id=current_user.id, target_lang=_current_target_lang())
    return jsonify(_kana_descriptor(read_kana_owned(kid)))


@bp.delete("/api/kanacards/<kid>")
@login_required
def api_delete_kanacard(kid: str) -> Any:
    """Dictionary-/KI-Karte löschen (inkl. SRS-Lernstand, falls im Vokabeltrainer).
    ---
    tags:
      - cards
    parameters:
      - name: kid
        in: path
        type: string
        required: true
    responses:
      200:
        description: Gelöscht.
      401:
        description: Nicht eingeloggt.
      404:
        description: Karte nicht gefunden oder gehört einem anderen Nutzer.
    """
    if read_kana_owned(kid) is None:
        abort(404)
    models.KanaCard.query.filter_by(id=kid, user_id=current_user.id).delete()
    _delete_srs_rows_for_card(current_user.id, "kana", kid)
    db.session.commit()
    return jsonify({"ok": True})
