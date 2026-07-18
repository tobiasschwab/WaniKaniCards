#!/usr/bin/env python3
"""anki_export.py – Export von WaniKani-Karteikarten als Anki-Paket (.apkg).

Anki läuft lokal beim Nutzer, dieses Tool im Docker-Container – die beiden
müssen dafür **nicht** verbunden sein: `genanki` baut hier rein in Python eine
`.apkg`-Datei (SQLite + Medien in einem Zip), die der Nutzer wie die PDF über
den Browser herunterlädt und in Anki ganz normal importiert
(Datei → Importieren). Keine Netzwerkverbindung zwischen Container und
lokalem Anki, kein AnkiConnect nötig.

Jeder Kartentyp (Radical/Kanji/Vokabel/Frei) bekommt einen eigenen Anki-
Notiztyp mit Front-/Rückseiten-Template + CSS, die sich optisch an den
gedruckten Karten orientieren (Tag-Chips, On/Kun/Composition-Farben,
Mnemonic-Box, Referenz-Zeichen auf der Rückseite). Die eingebetteten
Noto-JP-Schriften sorgen dafür, dass Kanji auch ohne lokal installierte
japanische Schrift sauber dargestellt werden.

WaniKani-Subject-IDs (bzw. die ID gespeicherter freier Karten) werden als
stabile Anki-Notiz-GUIDs verwendet: ein erneuter Export nach Lernfortschritt
aktualisiert bestehende Notizen in Anki, statt sie zu duplizieren.
"""
from __future__ import annotations

import html
import re
import shutil
import tempfile
import zlib
from pathlib import Path
from typing import Any, Sequence

import kanji_cards as kc

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"

# Unterstrich-Präfix: schützt die Dateien in Anki vor "Nicht verwendete
# Medien löschen" (Anki scannt dafür nur Feld-HTML, keine CSS @font-face-
# Referenzen – der Präfix ist die dokumentierte Konvention für Support-Dateien).
_FONT_FILES = {
    "_NotoSansJP-Regular.ttf": FONT_DIR / "NotoSansJP-Regular.ttf",
    "_NotoSansJP-Bold.ttf": FONT_DIR / "NotoSansJP-Bold.ttf",
    "_NotoSerifJP-SemiBold.ttf": FONT_DIR / "NotoSerifJP-SemiBold.ttf",
}

# Feste Modell-IDs, damit ein erneuter Export in Anki dieselben Notiztypen
# aktualisiert statt neue anzulegen.
_MODEL_ID_RADICAL = 1_607_021_301
_MODEL_ID_KANJI = 1_607_021_302
_MODEL_ID_VOCAB = 1_607_021_303
_MODEL_ID_CUSTOM = 1_607_021_304


class AnkiExportError(kc.WaniKaniError):
    """Verständlicher Fehler ohne Stacktrace (z. B. fehlendes genanki)."""


def _require_genanki() -> Any:
    try:
        import genanki
    except ImportError as exc:  # pragma: no cover - umgebungsabhängig
        raise AnkiExportError(
            "Für den Anki-Export wird das Paket 'genanki' benötigt. "
            "Bitte installieren: pip install genanki"
        ) from exc
    return genanki


# --------------------------------------------------------------------------- #
# Gemeinsames Styling (an die gedruckten Karten angelehnt, für den Bildschirm)
# --------------------------------------------------------------------------- #

