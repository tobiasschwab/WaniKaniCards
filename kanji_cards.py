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
CACHE_DIR = Path(".cache")

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
    """Alle Daten, die eine einzelne Karteikarte benötigt."""

    kanji: str
    meanings: list[str] = field(default_factory=list)
    onyomi: list[str] = field(default_factory=list)
    kunyomi: list[str] = field(default_factory=list)
    meaning_mnemonic: str | None = None
    reading_mnemonic: str | None = None
    vocab: str | None = None
    vocab_reading: str | None = None
    vocab_meaning: str | None = None
    sentence_ja: str | None = None
    sentence_en: str | None = None


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

def strip_markup(text: str | None) -> str | None:
    """Entfernt WaniKani-Tags (<kanji>, <ja>, <reading> …) defensiv."""
    if text is None:
        return None
    return _TAG_RE.sub("", text).strip()


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

    def fetch_vocab(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        """Vokabel-Subjects gebündelt nachladen → Map {id: subject} (gecacht).

        Nur nicht-gecachte IDs werden nachgeladen; die Anfrage wird in Batches
        aufgeteilt, um sehr lange URLs zu vermeiden.
        """
        want = sorted({int(i) for i in ids})
        result: dict[int, dict[str, Any]] = {}
        missing: list[int] = []
        for sid in want:
            cached = self._cache_read(f"vocab_{sid}")
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
                self._cache_write(f"vocab_{sid}", subject)
        return result


# --------------------------------------------------------------------------- #
# Modell-Aufbau
# --------------------------------------------------------------------------- #

def _primary_first(items: Sequence[dict[str, Any]], key: str) -> list[str]:
    """Werte extrahieren, primäre Einträge zuerst, Reihenfolge sonst erhalten."""
    primary = [strip_markup(i[key]) for i in items if i.get("primary")]
    rest = [strip_markup(i[key]) for i in items if not i.get("primary")]
    out = [v for v in (primary + rest) if v]
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


def build_card(kanji: dict[str, Any], vocab_map: dict[int, dict[str, Any]]) -> Card:
    """Aus einem Kanji-Subject (+ Vokabel-Map) eine Card bauen."""
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
        meanings=_primary_first(data.get("meanings", []), "meaning"),
        onyomi=onyomi,
        kunyomi=kunyomi,
        meaning_mnemonic=strip_markup(data.get("meaning_mnemonic")) or None,
        reading_mnemonic=strip_markup(data.get("reading_mnemonic")) or None,
    )

    vocab = pick_example_vocab(kanji, vocab_map)
    if vocab:
        vdata = vocab.get("data", {})
        card.vocab = strip_markup(vdata.get("characters"))
        vreadings = _primary_first(vdata.get("readings", []), "reading")
        card.vocab_reading = vreadings[0] if vreadings else None
        vmeanings = _primary_first(vdata.get("meanings", []), "meaning")
        card.vocab_meaning = vmeanings[0] if vmeanings else None
        sentences = vdata.get("context_sentences") or []
        if sentences:
            card.sentence_ja = strip_markup(sentences[0].get("ja"))
            card.sentence_en = strip_markup(sentences[0].get("en"))
    return card


def build_cards(
    kanji_list: list[dict[str, Any]], vocab_map: dict[int, dict[str, Any]]
) -> list[Card]:
    return [build_card(k, vocab_map) for k in kanji_list]


# --------------------------------------------------------------------------- #
# Layout / Paginierung / Duplex
# --------------------------------------------------------------------------- #

def paginate(
    cards: Sequence[Card | None], per_page: int = 6
) -> list[list[Card | None]]:
    """Karten in Seiten à `per_page` aufteilen; letzte Seite mit None auffüllen."""
    pages: list[list[Card | None]] = []
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

PAPER_SIZES = {"a4": "A4", "letter": "Letter"}

