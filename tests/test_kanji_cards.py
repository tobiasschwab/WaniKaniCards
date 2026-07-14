"""Tests für die Kernfunktionen (keine Netzwerk-/PDF-Abhängigkeiten)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kanji_cards import (  # noqa: E402
    LAYOUTS,
    Card,
    CoverCard,
    RadicalCard,
    VocabCard,
    build_card,
    build_cover,
    build_cover_radicals,
    build_radical_card,
    build_vocab_card,
    collect_composition,
    mirror_backside,
    paginate,
    pick_example_vocab,
    resolve_composition,
    strip_markup,
)


# --------------------------------------------------------------------------- #
# strip_markup
# --------------------------------------------------------------------------- #

def test_strip_markup_removes_tags():
    assert strip_markup("<kanji>山</kanji>に<ja>登る</ja>") == "山に登る"


def test_strip_markup_none():
    assert strip_markup(None) is None


def test_strip_markup_plain():
    assert strip_markup("  hello ") == "hello"


# --------------------------------------------------------------------------- #
# mirror_backside
# --------------------------------------------------------------------------- #

def test_mirror_backside_long_edge_2cols():
    page = [1, 2, 3, 4, 5, 6]
    assert mirror_backside(page, cols=2, duplex="long-edge") == [2, 1, 4, 3, 6, 5]


def test_mirror_backside_short_edge_2cols():
    page = [1, 2, 3, 4, 5, 6]
    assert mirror_backside(page, cols=2, duplex="short-edge") == [5, 6, 3, 4, 1, 2]


def test_mirror_backside_2x2_long_edge():
    # Neues Standardlayout: 4 Karten (2x2), Wenden an der langen Kante.
    page = [1, 2, 3, 4]
    assert mirror_backside(page, cols=2, duplex="long-edge") == [2, 1, 4, 3]


def test_mirror_backside_2x2_short_edge():
    page = [1, 2, 3, 4]
    assert mirror_backside(page, cols=2, duplex="short-edge") == [3, 4, 1, 2]


def test_mirror_backside_1up_is_noop():
    # A6-Layout: eine Karte pro Seite → keine Positionsänderung nötig.
    assert mirror_backside([1], cols=1, duplex="long-edge") == [1]
    assert mirror_backside([1], cols=1, duplex="short-edge") == [1]


def test_layout_profiles():
    assert LAYOUTS["a4-4up"]["cols"] * LAYOUTS["a4-4up"]["rows"] == 4
    a6 = LAYOUTS["a6"]
    assert a6["cols"] == 1 and a6["rows"] == 1
    assert a6["paper"] == "a6" and a6["landscape"] is True


def test_mirror_backside_keeps_empty_cells_aligned():
    # 5 Karten + 1 leere Zelle (None) → None bleibt beim Spiegeln an der
    # korrekten Position, damit Vorder-/Rückseite passen.
    page = [1, 2, 3, 4, 5, None]
    assert mirror_backside(page, cols=2, duplex="long-edge") == [2, 1, 4, 3, None, 5]


def test_mirror_backside_invalid_duplex():
    with pytest.raises(ValueError):
        mirror_backside([1, 2], cols=2, duplex="diagonal")


def test_mirror_backside_invalid_cols():
    with pytest.raises(ValueError):
        mirror_backside([1, 2], cols=0)


# --------------------------------------------------------------------------- #
# paginate
# --------------------------------------------------------------------------- #

def test_paginate_pads_last_page():
    cards = [Card(kanji=str(i)) for i in range(7)]
    pages = paginate(cards, per_page=6)
    assert len(pages) == 2
    assert len(pages[0]) == 6 and all(c is not None for c in pages[0])
    assert len(pages[1]) == 6
    assert pages[1][0].kanji == "6"
    assert pages[1][1:] == [None] * 5


def test_paginate_exact_fit():
    cards = [Card(kanji=str(i)) for i in range(6)]
    pages = paginate(cards, per_page=6)
    assert len(pages) == 1
    assert all(c is not None for c in pages[0])


def test_paginate_empty():
    assert paginate([], per_page=6) == []


# --------------------------------------------------------------------------- #
# pick_example_vocab
# --------------------------------------------------------------------------- #

def _kanji(ids):
    return {"data": {"amalgamation_subject_ids": ids}}


def _vocab(sid, level, chars):
    return {"id": sid, "data": {"level": level, "characters": chars}}


def test_pick_example_vocab_lowest_level():
    kanji = _kanji([10, 11])
    vmap = {10: _vocab(10, 5, "A"), 11: _vocab(11, 2, "B")}
    assert pick_example_vocab(kanji, vmap)["data"]["characters"] == "B"


def test_pick_example_vocab_tie_uses_first_in_order():
    kanji = _kanji([10, 11])
    vmap = {10: _vocab(10, 3, "A"), 11: _vocab(11, 3, "B")}
    assert pick_example_vocab(kanji, vmap)["data"]["characters"] == "A"


def test_pick_example_vocab_none_when_missing():
    kanji = _kanji([99])
    assert pick_example_vocab(kanji, {}) is None


def test_pick_example_vocab_no_ids():
    assert pick_example_vocab({"data": {}}, {}) is None


# --------------------------------------------------------------------------- #
# build_card
# --------------------------------------------------------------------------- #

def test_build_card_full():
    kanji = {
        "data": {
            "characters": "山",
            "meanings": [
                {"meaning": "Mountain", "primary": True},
                {"meaning": "Hill", "primary": False},
            ],
            "readings": [
                {"reading": "さん", "primary": True, "type": "onyomi"},
                {"reading": "やま", "primary": False, "type": "kunyomi"},
                {"reading": "た", "primary": False, "type": "nanori"},
            ],
            "meaning_mnemonic": "Three <radical>peaks</radical> make a <kanji>Mountain</kanji>.",
            "reading_mnemonic": "Read <reading>さん</reading> like Mountain-san.",
            "amalgamation_subject_ids": [77],
        }
    }
    vmap = {
        77: {
            "id": 77,
            "data": {
                "level": 1,
                "characters": "山",
                "meanings": [{"meaning": "Mountain", "primary": True}],
                "readings": [{"reading": "やま", "primary": True}],
                "context_sentences": [{"ja": "山に登る。", "en": "Climb a mountain."}],
            },
        }
    }
    card = build_card(kanji, vmap)
    assert card.kanji == "山"
    assert card.meanings == ["Mountain", "Hill"]
    assert card.onyomi == ["さん"]
    assert card.kunyomi == ["やま"]  # nanori wird nicht als kunyomi geführt
    # Mnemonics werden übernommen und WaniKani-Markup gestrippt
    assert card.meaning_mnemonic == "Three peaks make a Mountain."
    assert card.reading_mnemonic == "Read さん like Mountain-san."
    assert card.vocab == "山"
    assert card.vocab_reading == "やま"
    assert card.vocab_meaning == "Mountain"
    assert card.sentence_ja == "山に登る。"
    assert card.sentence_en == "Climb a mountain."


def test_build_cover_lists_kanji_and_meanings():
    cards = [
        Card(kanji="一", meanings=["One", "Primary"]),
        Card(kanji="人", meanings=["Person"]),
        Card(kanji="", meanings=["ignored"]),  # ohne Kanji → nicht gelistet
    ]
    cover = build_cover(5, cards)
    assert isinstance(cover, CoverCard)
    assert cover.subtitle == "Level 5"
    assert cover.entries == [("一", "One"), ("人", "Person")]


def test_build_radical_card_full():
    radical = {
        "data": {
            "characters": "山",
            "meanings": [{"meaning": "Mountain", "primary": True}],
            "meaning_mnemonic": "Three <radical>peaks</radical> = a Mountain.",
            "amalgamation_subject_ids": [10, 11],
        }
    }
    kanji_map = {
        10: {"data": {
            "characters": "山",
            "readings": [{"reading": "さん", "primary": True, "type": "onyomi"}],
            "meanings": [{"meaning": "Mountain", "primary": True}],
        }},
        11: {"data": {
            "characters": "岩",
            "readings": [{"reading": "がん", "primary": True, "type": "onyomi"}],
            "meanings": [{"meaning": "Boulder", "primary": True}],
        }},
    }
    card = build_radical_card(radical, kanji_map)
    assert isinstance(card, RadicalCard)
    assert card.radical == "山"
    assert card.meaning == "Mountain"
    assert card.mnemonic == "Three peaks = a Mountain."  # Markup gestrippt
    assert card.kanji_examples == [("山", "さん", "Mountain"), ("岩", "がん", "Boulder")]


def test_build_radical_card_image_only():
    radical = {
        "data": {
            "characters": None,
            "meanings": [{"meaning": "Stick", "primary": True}],
            "meaning_mnemonic": "A stick.",
            "character_images": [],
            "_image_data_uri": "data:image/svg+xml;base64,AAA",
            "amalgamation_subject_ids": [],
        }
    }
    card = build_radical_card(radical, {})
    assert card.radical == ""
    assert card.image_uri == "data:image/svg+xml;base64,AAA"
    assert card.kanji_examples == []


def test_default_tags_type_and_level():
    kanji = {"data": {"characters": "山", "level": 3,
             "meanings": [{"meaning": "Mountain", "primary": True}], "readings": []}}
    card = build_card(kanji, {})
    assert card.tags == ["Kanji", "Lv 3"]


def test_build_vocab_card():
    vocab = {
        "object": "vocabulary",
        "data": {
            "characters": "一人", "level": 3,
            "meanings": [{"meaning": "Alone", "primary": True}],
            "readings": [{"reading": "ひとり", "primary": True}],
            "parts_of_speech": ["noun"],
            "meaning_mnemonic": "<vocabulary>一人</vocabulary> is alone.",
            "reading_mnemonic": "Read ひとり.",
            "context_sentences": [{"ja": "一人で行く。", "en": "Go alone."}],
        },
    }
    card = build_vocab_card(vocab)
    assert isinstance(card, VocabCard)
    assert card.vocab == "一人"
    assert card.readings == ["ひとり"]
    assert card.meanings == ["Alone"]
    assert card.parts_of_speech == ["noun"]
    assert card.meaning_mnemonic == "一人 is alone."  # Markup gestrippt
    assert card.sentence_ja == "一人で行く。"
    assert card.tags == ["Vocab", "Lv 3"]


def test_collect_composition_recursive():
    reg = {
        1: {"id": 1, "object": "vocabulary", "data": {"component_subject_ids": [2, 3]}},
        2: {"id": 2, "object": "kanji", "data": {"component_subject_ids": [4]}},
        3: {"id": 3, "object": "kanji", "data": {"component_subject_ids": [4]}},
        4: {"id": 4, "object": "radical", "data": {}},
    }
    order = [s["id"] for s in collect_composition([1], reg)]
    # Wurzel zuerst, dann Kanji, dann (dedupliziert) das Radical
    assert order == [1, 2, 3, 4]


def test_resolve_composition_sample():
    # 一人 (id 2481) → 一,人 (Kanji) → Ground,Person (Radicals)
    cards = resolve_composition([2481], sample=True)
    kinds = [c["kind"] for c in cards]
    assert cards[0]["characters"] == "一人"
    assert "Kanji" in kinds and "Radical" in kinds
    assert len(cards) == 5


def test_build_cover_radicals_kind():
    cards = [RadicalCard(radical="山", meaning="Mountain"), RadicalCard(radical="", meaning="Stick")]
    cover = build_cover_radicals(3, cards)
    assert cover.kind == "Radicals"
    assert cover.subtitle == "Level 3"
    assert cover.entries == [("山", "Mountain"), ("", "Stick")]


def test_build_card_without_vocab_still_builds():
    kanji = {
        "data": {
            "characters": "口",
            "meanings": [{"meaning": "Mouth", "primary": True}],
            "readings": [{"reading": "こう", "primary": True, "type": "onyomi"}],
            "amalgamation_subject_ids": [],
        }
    }
    card = build_card(kanji, {})
    assert card.kanji == "口"
    assert card.vocab is None
    assert card.sentence_ja is None