_CSS = """
.card {
  font-family: "WKSans", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
  font-size: 17px;
  line-height: 1.45;
  color: #1a1a1a;
  background: #ffffff;
  text-align: center;
  padding: 26px 22px 20px;
  position: relative;
}
.night_mode .card { background: #1e1e1e; color: #eaeaea; }

@font-face { font-family: "WKSans"; src: url("_NotoSansJP-Regular.ttf") format("truetype"); font-weight: 400; }
@font-face { font-family: "WKSans"; src: url("_NotoSansJP-Bold.ttf") format("truetype"); font-weight: 700; }
@font-face { font-family: "WKSerif"; src: url("_NotoSerifJP-SemiBold.ttf") format("truetype"); font-weight: 600; }

.wk-tags { position: absolute; top: 8px; right: 10px; text-align: right; z-index: 2; }
.wk-tag {
  display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: .4px;
  text-transform: uppercase; color: #111; border: 1px solid #111; border-radius: 4px;
  padding: 2px 7px; margin-left: 5px; background: #fff; white-space: nowrap;
}
.night_mode .wk-tag { color: #eee; border-color: #888; background: #2a2a2a; }

.wk-stage { display: flex; align-items: center; justify-content: center; min-height: 120px; }
.wk-big { font-family: "WKSerif", "WKSans", serif; font-weight: 600; font-size: 82px; line-height: 1; }

/* Antwort eintippen (Anki-{{type:Field}}): Prompt unter dem großen Zeichen. */
.wk-typein { margin-top: 18px; }
.wk-typein-label {
  font-size: 11px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase;
  color: #999; margin-bottom: 5px;
}
.night_mode .wk-typein-label { color: #888; }
.wk-big-img img { height: 100px; width: auto; max-width: 80%; object-fit: contain; }
.wk-fallback { font-family: "WKSans"; font-weight: 700; font-size: 26px; }

.wk-back { text-align: left; margin-top: 6px; }
.wk-refhead { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.wk-refhead .wk-ref { font-family: "WKSerif", "WKSans", serif; font-weight: 600; font-size: 30px; flex: 0 0 auto; }
.wk-refhead .wk-ref.small { font-size: 24px; }
.wk-refhead img { height: 32px; width: auto; max-width: 64px; object-fit: contain; }

.wk-meaning { font-family: "WKSans"; font-weight: 700; font-size: 20px; color: #111; }
.night_mode .wk-meaning { color: #f2f2f2; }
.wk-meaning .sec { font-weight: 400; font-size: 14px; color: #777; }
.wk-pos { font-size: 13px; color: #8a8f98; font-style: italic; margin: -4px 0 8px; }

.wk-readings { margin-bottom: 8px; }
.wk-row { display: flex; align-items: baseline; gap: 10px; margin-top: 5px; }
.wk-row .lbl {
  flex: 0 0 64px; font-size: 11px; letter-spacing: .5px; text-transform: uppercase;
  font-weight: 700; padding-top: 1px;
}
.wk-row.on .lbl { color: #c1584a; }
.wk-row.kun .lbl { color: #4d7bc4; }
.wk-row.gen .lbl { color: #777; }
.wk-row .val { font-family: "WKSerif", "WKSans", serif; font-size: 19px; }

.wk-composition { margin: 4px 0 10px; line-height: 1.7; }
.wk-comp-label {
  font-size: 11px; letter-spacing: .5px; text-transform: uppercase;
  color: #5a9147; font-weight: 700; margin-right: 8px;
}
.wk-comp-item { display: inline-block; white-space: nowrap; margin-right: 12px; vertical-align: middle; }
.wk-comp-item .k { font-family: "WKSerif", "WKSans", serif; font-weight: 600; font-size: 17px; }
.wk-comp-item img { height: 16px; width: auto; max-width: 30px; object-fit: contain; vertical-align: middle; }
.wk-comp-item .m { font-size: 12px; color: #666; margin-left: 3px; }
.night_mode .wk-comp-item .m { color: #aaa; }

.wk-box {
  background: #faf7f1; border-left: 3px solid #e2d6c2; border-radius: 3px;
  padding: 9px 11px; margin: 8px 0; font-size: 13.5px; line-height: 1.4; color: #5a544c;
}
.night_mode .wk-box { background: #2a2620; border-left-color: #4a4237; color: #cfc7ba; }
.wk-box .item + .item { margin-top: 6px; }
.wk-box .lbl { display: inline-block; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .3px; margin-right: 6px; }
.wk-box .lbl.meaning { color: #a2792e; }
.wk-box .lbl.reading { color: #8a67ad; }

.wk-vocab { margin-top: 8px; padding-top: 9px; border-top: 1px dashed #e2e2e2; }
.night_mode .wk-vocab { border-top-color: #444; }
.wk-vocab .head { display: flex; align-items: baseline; gap: 9px; flex-wrap: wrap; }
.wk-vocab .word { font-family: "WKSerif", "WKSans", serif; font-weight: 600; font-size: 20px; }
.wk-vocab .rd { font-family: "WKSerif", "WKSans", serif; color: #666; font-size: 15px; }
.night_mode .wk-vocab .rd { color: #aaa; }
.wk-vocab .gl { color: #666; font-size: 14px; }
.wk-vocab audio { display: block; margin-top: 5px; width: 100%; max-width: 260px; height: 30px; }

.wk-sentence { margin-top: 8px; }
.wk-sentence .ja { font-size: 15px; line-height: 1.4; word-break: break-word; }
.wk-sentence .en { font-size: 13px; color: #808080; font-style: italic; margin-top: 3px; }
.wk-sentence audio { display: block; margin-top: 5px; width: 100%; max-width: 260px; height: 30px; }

.wk-examples { margin-top: 8px; }
.wk-examples .ttl { font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: .4px; color: #111; margin-bottom: 5px; }
.night_mode .wk-examples .ttl { color: #eee; }
.wk-ex-item { display: inline-block; margin: 2px 12px 2px 0; white-space: nowrap; }
.wk-ex-item .k { font-family: "WKSerif", "WKSans", serif; font-weight: 600; font-size: 16px; }
.wk-ex-item .r { color: #c1584a; font-size: 12px; margin-left: 3px; }
.wk-ex-item .m { color: #666; font-size: 12px; margin-left: 3px; }

/* Frei erstellte Karten: dieselben Klassennamen wie im Web-Editor/Print-Template. */
.wk-free-front { display: flex; align-items: center; justify-content: center; min-height: 110px; }
.free-big { font-family: "WKSerif", "WKSans", serif; font-weight: 600; font-size: 52px; line-height: 1.1; }
.wk-free-back { text-align: left; }
.wk-free-back p { margin: 0 0 8px; }
.wk-free-back img { max-width: 100%; max-height: 220px; object-fit: contain; }
.wk-free-back ul, .wk-free-back ol { margin: 5px 0 8px; padding-left: 22px; }
.c-title { display: block; font-family: "WKSans"; font-weight: 700; font-size: 21px; margin-bottom: 8px; }
.c-box {
  background: #faf7f1; border-left: 3px solid #e2d6c2; border-radius: 3px;
  padding: 9px 11px; margin: 8px 0; font-size: 13.5px; line-height: 1.4; color: #5a544c;
}
.night_mode .c-box { background: #2a2620; border-left-color: #4a4237; color: #cfc7ba; }
""".strip()

