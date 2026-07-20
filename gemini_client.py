#!/usr/bin/env python3
"""gemini_client.py – Gemini als Satz-Analyse-Engine für den Text-Modus.

Ersetzt Janomes reine Tokenisierung für Sätze, zu denen ein Gemini-API-Key
hinterlegt ist: bessere Wortgrenzen, grammatikalische Funktion pro Wort/
Partikel, eine kurze Grammatik-Erklärung und eine natürliche deutsche
Übersetzung – JSON-strukturiert über `responseSchema` (kein Markdown-
Tabellen-Parsing nötig).

Alle Sätze eines Texts werden in EINEM Batch-Request analysiert
(`analyze_sentences()`) statt in einem Request pro Satz – bei einem Text mit
z. B. 19 Sätzen sonst 19 einzelne Anfragen, die (v. a. bei niedrigem
Gratis-Kontingent) sofort in eine HTTP-429-Kaskade laufen. Ergebnisse werden
trotzdem pro Satz gecacht, damit spätere Teil-Änderungen am Text nicht den
kompletten Text neu anfragen.

Kein neues SDK (`google-genai` o. ä.) – reiner REST-Call über `requests`,
passend zum Projekt-Grundsatz "schlank halten" (DeepL/GitHub laufen genauso
über plain `requests`).

Fail-soft wie überall im Projekt: bei fehlendem Text/Key, Netzwerkfehler,
Quota oder kaputter Antwort bleiben betroffene Sätze `None` – der Aufrufer
(`kanji_cards.annotate_text()`) fällt für genau diese Sätze auf die
Janome-Pipeline zurück, nie ein harter Abbruch für den ganzen Text.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import struct
import time
from pathlib import Path
from typing import Any, Sequence

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache")) / "gemini"

# (connect, read) statt einem einzelnen Wert: eine tote/blockierte Verbindung
# (z. B. DNS/Firewall-Problem im Docker-Netz) darf höchstens 10s zum Verbin-
# den brauchen. Für Einzel-Requests (TTS, ListModels) reicht ein Read-Timeout
# von 60s – für Satz-Batches siehe `_batch_read_timeout()`: live beobachtet
# hat schon EIN Satz ~46s gebraucht und ein 19er-Batch nach 60s abgebrochen,
# ein fixer Wert unabhängig von der Satzanzahl war schlicht zu knapp bemessen.
_REQUEST_TIMEOUT = (10, 60)


def _batch_read_timeout(n_sentences: int) -> tuple[float, float]:
    """Read-Timeout für einen Satz-Batch, linear mit der Satzanzahl skaliert
    (Google generiert pro Satz strukturiertes JSON, das braucht spürbar
    länger als ein einzelner kurzer Prompt) – gedeckelt, damit ein einzelner
    Request nie unbegrenzt einen gunicorn-Worker blockiert."""
    return (10, min(280.0, 60.0 + 8.0 * n_sentences))

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# "-latest"-Aliase statt fest codierter Versionsnummern (z. B. "gemini-2.5-
# flash"): Google deprecatet konkrete Modellversionen regelmäßig für neue
# Projekte/Keys ("model X is no longer available to new users") – die Alias-
# Namen zeigen dagegen dauerhaft auf die aktuell aktive Version derselben
# Preis-/Geschwindigkeitsklasse. Dient nur noch als Fallback/Default, wenn
# `list_models()` nicht verfügbar ist (kein Key, Netzwerkfehler) – die
# Modellauswahl in der UI wird sonst per API abgerufen statt hartcodiert.
DEFAULT_MODEL = "gemini-flash-latest"
AVAILABLE_MODELS = ("gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest")

# Modellnamen, die zwar `generateContent` unterstützen, aber keine reinen
# Text-Chat-Modelle sind (Bild-/Audio-/Robotik-/Tool-Varianten, interne
# Preview-Spielereien) – für die Sprachanalyse hier nicht sinnvoll und würden
# die Modell-Auswahl nur unübersichtlich machen.
_MODEL_EXCLUDE_TOKENS = (
    "image", "tts", "computer-use", "robotics", "customtools", "clip",
    "nano-banana", "lyria", "antigravity", "deep-research", "omni",
)

_TOKENS_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "surface": {"type": "STRING"},
            "dictionary_form": {"type": "STRING"},
            "reading": {"type": "STRING"},
            "function": {"type": "STRING"},
            "meaning": {"type": "STRING"},
            "is_content_word": {"type": "BOOLEAN"},
        },
        "required": ["surface", "dictionary_form", "reading", "function", "meaning", "is_content_word"],
    },
}

_TOKEN_INSTRUCTIONS = """Zerlege JEDEN Satz in JEDES einzelne Wort, Partikel und Grammatikelement –
OHNE etwas auszulassen. Das schließt Satzzeichen (｡ 。 、 ! ? …) am Ende oder
mitten im Satz ausdrücklich mit ein, jedes als eigenes Token. Die
surface-Felder aller Tokens eines Satzes müssen, aneinandergereiht, exakt
wieder den kompletten Original-Satz ergeben (Zeichen für Zeichen, nichts
fehlt). Gib zu jedem Token: surface (Schreibweise wie im Satz),
dictionary_form (Grundform/Wörterbuchform, z. B. bei Verben die
Present-Wörterbuchform; bei Satzzeichen einfach dasselbe Zeichen), reading
(Lesung der dictionary_form in Hiragana; bei Satzzeichen leer lassen),
function (kurze grammatikalische Funktion/Bedeutung, auf Deutsch; bei
Satzzeichen z. B. "Satzzeichen"), meaning (kurze deutsche Kern-Bedeutung der
dictionary_form, wie in einem Wörterbuch, z. B. "gehen" oder "Schule"; bei
reinen Partikeln/Satzzeichen leer lassen), is_content_word (true für echte
Vokabeln zum Lernen: Nomen, Verben, Adjektive, Adverbien – false für
Partikel (は/が/を/に/で/も/の/…), Kopula (です/だ), Hilfsverben, Konjunktionen
und Satzzeichen. Wichtig: is_content_word richtet sich NACH DER FUNKTION
IM SATZ, nicht nach der reinen Lautung – z. B. ist die Themen-Partikel "は"
(gesprochen "wa") immer false, auch wenn dieselbe Kana-Folge in einem
Wörterbuch zufällig als eigenständiges Wort (z. B. "Flügel") auftauchen
könnte; das Wörterbuch würde hier die falsche, zum Satz nicht passende
Bedeutung liefern). Erkläre außerdem kurz die wichtigsten
Grammatik-Besonderheiten des Satzes (grammar_notes, auf Deutsch) und gib
eine natürliche, flüssige deutsche Übersetzung an (translation_de)."""

_BATCH_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "sentences": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "sentence": {"type": "STRING"},
                    "tokens": _TOKENS_SCHEMA,
                    "grammar_notes": {"type": "STRING"},
                    "translation_de": {"type": "STRING"},
                },
                "required": ["sentence", "tokens", "grammar_notes", "translation_de"],
            },
        },
    },
    "required": ["sentences"],
}

_BATCH_PROMPT_TEMPLATE = f"""Du bist ein professioneller Japanisch-Lehrer. Analysiere JEDEN der folgenden, durchnummerierten japanischen Sätze einzeln für mich, in genau dieser Reihenfolge. Gehe für jeden Satz strikt Schritt für Schritt vor:

