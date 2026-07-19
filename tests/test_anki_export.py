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


def test_sentences_html_embeds_audio_player():
    html = ae._sentences_html(
        "一から始めましょう。", "Let's start from the beginning.", "https://example.test/s.mp3", []
    )
    assert '<audio controls src="https://example.test/s.mp3"></audio>' in html


def test_sentences_html_includes_extra_sentences():
    html = ae._sentences_html(
        "一から始めましょう。",
        "Let's start from the beginning.",
        None,
        [{"ja": "一番になりたい。", "en": "I want to be number one.", "audio_url": None}],
    )
    assert "一から始めましょう。" in html
    assert "一番になりたい。" in html
    assert html.count('class="wk-sentence-item"') == 2


def test_sentences_html_empty_without_primary():
    assert ae._sentences_html(None, None, None, []) == ""


def test_doclink_html_renders_link():
    html = ae._doclink_html("https://www.wanikani.com/kanji/%E4%B8%80")
    assert 'href="https://www.wanikani.com/kanji/%E4%B8%80"' in html
    assert "WaniKani" in html


def test_doclink_html_empty_without_url():
    assert ae._doclink_html(None) == ""


# --------------------------------------------------------------------------- #
# Typ-Akzent (farbiger Streifen je Kartentyp)
# --------------------------------------------------------------------------- #

def test_models_have_distinct_accent_colors():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    for kind in ("radical", "kanji", "vocab"):
        assert ae._TYPE_ACCENT[kind] in models[kind].css
    colors = {ae._TYPE_ACCENT[k] for k in ("radical", "kanji", "vocab")}
    assert len(colors) == 3  # alle drei unterschiedlich


def test_custom_model_has_no_accent():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    for color in ae._TYPE_ACCENT.values():
        assert color not in models["custom"].css


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


def test_kana_note_fields():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.KanaCard(
        word="しあい", kanji_hint="試合", meaning="Spiel",
        sentence_ja="しあいがはじまりました。", sentence_translation="Das Spiel hat begonnen.",
        tags=["Dictionary"], card_id="kana_abc",
    )
    note = ae._kana_note(genanki, models["kana"], card)
    assert note.fields[0] == "しあい"
    assert "Spiel" in note.fields[1]
    assert "wk-meaning" in note.fields[1]
    assert "試合" in note.fields[2]
    assert "しあいがはじまりました" in note.fields[3]
    assert "Das Spiel hat begonnen." in note.fields[3]
    assert "Dictionary" in note.fields[4]
    assert note.fields[5] == "Spiel"  # MeaningPlain: nur die Kern-Bedeutung


def test_kana_note_meaning_extra_shown_as_secondary():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.KanaCard(word="ぼく", meaning="ich", meaning_extra="vertraulich im Ton; Kleiner", card_id="kana_boku")
    note = ae._kana_note(genanki, models["kana"], card)
    assert '<span class="wk-meaning">ich' in note.fields[1]
    assert '<span class="sec">' in note.fields[1]
    assert "vertraulich im Ton; Kleiner" in note.fields[1]
    assert note.fields[5] == "ich"  # MeaningPlain zeigt weiterhin nur die Kernbedeutung


def test_kana_note_without_meaning_extra_omits_secondary_span():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.KanaCard(word="さあ", meaning="well now", meaning_extra=None, card_id="kana_saa2")
    note = ae._kana_note(genanki, models["kana"], card)
    assert '<span class="sec">' not in note.fields[1]


def test_kana_note_without_kanji_hint_omits_it():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.KanaCard(word="さあ", kanji_hint=None, meaning="well now", card_id="kana_saa")
    note = ae._kana_note(genanki, models["kana"], card)
    assert note.fields[2] == ""


def test_note_for_dispatches_kana_card():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.KanaCard(word="しあい", meaning="match", card_id="kana_x")
    note = ae._note_for(genanki, models, card)
    assert note is not None
    assert note.fields[0] == "しあい"


def Card_(**kwargs):
    """Kleiner Helfer: Card mit sinnvollen Defaults für die Guid-Tests."""
    return kc.Card(**kwargs)


# --------------------------------------------------------------------------- #
# Antwort eintippen ({{type:Field}})
# --------------------------------------------------------------------------- #

def test_radical_front_template_has_type_in_meaning():
    assert "{{type:Meaning}}" in ae._RADICAL_FRONT


def test_kanji_front_template_has_type_in_meaning_plain():
    assert "{{type:MeaningPlain}}" in ae._KANJI_FRONT_MEANING


def test_kanji_on_template_gated_on_onyomi_primary():
    assert "{{#OnyomiPrimary}}" in ae._KANJI_FRONT_ON
    assert "{{type:OnyomiPrimary}}" in ae._KANJI_FRONT_ON


def test_kanji_kun_template_gated_on_kunyomi_primary():
    assert "{{#KunyomiPrimary}}" in ae._KANJI_FRONT_KUN
    assert "{{type:KunyomiPrimary}}" in ae._KANJI_FRONT_KUN


def test_vocab_front_template_has_type_in_meaning_plain():
    assert "{{type:MeaningPlain}}" in ae._VOCAB_FRONT