_RADICAL_FRONT = """
<div class="wk-tags">{{TagsHtml}}</div>
<div class="wk-stage">
{{#Radical}}<div class="wk-big">{{Radical}}</div>{{/Radical}}
{{^Radical}}{{#RadicalImage}}<div class="wk-big wk-big-img">{{RadicalImage}}</div>{{/RadicalImage}}{{/Radical}}
{{^Radical}}{{^RadicalImage}}<div class="wk-fallback">{{Meaning}}</div>{{/RadicalImage}}{{/Radical}}
</div>
<div class="wk-typein">
  <div class="wk-typein-label">Bedeutung eingeben</div>
  {{type:Meaning}}
</div>
""".strip()

_RADICAL_BACK = """
{{FrontSide}}
<hr id="answer">
<div class="wk-back">
  <div class="wk-refhead">
    {{#Radical}}<span class="wk-ref">{{Radical}}</span>{{/Radical}}
    {{^Radical}}{{RadicalImage}}{{/Radical}}
    <span class="wk-meaning">{{Meaning}}</span>
  </div>
  {{MnemonicHtml}}
  {{ExamplesHtml}}
</div>
""".strip()

_KANJI_FRONT = """
<div class="wk-tags">{{TagsHtml}}</div>
<div class="wk-stage"><div class="wk-big">{{Kanji}}</div></div>
<div class="wk-typein">
  <div class="wk-typein-label">Bedeutung eingeben</div>
  {{type:MeaningPlain}}
</div>
""".strip()