{_TOKEN_INSTRUCTIONS}

Gib "sentences" als Array zurück – für JEDEN unten aufgeführten Satz genau ein Objekt, mit "sentence" (der Original-Satz, exakt wie unten angegeben, unverändert), "tokens", "grammar_notes", "translation_de". Kein Satz darf ausgelassen werden.

Sätze:
{{sentences}}"""

# Wie viele Sätze maximal in einem einzigen Request landen – ein Sicherheits-
# Deckel gegen extrem lange Texte, nicht weil Gemini das nicht könnte
# (Kontextfenster ist riesig), sondern damit eine einzelne Antwort nicht
# unnötig groß/langsam wird. Der Rest landet in einem weiteren Batch-Request.
_BATCH_CHUNK_SIZE = 40


class GeminiError(Exception):
    """Verständlicher Fehler ohne Stacktrace, wenn Gemini nicht verfügbar ist."""


def _cache_path(sentence: str, model: str) -> Path:
    key = hashlib.sha1(f"{model}\n{sentence}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _read_cache(sentence: str, model: str) -> dict[str, Any] | None:
    cache_file = _cache_path(sentence, model)
    if not cache_file.is_file():
        return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(sentence: str, model: str, result: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(sentence, model).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _server_retry_delay(resp: requests.Response) -> float | None:
    """Von Google empfohlene Wartezeit aus einer 429-Antwort lesen (`Retry-After`-
    Header oder `RetryInfo` in der JSON-Fehlerantwort).

    Zuverlässiger als eine geratene Backoff-Zeit: Rate-Limits laufen über ein
    Zeitfenster von oft ~60s – ein reines Backoff bis max. 8s wartet dann bei
    jedem Versuch zu kurz und schlägt dutzende Male hintereinander mit
    HTTP 429 fehl, statt einmal lange genug zu warten und danach zu klappen.
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


