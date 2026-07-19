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
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache")) / "gemini"

# (connect, read) statt einem einzelnen Wert: eine tote/blockierte Verbindung
# (z. B. DNS/Firewall-Problem im Docker-Netz) darf höchstens 10s zum Verbin-
# den brauchen, das eigentliche Warten auf die Antwort maximal 25s – sonst
# hängt ein Satz (und damit ein ganzer gunicorn-Worker) im schlimmsten Fall
# lange fest, ohne dass im Frontend oder Log erkennbar ist, woran es liegt.
_REQUEST_TIMEOUT = (10, 25)

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


def _server_retry_delay(resp: requests.Response) -> float | None:
    """Von Google empfohlene Wartezeit aus einer 429-Antwort lesen (`Retry-After`-
    Header oder `RetryInfo` in der JSON-Fehlerantwort).

    Zuverlässiger als eine geratene Backoff-Zeit: Rate-Limits (v. a. bei
    `gemini-2.5-pro`, dessen Free-Tier-Kontingent deutlich enger ist als bei
    `flash`/`flash-lite`) laufen über ein Zeitfenster von oft ~60s – ein reines
    Backoff bis max. 8s wartet dann bei jedem Versuch zu kurz und schlägt
    dutzende Male hintereinander mit HTTP 429 fehl, statt einmal lange genug
    zu warten und danach zu klappen.
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            delay = detail.get("retryDelay")
            if isinstance(detail.get("@type"), str) and detail["@type"].endswith("RetryInfo") and delay:
                return float(str(delay).rstrip("s"))
    except (ValueError, TypeError, AttributeError):
        pass
    return None


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

    short = sentence if len(sentence) <= 40 else sentence[:40] + "…"

    cache_file = _cache_path(sentence, model) if use_cache else None
    if cache_file and cache_file.is_file():
        try:
            result = json.loads(cache_file.read_text(encoding="utf-8"))
            logger.info("Gemini: Cache-Treffer für Satz %r (%s)", short, model)
            return result
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

    logger.info("Gemini: Anfrage für Satz %r (%s) …", short, model)
    t0 = time.monotonic()
    backoff = 2.0
    total_waited = 0.0
    max_total_wait = 70.0  # ein Satz darf insgesamt nicht länger blockieren
    resp = None
    for attempt in range(5):
        try:
            resp = session.post(url, params={"key": api_key}, json=body, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning(
                "Gemini: Netzwerkfehler bei Satz %r nach %.1fs (%s): %s",
                short, time.monotonic() - t0, type(exc).__name__, exc,
            )
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            if total_waited >= max_total_wait or attempt == 4:
                break
            wait = _server_retry_delay(resp) if resp.status_code == 429 else None
            source = "vom Server empfohlen"
            if wait is None:
                wait, source = backoff, "geschätzt"
                backoff = min(backoff * 2, 20)
            wait = min(wait, max_total_wait - total_waited)
            logger.info(
                "Gemini: HTTP %s für Satz %r, Versuch %d/5 – warte %.0fs (%s)",
                resp.status_code, short, attempt + 1, wait, source,
            )
            time.sleep(wait)
            total_waited += wait
            continue
        break
    if resp is None or not resp.ok:
        status = resp.status_code if resp is not None else "?"
        logger.warning(
            "Gemini: Anfrage für Satz %r endgültig fehlgeschlagen (HTTP %s) nach %.1fs",
            short, status, time.monotonic() - t0,
        )
        return None

    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Gemini: Antwort für Satz %r nicht auswertbar (%s): %s", short, type(exc).__name__, exc)
        return None

    if not isinstance(result.get("tokens"), list):
        logger.warning("Gemini: Antwort für Satz %r ohne 'tokens'-Liste", short)
        return None

    logger.info("Gemini: Satz %r analysiert in %.1fs (%d Tokens)", short, time.monotonic() - t0, len(result["tokens"]))

    if cache_file:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return result