_KANJI_BACK = """
{{FrontSide}}
<hr id="answer">
<div class="wk-back">
  <div class="wk-refhead"><span class="wk-ref">{{Kanji}}</span>{{MeaningsHtml}}</div>
  <div class="wk-readings">
    {{#Onyomi}}<div class="wk-row on"><div class="lbl">On</div><div class="val">{{Onyomi}}</div></div>{{/Onyomi}}
    {{#Kunyomi}}<div class="wk-row kun"><div class="lbl">Kun</div><div class="val">{{Kunyomi}}</div></div>{{/Kunyomi}}
  </div>
  {{CompositionHtml}}
  {{MnemonicsHtml}}
  {{VocabHtml}}
  {{SentenceHtml}}
</div>
""".strip()

_VOCAB_FRONT = """
<div class="wk-tags">{{TagsHtml}}</div>
<div class="wk-stage"><div class="wk-big" style="font-size:{{VocabFontSize}}px;">{{Vocab}}</div></div>
<div class="wk-typein">
  <div class="wk-typein-label">Bedeutung eingeben</div>
  {{type:MeaningPlain}}
</div>
""".strip()

_VOCAB_BACK = """
{{FrontSide}}
<hr id="answer">
<div class="wk-back">
  <div class="wk-refhead"><span class="wk-ref small">{{Vocab}}</span>{{MeaningsHtml}}</div>
  {{#PartsOfSpeech}}<div class="wk-pos">{{PartsOfSpeech}}</div>{{/PartsOfSpeech}}
  {{#Readings}}<div class="wk-row gen"><div class="lbl">Reading</div><div class="val">{{Readings}}</div></div>{{/Readings}}
  {{MnemonicsHtml}}
  {{SentenceHtml}}
</div>
""".strip()

_CUSTOM_FRONT = """
<div class="wk-tags">{{TagsHtml}}</div>
<div class="wk-free-front">{{FrontHtml}}</div>
""".strip()

_CUSTOM_BACK = """
{{FrontSide}}
<hr id="answer">
<div class="wk-free-back">{{BackHtml}}</div>
""".strip()


def _build_models(genanki: Any) -> dict[str, Any]:
    return {
        "radical": genanki.Model(
            _MODEL_ID_RADICAL,
            "WaniKani Card Studio – Radical",
            fields=[
                {"name": n}
                for n in ("Radical", "RadicalImage", "Meaning", "MnemonicHtml", "ExamplesHtml", "TagsHtml")
            ],
            templates=[{"name": "Radical", "qfmt": _RADICAL_FRONT, "afmt": _RADICAL_BACK}],
            css=_CSS,
            sort_field_index=2,
        ),
        "kanji": genanki.Model(
            _MODEL_ID_KANJI,
            "WaniKani Card Studio – Kanji",
            fields=[
                {"name": n}
                for n in (
                    "Kanji", "MeaningsHtml", "Onyomi", "Kunyomi", "CompositionHtml",
                    "MnemonicsHtml", "VocabHtml", "SentenceHtml", "TagsHtml", "MeaningPlain",
                )
            ],
            templates=[{"name": "Kanji", "qfmt": _KANJI_FRONT, "afmt": _KANJI_BACK}],
            css=_CSS,
            sort_field_index=0,
        ),
        "vocab": genanki.Model(
            _MODEL_ID_VOCAB,
            "WaniKani Card Studio – Vokabel",
            fields=[
                {"name": n}
                for n in (
                    "Vocab", "VocabFontSize", "MeaningsHtml", "Readings",
                    "PartsOfSpeech", "MnemonicsHtml", "SentenceHtml", "TagsHtml", "MeaningPlain",
                )
            ],
            templates=[{"name": "Vokabel", "qfmt": _VOCAB_FRONT, "afmt": _VOCAB_BACK}],
            css=_CSS,
            sort_field_index=0,
        ),
        "custom": genanki.Model(
            _MODEL_ID_CUSTOM,
            "WaniKani Card Studio – Frei",
            fields=[{"name": n} for n in ("FrontHtml", "BackHtml", "TagsHtml")],
            templates=[{"name": "Frei", "qfmt": _CUSTOM_FRONT, "afmt": _CUSTOM_BACK}],
            css=_CSS,
            sort_field_index=0,
        ),
    }


