#!/usr/bin/env python3
"""dictionary.py – JMdict-Anbindung für Wörter, die WaniKani nicht kennt.

WaniKani indiziert Vokabeln über ihre Kanji-Schreibweise (der `slug`). Ein
Wort, das im Text nur in Hiragana vorkommt (z. B. „しあい" statt „試合" – wie
in vereinfachten Lesetexten, etwa NHK Easy News), matcht dort nie – ist aber
trotzdem ein ganz normales, lernwertes Wort. Für genau diesen Fall wird hier
JMdict (offenes JA-DE-Wörterbuch, https://www.edrdg.org/, deutsche Glosse aus
dem German Edition-Release von jmdict-simplified) über die Lesung statt die
Kanji-Schreibweise nachgeschlagen.

Kein `jamdict`-Paket: der offizielle JMdict-Wrapper lässt sich wegen eines
veralteten `setup.py`-Build-Prozesses (`puchikarui`/`chirptext`) in vielen
Umgebungen nicht zuverlässig installieren. Stattdessen wird die rohe JSON-
Distribution von [jmdict-simplified](https://github.com/scriptin/jmdict-simplified)
einmalig heruntergeladen und in einen kompakten Lesungs-Index umgewandelt,
der lokal gecacht wird (danach kein Netzwerk mehr nötig).
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

import requests

CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache"))
JMDICT_DIR = CACHE_DIR / "jmdict"
JMDICT_INDEX_FILE = CACHE_DIR / "jmdict_index_de.json"

_RELEASES_API = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"
_ASSET_PREFIX = "jmdict-ger-"
_ASSET_SUFFIX = ".json.zip"
_GLOSS_LANG = "ger"


class DictionaryError(Exception):
    """Verständlicher Fehler ohne Stacktrace, wenn JMdict nicht verfügbar ist."""


def _find_asset(session: requests.Session) -> tuple[str, str]:
    """Neuestes `jmdict-ger-*.json.zip`-Release-Asset (deutsche Edition) über
    die GitHub-API finden.

    Der Dateiname trägt Version+Zeitstempel (`jmdict-ger-3.6.1+20260101.json.zip`)
    und ändert sich mit jedem Release – deshalb dynamisch über die
    releases/latest-API auflösen statt eine feste URL zu hinterlegen.
    """
    try:
        resp = session.get(
            _RELEASES_API, timeout=30, headers={"Accept": "application/vnd.github+json"}
        )
    except requests.RequestException as exc:
        raise DictionaryError(f"JMdict-Release nicht erreichbar: {exc}") from exc
    if not resp.ok:
        raise DictionaryError(
            f"JMdict-Release konnte nicht ermittelt werden (HTTP {resp.status_code})."
        )
    data = resp.json()
    for asset in data.get("assets", []) or []:
        name = asset.get("name", "")
        if name.startswith(_ASSET_PREFIX) and name.endswith(_ASSET_SUFFIX):
            url = asset.get("browser_download_url")
            if url:
                return name, url
    raise DictionaryError("Kein passendes JMdict-ger-Release-Asset gefunden.")


def download_jmdict(*, session: requests.Session | None = None) -> Path:
    """JMdict (Deutsch, ohne Beispielsätze) als JSON herunterladen und entpacken.

    Läuft nur einmal – das Zip (~15–20 MB) und die entpackte JSON bleiben unter
    `.cache/jmdict/` liegen, ein erneuter Aufruf lädt nichts neu herunter.
    """
    session = session or requests.Session()
    name, url = _find_asset(session)
    JMDICT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = JMDICT_DIR / name
    if not zip_path.is_file():
        try:
            resp = session.get(url, timeout=180)
        except requests.RequestException as exc:
            raise DictionaryError(f"JMdict-Download fehlgeschlagen: {exc}") from exc
        if not resp.ok:
            raise DictionaryError(f"JMdict-Download fehlgeschlagen (HTTP {resp.status_code}).")
        tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
        tmp_path.write_bytes(resp.content)
        tmp_path.rename(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        json_names = [n for n in zf.namelist() if n.endswith(".json")]
        if not json_names:
            raise DictionaryError("JMdict-ZIP enthält keine JSON-Datei.")
        json_path = JMDICT_DIR / json_names[0]
        if not json_path.is_file():
            zf.extract(json_names[0], JMDICT_DIR)
    return json_path


# Wie viele Bedeutungen (gloss-Einträge) der ersten Sense maximal übernommen
# werden – reicht für die Kartenrückseite, ohne den ganzen Wörterbucheintrag
# abzudrucken.
MAX_GLOSSES = 4


def _split_primary_and_note(gloss: str) -> tuple[str, str | None]:
    """Eine JMdict-DE-Glosse in Kernbedeutung + Erläuterung trennen.

    Die deutsche Edition packt Nutzungshinweise oft direkt in Klammern hinter
    die eigentliche Bedeutung, z. B. „ich (vertraulich im Ton; Männersprache;
    kam in dieser Bedeutung während der Meiji-Zeit unter Studenten auf und
    ging dann in die Umgangssprache über)". Für die Karte zählt nur „ich" als
    Bedeutung – der Rest ist Zusatzerklärung, keine weitere Übersetzung.
    """
    gloss = gloss.strip()
    if "(" in gloss and gloss.endswith(")"):
        primary, _, rest = gloss.partition("(")
        primary = primary.strip().rstrip(",;").strip()
        note = rest[:-1].strip()
        if primary and note:
            return primary, note
    return gloss, None


def build_reading_index(json_path: Path) -> dict[str, dict[str, Any]]:
    """Rohe JMdict-JSON in einen kompakten Lesungs-Index umwandeln.

    `{"しあい": {"kanji": "試合", "meaning": "Spiel", "meaning_extra": "Wettkampf"}, …}`
    `meaning` ist bewusst nur die *erste, kurze* Glosse (das ist die eigentliche
    Bedeutung für die Kartenvorderseite/den Titel); alles Weitere – zusätzliche
    Glossen der ersten Sense sowie in Klammern angehängte Nutzungshinweise –
    landet in `meaning_extra` als kleinere Zusatzerklärung. Nur die *erste*
    Sense wird übernommen; bei mehreren Wörtern mit derselben Lesung gewinnt
    das erste (JMdict listet gebräuchliche Wörter zuerst).
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    index: dict[str, dict[str, Any]] = {}
    for word in data.get("words", []):
        kana_texts = [k.get("text") for k in word.get("kana", []) if k.get("text")]
        if not kana_texts:
            continue
        kanji_texts = [k.get("text") for k in word.get("kanji", []) if k.get("text")]
        glosses: list[str] = []
        for sense in word.get("sense", []):
            sense_glosses = [
                g.get("text")
                for g in sense.get("gloss", [])
                if g.get("lang") == _GLOSS_LANG and g.get("text")
            ]
            if sense_glosses:
                glosses = sense_glosses
                break
        if not glosses:
            continue
        primary, note = _split_primary_and_note(glosses[0])
        extra_parts = ([note] if note else []) + glosses[1:MAX_GLOSSES]
        meaning_extra = "; ".join(extra_parts) if extra_parts else None
        for kana in kana_texts:
            if kana not in index:
                index[kana] = {
                    "kanji": kanji_texts[0] if kanji_texts else None,
                    "meaning": primary,
                    "meaning_extra": meaning_extra,
                }
    return index


