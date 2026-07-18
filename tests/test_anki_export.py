"""Tests für den Anki-Export (anki_export.py)."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import anki_export as ae  # noqa: E402
import kanji_cards as kc  # noqa: E402


# --------------------------------------------------------------------------- #
# Tag-Konvertierung
# --------------------------------------------------------------------------- #

def test_anki_tags_hierarchical():
    assert ae._anki_tags(["Kanji", "Lv 5"]) == ["WaniKani::Kanji", "WaniKani::Level::5"]


def test_anki_tags_freeform_spaces_become_dashes():
    assert ae._anki_tags(["Meine Karte"]) == ["WaniKani::Meine-Karte"]


def test_anki_tags_empty_falls_back():
    assert ae._anki_tags([]) == ["WaniKani"]


# --------------------------------------------------------------------------- #
# HTML-Fragmente
# --------------------------------------------------------------------------- #

def test_tags_html_escapes_and_wraps():
    out = ae._tags_html(["Kanji", "Lv <3"])
    assert '<span class="wk-tag">Kanji</span>' in out
    assert "&lt;3" in out  # escaped, kein rohes "<"


def test_composition_html_prefers_char_over_image():
    html = ae._composition_html([{"radical": "人", "image_uri": None, "meaning": "Person"}])
    assert '<span class="k">人</span>' in html
    assert "COMPOSITION" not in html  # Label kommt über CSS text-transform, nicht im HTML
    assert "Composition" in html


def test_composition_html_falls_back_to_image():
    html = ae._composition_html([{"radical": "", "image_uri": "data:image/png;base64,AAA", "meaning": "Stick"}])
    assert '<img src="data:image/png;base64,AAA"' in html


def test_composition_html_empty_is_empty_string():
    assert ae._composition_html([]) == ""


def test_mnemonics_html_both_present():
    html = ae._mnemonics_html("Merke dir <das>.", "Liest sich wie X")
    assert "&lt;das&gt;" in html  # escaped
    assert "Reading" in html and "Mnemonic" in html


def test_vocab_font_size_scales_down_with_length():
    assert ae._vocab_font_size("一") > ae._vocab_font_size("一二三四五")


def test_vocab_example_html_embeds_audio_player():
    html = ae._vocab_example_html("大きい", "おおきい", "Big", audio_url="https://example.test/a.mp3")
    assert '<audio controls src="https://example.test/a.mp3"></audio>' in html


def test_vocab_example_html_without_audio_has_no_player():
    html = ae._vocab_example_html("大きい", "おおきい", "Big")
    assert "<audio" not in html


def test_sentence_html_embeds_audio_player():
    html = ae._sentence_html("一から始めましょう。", "Let's start from the beginning.", audio_url="https://example.test/s.mp3")
    assert '<audio controls src="https://example.test/s.mp3"></audio>' in html


# --------------------------------------------------------------------------- #
# Note-Aufbau & stabile GUIDs
# --------------------------------------------------------------------------- #

def test_kanji_note_guid_stable_across_rebuilds():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = Card_(kanji="大", subject_id=440)
    note1 = ae._kanji_note(genanki, models["kanji"], card)
    note2 = ae._kanji_note(genanki, models["kanji"], card)
    assert note1.guid == note2.guid


def test_kanji_note_guid_differs_by_subject_id():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    a = ae._kanji_note(genanki, models["kanji"], Card_(kanji="大", subject_id=1))
    b = ae._kanji_note(genanki, models["kanji"], Card_(kanji="大", subject_id=2))
    assert a.guid != b.guid


def test_custom_note_passes_html_through_unescaped():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.CustomCard(front_html='<div class="free-big">勉強</div>', back_html="<b>x</b>", tags=["Eigene"])
    note = ae._custom_note(genanki, models["custom"], card)
    assert note.fields[0] == '<div class="free-big">勉強</div>'  # nicht escaped
    assert note.fields[1] == "<b>x</b>"


def Card_(**kwargs):
    """Kleiner Helfer: Card mit sinnvollen Defaults für die Guid-Tests."""
    return kc.Card(**kwargs)


# --------------------------------------------------------------------------- #
# End-to-End: .apkg-Datei
# --------------------------------------------------------------------------- #

def test_export_deck_writes_valid_apkg(tmp_path):
    kanji_cards = kc.load_sample_cards()
    radical_cards = kc.load_sample_radicals()
    out = tmp_path / "deck.apkg"
    path, n = ae.export_deck(kanji_cards + radical_cards, out, deck_name="Test Deck")

    assert path == out
    assert path.is_file()
    assert n == len(kanji_cards) + len(radical_cards)

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "collection.anki2" in names
        assert "media" in names
        z.extract("collection.anki2", tmp_path)

    conn = sqlite3.connect(tmp_path / "collection.anki2")
    try:
        (note_count,) = conn.execute("select count(*) from notes").fetchone()
        (card_count,) = conn.execute("select count(*) from cards").fetchone()
    finally:
        conn.close()
    assert note_count == n
    assert card_count == n


def test_export_deck_embeds_fonts_as_media():
    import kanji_cards as kc2
    cards = kc2.load_sample_radicals()[:1]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "deck.apkg"
        ae.export_deck(cards, out, deck_name="Fonts Test")
        with zipfile.ZipFile(out) as z:
            import json

            media = json.loads(z.read("media"))
            assert set(media.values()) == {
                "_NotoSansJP-Regular.ttf",
                "_NotoSansJP-Bold.ttf",
                "_NotoSerifJP-SemiBold.ttf",
            }


def test_export_deck_skips_cover_and_raises_if_nothing_left():
    cover_only = [kc.CoverCard(title="X", subtitle="Y")]
    try:
        ae.export_deck(cover_only, "/dev/null")
        assert False, "sollte AnkiExportError werfen"
    except ae.AnkiExportError:
        pass


# --------------------------------------------------------------------------- #
# CLI: `python kanji_cards.py --anki` (Regression für den __main__-Modul-
# Identitäts-Bug: als Skript ausgeführt landen die Card-Klassen unter dem
# Modulnamen "__main__" statt "kanji_cards" – ohne den sys.modules-Alias vor
# main() würde anki_export.py's isinstance()-Dispatch beim Import als eigenes
# Modul stillschweigend keine einzige Karte erkennen.)
# --------------------------------------------------------------------------- #

def test_cli_anki_flag_produces_apkg(tmp_path):
    out = tmp_path / "cards.pdf"  # Endung wird bei --anki automatisch auf .apkg korrigiert
    result = subprocess.run(
        [sys.executable, "kanji_cards.py", "--sample", "--anki", "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    apkg = out.with_suffix(".apkg")
    assert apkg.is_file()
    assert "Anki-Paket" in result.stdout
    with zipfile.ZipFile(apkg) as z:
        assert "collection.anki2" in z.namelist()


def test_export_custom_uses_stable_card_id_guid(tmp_path):
    data = {
        "id": "abc123",
        "front_html": "<div>front</div>",
        "back_html": "<div>back</div>",
        "tags": ["Eigene"],
    }
    out1 = tmp_path / "one.apkg"
    out2 = tmp_path / "two.apkg"
    ae.export_custom([data], out1, deck_name="D1")
    ae.export_custom([data], out2, deck_name="D1")

    def guid_of(path):
        with zipfile.ZipFile(path) as z:
            z.extract("collection.anki2", tmp_path)
        conn = sqlite3.connect(tmp_path / "collection.anki2")
        try:
            return conn.execute("select guid from notes limit 1").fetchone()[0]
        finally:
            conn.close()

    assert guid_of(out1) == guid_of(out2)