# --------------------------------------------------------------------------- #
# HTML-Fragmente (Python statt Jinja2 – dieselbe Logik wie im Print-Template)
# --------------------------------------------------------------------------- #

def _esc(text: str | None) -> str:
    return html.escape(text or "")


def _tags_html(tags: list[str]) -> str:
    return "".join(f'<span class="wk-tag">{_esc(t)}</span>' for t in tags or [])


def _meanings_html(meanings: list[str]) -> str:
    if not meanings:
        return ""
    primary = _esc(meanings[0])
    rest = meanings[1:]
    secondary = (
        f'<span class="sec">&nbsp;· {_esc(", ".join(rest))}</span>' if rest else ""
    )
    return f'<span class="wk-meaning">{primary}{secondary}</span>'


def _first_plain(meanings: list[str]) -> str:
    """Primäre Bedeutung als reiner Text – Vergleichsfeld für Anki {{type:Field}}."""
    return _esc(meanings[0]) if meanings else ""


def _mnemonics_html(meaning_mnemonic: str | None, reading_mnemonic: str | None) -> str:
    items = []
    if meaning_mnemonic:
        items.append(f'<div class="item"><span class="lbl meaning">Mnemonic</span>{_esc(meaning_mnemonic)}</div>')
    if reading_mnemonic:
        items.append(f'<div class="item"><span class="lbl reading">Reading</span>{_esc(reading_mnemonic)}</div>')
    if not items:
        return ""
    return '<div class="wk-box">' + "".join(items) + "</div>"


def _composition_html(components: list[dict[str, Any]]) -> str:
    if not components:
        return ""
    items = []
    for c in components:
        radical = c.get("radical") or ""
        image_uri = c.get("image_uri")
        meaning = c.get("meaning") or ""
        if radical:
            visual = f'<span class="k">{_esc(radical)}</span>'
        elif image_uri:
            visual = f'<img src="{image_uri}" alt="">'
        else:
            visual = ""
        items.append(f'<span class="wk-comp-item">{visual}<span class="m">{_esc(meaning)}</span></span>')
    return (
        '<div class="wk-composition"><span class="wk-comp-label">Composition</span>'
        + "".join(items)
        + "</div>"
    )


def _examples_html(examples: list[tuple[str, str, str]]) -> str:
    if not examples:
        return ""
    items = []
    for kanji, reading, meaning in examples:
        item = f'<span class="wk-ex-item"><span class="k">{_esc(kanji)}</span>'
        if reading:
            item += f'<span class="r">{_esc(reading)}</span>'
        item += f'<span class="m">{_esc(meaning)}</span></span>'
        items.append(item)
    return '<div class="wk-examples"><div class="ttl">Kanji</div>' + "".join(items) + "</div>"


def _audio_html(url: str | None) -> str:
    """Abspielbares <audio>-Element (referenziert die URL direkt statt sie in
    die apkg-Medien einzubetten – schlank, funktioniert für WaniKani-CDN-URLs
    und für manuell hinterlegte Audios gleichermaßen)."""
    if not url:
        return ""
    return f'<audio controls src="{_esc(url)}"></audio>'