def _load_or_build_index(*, session: requests.Session | None = None) -> dict[str, dict[str, Any]]:
    if JMDICT_INDEX_FILE.is_file():
        try:
            return json.loads(JMDICT_INDEX_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    json_path = download_jmdict(session=session)
    index = build_reading_index(json_path)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    JMDICT_INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


_index_cache: dict[str, dict[str, Any]] | None = None


def get_index(*, session: requests.Session | None = None) -> dict[str, dict[str, Any]]:
    """Lesungs-Index lazy laden (Prozess-Singleton – nur einmal pro Lauf gebaut)."""
    global _index_cache
    if _index_cache is None:
        _index_cache = _load_or_build_index(session=session)
    return _index_cache


def lookup_reading(word: str) -> dict[str, Any] | None:
    """Wort (Hiragana/Katakana-Lesung) im JMdict-Index nachschlagen.

    Gibt `{"kanji": str|None, "meaning": str}` zurück oder `None`, wenn nichts
    gefunden wurde (dann bleibt das Wort im Text-Modus einfach unmarkiert).
    """
    try:
        return get_index().get(word)
    except DictionaryError:
        return None


# --------------------------------------------------------------------------- #
# DeepL: optionale Satzübersetzung für Dictionary-Karten
# --------------------------------------------------------------------------- #

_DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
_DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"


def translate_sentence(
    text: str,
    api_key: str,
    *,
    target_lang: str = "DE",
    session: requests.Session | None = None,
) -> str | None:
    """Satz per DeepL übersetzen (Default: Deutsch, passend zur restlichen App-Sprache).

    Gibt bei fehlendem Text/Key, Netzwerkfehler oder unerwarteter Antwort
    `None` zurück statt einer Exception – die Karte wird dann trotzdem
    erstellt, nur ohne Satzübersetzung (dieselbe „nie hart abbrechen"-Logik
    wie beim restlichen Projekt).
    """
    if not text or not api_key:
        return None
    session = session or requests.Session()
    url = _DEEPL_FREE_URL if api_key.endswith(":fx") else _DEEPL_PRO_URL
    try:
        resp = session.post(
            url,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            data={"text": text, "target_lang": target_lang, "source_lang": "JA"},
            timeout=20,
        )
    except requests.RequestException:
        return None
    if not resp.ok:
        return None
    try:
        data = resp.json()
        return data["translations"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