def test_custom_front_template_has_no_type_in():
    # Freie Karten haben keine feste "richtige Antwort" – kein Eintippen.
    assert "{{type:" not in ae._CUSTOM_FRONT


def test_kanji_note_meaning_plain_matches_primary_meaning():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = Card_(kanji="大", meanings=["Big", "Large"], subject_id=1)
    note = ae._kanji_note(genanki, models["kanji"], card)
    field_names = [f["name"] for f in models["kanji"].fields]
    assert note.fields[field_names.index("MeaningPlain")] == "Big"


def test_vocab_note_meaning_plain_matches_primary_meaning():
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = kc.VocabCard(vocab="大きい", meanings=["Big", "Large"], subject_id=1)
    note = ae._vocab_note(genanki, models["vocab"], card)
    field_names = [f["name"] for f in models["vocab"].fields]
    assert note.fields[field_names.index("MeaningPlain")] == "Big"


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
    # Kanji-Notizen erzeugen bis zu 3 Karten (Meaning/On'yomi/Kun'yomi), Radicals
    # genau eine – die Sample-Kanji haben alle beide Lesungsarten, daher exakt
    # das 3-fache für Kanji + 1-fache für Radicals.
    assert card_count == len(kanji_cards) * 3 + len(radical_cards)


# --------------------------------------------------------------------------- #
# Deck-Struktur: Japanisch::WaniKani::Level N / Japanisch::sonstige
# --------------------------------------------------------------------------- #

def _deck_names(apkg_path, tmp_path):
    import json as _json
    with zipfile.ZipFile(apkg_path) as z:
        z.extract("collection.anki2", tmp_path)
    conn = sqlite3.connect(tmp_path / "collection.anki2")
    try:
        decks = _json.loads(conn.execute("select decks from col").fetchone()[0])
    finally:
        conn.close()
    return {d["name"] for d in decks.values()}


def test_deck_path_for_wanikani_card_uses_level():
    assert ae._deck_path_for(Card_(kanji="大", level=5)) == "Japanisch::WaniKani::Level 5"


def test_deck_path_for_card_without_level_falls_back_to_sonstige():
    assert ae._deck_path_for(Card_(kanji="大", level=None)) == "Japanisch::sonstige"


def test_deck_path_for_custom_card_is_sonstige():
    custom = kc.CustomCard(front_html="<div>x</div>", back_html="<div>y</div>")
    assert ae._deck_path_for(custom) == "Japanisch::sonstige"


def test_export_deck_groups_notes_by_wanikani_level(tmp_path):
    lvl1 = Card_(kanji="一", subject_id=1, level=1)
    lvl5 = Card_(kanji="五", subject_id=5, level=5)
    custom = kc.CustomCard(front_html="<div>frei</div>", back_html="<div>x</div>", card_id="c1")
    out = tmp_path / "deck.apkg"
    ae.export_deck([lvl1, lvl5, custom], out)

    names = _deck_names(out, tmp_path)
    assert "Japanisch::WaniKani::Level 1" in names
    assert "Japanisch::WaniKani::Level 5" in names
    assert "Japanisch::sonstige" in names


def test_export_deck_ignores_deck_name_for_placement(tmp_path):
    card = Card_(kanji="一", subject_id=1, level=3)
    out = tmp_path / "deck.apkg"
    ae.export_deck([card], out, deck_name="Irgendein Titel")
    names = _deck_names(out, tmp_path)
    assert "Japanisch::WaniKani::Level 3" in names
    assert "Irgendein Titel" not in names


def test_kanji_note_skips_missing_reading_cards(tmp_path):
    """Ein Kanji ohne Kun'yomi darf keine (leere) Kun'yomi-Karte erzeugen."""
    genanki = ae._require_genanki()
    models = ae._build_models(genanki)
    card = Card_(kanji="口", meanings=["Mouth"], onyomi=["こう"], kunyomi=[], subject_id=999)
    note = ae._kanji_note(genanki, models["kanji"], card)
    template_names = [models["kanji"].templates[c.ord]["name"] for c in note.cards]
    assert template_names == ["Meaning", "On'yomi"]  # kein Kun'yomi-Card


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
                "_wanakana.min.js",
            }


def test_onyomi_kunyomi_templates_bind_wanakana_to_typeans():
    """Romaji->Kana-Live-Konvertierung nur an den Lesungs-Type-in-Feldern
    (nicht an der Bedeutung, die auf Englisch eingetippt wird)."""
    assert '<script src="_wanakana.min.js">' in ae._KANJI_FRONT_ON
    assert 'wanakana.bind(answerDiv)' in ae._KANJI_FRONT_ON
    assert '<script src="_wanakana.min.js">' in ae._KANJI_FRONT_KUN
    assert 'wanakana.bind(answerDiv)' in ae._KANJI_FRONT_KUN
    assert "wanakana" not in ae._KANJI_FRONT_MEANING
    assert "wanakana" not in ae._VOCAB_FRONT
    assert "wanakana" not in ae._RADICAL_FRONT


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