def _vocab_example_html(
    vocab: str | None, reading: str | None, meaning: str | None, audio_url: str | None = None
) -> str:
    if not vocab:
        return ""
    head = f'<span class="word">{_esc(vocab)}</span>'
    if reading:
        head += f'<span class="rd">{_esc(reading)}</span>'
    if meaning:
        head += f'<span class="gl">{_esc(meaning)}</span>'
    return f'<div class="wk-vocab"><div class="head">{head}</div>{_audio_html(audio_url)}</div>'


def _sentence_html(ja: str | None, en: str | None, audio_url: str | None = None) -> str:
    if not ja:
        return ""
    out = f'<div class="wk-sentence"><div class="ja">{_esc(ja)}</div>'
    if en:
        out += f'<div class="en">{_esc(en)}</div>'
    out += _audio_html(audio_url)
    return out + "</div>"


# Grobe Skalierung wie bei den gedruckten Vokabelkarten (dort pt, hier px).
_VOCAB_FONT_STEPS = ((1, 92), (2, 78), (3, 64), (4, 54))


def _vocab_font_size(word: str | None) -> int:
    n = len(word or "")
    for limit, size in _VOCAB_FONT_STEPS:
        if n <= limit:
            return size
    return 42


_LEVEL_TAG_RE = re.compile(r"(?i)^lv\.?\s*(\d+)$")


def _anki_tags(tags: list[str]) -> list[str]:
    """Druck-Tags (["Kanji","Lv 5"]) in hierarchische Anki-Tags übersetzen."""
    out: list[str] = []
    for raw in tags or []:
        t = str(raw).strip()
        if not t:
            continue
        m = _LEVEL_TAG_RE.match(t)
        if m:
            out.append(f"WaniKani::Level::{m.group(1)}")
        else:
            out.append("WaniKani::" + re.sub(r"\s+", "-", t))
    return out or ["WaniKani"]


# --------------------------------------------------------------------------- #
# Card-Dataclass → genanki.Note
# --------------------------------------------------------------------------- #

def _radical_note(genanki: Any, model: Any, card: kc.RadicalCard) -> Any:
    has_char = bool(card.radical)
    fields = [
        card.radical or "",
        (f'<img src="{card.image_uri}" alt="">' if (not has_char and card.image_uri) else ""),
        _esc(card.meaning),
        _mnemonics_html(card.mnemonic, None),
        _examples_html(card.kanji_examples),
        _tags_html(card.tags),
    ]
    guid = genanki.guid_for("wkcards", "radical", card.subject_id) if card.subject_id else None
    return genanki.Note(model=model, fields=fields, tags=_anki_tags(card.tags), guid=guid)


def _kanji_note(genanki: Any, model: Any, card: kc.Card) -> Any:
    fields = [
        _esc(card.kanji),
        _meanings_html(card.meanings),
        _esc("、".join(card.onyomi)),
        _esc("、".join(card.kunyomi)),
        _composition_html(card.components),
        _mnemonics_html(card.meaning_mnemonic, card.reading_mnemonic),
        _vocab_example_html(card.vocab, card.vocab_reading, card.vocab_meaning, card.vocab_audio_url),
        _sentence_html(card.sentence_ja, card.sentence_en, card.sentence_audio_url),
        _tags_html(card.tags),
        _first_plain(card.meanings),
    ]
    guid = genanki.guid_for("wkcards", "kanji", card.subject_id) if card.subject_id else None
    return genanki.Note(model=model, fields=fields, tags=_anki_tags(card.tags), guid=guid)


