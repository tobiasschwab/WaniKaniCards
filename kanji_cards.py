#!/usr/bin/env python3
"""kanji_cards.py – erzeugt doppelseitig bedruckbare Kanji-Karteikarten (PDF)
aus einem WaniKani-Level.

Aufruf:
    python kanji_cards.py <level> [--output cards.pdf]

Vorderseite: nur das Kanji, groß und zentriert.
Rückseite:   Bedeutungen, Lesungen (On/Kun), eine Beispielvokabel und ein
             Beispielsatz.

Siehe CLAUDE.md für Details zur Architektur.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv ist optional
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:  # type: ignore
        return False


# --------------------------------------------------------------------------- #
# Konstanten
# --------------------------------------------------------------------------- #

WK_BASE_URL = "https://api.wanikani.com/v2/"
WK_REVISION = "20170710"
# Cache-Verzeichnis; per Env überschreibbar (z. B. für den Docker-Container).
CACHE_DIR = Path(os.environ.get("WKCARDS_CACHE_DIR", ".cache"))

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_DIR = HERE / "templates"
DEFAULT_FONT_DIR = HERE / "fonts"

# Standard-Schriften (im Repo unter fonts/ abgelegt)
DEFAULT_KANJI_FONT = DEFAULT_FONT_DIR / "NotoSerifJP-SemiBold.ttf"
DEFAULT_SANS_FONT = DEFAULT_FONT_DIR / "NotoSansJP-Regular.ttf"
DEFAULT_SANS_BOLD_FONT = DEFAULT_FONT_DIR / "NotoSansJP-Bold.ttf"

# WaniKani-Markup, das in Textfeldern auftauchen kann → strippen.
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


class WaniKaniError(RuntimeError):
    """Verständlicher Fehler ohne Stacktrace für den Nutzer."""


# --------------------------------------------------------------------------- #
# Datenmodell
# --------------------------------------------------------------------------- #

@dataclass
class Card:
    """Alle Daten, die eine einzelne Kanji-Karteikarte benötigt."""

    kanji: str
    meanings: list[str] = field(default_factory=list)
    onyomi: list[str] = field(default_factory=list)
    kunyomi: list[str] = field(default_factory=list)
    meaning_mnemonic: str | None = None
    reading_mnemonic: str | None = None
    vocab: str | None = None
    vocab_reading: str | None = None
    vocab_meaning: str | None = None
    vocab_audio_url: str | None = None
    sentence_ja: str | None = None
    sentence_en: str | None = None
    sentence_audio_url: str | None = None
    # Weitere Beispielsätze (über den ersten hinaus). Je Eintrag:
    # {"ja": str, "en": str, "audio_url": str|None}
    extra_sentences: list[dict[str, Any]] = field(default_factory=list)
    # Link zur WaniKani-Seite des Kanji.
    document_url: str | None = None
    # Zusammensetzung: die Radicals, aus denen das Kanji besteht.
    # Je Eintrag: {"radical": str, "image_uri": str|None, "meaning": str}
    components: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # WaniKani-Subject-ID (falls bekannt) – für stabile Anki-Notiz-IDs beim
    # Export, damit ein erneuter Export bestehende Notizen aktualisiert statt
    # sie zu duplizieren.
    subject_id: int | None = None


@dataclass
class CoverCard:
    """Deckkarte des Stapels: vorne Titel/Level, hinten die Übersicht."""

    title: str
    subtitle: str
    kind: str = "Kanji"  # Untertitel: "Kanji" oder "Radicals"
    entries: list[tuple[str, str]] = field(default_factory=list)  # (Zeichen, Bedeutung)


@dataclass
class RadicalCard:
    """Karte für ein Radical: vorne das Zeichen/Bild, hinten Bedeutung + Merkhilfe."""

    radical: str = ""                       # Unicode-Zeichen (kann leer sein)
    image_uri: str | None = None            # data:-URI des Radical-Bildes (Fallback)
    meaning: str = ""
    mnemonic: str | None = None
    # (Kanji, primäre Lesung, primäre Bedeutung) der ersten zugehörigen Kanji
    kanji_examples: list[tuple[str, str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    subject_id: int | None = None
    # Link zur WaniKani-Seite des Radicals.
    document_url: str | None = None


@dataclass
class VocabCard:
    """Karte für eine Vokabel: vorne das Wort, hinten Lesung/Bedeutung/Merkhilfe."""

    vocab: str = ""
    readings: list[str] = field(default_factory=list)
    meanings: list[str] = field(default_factory=list)
    parts_of_speech: list[str] = field(default_factory=list)
    meaning_mnemonic: str | None = None
    reading_mnemonic: str | None = None
    audio_url: str | None = None
    sentence_ja: str | None = None
    sentence_en: str | None = None
    sentence_audio_url: str | None = None
    extra_sentences: list[dict[str, Any]] = field(default_factory=list)
    document_url: str | None = None
    tags: list[str] = field(default_factory=list)
    subject_id: int | None = None


@dataclass
class CustomCard:
    """Frei erstellte Karte: Vorder- und Rückseite als frei formatiertes HTML.

    Formatierung und Bilder stecken direkt im HTML (aus dem Editor). Nur die
    Tags werden separat geführt und immer vorne oben rechts gedruckt.
    """

    front_html: str = ""
    back_html: str = ""
    tags: list[str] = field(default_factory=list)
    # ID der Karte in customcards/ (falls gespeichert) – für stabile Anki-IDs.
    card_id: str | None = None


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

def strip_markup(text: str | None) -> str | None:
    """Entfernt WaniKani-Tags (<kanji>, <ja>, <reading> …) defensiv."""
    if text is None:
        return None
    return _TAG_RE.sub("", text).strip()


def _lower_first(text: str) -> str:
    """Ersten Buchstaben klein schreiben (WaniKani liefert Meanings groß, z. B. 'Fins')."""
    return text[:1].lower() + text[1:] if text else text


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# WaniKani-Client
# --------------------------------------------------------------------------- #

class WaniKaniClient:
    """Dünner Client für die relevanten /subjects-Aufrufe.

    Kümmert sich um Auth-Header, Revision-Header, 429/5xx-Backoff und einen
    einfachen JSON-Cache unter .cache/.
    """

    def __init__(
        self,
        token: str,
        *,
        use_cache: bool = True,
        cache_dir: Path = CACHE_DIR,
        session: requests.Session | None = None,
    ) -> None:
        self.token = token
        self.use_cache = use_cache
        self.cache_dir = cache_dir
        self.session = session or requests.Session()

    # -- interne Helfer ---------------------------------------------------- #

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Wanikani-Revision": WK_REVISION,
        }

    def _cache_path(self, key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
        return self.cache_dir / f"{safe}.json"

    def _cache_read(self, key: str) -> Any | None:
        if not self.use_cache:
            return None
        path = self._cache_path(key)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _cache_write(self, key: str, value: Any) -> None:
        if not self.use_cache:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._cache_path(key).write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass  # Cache ist best-effort, nie hart abbrechen

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ein GET auf die WaniKani-API mit Backoff bei 429/5xx."""
        url = path if path.startswith("http") else WK_BASE_URL + path.lstrip("/")
        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                resp = self.session.get(
                    url, headers=self._headers(), params=params, timeout=30
                )
            except requests.RequestException as exc:  # Netzwerkfehler
                last_exc = exc
                time.sleep(backoff)
                backoff = min(backoff * 2, 16)
                continue

            if resp.status_code == 401:
                raise WaniKaniError(
                    "WaniKani lehnt den Token ab (401). Bitte WANIKANI_API_TOKEN prüfen."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                # Rate-Limit oder Serverfehler → warten und erneut versuchen
                time.sleep(backoff)
                backoff = min(backoff * 2, 16)
                continue
            if not resp.ok:
                raise WaniKaniError(
                    f"WaniKani-Anfrage fehlgeschlagen ({resp.status_code}): {resp.text[:200]}"
                )
            return resp.json()

        raise WaniKaniError(
            f"WaniKani nicht erreichbar nach mehreren Versuchen ({last_exc})."
        )

    def _fetch_all(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Folgt der Paginierung (`pages.next_url`) und sammelt alle `data`."""
        results: list[dict[str, Any]] = []
        page = self._request(path, params)
        results.extend(page.get("data", []))
        next_url = (page.get("pages") or {}).get("next_url")
        while next_url:
            page = self._request(next_url)
            results.extend(page.get("data", []))
            next_url = (page.get("pages") or {}).get("next_url")
        return results

    # -- öffentliche API --------------------------------------------------- #

    def search_subjects(self, query: str) -> list[dict[str, Any]]:
        """Subjects über den `slugs`-Filter suchen.

        Für Kanji/Vokabeln entspricht der Slug den Zeichen (z. B. „一人"), für
        Radicals dem englischen Namen (z. B. „ground"). Nicht gecacht.
        """
        query = query.strip()
        if not query:
            return []
        return self._fetch_all("subjects", {"slugs": query})

    def fetch_kanji(self, level: int) -> list[dict[str, Any]]:
        """Alle Kanji-Subjects eines Levels holen (mit Cache)."""
        key = f"kanji_level_{level}"
        cached = self._cache_read(key)
        if cached is not None:
            return cached
        data = self._fetch_all(
            "subjects", {"types": "kanji", "levels": str(level)}
        )
        self._cache_write(key, data)
        return data

    def fetch_radicals(self, level: int) -> list[dict[str, Any]]:
        """Alle Radical-Subjects eines Levels holen (mit Cache)."""
        key = f"radical_level_{level}"
        cached = self._cache_read(key)
        if cached is not None:
            return cached
        data = self._fetch_all(
            "subjects", {"types": "radical", "levels": str(level)}
        )
        self._cache_write(key, data)
        return data

    def fetch_vocabulary(self, level: int) -> list[dict[str, Any]]:
        """Alle Vokabel-Subjects eines Levels holen (mit Cache)."""
        key = f"vocabulary_level_{level}"
        cached = self._cache_read(key)
        if cached is not None:
            return cached
        data = self._fetch_all(
            "subjects", {"types": "vocabulary", "levels": str(level)}
        )
        self._cache_write(key, data)
        return data

    def fetch_subjects(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        """Beliebige Subjects gebündelt nach IDs nachladen → Map {id: subject}.

        Nur nicht-gecachte IDs werden nachgeladen; die Anfrage wird in Batches
        aufgeteilt, um sehr lange URLs zu vermeiden.
        """
        want = sorted({int(i) for i in ids})
        result: dict[int, dict[str, Any]] = {}
        missing: list[int] = []
        for sid in want:
            cached = self._cache_read(f"subject_{sid}")
            if cached is not None:
                result[sid] = cached
            else:
                missing.append(sid)

        BATCH = 200  # großzügig unterhalb der URL-Längenlimits
        for start in range(0, len(missing), BATCH):
            batch = missing[start : start + BATCH]
            # WICHTIG: beim /subjects-Endpoint heißt der ID-Filter `ids`.
            data = self._fetch_all(
                "subjects", {"ids": ",".join(str(i) for i in batch)}
            )
            for subject in data:
                sid = int(subject["id"])
                result[sid] = subject
                self._cache_write(f"subject_{sid}", subject)
        return result

    # Rückwärtskompatibler Alias (Vokabeln sind auch nur Subjects).
    fetch_vocab = fetch_subjects

    def fetch_image_data_uri(self, url: str) -> str | None:
        """Ein Radical-Bild laden und als data:-URI zurückgeben (best-effort).

        Bei Netzwerk-/Zugriffsfehlern wird still `None` zurückgegeben – die
        Karte wird dann ohne Bild erzeugt.
        """
        import base64

        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=30)
            except requests.RequestException:
                time.sleep(1.0 * (attempt + 1))
                continue
            if resp.ok:
                ctype = resp.headers.get("Content-Type", "image/png").split(";")[0]
                b64 = base64.b64encode(resp.content).decode("ascii")
                return f"data:{ctype};base64,{b64}"
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(1.0 * (attempt + 1))
                continue
            break
        return None

    # Content-Type-agnostisch (nutzt den echten Content-Type-Header) – derselbe
    # Fetcher lädt daher auch Vertonungen (mp3/ogg) als data:-URI herunter, die
    # dann direkt im Anki-Feld abspielbar sind (voll offline, kein Streaming
    # vom WaniKani-Server nötig).
    fetch_audio_data_uri = fetch_image_data_uri


# --------------------------------------------------------------------------- #
# Modell-Aufbau
# --------------------------------------------------------------------------- #

def _primary_first(
    items: Sequence[dict[str, Any]], key: str, lower_first: bool = False
) -> list[str]:
    """Werte extrahieren, primäre Einträge zuerst, Reihenfolge sonst erhalten."""
    primary = [strip_markup(i[key]) for i in items if i.get("primary")]
    rest = [strip_markup(i[key]) for i in items if not i.get("primary")]
    out = [v for v in (primary + rest) if v]
    if lower_first:
        out = [_lower_first(v) for v in out]
    # Duplikate entfernen, Reihenfolge erhalten
    seen: set[str] = set()
    result: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result


def pick_example_vocab(
    kanji: dict[str, Any], vocab_map: dict[int, dict[str, Any]]
) -> dict[str, Any] | None:
    """Repräsentative Beispielvokabel für ein Kanji wählen.

    Default: die Vokabel mit der niedrigsten `level`; bei Gleichstand die
    zuerst in `amalgamation_subject_ids` genannte.
    """
    data = kanji.get("data", {})
    ids = data.get("amalgamation_subject_ids") or []
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for order, sid in enumerate(ids):
        vocab = vocab_map.get(int(sid))
        if not vocab:
            continue
        # Nur echte Vokabeln berücksichtigen (nicht z. B. Kana-Vocab ohne Sätze)
        vlevel = vocab.get("data", {}).get("level", 9999)
        candidates.append((vlevel, order, vocab))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][2]


def _default_tags(kind: str, data: dict[str, Any]) -> list[str]:
    """Standard-Tags einer Karte: Typ + WaniKani-Level (aus dem Subject)."""
    tags = [kind]
    level = data.get("level")
    if level is not None:
        tags.append(f"Lv {level}")
    return tags


def _pick_audio_url(audios: list[dict[str, Any]] | None) -> str | None:
    """Erste Audio-URL wählen (mp3 bevorzugt).

    Passt zu WaniKanis `pronunciation_audios` auf Vokabel-Subjects
    (`[{url, content_type, metadata}, …]`); dieselbe Struktur funktioniert
    auch für manuell nachgetragene Audios (z. B. für Beispielsätze, die
    WaniKani selbst nicht vertont).
    """
    if not audios:
        return None
    mp3 = next(
        (a for a in audios if a.get("content_type") == "audio/mpeg" and a.get("url")),
        None,
    )
    chosen = mp3 or next((a for a in audios if a.get("url")), None)
    return chosen.get("url") if chosen else None


def _resolve_audio_url(url: str | None, fetcher: "callable | None") -> str | None:
    """Audio-URL für den Anki-Export einbetten (herunterladen → data-URI).

    So funktionieren die Karten im Anki-Review komplett offline, ohne bei
    jeder Wiederholung vom WaniKani-Server zu streamen. Bereits eingebettete
    data-URIs (Sample-Daten) oder fehlender Fetcher (kein Netzwerk/PDF-Modus)
    lassen die URL unverändert; schlägt der Download fehl, bleibt die
    Original-URL als Fallback erhalten (funktioniert dann online weiter).
    """
    if not url or url.startswith("data:") or fetcher is None:
        return url
    return fetcher(url) or url


# Wie viele zusätzliche Beispielsätze (über den ersten hinaus) übernommen werden.
MAX_EXTRA_SENTENCES = 2


def _build_extra_sentences(
    sentences: list[dict[str, Any]], fetcher: "callable | None"
) -> list[dict[str, Any]]:
    """Beispielsätze 2..N (der erste läuft separat über sentence_ja/_en)."""
    out: list[dict[str, Any]] = []
    for s in sentences[:MAX_EXTRA_SENTENCES]:
        ja = strip_markup(s.get("ja"))
        if not ja:
            continue
        out.append(
            {
                "ja": ja,
                "en": strip_markup(s.get("en")) or "",
                "audio_url": _resolve_audio_url(_pick_audio_url(s.get("audios")), fetcher),
            }
        )
    return out


def _build_components(
    data: dict[str, Any],
    subject_map: dict[int, dict[str, Any]],
    image_fetcher: "callable | None" = None,
) -> list[dict[str, Any]]:
    """Die Radicals auflösen, aus denen ein Kanji zusammengesetzt ist.

    Nutzt `component_subject_ids`. Je Radical Zeichen + Bedeutung; fehlt ein
    Unicode-Zeichen, wird – sofern möglich – das eingebettete oder nachladbare
    Bild verwendet.
    """
    components: list[dict[str, Any]] = []
    for cid in data.get("component_subject_ids") or []:
        comp = subject_map.get(int(cid))
        if not comp:
            continue
        cdata = comp.get("data", {})
        cmeanings = _primary_first(cdata.get("meanings", []), "meaning", lower_first=True)
        char = strip_markup(cdata.get("characters")) or ""
        image_uri = cdata.get("_image_data_uri")
        if not char and not image_uri and image_fetcher is not None:
            images = cdata.get("character_images") or []
            png = next(
                (i for i in images if i.get("content_type") == "image/png"), None
            )
            chosen = png or (images[0] if images else None)
            if chosen and chosen.get("url"):
                image_uri = image_fetcher(chosen["url"])
        components.append(
            {
                "radical": char,
                "image_uri": image_uri,
                "meaning": cmeanings[0] if cmeanings else "",
            }
        )
    return components


def build_card(
    kanji: dict[str, Any],
    vocab_map: dict[int, dict[str, Any]],
    image_fetcher: "callable | None" = None,
) -> Card:
    """Aus einem Kanji-Subject (+ Subject-Map) eine Card bauen.

    `vocab_map` dient sowohl den Beispielvokabeln (amalgamation) als auch den
    Kompositions-Radicals (component); es genügt eine Map, die beide enthält.
    """
    data = kanji.get("data", {})
    readings = data.get("readings", [])
    onyomi = _primary_first(
        [r for r in readings if r.get("type") == "onyomi"], "reading"
    )
    kunyomi = _primary_first(
        [r for r in readings if r.get("type") == "kunyomi"], "reading"
    )

    card = Card(
        kanji=strip_markup(data.get("characters")) or "",
        meanings=_primary_first(data.get("meanings", []), "meaning", lower_first=True),
        onyomi=onyomi,
        kunyomi=kunyomi,
        meaning_mnemonic=strip_markup(data.get("meaning_mnemonic")) or None,
        reading_mnemonic=strip_markup(data.get("reading_mnemonic")) or None,
        components=_build_components(data, vocab_map, image_fetcher),
        tags=_default_tags("Kanji", data),
        subject_id=_int_or_none(kanji.get("id")),
        document_url=data.get("document_url"),
    )

    vocab = pick_example_vocab(kanji, vocab_map)
    if vocab:
        vdata = vocab.get("data", {})
        card.vocab = strip_markup(vdata.get("characters"))
        vreadings = _primary_first(vdata.get("readings", []), "reading")
        card.vocab_reading = vreadings[0] if vreadings else None
        vmeanings = _primary_first(vdata.get("meanings", []), "meaning", lower_first=True)
        card.vocab_meaning = vmeanings[0] if vmeanings else None
        card.vocab_audio_url = _resolve_audio_url(
            _pick_audio_url(vdata.get("pronunciation_audios")), image_fetcher
        )
        sentences = vdata.get("context_sentences") or []
        if sentences:
            card.sentence_ja = strip_markup(sentences[0].get("ja"))
            card.sentence_en = strip_markup(sentences[0].get("en"))
            # WaniKani vertont Beispielsätze selbst nicht – optionales,
            # manuell nachgetragenes Feld (gleiche Struktur wie pronunciation_audios).
            card.sentence_audio_url = _resolve_audio_url(
                _pick_audio_url(sentences[0].get("audios")), image_fetcher
            )
            card.extra_sentences = _build_extra_sentences(sentences[1:], image_fetcher)
    return card


def build_cards(
    kanji_list: list[dict[str, Any]],
    vocab_map: dict[int, dict[str, Any]],
    image_fetcher: "callable | None" = None,
) -> list[Card]:
    return [build_card(k, vocab_map, image_fetcher) for k in kanji_list]


def build_cover(level: int | str, cards: Sequence[Card]) -> CoverCard:
    """Deckkarte für einen Kanji-Stapel (Kanji + primäre Bedeutung)."""
    entries = [
        (c.kanji, c.meanings[0] if c.meanings else "")
        for c in cards
        if c.kanji
    ]
    return CoverCard(
        title="WaniKani", subtitle=f"Level {level}", kind="Kanji", entries=entries
    )


# Wie viele Beispiel-Kanji auf der Radical-Rückseite gelistet werden.
RADICAL_MAX_EXAMPLES = 6


def build_radical_card(
    radical: dict[str, Any],
    kanji_map: dict[int, dict[str, Any]],
    image_fetcher: "callable | None" = None,
) -> RadicalCard:
    """Aus einem Radical-Subject (+ Kanji-Map) eine RadicalCard bauen.

    `image_fetcher(url) -> data-URI|None` wird nur genutzt, wenn das Radical
    kein Unicode-Zeichen hat oder zusätzlich ein Bild vorliegt.
    """
    data = radical.get("data", {})
    meanings = _primary_first(data.get("meanings", []), "meaning", lower_first=True)

    card = RadicalCard(
        radical=strip_markup(data.get("characters")) or "",
        meaning=meanings[0] if meanings else "",
        mnemonic=strip_markup(data.get("meaning_mnemonic")) or None,
        tags=_default_tags("Radical", data),
        subject_id=_int_or_none(radical.get("id")),
        document_url=data.get("document_url"),
    )

    # Bild: bereits eingebettete data-URI (Sample) oder per Fetcher nachladen.
    card.image_uri = data.get("_image_data_uri")
    if not card.image_uri:
        images = data.get("character_images") or []
        # PNG bevorzugen (WeasyPrint-freundlich), sonst SVG.
        png = next(
            (i for i in images if i.get("content_type") == "image/png"), None
        )
        chosen = png or (images[0] if images else None)
        if chosen and chosen.get("url") and image_fetcher is not None:
            card.image_uri = image_fetcher(chosen["url"])

    # Erste Beispiel-Kanji (Lesung + Bedeutung) aus den amalgamation-IDs.
    examples: list[tuple[str, str, str]] = []
    for sid in data.get("amalgamation_subject_ids") or []:
        kanji = kanji_map.get(int(sid))
        if not kanji:
            continue
        kdata = kanji.get("data", {})
        chars = strip_markup(kdata.get("characters")) or ""
        readings = _primary_first(
            [r for r in kdata.get("readings", []) if r.get("primary")], "reading"
        ) or _primary_first(kdata.get("readings", []), "reading")
        kmeanings = _primary_first(kdata.get("meanings", []), "meaning", lower_first=True)
        if chars:
            examples.append(
                (chars, readings[0] if readings else "", kmeanings[0] if kmeanings else "")
            )
        if len(examples) >= RADICAL_MAX_EXAMPLES:
            break
    card.kanji_examples = examples
    return card


def build_radical_cards(
    radical_list: list[dict[str, Any]],
    kanji_map: dict[int, dict[str, Any]],
    image_fetcher: "callable | None" = None,
) -> list[RadicalCard]:
    return [build_radical_card(r, kanji_map, image_fetcher) for r in radical_list]


def build_vocab_card(
    vocab: dict[str, Any], image_fetcher: "callable | None" = None
) -> VocabCard:
    """Aus einem Vokabel-Subject eine VocabCard bauen."""
    data = vocab.get("data", {})
    sentences = data.get("context_sentences") or []
    card = VocabCard(
        vocab=strip_markup(data.get("characters")) or "",
        readings=_primary_first(data.get("readings", []), "reading"),
        meanings=_primary_first(data.get("meanings", []), "meaning", lower_first=True),
        parts_of_speech=[p for p in (data.get("parts_of_speech") or []) if p],
        meaning_mnemonic=strip_markup(data.get("meaning_mnemonic")) or None,
        reading_mnemonic=strip_markup(data.get("reading_mnemonic")) or None,
        audio_url=_resolve_audio_url(
            _pick_audio_url(data.get("pronunciation_audios")), image_fetcher
        ),
        document_url=data.get("document_url"),
        tags=_default_tags("Vocab", data),
        subject_id=_int_or_none(vocab.get("id")),
    )
    if sentences:
        card.sentence_ja = strip_markup(sentences[0].get("ja"))
        card.sentence_en = strip_markup(sentences[0].get("en"))
        card.sentence_audio_url = _resolve_audio_url(
            _pick_audio_url(sentences[0].get("audios")), image_fetcher
        )
        card.extra_sentences = _build_extra_sentences(sentences[1:], image_fetcher)
    return card


def build_custom_card(d: dict[str, Any]) -> CustomCard:
    """Aus einem Formular-/JSON-Dict eine CustomCard bauen (freies HTML)."""
    tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
    return CustomCard(
        front_html=str(d.get("front_html") or ""),
        back_html=str(d.get("back_html") or ""),
        tags=tags,
        card_id=str(d["id"]) if d.get("id") else None,
    )


def build_cover_radicals(
    level: int | str, cards: Sequence[RadicalCard]
) -> CoverCard:
    """Deckkarte für einen Radical-Stapel (Zeichen falls vorhanden + Bedeutung)."""
    entries = [(c.radical, c.meaning) for c in cards if c.meaning]
    return CoverCard(
        title="WaniKani", subtitle=f"Level {level}", kind="Radicals", entries=entries
    )


# --------------------------------------------------------------------------- #
# Layout / Paginierung / Duplex
# --------------------------------------------------------------------------- #

def paginate(
    cards: Sequence[Card | CoverCard | RadicalCard | VocabCard | CustomCard | None], per_page: int = 6
) -> list[list[Card | CoverCard | RadicalCard | VocabCard | CustomCard | None]]:
    """Karten in Seiten à `per_page` aufteilen; letzte Seite mit None auffüllen."""
    pages: list[list[Card | CoverCard | RadicalCard | VocabCard | CustomCard | None]] = []
    for start in range(0, len(cards), per_page):
        chunk: list[Card | None] = list(cards[start : start + per_page])
        while len(chunk) < per_page:
            chunk.append(None)
        pages.append(chunk)
    return pages


def mirror_backside(
    chunk: Sequence[Card | None], cols: int, duplex: str = "long-edge"
) -> list[Card | None]:
    """Rückseiten-Raster für Duplexdruck spiegeln.

    Der Chunk ist zeilenweise (row-major) mit `cols` Spalten angeordnet.

    - ``long-edge``  (Wenden an der langen Kante, Default): jede Zeile wird in
      Spaltenreihenfolge gespiegelt.
    - ``short-edge`` (Wenden an der kurzen Kante): die Zeilenreihenfolge wird
      gespiegelt.

    Beispiel (2 Spalten, long-edge)::

        1 2        2 1
        3 4   →    4 3
        5 6        6 5
    """
    if cols <= 0:
        raise ValueError("cols muss > 0 sein")
    rows = [list(chunk[i : i + cols]) for i in range(0, len(chunk), cols)]
    if duplex == "long-edge":
        mirrored_rows = [list(reversed(row)) for row in rows]
    elif duplex == "short-edge":
        mirrored_rows = list(reversed(rows))
    else:
        raise ValueError(f"Unbekannter Duplex-Modus: {duplex!r}")
    return [cell for row in mirrored_rows for cell in row]


# --------------------------------------------------------------------------- #
# PDF-Rendering (HTML/CSS → WeasyPrint)
# --------------------------------------------------------------------------- #

PAPER_SIZES = {"a4": "A4", "letter": "Letter", "a6": "A6"}

# Papiermaße in mm (Breite, Höhe, Hochformat) – Basis für die *feste*
# Rastergeometrie, damit Vorder- und Rückseite exakt deckungsgleich sind.
PAPER_DIMS_MM = {
    "a4": (210.0, 297.0),
    "letter": (215.9, 279.4),
    "a6": (105.0, 148.0),
}

# Layout-Profile: bestimmen Papier, Ausrichtung, Raster und Rand.
#   a4-4up: 4 Karten pro A4-Blatt (quer), mittiges Schnittkreuz, dann schneiden.
#   a6:     eine Karte pro A6-Seite (quer) – direkt auf A6-Karten drucken,
#           kein Schneiden nötig.
LAYOUTS: dict[str, dict[str, Any]] = {
    "a4-4up": {"paper": "a4", "landscape": True, "cols": 2, "rows": 2, "margin": 8.0},
    "a6": {"paper": "a6", "landscape": True, "cols": 1, "rows": 1, "margin": 0.0},
}
# Kleiner Außenrand: die einzigen SCHNITT-Kanten sind das mittige Kreuz
# (waagerecht + senkrecht) zwischen den 4 Karten. Der schmale Rand am
# Blattrand wird nicht geschnitten (Papierkante) und verhindert zugleich das
# Abschneiden durch den nicht bedruckbaren Bereich vieler Heimdrucker.
PAGE_MARGIN_MM = 8.0


def _merged_sentences(card: "Card | VocabCard") -> list[dict[str, Any]]:
    """Primärer Beispielsatz + weitere zu einer Liste zusammenführen (fürs
    Template – die Karte selbst behält sentence_ja/_en getrennt für die API)."""
    out: list[dict[str, Any]] = []
    if card.sentence_ja:
        out.append(
            {"ja": card.sentence_ja, "en": card.sentence_en or "", "audio_url": card.sentence_audio_url}
        )
    out.extend(card.extra_sentences)
    return out


def _card_to_dict(
    card: Card | CoverCard | RadicalCard | VocabCard | CustomCard | None,
) -> dict[str, Any] | None:
    if card is None:
        return None
    if isinstance(card, CoverCard):
        return {
            "type": "cover",
            "title": card.title,
            "subtitle": card.subtitle,
            "kind": card.kind,
            "count": len(card.entries),
            "entries": [{"kanji": k, "meaning": m} for k, m in card.entries],
        }
    if isinstance(card, RadicalCard):
        return {
            "type": "radical",
            "radical": card.radical,
            "image_uri": card.image_uri,
            "meaning": card.meaning,
            "mnemonic": card.mnemonic,
            "kanji_examples": [
                {"kanji": k, "reading": r, "meaning": m}
                for k, r, m in card.kanji_examples
            ],
            "tags": card.tags,
        }
    if isinstance(card, VocabCard):
        return {
            "type": "vocab",
            "vocab": card.vocab,
            "readings": card.readings,
            "meanings": card.meanings,
            "parts_of_speech": card.parts_of_speech,
            "meaning_mnemonic": card.meaning_mnemonic,
            "reading_mnemonic": card.reading_mnemonic,
            "sentence_ja": card.sentence_ja,
            "sentence_en": card.sentence_en,
            "sentences": _merged_sentences(card),
            "tags": card.tags,
        }
    if isinstance(card, CustomCard):
        return {
            "type": "custom",
            "front_html": card.front_html,
            "back_html": card.back_html,
            "tags": card.tags,
        }
    return {
        "type": "kanji",
        "kanji": card.kanji,
        "meanings": card.meanings,
        "onyomi": card.onyomi,
        "kunyomi": card.kunyomi,
        "meaning_mnemonic": card.meaning_mnemonic,
        "reading_mnemonic": card.reading_mnemonic,
        "vocab": card.vocab,
        "vocab_reading": card.vocab_reading,
        "vocab_meaning": card.vocab_meaning,
        "sentence_ja": card.sentence_ja,
        "sentence_en": card.sentence_en,
        "sentences": _merged_sentences(card),
        "components": card.components,
        "tags": card.tags,
    }


def build_sheets(
    cards: Sequence[Card | CoverCard | RadicalCard | VocabCard | CustomCard | None],
    *,
    cols: int = 2,
    rows: int = 2,
    duplex: str = "long-edge",
) -> list[dict[str, Any]]:
    """Abwechselnd Vorder- und Rückseite pro Seite als Render-Kontext bauen."""
    per_page = cols * rows
    sheets: list[dict[str, Any]] = []
    for page in paginate(cards, per_page):
        sheets.append({"side": "front", "cells": [_card_to_dict(c) for c in page]})
        back = mirror_backside(page, cols, duplex)
        sheets.append({"side": "back", "cells": [_card_to_dict(c) for c in back]})
    return sheets


def render_pdf(
    cards: Sequence[Card | CoverCard | RadicalCard | VocabCard | CustomCard | None],
    output: str | Path,
    *,
    template_dir: Path = DEFAULT_TEMPLATE_DIR,
    kanji_font: Path = DEFAULT_KANJI_FONT,
    sans_font: Path = DEFAULT_SANS_FONT,
    sans_bold_font: Path = DEFAULT_SANS_BOLD_FONT,
    duplex: str = "long-edge",
    paper: str = "a4",
    landscape: bool = True,
    cols: int = 2,
    rows: int = 2,
    margin: float = PAGE_MARGIN_MM,
    cut_marks: bool = True,
    hole: bool = False,
    username: str = "",
) -> Path:
    """Karten als doppelseitiges PDF rendern (HTML/CSS via WeasyPrint)."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from weasyprint import HTML

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("cards.html.j2")

    sheets = build_sheets(cards, cols=cols, rows=rows, duplex=duplex)

    page_w, page_h = PAPER_DIMS_MM.get(paper, PAPER_DIMS_MM["a4"])
    if landscape:
        page_w, page_h = page_h, page_w
    # Feste Maße der bedruckbaren Fläche → identische Zellen auf Vorder-/Rückseite.
    content_w = page_w - 2 * margin
    content_h = page_h - 2 * margin

    html_str = template.render(
        sheets=sheets,
        cols=cols,
        rows=rows,
        duplex=duplex,
        page_w=page_w,
        page_h=page_h,
        margin=margin,
        content_w=content_w,
        content_h=content_h,
        cell_w=content_w / cols,
        cell_h=content_h / rows,
        # Schnittkreuz nur, wenn mehrere Karten pro Blatt geschnitten werden.
        show_cross=cut_marks and (cols * rows > 1),
        show_hole=hole,
        username=username,
        kanji_font_url=Path(kanji_font).resolve().as_uri(),
        sans_font_url=Path(sans_font).resolve().as_uri(),
        sans_bold_font_url=Path(sans_bold_font).resolve().as_uri(),
        cut_marks=cut_marks,
    )

    out_path = Path(output)
    # base_url erlaubt @font-face mit file://-URLs
    HTML(string=html_str, base_url=str(HERE)).write_pdf(str(out_path))
    return out_path


# --------------------------------------------------------------------------- #
# Datenquellen
# --------------------------------------------------------------------------- #

def _load_sample_raw(path: Path | None = None) -> dict[str, Any]:
    fixture = path or (HERE / "sample_data.json")
    return json.loads(Path(fixture).read_text(encoding="utf-8"))


def load_sample_cards(path: Path | None = None) -> list[Card]:
    """Beispiel-Kanji (ohne API-Token) laden – für Demo & Tests.

    Das Fixture hat dieselbe Struktur wie die WaniKani-API, sodass exakt
    derselbe Modell-Code (`build_card`) verwendet wird.
    """
    raw = _load_sample_raw(path)
    kanji_list = raw["kanji"]
    # Map mit Vokabeln (Beispiele) UND Radicals (Komposition) – build_card nutzt beide.
    subject_map = {int(v["id"]): v for v in raw.get("vocab", [])}
    subject_map.update({int(r["id"]): r for r in raw.get("radicals", [])})
    return build_cards(kanji_list, subject_map)


def load_sample_radicals(path: Path | None = None) -> list[RadicalCard]:
    """Beispiel-Radicals (ohne API-Token) laden – für Demo & Tests."""
    raw = _load_sample_raw(path)
    radical_list = raw.get("radicals", [])
    # Kanji-Map für die Beispiel-Kanji auf der Radical-Rückseite.
    kanji_map = {int(k["id"]): k for k in raw.get("kanji", [])}
    return build_radical_cards(radical_list, kanji_map)


def _make_client(*, use_cache: bool = True) -> WaniKaniClient:
    load_dotenv()
    token = os.environ.get("WANIKANI_API_TOKEN")
    if not token:
        raise WaniKaniError(
            "Kein WANIKANI_API_TOKEN gesetzt. Bitte in der Umgebung oder in "
            "einer .env-Datei hinterlegen (Settings → API Tokens auf wanikani.com). "
            "Zum Ausprobieren ohne Token: --sample verwenden."
        )
    return WaniKaniClient(token, use_cache=use_cache)


def load_cards_from_api(level: int, *, use_cache: bool = True) -> list[Card]:
    """Kanji eines Levels via WaniKani-API holen und in Cards umwandeln."""
    client = _make_client(use_cache=use_cache)
    kanji_list = client.fetch_kanji(level)
    if not kanji_list:
        raise WaniKaniError(f"Keine Kanji für Level {level} gefunden.")

    # Alle Bezug-IDs einsammeln: amalgamation (Beispielvokabeln) UND
    # component (Kompositions-Radicals). Einmalig gebündelt vorladen.
    ids: set[int] = set()
    for k in kanji_list:
        kdata = k.get("data", {})
        for sid in kdata.get("amalgamation_subject_ids") or []:
            ids.add(int(sid))
        for sid in kdata.get("component_subject_ids") or []:
            ids.add(int(sid))
    subject_map = client.fetch_subjects(ids) if ids else {}
    return build_cards(kanji_list, subject_map, client.fetch_image_data_uri)


def load_radicals_from_api(level: int, *, use_cache: bool = True) -> list[RadicalCard]:
    """Radicals eines Levels via WaniKani-API holen und in RadicalCards wandeln."""
    client = _make_client(use_cache=use_cache)
    radical_list = client.fetch_radicals(level)
    if not radical_list:
        raise WaniKaniError(f"Keine Radicals für Level {level} gefunden.")

    # Zugehörige Kanji (amalgamation) einmalig vorladen für die Beispiel-Liste.
    ids: set[int] = set()
    for r in radical_list:
        for sid in r.get("data", {}).get("amalgamation_subject_ids") or []:
            ids.add(int(sid))
    kanji_map = client.fetch_subjects(ids) if ids else {}
    return build_radical_cards(radical_list, kanji_map, client.fetch_image_data_uri)


def _sample_registry() -> dict[int, dict[str, Any]]:
    """Alle Beispiel-Subjects (Radicals, Kanji, Vokabeln) als {id: subject}."""
    raw = _load_sample_raw()
    reg: dict[int, dict[str, Any]] = {}
    for key in ("radicals", "kanji", "vocab"):
        for s in raw.get(key, []):
            reg[int(s["id"])] = s
    return reg


# ---- Web-Tabellen-Modus: auflisten (resolve) und rendern (by ids) --------- #

_LEVEL_TYPE_ORDER = {"radicals": 0, "kanji": 1, "vocabulary": 2}
_LEVEL_SAMPLE_KEY = {"radicals": "radicals", "kanji": "kanji", "vocabulary": "vocab"}


def resolve_level(
    level: int,
    deck_types: str | Iterable[str],
    *,
    use_cache: bool = True,
    sample: bool = False,
) -> list[dict[str, Any]]:
    """Kanji, Radicals und/oder Vokabeln eines Levels als Tabellen-Beschreibungen.

    `deck_types` ist ein einzelner Typ oder eine Liste aus "kanji", "radicals",
    "vocabulary" – bei mehreren werden die Ergebnisse kombiniert (Reihenfolge:
    Radicals → Kanji → Vokabeln, dem WaniKani-Lernpfad folgend).
    """
    types = [deck_types] if isinstance(deck_types, str) else list(deck_types)
    types = [t for t in dict.fromkeys(types) if t in _LEVEL_TYPE_ORDER]
    if not types:
        raise WaniKaniError(
            "Bitte mindestens einen Kartentyp auswählen (Radical/Kanji/Vokabel)."
        )
    types.sort(key=lambda t: _LEVEL_TYPE_ORDER[t])

    items: list[dict[str, Any]] = []
    if sample:
        raw = _load_sample_raw()
        for t in types:
            items.extend(raw.get(_LEVEL_SAMPLE_KEY[t], []))
    else:
        client = _make_client(use_cache=use_cache)
        fetchers = {
            "radicals": client.fetch_radicals,
            "kanji": client.fetch_kanji,
            "vocabulary": client.fetch_vocabulary,
        }
        for t in types:
            items.extend(fetchers[t](level))
    if not items:
        raise WaniKaniError(f"Nichts für Level {level} gefunden.")
    return [_subject_descriptor(s) for s in items]


def search_subjects(
    query: str, *, use_cache: bool = True, sample: bool = False
) -> list[dict[str, Any]]:
    """Subjects per Zeichen/Namen suchen → Tabellen-Beschreibungen."""
    if sample:
        q = query.strip().lower()
        out = []
        for s in _sample_registry().values():
            data = s.get("data", {})
            chars = (data.get("characters") or "").lower()
            meanings = [
                (m.get("meaning") or "").lower() for m in data.get("meanings", [])
            ]
            if q and (q == chars or q in meanings):
                out.append(s)
        return [_subject_descriptor(s) for s in out]
    client = _make_client(use_cache=use_cache)
    return [_subject_descriptor(s) for s in client.search_subjects(query)]


def resolve_composition(
    subject_ids: Iterable[int], *, use_cache: bool = True, sample: bool = False
) -> list[dict[str, Any]]:
    """Rekursiv über die Komposition absteigen (Vokabel→Kanji→Radicals)."""
    root_ids = [int(i) for i in subject_ids]
    if sample:
        reg = _sample_registry()
    else:
        client = _make_client(use_cache=use_cache)
        reg = {}
        frontier = list(root_ids)
        while frontier:
            need = [i for i in dict.fromkeys(frontier) if i not in reg]
            if need:
                reg.update(client.fetch_subjects(need))
            nxt: list[int] = []
            for i in need:
                s = reg.get(i)
                if not s:
                    continue
                for cid in s.get("data", {}).get("component_subject_ids") or []:
                    if int(cid) not in reg:
                        nxt.append(int(cid))
            frontier = nxt
    ordered = collect_composition(root_ids, reg)
    return [_subject_descriptor(s) for s in ordered]


def resolve_subject_deck(
    subject_ids: Iterable[int],
    *,
    use_cache: bool = True,
    sample: bool = False,
) -> list[Card | RadicalCard | VocabCard]:
    """Die gewählten Subjects (nach ID) in Card-Objekte auflösen (ohne zu rendern).

    Gemeinsam genutzt von PDF- (`render_subjects`) und Anki-Export.
    """
    ids = [int(i) for i in subject_ids]
    image_fetcher: "callable | None" = None
    if sample:
        reg = _sample_registry()
    else:
        client = _make_client(use_cache=use_cache)
        reg = dict(client.fetch_subjects(ids))
        # Bezüge nachladen: Kanji→Beispielvokabeln, Radical→Beispielkanji.
        related: set[int] = set()
        for i in ids:
            s = reg.get(i)
            if not s:
                continue
            sdata = s.get("data", {})
            for a in sdata.get("amalgamation_subject_ids") or []:
                related.add(int(a))
            for c in sdata.get("component_subject_ids") or []:
                related.add(int(c))
        related -= set(reg)
        if related:
            reg.update(client.fetch_subjects(related))
        image_fetcher = client.fetch_image_data_uri

    deck: list[Card | RadicalCard | VocabCard] = []
    for i in ids:
        s = reg.get(i)
        if s:
            deck.append(build_any_card(s, reg, image_fetcher))
    if not deck:
        raise WaniKaniError("Keine gültigen Karten für die Auswahl gefunden.")
    return deck


def render_subjects(
    subject_ids: Iterable[int],
    output: str | Path,
    *,
    layout: str = "a6",
    paper: str = "a4",
    duplex: str = "long-edge",
    cut_marks: bool = True,
    hole: bool = False,
    username: str = "",
    use_cache: bool = True,
    sample: bool = False,
) -> tuple[Path, int]:
    """Genau die gewählten Subjects (nach ID) als ein PDF rendern (kein Deckblatt)."""
    deck = resolve_subject_deck(subject_ids, use_cache=use_cache, sample=sample)
    path = render_deck(
        deck, output, layout=layout, paper=paper, duplex=duplex,
        cut_marks=cut_marks, hole=hole, username=username,
    )
    return path, len(deck)


def render_custom(
    cards_data: Sequence[dict[str, Any]],
    output: str | Path,
    *,
    layout: str = "a6",
    paper: str = "a4",
    duplex: str = "long-edge",
    cut_marks: bool = True,
    hole: bool = False,
    username: str = "",
) -> tuple[Path, int]:
    """Selbst erstellte Karten (Dict-Form) als ein PDF rendern."""
    deck = [build_custom_card(d) for d in cards_data]
    if not deck:
        raise WaniKaniError("Keine Karten ausgewählt.")
    path = render_deck(
        deck, output, layout=layout, paper=paper, duplex=duplex,
        cut_marks=cut_marks, hole=hole, username=username,
    )
    return path, len(deck)


# --------------------------------------------------------------------------- #
# Orchestrierung (von CLI und Web-Frontend gemeinsam genutzt)
# --------------------------------------------------------------------------- #

def build_deck(
    level: int | None,
    deck_type: str = "kanji",
    *,
    use_cache: bool = True,
    with_cover: bool = True,
    sample: bool = False,
) -> list[Card | CoverCard | RadicalCard]:
    """Kompletten Kartenstapel (inkl. optionaler Deckkarte) für ein Level bauen."""
    radicals = deck_type == "radicals"
    if sample:
        cards: Sequence[Card] | Sequence[RadicalCard] = (
            load_sample_radicals() if radicals else load_sample_cards()
        )
    elif radicals:
        cards = load_radicals_from_api(level, use_cache=use_cache)  # type: ignore[arg-type]
    else:
        cards = load_cards_from_api(level, use_cache=use_cache)  # type: ignore[arg-type]

    deck: list[Card | CoverCard | RadicalCard] = list(cards)
    if with_cover and cards:
        label = level if level is not None else 1
        cover = (
            build_cover_radicals(label, cards)  # type: ignore[arg-type]
            if radicals
            else build_cover(label, cards)  # type: ignore[arg-type]
        )
        deck.insert(0, cover)
    return deck


def render_deck(
    deck: Sequence[Card | CoverCard | RadicalCard | VocabCard],
    output: str | Path,
    *,
    layout: str = "a6",
    paper: str = "a4",
    duplex: str = "long-edge",
    cut_marks: bool = True,
    hole: bool = False,
    username: str = "",
    kanji_font: str | Path = DEFAULT_KANJI_FONT,
) -> Path:
    """Einen Stapel gemäß Layout-Profil als PDF rendern."""
    profile = dict(LAYOUTS[layout])
    if layout == "a4-4up":
        profile["paper"] = paper  # a4/letter erlaubt
    return render_pdf(
        deck,
        output,
        kanji_font=Path(kanji_font),
        duplex=duplex,
        paper=profile["paper"],
        landscape=profile["landscape"],
        cols=profile["cols"],
        rows=profile["rows"],
        margin=profile["margin"],
        cut_marks=cut_marks,
        hole=hole,
        username=username,
    )


# --------------------------------------------------------------------------- #
# Subject-Registry, Suche & rekursive Komposition (für den Web-Tabellen-Modus)
# --------------------------------------------------------------------------- #

_OBJ_KIND = {"kanji": "Kanji", "radical": "Radical", "vocabulary": "Vocab"}


def _subject_descriptor(subject: dict[str, Any]) -> dict[str, Any]:
    """Kompakte Beschreibung eines Subjects für die Tabelle im Frontend."""
    data = subject.get("data", {})
    meanings = _primary_first(data.get("meanings", []), "meaning", lower_first=True)
    obj = subject.get("object", "")
    return {
        "id": int(subject.get("id")),
        "object": obj,
        "kind": _OBJ_KIND.get(obj, obj or "?"),
        "characters": strip_markup(data.get("characters")) or "",
        "meaning": meanings[0] if meanings else "",
        "level": data.get("level"),
        "has_image": bool(data.get("character_images") or data.get("_image_data_uri")),
    }


def collect_composition(
    root_ids: Iterable[int], registry: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Von den Wurzel-Subjects rekursiv über `component_subject_ids` absteigen.

    Vokabel → Kanji → Radicals. Ergebnis in Entdeckungsreihenfolge, dedupliziert.
    """
    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()
    queue: list[int] = list(dict.fromkeys(int(i) for i in root_ids))
    while queue:
        sid = queue.pop(0)
        if sid in seen:
            continue
        subject = registry.get(sid)
        if not subject:
            continue
        seen.add(sid)
        ordered.append(subject)
        for cid in subject.get("data", {}).get("component_subject_ids") or []:
            if int(cid) not in seen:
                queue.append(int(cid))
    return ordered


def build_any_card(
    subject: dict[str, Any],
    registry: dict[int, dict[str, Any]],
    image_fetcher: "callable | None" = None,
) -> Card | RadicalCard | VocabCard:
    """Passende Karte je nach Subject-Typ bauen (nutzt registry für Bezüge)."""
    obj = subject.get("object")
    if obj == "radical":
        return build_radical_card(subject, registry, image_fetcher)
    if obj == "vocabulary":
        return build_vocab_card(subject, image_fetcher)
    return build_card(subject, registry, image_fetcher)  # kanji


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kanji_cards.py",
        description="Erzeugt doppelseitig bedruckbare Kanji-Karteikarten (PDF) "
        "aus einem WaniKani-Level.",
    )
    parser.add_argument(
        "level",
        nargs="?",
        type=int,
        help="WaniKani-Level (1–60). Ohne Level --sample verwenden.",
    )
    parser.add_argument(
        "--output", "-o", default="cards.pdf", help="Ausgabedatei (Default: cards.pdf)"
    )
    parser.add_argument(
        "--type",
        choices=["kanji", "radicals"],
        default="kanji",
        dest="deck_type",
        help="Welcher Stapel: 'kanji' (Default) oder 'radicals'.",
    )
    parser.add_argument(
        "--duplex",
        choices=["long-edge", "short-edge"],
        default="long-edge",
        help="Wende-Kante für den Duplexdruck (Default: long-edge).",
    )
    parser.add_argument(
        "--layout",
        choices=list(LAYOUTS),
        default="a6",
        help="Druck-Layout: 'a6' = eine Karte pro A6-Seite, direkt auf "
        "A6-Karten drucken (Default, kein Schneiden); 'a4-4up' = 4 Karten pro "
        "A4-Blatt (quer) zum Schneiden.",
    )
    parser.add_argument(
        "--paper",
        choices=["a4", "letter", "a6"],
        default="a4",
        help="Papierformat für Layout 'a4-4up' (Default: a4). Bei '--layout a6' "
        "ohne Wirkung.",
    )
    parser.add_argument(
        "--font",
        default=str(DEFAULT_KANJI_FONT),
        help="Pfad zur Kanji-Schrift (TTF/OTF).",
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="API-Cache unter .cache/ umgehen."
    )
    parser.add_argument(
        "--no-cut-marks", action="store_true", help="Keine Schnittmarken zeichnen."
    )
    parser.add_argument(
        "--hole",
        action="store_true",
        help="Lochbereich/Loch-Markierung reservieren (Default: aus).",
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="Keine Deckkarte (Titel + Kanji-Übersicht) voranstellen.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Beispieldaten ohne API-Token verwenden (Demo).",
    )
    parser.add_argument(
        "--anki",
        action="store_true",
        help="Statt PDF ein Anki-Paket (.apkg) erzeugen, zum lokalen Import in "
        "Anki (Datei → Importieren). Kein Docker/Anki-Netzwerk nötig; --output "
        "bekommt automatisch die Endung .apkg.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.sample and args.level is None:
        parser.error("Bitte ein Level angeben oder --sample verwenden.")

    radicals = args.deck_type == "radicals"
    kind = "Radicals" if radicals else "Kanji"
    try:
        deck = build_deck(
            args.level,
            args.deck_type,
            use_cache=not args.no_cache,
            with_cover=not args.no_cover and not args.anki,
            sample=args.sample,
        )
    except WaniKaniError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    if not deck:
        print("Keine Karten zu erzeugen.", file=sys.stderr)
        return 1

    if args.anki:
        import anki_export

        output = args.output
        if Path(output).suffix.lower() != ".apkg":
            output = str(Path(output).with_suffix(".apkg"))
        label = args.level if args.level is not None else 1
        try:
            out, n = anki_export.export_deck(
                deck, output, deck_name=f"WaniKani Level {label} · {kind}"
            )
        # Hinweis: anki_export importiert kanji_cards separat als eigenes Modul
        # (nicht als __main__), daher hier explizit dessen Fehlerklasse fangen –
        # ein bloßes `except WaniKaniError` (an die __main__-Klasse gebunden)
        # würde die Instanz aus anki_export sonst nicht erkennen.
        except anki_export.AnkiExportError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)
            return 1
        print(f"{n} {kind}-Karten → Anki-Paket {out} (in Anki: Datei → Importieren).")
        return 0

    out = render_deck(
        deck,
        args.output,
        layout=args.layout,
        paper=args.paper,
        duplex=args.duplex,
        cut_marks=not args.no_cut_marks,
        hole=args.hole,
        kanji_font=args.font,
    )
    profile = LAYOUTS[args.layout]
    per_page = profile["cols"] * profile["rows"]
    n_sheets = ((len(deck) + per_page - 1) // per_page) * 2
    cover_note = "" if args.no_cover else " inkl. Deckkarte"
    paper_label = (args.paper if args.layout == "a4-4up" else profile["paper"]).upper()
    print(
        f"{len(deck)} {kind}-Karten{cover_note} → {out} ({n_sheets} Seiten, "
        f"{per_page}/Seite, {paper_label} quer, Duplex: {args.duplex})."
    )
    return 0


if __name__ == "__main__":
    # Als Skript ausgeführt landet dieses Modul unter dem Namen "__main__", nicht
    # "kanji_cards" – ein `import kanji_cards` (z. B. aus anki_export.py für den
    # --anki-Zweig) würde die Datei sonst ein zweites Mal unter dem Namen
    # "kanji_cards" laden. Die Folge: zwei nicht-identische Klassenobjekte
    # (__main__.Card vs. kanji_cards.Card), sodass isinstance()-Prüfungen in
    # anki_export.py fälschlich fehlschlagen. Fix: den bereits geladenen
    # __main__-Modulcode unter dem Namen "kanji_cards" zwischenspeichern.
    sys.modules.setdefault("kanji_cards", sys.modules["__main__"])
    raise SystemExit(main())