def _post_with_retry(
    url: str,
    api_key: str,
    body: dict[str, Any],
    session: requests.Session,
    label: str,
    *,
    timeout: tuple[float, float] = _REQUEST_TIMEOUT,
    max_attempts: int = 5,
) -> requests.Response | None:
    """POST mit Retry bei 429/5xx (Server-empfohlene Wartezeit bevorzugt,
    sonst geschätztes Backoff) UND bei Netzwerkfehlern/Timeouts (geschätztes
    Backoff) – ein einzelner ReadTimeout ist bei Gemini kein Dauerzustand,
    ein zweiter Versuch schlägt oft durch. Gedeckelt auf insgesamt ~70s
    Wartezeit zwischen den Versuchen (nicht zu verwechseln mit `timeout`,
    der Wartezeit PRO Versuch auf die Antwort selbst)."""
    # Netzwerkfehler/Timeouts nur einmal wiederholt (nicht die vollen 5
    # Versuche): jeder Versuch kann hier bis zu `timeout[1]` (bei großen
    # Batches mehrere Minuten) dauern, statt wie ein 429/5xx sofort mit
    # einer HTTP-Antwort zurückzukommen – ein gunicorn-Worker soll dadurch
    # nicht mehrfach die volle Wartezeit blockieren.
    max_network_retries = 1
    network_retries = 0
    t0 = time.monotonic()
    backoff = 2.0
    total_waited = 0.0
    max_total_wait = 70.0
    resp = None
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        last_exc = None
        try:
            resp = session.post(url, params={"key": api_key}, json=body, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "Gemini: Netzwerkfehler/Timeout bei %s nach %.1fs (%s): %s",
                label, time.monotonic() - t0, type(exc).__name__, exc,
            )
            if network_retries >= max_network_retries:
                break
            network_retries += 1
            wait = min(backoff, max_total_wait - total_waited) if total_waited < max_total_wait else 0.0
            backoff = min(backoff * 2, 20)
            logger.info(
                "Gemini: Erneuter Versuch für %s nach Netzwerkfehler (%d/%d) – warte %.0fs",
                label, network_retries, max_network_retries, wait,
            )
            if wait:
                time.sleep(wait)
                total_waited += wait
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if total_waited >= max_total_wait or attempt == max_attempts - 1:
                break
            wait = _server_retry_delay(resp) if resp.status_code == 429 else None
            source = "vom Server empfohlen"
            if wait is None:
                wait, source = backoff, "geschätzt"
                backoff = min(backoff * 2, 20)
            wait = min(wait, max_total_wait - total_waited)
            logger.info(
                "Gemini: HTTP %s für %s, Versuch %d/%d – warte %.0fs (%s)",
                resp.status_code, label, attempt + 1, max_attempts, wait, source,
            )
            time.sleep(wait)
            total_waited += wait
            continue
        break
    if last_exc is not None or resp is None or not resp.ok:
        status = resp.status_code if resp is not None else "?"
        logger.warning(
            "Gemini: Anfrage für %s endgültig fehlgeschlagen (HTTP %s) nach %.1fs",
            label, status, time.monotonic() - t0,
        )
        return None
    logger.info("Gemini: %s beantwortet in %.1fs", label, time.monotonic() - t0)
    return resp