def _vocab_note(genanki: Any, model: Any, card: kc.VocabCard) -> Any:
    fields = [
        _esc(card.vocab),
        str(_vocab_font_size(card.vocab)),
        _meanings_html(card.meanings),
        _esc("、".join(card.readings)),
        _esc(", ".join(card.parts_of_speech)),
        _mnemonics_html(card.meaning_mnemonic, card.reading_mnemonic),
        _sentence_html(card.sentence_ja, card.sentence_en),
        _tags_html(card.tags),
        _first_plain(card.meanings),
    ]
    guid = genanki.guid_for("wkcards", "vocab", card.subject_id) if card.subject_id else None
    return genanki.Note(model=model, fields=fields, tags=_anki_tags(card.tags), guid=guid)


def _custom_note(genanki: Any, model: Any, card: kc.CustomCard) -> Any:
    fields = [card.front_html or "", card.back_html or "", _tags_html(card.tags)]
    guid = genanki.guid_for("wkcards", "custom", card.card_id) if card.card_id else None
    return genanki.Note(model=model, fields=fields, tags=_anki_tags(card.tags), guid=guid)


def _note_for(genanki: Any, models: dict[str, Any], card: Any) -> Any | None:
    if isinstance(card, kc.RadicalCard):
        return _radical_note(genanki, models["radical"], card)
    if isinstance(card, kc.VocabCard):
        return _vocab_note(genanki, models["vocab"], card)
    if isinstance(card, kc.CustomCard):
        return _custom_note(genanki, models["custom"], card)
    if isinstance(card, kc.Card):
        return _kanji_note(genanki, models["kanji"], card)
    return None  # CoverCard o. ä. – im Anki-Export nicht sinnvoll, wird übersprungen


def _deck_id(name: str) -> int:
    """Stabile Deck-ID aus dem Namen ableiten, damit wiederholte Exporte

    desselben Deck-Namens in Anki dasselbe Deck aktualisieren statt ein
    zweites (nummeriertes) Deck anzulegen.
    """
    return 1_607_000_000_000 + (zlib.crc32(name.encode("utf-8")) % 1_000_000_000)


# --------------------------------------------------------------------------- #
# Öffentliche API
# --------------------------------------------------------------------------- #

def export_deck(
    cards: Sequence[Any],
    output: str | Path,
    *,
    deck_name: str = "WaniKani Card Studio",
) -> tuple[Path, int]:
    """Card-/RadicalCard-/VocabCard-/CustomCard-Objekte als .apkg exportieren."""
    genanki = _require_genanki()
    models = _build_models(genanki)
    deck = genanki.Deck(_deck_id(deck_name), deck_name)

    n = 0
    for card in cards:
        note = _note_for(genanki, models, card)
        if note is None:
            continue
        deck.add_note(note)
        n += 1
    if n == 0:
        raise AnkiExportError("Keine für Anki unterstützten Karten in der Auswahl gefunden.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="wkcards_anki_"))
    try:
        media_files = []
        for name, src in _FONT_FILES.items():
            dst = tmp_dir / name
            dst.write_bytes(src.read_bytes())
            media_files.append(str(dst))
        package = genanki.Package(deck, media_files=media_files)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        package.write_to_file(str(output))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return output, n


def export_subjects(
    subject_ids: Sequence[int],
    output: str | Path,
    *,
    deck_name: str | None = None,
    use_cache: bool = True,
    sample: bool = False,
) -> tuple[Path, int]:
    """WaniKani-Subjects (nach ID) direkt als Anki-Paket exportieren."""
    cards = kc.resolve_subject_deck(subject_ids, use_cache=use_cache, sample=sample)
    return export_deck(cards, output, deck_name=deck_name or "WaniKani Card Studio")


def export_custom(
    cards_data: Sequence[dict[str, Any]],
    output: str | Path,
    *,
    deck_name: str | None = None,
) -> tuple[Path, int]:
    """Selbst erstellte Karten (Dict-Form) als Anki-Paket exportieren."""
    cards = [kc.build_custom_card(d) for d in cards_data]
    if not cards:
        raise AnkiExportError("Keine Karten ausgewählt.")
    return export_deck(cards, output, deck_name=deck_name or "WaniKani Card Studio – Eigene Karten")