# Papiermaße in mm (Breite, Höhe, Hochformat) – Basis für die *feste*
# Rastergeometrie, damit Vorder- und Rückseite exakt deckungsgleich sind.
PAPER_DIMS_MM = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}
# Kleiner Außenrand: die einzigen SCHNITT-Kanten sind das mittige Kreuz
# (waagerecht + senkrecht) zwischen den 4 Karten. Der schmale Rand am
# Blattrand wird nicht geschnitten (Papierkante) und verhindert zugleich das
# Abschneiden durch den nicht bedruckbaren Bereich vieler Heimdrucker.
PAGE_MARGIN_MM = 8.0


def _card_to_dict(card: Card | None) -> dict[str, Any] | None:
    if card is None:
        return None
    return {
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
    }


def build_sheets(
    cards: Sequence[Card | None],
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
    cards: Sequence[Card | None],
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

def load_sample_cards(path: Path | None = None) -> list[Card]:
    """Beispieldaten (ohne API-Token) laden – für Demo & Tests.

    Das Fixture hat dieselbe Struktur wie die WaniKani-API, sodass exakt
    derselbe Modell-Code (`build_card`) verwendet wird.
    """
    fixture = path or (HERE / "sample_data.json")
    raw = json.loads(Path(fixture).read_text(encoding="utf-8"))
    kanji_list = raw["kanji"]
    vocab_map = {int(v["id"]): v for v in raw.get("vocab", [])}
    return build_cards(kanji_list, vocab_map)


def load_cards_from_api(level: int, *, use_cache: bool = True) -> list[Card]:
    """Kanji eines Levels via WaniKani-API holen und in Cards umwandeln."""
    load_dotenv()
    token = os.environ.get("WANIKANI_API_TOKEN")
    if not token:
        raise WaniKaniError(
            "Kein WANIKANI_API_TOKEN gesetzt. Bitte in der Umgebung oder in "
            "einer .env-Datei hinterlegen (Settings → API Tokens auf wanikani.com). "
            "Zum Ausprobieren ohne Token: --sample verwenden."
        )
    client = WaniKaniClient(token, use_cache=use_cache)
    kanji_list = client.fetch_kanji(level)
    if not kanji_list:
        raise WaniKaniError(f"Keine Kanji für Level {level} gefunden.")

    # Alle amalgamation-IDs einsammeln und Vokabeln einmalig vorladen.
    ids: set[int] = set()
    for k in kanji_list:
        for sid in k.get("data", {}).get("amalgamation_subject_ids") or []:
            ids.add(int(sid))
    vocab_map = client.fetch_vocab(ids) if ids else {}
    return build_cards(kanji_list, vocab_map)


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
        "--duplex",
        choices=["long-edge", "short-edge"],
        default="long-edge",
        help="Wende-Kante für den Duplexdruck (Default: long-edge).",
    )
    parser.add_argument(
        "--paper",
        choices=list(PAPER_SIZES),
        default="a4",
        help="Papierformat (Default: a4).",
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
        "--sample",
        action="store_true",
        help="Beispieldaten ohne API-Token verwenden (Demo).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.sample and args.level is None:
        parser.error("Bitte ein Level angeben oder --sample verwenden.")

    try:
        if args.sample:
            cards = load_sample_cards()
        else:
            cards = load_cards_from_api(args.level, use_cache=not args.no_cache)
    except WaniKaniError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    if not cards:
        print("Keine Karten zu erzeugen.", file=sys.stderr)
        return 1

    out = render_pdf(
        cards,
        args.output,
        kanji_font=Path(args.font),
        duplex=args.duplex,
        paper=args.paper,
        cut_marks=not args.no_cut_marks,
    )
    n_sheets = ((len(cards) + 3) // 4) * 2
    print(
        f"{len(cards)} Karten → {out} ({n_sheets} Seiten, 4/Seite, A4 quer, "
        f"Duplex: {args.duplex}, {args.paper.upper()})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