def analyze_sentence(
    sentence: str,
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    session: requests.Session | None = None,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    """Einen einzelnen japanischen Satz per Gemini analysieren (ein Request).

    Für mehrere Sätze `analyze_sentences()` verwenden (ein Batch-Request statt
    vieler Einzel-Requests). Gibt bei fehlendem Text/Key, Netzwerkfehler,
    Rate-Limit/Quota oder kaputter/unerwarteter Antwort `None` zurück statt
    eine Exception zu werfen – der Aufrufer fällt dann für diesen Satz auf
    Janome zurück.
    """
    sentence = sentence.strip()
    if not sentence or not api_key:
        return None
    return analyze_sentences([sentence], api_key, model=model, session=session, use_cache=use_cache).get(sentence)


def analyze_sentences(
    sentences: Sequence[str],
    api_key: str,
    *,
    model: str = DEFAULT_MODEL,
    session: requests.Session | None = None,
    use_cache: bool = True,
) -> dict[str, dict[str, Any] | None]:
    """Mehrere Sätze in möglichst wenigen Gemini-Requests analysieren lassen
    (ein Batch-Request pro bis zu `_BATCH_CHUNK_SIZE` noch nicht gecachten
    Sätzen, statt einem Request pro Satz).

    Gibt ein dict `{satz: ergebnis_oder_None}` zurück – für jeden übergebenen,
    nicht-leeren Satz garantiert ein Eintrag. `None` bei allem, was fehl-
    schlägt (Aufrufer fällt für genau diesen Satz auf Janome zurück).
    """
    unique = list(dict.fromkeys(s.strip() for s in sentences if s and s.strip()))
    results: dict[str, dict[str, Any] | None] = {}
    if not unique or not api_key:
        return dict.fromkeys(unique)

    todo: list[str] = []
    for s in unique:
        cached = _read_cache(s, model) if use_cache else None
        if cached is not None:
            results[s] = cached
        else:
            todo.append(s)
    if not todo:
        return results

    session = session or requests.Session()
    for i in range(0, len(todo), _BATCH_CHUNK_SIZE):
        chunk = todo[i : i + _BATCH_CHUNK_SIZE]
        chunk_results = _analyze_batch(chunk, api_key, model=model, session=session)
        for s in chunk:
            result = chunk_results.get(s)
            results[s] = result
            if result is not None and use_cache:
                _write_cache(s, model, result)
    return results


def _analyze_batch(
    sentences: list[str], api_key: str, *, model: str, session: requests.Session
) -> dict[str, dict[str, Any] | None]:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    body = {
        "contents": [{"parts": [{"text": _BATCH_PROMPT_TEMPLATE.format(sentences=numbered)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _BATCH_RESPONSE_SCHEMA,
        },
    }
    url = f"{_API_BASE}/models/{model}:generateContent"
    label = f"Batch mit {len(sentences)} Satz/Sätzen ({model})"
    logger.info("Gemini: Anfrage für %s …", label)
    resp = _post_with_retry(url, api_key, body, session, label, timeout=_batch_read_timeout(len(sentences)))
    if resp is None:
        return dict.fromkeys(sentences)

    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        payload = json.loads(text)
        items = payload["sentences"]
        if not isinstance(items, list):
            raise TypeError("'sentences' ist keine Liste")
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Gemini: Antwort für %s nicht auswertbar (%s): %s", label, type(exc).__name__, exc)
        return dict.fromkeys(sentences)

    by_sentence: dict[str, dict[str, Any] | None] = dict.fromkeys(sentences)
    for item in items:
        if not isinstance(item, dict):
            continue
        sentence = item.get("sentence")
        tokens = item.get("tokens")
        if sentence in by_sentence and isinstance(tokens, list):
            by_sentence[sentence] = {
                "tokens": tokens,
                "grammar_notes": item.get("grammar_notes") or "",
                "translation_de": item.get("translation_de") or "",
            }
    missing = [s for s, r in by_sentence.items() if r is None]
    if missing:
        logger.warning("Gemini: %d von %d Sätzen fehlen in der Antwort für %s", len(missing), len(sentences), label)
    return by_sentence


def list_models(api_key: str, *, session: requests.Session | None = None) -> list[str] | None:
    """Für Text-Chat geeignete Gemini-Modelle live über die API abrufen
    (`ListModels`), statt eine feste Liste im Code zu pflegen – Google fügt
    neue Modelle hinzu und deprecatet alte regelmäßig (siehe DEFAULT_MODEL).

    Gibt `None` zurück bei fehlendem Key/Netzwerkfehler/kaputter Antwort
    (Aufrufer zeigt dann die hartcodierten AVAILABLE_MODELS als Fallback).
    """
    if not api_key:
        return None
    session = session or requests.Session()
    try:
        resp = session.get(f"{_API_BASE}/models", params={"key": api_key}, timeout=_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Gemini: Modell-Liste nicht abrufbar (%s): %s", type(exc).__name__, exc)
        return None
    if not resp.ok:
        logger.warning("Gemini: Modell-Liste-Request fehlgeschlagen (HTTP %s)", resp.status_code)
        return None
    try:
        models = resp.json().get("models", [])
    except ValueError:
        return None

    names: list[str] = []
    for m in models:
        name = str(m.get("name", "")).removeprefix("models/")
        methods = m.get("supportedGenerationMethods") or []
        if not name.startswith("gemini-") or "generateContent" not in methods:
            continue
        if any(token in name for token in _MODEL_EXCLUDE_TOKENS):
            continue
        names.append(name)
    return sorted(set(names))


# --------------------------------------------------------------------------- #
# Text-to-Speech (KI-Modus: Original-Satz vorlesen)
# --------------------------------------------------------------------------- #

# Gemini-eigenes Audio-Ausgabemodell statt einer separaten Google-Cloud-
# Text-to-Speech-API: nutzt denselben Gemini-Key, den es für die Satzanalyse
# schon braucht, statt einen zweiten API-Zugang extra aktivieren zu müssen.
# Aktuell ein Preview-Modell bei Google (kann sich ändern/deprecaten wie die
# Chat-Modelle auch).
TTS_MODEL = "gemini-2.5-flash-preview-tts"
# Stimme ist sprachunabhängig (Gemini erkennt Japanisch automatisch am Text) -
# "Kore" ist eine der von Google dokumentierten Standardstimmen.
TTS_VOICE = "Kore"

_TTS_CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache")) / "gemini_tts"

_RATE_RE = re.compile(r"rate=(\d+)")


def _tts_cache_path(text: str, model: str, voice: str) -> Path:
    key = hashlib.sha1(f"{model}\n{voice}\n{text}".encode("utf-8")).hexdigest()
    return _TTS_CACHE_DIR / f"{key}.wav"


def _pcm_to_wav(pcm: bytes, *, sample_rate: int, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Gemini liefert rohe PCM-Samples (kein Container) – Browser/Anki können
    das nicht direkt abspielen, deshalb hier in einen minimalen WAV-Container
    (RIFF-Header) verpackt."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample)
        + b"data" + struct.pack("<I", len(pcm))
    )
    return header + pcm


def synthesize_speech(
    text: str,
    api_key: str,
    *,
    model: str = TTS_MODEL,
    voice: str = TTS_VOICE,
    session: requests.Session | None = None,
    use_cache: bool = True,
) -> bytes | None:
    """Text (i. d. R. ein japanischer Satz) per Gemini vorlesen lassen –
    gibt fertige WAV-Bytes zurück oder `None` bei fehlendem Text/Key,
    Netzwerkfehler, Quota oder kaputter Antwort (nie eine Exception, fail-soft
    wie der Rest dieses Moduls)."""
    text = text.strip()
    if not text or not api_key:
        return None

    cache_file = _tts_cache_path(text, model, voice) if use_cache else None
    if cache_file and cache_file.is_file():
        try:
            return cache_file.read_bytes()
        except OSError:
            pass

    session = session or requests.Session()
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    url = f"{_API_BASE}/models/{model}:generateContent"
    label = f"TTS für {len(text)} Zeichen ({model})"
    resp = _post_with_retry(url, api_key, body, session, label)
    if resp is None:
        return None

    try:
        part = resp.json()["candidates"][0]["content"]["parts"][0]
        inline = part["inlineData"]
        pcm = base64.b64decode(inline["data"])
        rate_match = _RATE_RE.search(inline.get("mimeType") or "")
        sample_rate = int(rate_match.group(1)) if rate_match else 24000
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gemini: TTS-Antwort für %s nicht auswertbar (%s): %s", label, type(exc).__name__, exc)
        return None

    wav = _pcm_to_wav(pcm, sample_rate=sample_rate)
    if cache_file:
        try:
            _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(wav)
        except OSError:
            pass
    return wav


# --------------------------------------------------------------------------- #
# Bild-Transkription (PDF-Import: Seiten ohne Textlayer, direkt hochgeladene
# Bilder) – siehe pdf_import.py
# --------------------------------------------------------------------------- #

_OCR_CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache")) / "gemini_ocr"

_OCR_PROMPT = """Transkribiere GENAU den japanischen (und ggf. deutschen/englischen) Text in diesem Bild.
Gib NUR den reinen Text zurück, Zeile für Zeile wie im Bild angeordnet -
keine Übersetzung, keine Erklärung, keine Markdown-Formatierung, keine
Anführungszeichen drumherum. Furigana (kleine Lesehilfen über oder neben
Kanji) NICHT mit ausgeben, nur den eigentlichen Haupttext. Ist kein
lesbarer Text im Bild, gib einen leeren String zurück."""


def _ocr_cache_path(image_bytes: bytes, model: str) -> Path:
    key = hashlib.sha1(model.encode("utf-8") + b"\0" + image_bytes).hexdigest()
    return _OCR_CACHE_DIR / f"{key}.txt"


def transcribe_image(
    image_bytes: bytes,
    api_key: str,
    *,
    mime_type: str = "image/png",
    model: str = DEFAULT_MODEL,
    session: requests.Session | None = None,
    use_cache: bool = True,
) -> str | None:
    """Text aus einem Bild transkribieren (OCR per Gemini) – für PDF-Seiten
    ohne Textlayer oder direkt hochgeladene Bilder (siehe `pdf_import.py`).
    Nutzt dasselbe Chat-Modell wie die Satzanalyse statt eines separaten
    OCR-Produkts (z. B. Google Cloud Vision) – ein Key reicht für alles.

    Gibt den transkribierten Text zurück (leerer String, wenn nichts
    lesbar war), oder `None` bei fehlendem Bild/Key, Netzwerkfehler, Quota
    oder kaputter Antwort (fail-soft wie der Rest dieses Moduls)."""
    if not image_bytes or not api_key:
        return None

    cache_file = _ocr_cache_path(image_bytes, model) if use_cache else None
    if cache_file and cache_file.is_file():
        try:
            return cache_file.read_text(encoding="utf-8")
        except OSError:
            pass

    session = session or requests.Session()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "contents": [{"parts": [
            {"text": _OCR_PROMPT},
            {"inlineData": {"mimeType": mime_type, "data": b64}},
        ]}],
    }
    url = f"{_API_BASE}/models/{model}:generateContent"
    label = f"Bild-Transkription ({len(image_bytes)} Bytes, {model})"
    resp = _post_with_retry(url, api_key, body, session, label)
    if resp is None:
        return None

    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gemini: Transkriptions-Antwort für %s nicht auswertbar (%s): %s", label, type(exc).__name__, exc)
        return None

    text = (text or "").strip()
    if cache_file:
        try:
            _OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return text


# --------------------------------------------------------------------------- #
# Bildkarten: Clipart-Bild für eine Vokabel generieren (Vorderseite = nur
# Bild + Wort statt Text) – siehe webapp.api_gemini_generate_image()
# --------------------------------------------------------------------------- #

# Eigenes Bild-Modell statt des Text-Chat-Modells der Satzanalyse (siehe
# DEFAULT_MODEL) – nur bestimmte Gemini-Modelle können überhaupt Bilder
# erzeugen, "-latest"-Text-Aliase können das nicht. Bewusst keine "-latest"-
# Variante: für Bildgenerierung pflegt Google (Stand jetzt) keinen stabilen
# Alias, die konkrete Modellversion muss direkt benannt werden.
IMAGE_MODEL = "gemini-2.5-flash-image"

_IMAGE_PROMPT_TEMPLATE = """Erstelle ein einfaches, flaches Clipart-/Icon-Bild (KEIN Foto, KEIN Text, \
KEINE Schriftzeichen im Bild), das den Begriff "{meaning}" (japanisch: {word}) \
klar und eindeutig darstellt. Ein einzelnes zentrales Motiv, reduzierter \
freundlicher Icon-Stil, schlichter oder transparenter Hintergrund – \
geeignet als Vorderseite einer Lernkarteikarte."""


def generate_image(
    word: str,
    meaning: str,
    api_key: str,
    *,
    model: str = IMAGE_MODEL,
    session: requests.Session | None = None,
) -> tuple[bytes, str] | None:
    """Ein einfaches Clipart-Bild für eine Vokabel generieren (Bildkarten-
    Feature) – gibt `(bild_bytes, mime_type)` zurück oder `None` bei
    fehlendem Wort/Key, Netzwerkfehler, Quota oder Antwort ohne Bild.

    Bewusst UNGECACHT (anders als `transcribe_image`/`synthesize_speech`):
    Bildgenerierung ist nicht deterministisch, der "Neu generieren"-Button im
    Frontend soll bei jedem Klick tatsächlich ein neues Ergebnis anfragen
    statt denselben gecachten Treffer zurückzubekommen."""
    if not word or not api_key:
        return None
    session = session or requests.Session()
    prompt = _IMAGE_PROMPT_TEMPLATE.format(meaning=meaning or word, word=word)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    url = f"{_API_BASE}/models/{model}:generateContent"
    label = f"Bildgenerierung ({word}, {model})"
    resp = _post_with_retry(url, api_key, body, session, label)
    if resp is None:
        return None

    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gemini: Bildgenerierungs-Antwort für %s nicht auswertbar (%s): %s", label, type(exc).__name__, exc)
        return None

    for part in parts:
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            try:
                return base64.b64decode(inline["data"]), inline.get("mimeType") or "image/png"
            except (ValueError, TypeError):
                return None
    logger.warning("Gemini: Antwort für %s enthielt kein Bild.", label)
    return None
