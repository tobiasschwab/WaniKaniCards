#!/usr/bin/env python3
"""gemini_client.py – Gemini als Satz-Analyse-Engine für den Text-Modus.

Ersetzt Janomes reine Tokenisierung für Sätze, zu denen ein Gemini-API-Key
hinterlegt ist: bessere Wortgrenzen, grammatikalische Funktion pro Wort/
Partikel, eine kurze Grammatik-Erklärung und eine natürliche deutsche
Übersetzung – ein Request pro Satz, JSON-strukturiert über
`responseSchema` (kein Markdown-Tabellen-Parsing nötig).

Kein neues SDK (`google-genai` o. ä.) – reiner REST-Call über `requests`,
passend zum Projekt-Grundsatz "schlank halten" (DeepL/GitHub laufen genauso
über plain `requests`).

Fail-soft wie überall im Projekt: bei fehlendem Text/Key, Netzwerkfehler,
Quota oder kaputter Antwort gibt `analyze_sentence()` `None` zurück – der
Aufrufer (`kanji_cards.annotate_text()`) fällt für genau diesen Satz auf die
Janome-Pipeline zurück, nie ein harter Abbruch für den ganzen Text.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache")) / "gemini"

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODEL = "gemini-2.5-flash"
AVAILABLE_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro")

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tokens": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "surface": {"type": "STRING"},
                    "dictionary_form": {"type": "STRING"},
                    "function": {"type": "STRING"},
                },
                "required": ["surface", "dictionary_form", "function"],
            },
        },
        "grammar_notes": {"type": "STRING"},
        "translation_de": {"type": "STRING"},
    },
    "required": ["tokens", "grammar_notes", "translation_de"],
}

_PROMPT_TEMPLATE = """Du bist ein professioneller Japanisch-Lehrer. Analysiere den folgenden japanischen Satz für mich. Gehe strikt Schritt für Schritt vor:

1. Zerlege den Satz in JEDES einzelne Wort, Partikel und Grammatikelement.
   Gib zu jedem: surface (Schreibweise wie im Satz), dictionary_form
   (Grundform/Wörterbuchform, z. B. bei Verben die Present-Wörterbuchform),
   function (kurze grammatikalische Funktion/Bedeutung, auf Deutsch).
2. Erkläre kurz die wichtigsten Grammatik-Besonderheiten des Satzes
   (grammar_notes, auf Deutsch).
3. Gib eine natürliche, flüssige deutsche Übersetzung für den Gesamtsatz an
   (translation_de).

Satz: {sentence}"""


class GeminiError(Exception):
    """Verständlicher Fehler ohne Stacktrace, wenn Gemini nicht verfügbar ist."""


def _cache_path(sentence: str, model: str) -> Path:
    key = hashlib.sha1(f"{model}\n{sentence}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def analyze_sentence(
    sentence: str,
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    session: requests.Session | None = None,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    """Einen japanischen Satz per Gemini analysieren lassen: Tokens (mit
    Grundform + grammatikalischer Funktion), Grammatik-Erklärung und eine
    natürliche deutsche Übersetzung.

    Gibt bei fehlendem Text/Key, Netzwerkfehler, Rate-Limit/Quota oder
    kaputter/unerwarteter Antwort `None` zurück statt eine Exception zu
    werfen – der Aufrufer fällt dann für diesen Satz auf Janome zurück.
    """
    sentence = sentence.strip()
    if not sentence or not api_key:
        return None

    cache_file = _cache_path(sentence, model) if use_cache else None
    if cache_file and cache_file.is_file():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    session = session or requests.Session()
    url = f"{_API_BASE}/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": _PROMPT_TEMPLATE.format(sentence=sentence)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }

    backoff = 1.0
    resp = None
    for _attempt in range(4):
        try:
            resp = session.post(url, params={"key": api_key}, json=body, timeout=30)
        except requests.RequestException:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(backoff)
            backoff = min(backoff * 2, 8)
            continue
        break
    if resp is None or not resp.ok:
        return None

    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None

    if not isinstance(result.get("tokens"), list):
        return None

    if cache_file:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return result
