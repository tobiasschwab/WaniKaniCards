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
    CustomCard,
    RadicalCard,
    VocabCard,
    WaniKaniClient,
    build_card,
    build_custom_card,
    build_cover,
    build_cover_radicals,
    build_radical_card,
    build_vocab_card,
    build_kana_card,
    build_generic_dictionary_card,
    build_kana_card_from_dict,
    build_ai_kana_card,
    KanaCard,
    collect_composition,
    mirror_backside,
    paginate,
    WaniKaniError,
    pick_example_vocab,
    resolve_composition,
    resolve_subject_ids,
    resolve_level,
    annotate_text,
    annotate_text_ai,
    strip_markup,
    lemmatize_text,
    kana_card_id,
    ai_kana_card_id,
    _resolve_audio_url,
    _split_sentences,
    _is_kana_only,
    _reconcile_gemini_tokens,
    _load_sample_raw,
)

import dictionary as dic
import gemini_client


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
    assert card.meanings == ["mountain", "hill"]
    assert card.onyomi == ["さん"]
    assert card.kunyomi == ["やま"]  # nanori wird nicht als kunyomi geführt
    # Mnemonics werden übernommen und WaniKani-Markup gestrippt
    assert card.meaning_mnemonic == "Three peaks make a Mountain."
    assert card.reading_mnemonic == "Read さん like Mountain-san."
    assert card.vocab == "山"
    assert card.vocab_reading == "やま"
    assert card.vocab_meaning == "mountain"
    assert card.sentence_ja == "山に登る。"
    assert card.sentence_en == "Climb a mountain."


def test_build_card_extracts_audio_urls():
    kanji = {
        "data": {
            "characters": "山",
            "meanings": [{"meaning": "Mountain", "primary": True}],
            "readings": [{"reading": "さん", "primary": True, "type": "onyomi"}],
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
                "context_sentences": [
                    {
                        "ja": "山に登る。",
                        "en": "Climb a mountain.",
                        "audios": [{"url": "https://example.test/sentence.mp3", "content_type": "audio/mpeg"}],
                    }
                ],
                # WaniKani-Schema: mehrere Stimmen, mp3 bevorzugt
                "pronunciation_audios": [
                    {"url": "https://example.test/vocab.ogg", "content_type": "audio/ogg"},
                    {"url": "https://example.test/vocab.mp3", "content_type": "audio/mpeg"},
                ],
            },
        }
    }
    card = build_card(kanji, vmap)
    assert card.vocab_audio_url == "https://example.test/vocab.mp3"  # mp3 bevorzugt
    assert card.sentence_audio_url == "https://example.test/sentence.mp3"


def test_build_card_without_audio_fields_stays_none():
    kanji = {"data": {"characters": "口", "meanings": [{"meaning": "Mouth", "primary": True}]}}
    card = build_card(kanji, {})
    assert card.vocab_audio_url is None
    assert card.sentence_audio_url is None


def test_build_card_downloads_audio_via_fetcher_for_anki():
    """Ohne Fetcher (PDF/Test) bleibt die rohe URL; mit Fetcher (Anki-Export)
    wird heruntergeladen und als data-URI eingebettet (funktioniert offline)."""
    kanji = {
        "data": {
            "characters": "山",
            "meanings": [{"meaning": "Mountain", "primary": True}],
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
                "pronunciation_audios": [{"url": "https://example.test/vocab.mp3", "content_type": "audio/mpeg"}],
            },
        }
    }
    calls = []

    def fake_fetcher(url):
        calls.append(url)
        return "data:audio/mpeg;base64,AAAA"

    card = build_card(kanji, vmap, image_fetcher=fake_fetcher)
    assert card.vocab_audio_url == "data:audio/mpeg;base64,AAAA"
    assert calls == ["https://example.test/vocab.mp3"]


def test_resolve_audio_url_passes_through_data_uri_without_fetching():
    calls = []

    def fetcher(url):
        calls.append(url)
        return "data:audio/mpeg;base64,SHOULD_NOT_BE_USED"

    result = _resolve_audio_url("data:audio/wav;base64,AAAA", fetcher)
    assert result == "data:audio/wav;base64,AAAA"
    assert calls == []  # bereits eingebettet – kein Download nötig


def test_resolve_audio_url_falls_back_to_raw_url_if_fetch_fails():
    result = _resolve_audio_url("https://example.test/a.mp3", lambda url: None)
    assert result == "https://example.test/a.mp3"  # funktioniert dann online weiter


def test_build_card_collects_extra_sentences():
    kanji = {
        "data": {
            "characters": "山",
            "meanings": [{"meaning": "Mountain", "primary": True}],
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
                "context_sentences": [
                    {"ja": "山に登る。", "en": "Climb a mountain."},
                    {"ja": "高い山です。", "en": "It's a tall mountain."},
                    {"ja": "三つ目の文。", "en": "Third sentence."},
                    {"ja": "四つ目の文。", "en": "Fourth sentence (verworfen)."},
                ],
            },
        }
    }
    card = build_card(kanji, vmap)
    assert card.sentence_ja == "山に登る。"
    # Nur 2 zusätzliche Sätze (MAX_EXTRA_SENTENCES) – der vierte fällt weg.
    assert [s["ja"] for s in card.extra_sentences] == ["高い山です。", "三つ目の文。"]


def test_build_card_document_url():
    kanji = {
        "data": {
            "characters": "山",
            "meanings": [{"meaning": "Mountain", "primary": True}],
            "document_url": "https://www.wanikani.com/kanji/%E5%B1%B1",
        }
    }
    card = build_card(kanji, {})
    assert card.document_url == "https://www.wanikani.com/kanji/%E5%B1%B1"


def test_build_card_resolves_composition():
    kanji = {
        "data": {
            "characters": "大",
            "meanings": [{"meaning": "Big", "primary": True}],
            "readings": [{"reading": "だい", "primary": True, "type": "onyomi"}],
            "component_subject_ids": [2, 4],
        }
    }
    subject_map = {
        2: {
            "id": 2,
            "object": "radical",
            "data": {
                "characters": "人",
                "meanings": [{"meaning": "Person", "primary": True}],
            },
        },
        4: {
            "id": 4,
            "object": "radical",
            "data": {  # bildbasiertes Radical ohne Unicode-Zeichen
                "characters": None,
                "meanings": [{"meaning": "Big", "primary": True}],
                "_image_data_uri": "data:image/png;base64,AAA",
            },
        },
    }
    card = build_card(kanji, subject_map)
    assert [c["radical"] for c in card.components] == ["人", ""]
    assert [c["meaning"] for c in card.components] == ["person", "big"]
    # Bild-Radical ohne Zeichen führt die eingebettete Bild-URI mit.
    assert card.components[1]["image_uri"] == "data:image/png;base64,AAA"


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
    assert card.meaning == "mountain"
    assert card.mnemonic == "Three peaks = a Mountain."  # Markup gestrippt
    assert card.kanji_examples == [("山", "さん", "mountain"), ("岩", "がん", "boulder")]


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
    assert card.meanings == ["alone"]
    assert card.parts_of_speech == ["noun"]
    assert card.meaning_mnemonic == "一人 is alone."  # Markup gestrippt
    assert card.sentence_ja == "一人で行く。"
    assert card.tags == ["Vocab", "Lv 3"]


def test_build_vocab_card_own_audio_and_document_url():
    vocab = {
        "id": 99,
        "data": {
            "characters": "一人",
            "meanings": [{"meaning": "Alone", "primary": True}],
            "pronunciation_audios": [{"url": "https://example.test/hitori.mp3", "content_type": "audio/mpeg"}],
            "document_url": "https://www.wanikani.com/vocabulary/%E4%B8%80%E4%BA%BA",
            "context_sentences": [
                {"ja": "一人で行く。", "en": "Go alone."},
                {"ja": "二番目の文。", "en": "Second sentence."},
            ],
        },
    }
    card = build_vocab_card(vocab)  # ohne Fetcher: rohe URL bleibt (z. B. PDF-Modus)
    assert card.audio_url == "https://example.test/hitori.mp3"
    assert card.document_url == "https://www.wanikani.com/vocabulary/%E4%B8%80%E4%BA%BA"
    assert [s["ja"] for s in card.extra_sentences] == ["二番目の文。"]

    downloaded = []
    card2 = build_vocab_card(vocab, image_fetcher=lambda u: downloaded.append(u) or "data:audio/mpeg;base64,BBBB")
    assert card2.audio_url == "data:audio/mpeg;base64,BBBB"
    assert downloaded == ["https://example.test/hitori.mp3"]


def test_build_radical_card_document_url():
    radical = {
        "data": {
            "characters": "山",
            "meanings": [{"meaning": "Mountain", "primary": True}],
            "document_url": "https://www.wanikani.com/radicals/mountain",
        }
    }
    card = build_radical_card(radical, {})
    assert card.document_url == "https://www.wanikani.com/radicals/mountain"


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


def test_resolve_subject_ids_returns_only_requested_subjects_no_descent():
    # 一人 (id 2481) hat Komponenten (一, 人 usw.) - resolve_subject_ids soll
    # NICHT absteigen, nur die angeforderte ID selbst liefern.
    cards = resolve_subject_ids([2481], sample=True)
    assert len(cards) == 1
    assert cards[0]["characters"] == "一人"


def test_resolve_subject_ids_preserves_order_and_dedupes():
    cards = resolve_subject_ids([2481, 2467, 2481], sample=True)
    assert [c["id"] for c in cards] == [2481, 2467]


def test_resolve_subject_ids_empty_list():
    assert resolve_subject_ids([], sample=True) == []


def test_resolve_level_single_type_string_backward_compat():
    cards = resolve_level(1, "kanji", sample=True)
    assert cards and all(c["kind"] == "Kanji" for c in cards)


def test_resolve_level_combines_multiple_types_in_order():
    cards = resolve_level(1, ["kanji", "radicals"], sample=True)
    kinds = [c["kind"] for c in cards]
    # Reihenfolge: Radicals vor Kanji (WaniKani-Lernpfad), unabhängig von der
    # Reihenfolge in der übergebenen Liste.
    assert kinds.index("Radical") < kinds.index("Kanji")
    assert "Vocab" not in kinds


def test_resolve_level_all_three_types():
    cards = resolve_level(1, ["radicals", "kanji", "vocabulary"], sample=True)
    kinds = {c["kind"] for c in cards}
    assert kinds == {"Radical", "Kanji", "Vocab"}


def test_resolve_level_empty_types_raises():
    with pytest.raises(WaniKaniError):
        resolve_level(1, [], sample=True)


def test_resolve_level_ignores_unknown_types():
    with pytest.raises(WaniKaniError):
        resolve_level(1, ["not-a-real-type"], sample=True)


def test_build_custom_card_html():
    d = {
        "front_html": '<div class="free-big">勉強</div>',
        "back_html": '<div class="c-title">Study</div><div class="c-box">bench + study</div>',
        "tags": ["Vocab", "", "  "],
    }
    c = build_custom_card(d)
    assert isinstance(c, CustomCard)
    assert c.front_html == '<div class="free-big">勉強</div>'
    assert "c-title" in c.back_html
    assert c.tags == ["Vocab"]  # leere Tags entfernt


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


# --------------------------------------------------------------------------- #
# WaniKaniClient.fetch_audio_data_uri (mockt HTTP – kein echtes Netzwerk nötig,
# WaniKani ist in dieser Sandbox ohnehin geblockt; verifiziert aber, dass der
# reale Download-Mechanismus für den Anki-Audio-Export funktioniert)
# --------------------------------------------------------------------------- #

class _FakeResponse:
    def __init__(self, content: bytes, content_type: str, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {"Content-Type": content_type}


class _FakeSession:
    def __init__(self, response: "_FakeResponse"):
        self.response = response
        self.calls: list[str] = []

    def get(self, url: str, timeout: int = 30):
        self.calls.append(url)
        return self.response


def test_fetch_audio_data_uri_downloads_and_embeds_as_data_uri():
    """Simuliert einen echten WaniKani-Audio-Download: MP3-Bytes rein, korrekt
    kodierte data:-URI raus – derselbe Mechanismus, der real gegen WaniKanis
    Audio-CDN läuft, hier nur mit einer Fake-Session statt echtem Netzwerk."""
    fake_mp3_bytes = b"ID3\x03\x00\x00\x00fake-mp3-bytes"
    session = _FakeSession(_FakeResponse(fake_mp3_bytes, "audio/mpeg"))
    client = WaniKaniClient("dummy-token", use_cache=False, session=session)

    uri = client.fetch_audio_data_uri("https://api.wanikani.com/audio/hitori.mp3")

    assert session.calls == ["https://api.wanikani.com/audio/hitori.mp3"]
    assert uri.startswith("data:audio/mpeg;base64,")
    import base64
    assert base64.b64decode(uri.split(",", 1)[1]) == fake_mp3_bytes


def test_fetch_audio_data_uri_is_same_function_as_image_fetcher():
    # Bewusst derselbe (content-type-agnostische) Fetcher für Bilder und Audio.
    assert WaniKaniClient.fetch_audio_data_uri is WaniKaniClient.fetch_image_data_uri


def test_fetch_audio_data_uri_returns_none_on_persistent_failure():
    session = _FakeSession(_FakeResponse(b"", "text/html", status_code=404))
    client = WaniKaniClient("dummy-token", use_cache=False, session=session)
    assert client.fetch_audio_data_uri("https://example.test/missing.mp3") is None


# --------------------------------------------------------------------------- #
# Text-Modus: Sätze zerlegen, lemmatisieren, gegen WaniKani abgleichen
# --------------------------------------------------------------------------- #

def test_split_sentences_splits_on_japanese_punctuation():
    text = "大きい山に登った。小さい犬がいた！本当？"
    assert _split_sentences(text) == [
        "大きい山に登った。",
        "小さい犬がいた！",
        "本当？",
    ]


def test_split_sentences_splits_on_newlines_too():
    assert _split_sentences("一行目\n二行目\n\n三行目") == ["一行目", "二行目", "三行目"]


def test_split_sentences_strips_and_drops_empty():
    assert _split_sentences("  一。  \n\n  ") == ["一。"]


def test_lemmatize_text_uses_dictionary_base_form():
    # 「大きく」 (Adverbform) → Grundform 「大きい」; jedes Paar trägt den
    # Original-Satz mit, in dem das Wort vorkam.
    pairs = lemmatize_text("犬が大きく吠えた。")
    lemmas = [p[0] for p in pairs]
    assert "大きい" in lemmas
    assert all(sentence == "犬が大きく吠えた。" for _, sentence in pairs)


def test_lemmatize_text_empty_string():
    assert lemmatize_text("") == []


def test_annotate_text_reconstructs_lines_exactly():
    text = "大きい山に人が一人います。\n犬は口を大きく開けた。"
    lines = annotate_text(text, sample=True)
    assert len(lines) == 2
    for original, segments in zip(text.split("\n"), lines):
        assert "".join(s["text"] for s in segments) == original


def test_annotate_text_marks_wanikani_matches_as_word_segments():
    text = "大きい山に人が一人います。"
    lines = annotate_text(text, sample=True)
    words = {s["lemma"]: s for s in lines[0] if s["type"] == "word"}
    assert "大きい" in words
    assert words["大きい"]["kind"] == "Vocab"
    assert words["大きい"]["meaning"] == "big"
    assert words["大きい"]["sentence"] == text


def test_annotate_text_prefers_vocabulary_over_kanji_for_same_lemma():
    # "一" ist in den Sample-Daten sowohl Vokabel (id 2467) als auch Kanji
    # (id 440) und Radical (id 1) – im Lesefluss soll das Wort gewinnen.
    lines = annotate_text("一人います。", sample=True)
    words = [s for s in lines[0] if s["type"] == "word" and s["lemma"] == "一"]
    assert words and words[0]["kind"] == "Vocab"


def test_annotate_text_no_match_stays_plain_text():
    lines = annotate_text("asdf qwer zxcv", sample=True)
    assert all(s["type"] == "text" for s in lines[0])


def test_annotate_text_empty_string_returns_single_empty_line():
    assert annotate_text("", sample=True) == [[]]


def test_annotate_text_wanikani_words_carry_source_field():
    lines = annotate_text("大きい山に人が一人います。", sample=True)
    words = [s for s in lines[0] if s["type"] == "word"]
    assert words and all(s["source"] == "wanikani" for s in words)


# --------------------------------------------------------------------------- #
# _is_kana_only
# --------------------------------------------------------------------------- #

def test_is_kana_only_true_for_pure_hiragana():
    assert _is_kana_only("しあい") is True


def test_is_kana_only_false_when_kanji_present():
    assert _is_kana_only("試合") is False


def test_is_kana_only_false_for_empty_string():
    assert _is_kana_only("") is False


# --------------------------------------------------------------------------- #
# annotate_text: JMdict-Fallback für kana-only Wörter ohne WaniKani-Treffer
# --------------------------------------------------------------------------- #

def test_annotate_text_falls_back_to_dictionary_for_kana_only_unmatched_word(monkeypatch):
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})
    lines = annotate_text("しあいがはじまりました。", sample=True)
    words = [s for s in lines[0] if s["type"] == "word"]
    assert len(words) == 1
    seg = words[0]
    assert seg["source"] == "dictionary"
    assert seg["kind"] == "Dict"
    assert seg["text"] == "しあい"
    assert seg["meaning"] == "match; game"
    assert seg["kanji_hint"] == "試合"
    assert seg["id"] == kana_card_id("しあい")
    assert seg["sentence"] == "しあいがはじまりました。"


def test_annotate_text_does_not_dictionary_fallback_for_kanji_words(monkeypatch):
    # "試合" enthält Kanji -> auch ohne WaniKani-Treffer KEIN JMdict-Fallback
    # (der Nutzer soll das dann als Kanji lernen, nicht als Hiragana-Karte).
    monkeypatch.setattr(dic, "_index_cache", {"試合": {"kanji": None, "meaning": "should not be used"}})
    lines = annotate_text("試合があります。", sample=True)
    words = [s for s in lines[0] if s["type"] == "word"]
    assert words == []


def test_annotate_text_no_dictionary_fallback_when_jmdict_has_no_entry(monkeypatch):
    monkeypatch.setattr(dic, "_index_cache", {})
    lines = annotate_text("ぜんぜんちがう。", sample=True)
    words = [s for s in lines[0] if s["type"] == "word"]
    assert words == []


def test_annotate_text_wanikani_match_wins_over_dictionary_fallback(monkeypatch):
    # "大きい" hat sowohl einen WaniKani-Treffer (Sample-Daten) als auch einen
    # JMdict-Eintrag -> WaniKani gewinnt (kommt vor dem Fallback-Zweig).
    monkeypatch.setattr(dic, "_index_cache", {"大きい": {"kanji": None, "meaning": "should not be used"}})
    lines = annotate_text("大きい山です。", sample=True)
    seg = next(s for s in lines[0] if s["type"] == "word" and s["lemma"] == "大きい")
    assert seg["source"] == "wanikani"


# --------------------------------------------------------------------------- #
# annotate_text_ai: KI-Modus (Gemini, Satz-Tabelle, kein Janome-Fallback)
# --------------------------------------------------------------------------- #

def _fake_gemini(tokens, grammar_notes="Notiz", translation="Übersetzung"):
    def _analyze_sentences(sentences, api_key, *, model=gemini_client.DEFAULT_MODEL, session=None, use_cache=True, **kwargs):
        return {
            s: {"tokens": tokens, "grammar_notes": grammar_notes, "translation": translation}
            for s in sentences
        }
    return _analyze_sentences


def _ai_tok(surface, dictionary_form=None, reading="", function="", meaning="", is_content_word=True):
    return {
        "surface": surface,
        "dictionary_form": dictionary_form or surface,
        "reading": reading,
        "function": function,
        "meaning": meaning,
        "is_content_word": is_content_word,
    }


def test_reconcile_gemini_tokens_exact_match_passes_through():
    gtoks = [("大きい", "大きい", "Adjektiv"), ("。", "。", "Satzzeichen")]
    assert _reconcile_gemini_tokens(gtoks, "大きい。") == gtoks


def test_reconcile_gemini_tokens_appends_missing_trailing_punctuation():
    # Gemini lässt das abschließende 。 regelmäßig weg, obwohl der Prompt
    # explizit danach fragt -> wird als eigenes, funktionsloses Token ergänzt
    # statt die ganze Satzgruppe zu verwerfen.
    gtoks = [("大きい", "大きい", "Adjektiv")]
    result = _reconcile_gemini_tokens(gtoks, "大きい。")
    assert result == [("大きい", "大きい", "Adjektiv"), ("。", "。", "")]


def test_reconcile_gemini_tokens_rejects_missing_word_characters():
    # Fehlt mehr als reine Satzzeichen (hier ein ganzes Wort) -> kein Ergänzen,
    # sondern Fallback (None signalisiert das dem Aufrufer).
    gtoks = [("大きい", "大きい", "Adjektiv")]
    assert _reconcile_gemini_tokens(gtoks, "大きい猫。") is None


def test_reconcile_gemini_tokens_rejects_unrelated_mismatch():
    gtoks = [("komplett anders", "x", "y")]
    assert _reconcile_gemini_tokens(gtoks, "大きい山です。") is None


def test_reconcile_gemini_tokens_works_with_five_tuples_for_ai_mode():
    # KI-Modus nutzt 5er-Tupel (surface, lemma, reading, function, meaning) –
    # dieselbe Funktion muss für beide Tupel-Breiten funktionieren.
    gtoks = [("大きい", "大きい", "おおきい", "Adjektiv", "groß")]
    result = _reconcile_gemini_tokens(gtoks, "大きい。")
    assert result == [("大きい", "大きい", "おおきい", "Adjektiv", "groß"), ("。", "。", "", "", "")]


def test_annotate_text_ai_marks_wanikani_and_dictionary_and_ai_sources(monkeypatch):
    tokens = [
        _ai_tok("しあい", reading="しあい", function="Subjekt", meaning="Spiel"),
        _ai_tok("が", function="Partikel (Subjektmarker)"),  # keine Bedeutung -> reiner Text, keine Karte
        _ai_tok("急に", reading="きゅうに", function="Adverb", meaning="plötzlich"),  # kein WK-/JMdict-Treffer -> "ai"
        _ai_tok("大きい", reading="おおきい", function="Adjektiv", meaning="groß"),  # hat einen WK-Sample-Treffer
        _ai_tok("。", function="Satzzeichen"),
    ]
    monkeypatch.setattr(gemini_client, "analyze_sentences", _fake_gemini(tokens))
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "Spiel; Wettkampf"}})

    rows = annotate_text_ai("しあいが急に大きい。", gemini_key="dummy", sample=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["error"] is None
    assert row["translation"] == "Übersetzung"
    assert row["grammar_notes"] == "Notiz"
    assert "".join(
        s["text"] for s in row["segments"]
    ) == "しあいが急に大きい。"

    dict_word = next(s for s in row["segments"] if s.get("source") == "dictionary")
    assert dict_word["text"] == "しあい"

    ai_words = {s["text"]: s for s in row["segments"] if s.get("source") == "ai"}
    assert ai_words["急に"]["meaning"] == "plötzlich"
    assert ai_words["急に"]["reading"] == "きゅうに"
    assert ai_words["急に"]["id"] == ai_kana_card_id("急に")
    assert "が" not in ai_words  # Partikel ohne Bedeutung wird nicht zum "ai"-Wort
    assert "。" not in ai_words  # reines Satzzeichen ohne Bedeutung wird nicht zum "ai"-Wort

    wk_word = next(s for s in row["segments"] if s.get("source") == "wanikani")
    assert wk_word["text"] == "大きい"


def test_annotate_text_ai_particle_is_not_looked_up_even_with_dictionary_homograph(monkeypatch):
    # Regressionstest für einen realen Bug: die Themen-Partikel "は" (gesprochen
    # "wa") hat im JMdict-Wörterbuch zufällig auch einen Eintrag als eigen-
    # ständiges Wort ("Flügel", von 羽) - eine reine Lesungs-Suche würde die
    # Partikel fälschlich als dieses völlig unpassende Wort anzeigen. Gemini
    # kennt die tatsächliche Funktion im Satz (is_content_word=False) und
    # das darf nicht überschrieben werden, auch wenn das Wörterbuch einen
    # (falschen) Treffer für dieselbe Lesung hat.
    tokens = [
        _ai_tok("ぼく", reading="ぼく", function="Subjekt", meaning="ich"),
        _ai_tok("は", function="Themen-Partikel", is_content_word=False),
        _ai_tok("学生", reading="がくせい", function="Prädikat", meaning="Schüler"),
        _ai_tok("だ", function="Kopula", is_content_word=False),
        _ai_tok("。", function="Satzzeichen", is_content_word=False),
    ]
    monkeypatch.setattr(gemini_client, "analyze_sentences", _fake_gemini(tokens))
    monkeypatch.setattr(
        dic, "_index_cache",
        {"は": {"kanji": "羽", "meaning": "Flügel"}, "ぼく": {"kanji": "僕", "meaning": "ich"}},
    )

    rows = annotate_text_ai("ぼくは学生だ。", gemini_key="dummy", sample=True)
    row = rows[0]
    assert row["error"] is None
    assert "".join(s["text"] for s in row["segments"]) == "ぼくは学生だ。"

    # "は" darf NICHT als Dictionary-Wort "Flügel" auftauchen - weder als
    # eigenes Segment noch versteckt in einem anderen Wort.
    assert not any(s.get("text") == "は" and s.get("type") == "word" for s in row["segments"])
    assert not any(s.get("meaning") == "Flügel" for s in row["segments"])
    # "ぼく" (davor) darf trotzdem ganz normal als Dictionary-Wort erkannt werden.
    boku = next(s for s in row["segments"] if s.get("text") == "ぼく")
    assert boku["source"] == "dictionary"
    assert boku["meaning"] == "ich"


def test_annotate_text_ai_marks_sentence_as_error_when_gemini_returns_none(monkeypatch):
    monkeypatch.setattr(gemini_client, "analyze_sentences", lambda sentences, *a, **k: dict.fromkeys(sentences))
    rows = annotate_text_ai("大きい山です。", gemini_key="dummy", sample=True)
    assert rows[0]["error"]
    assert rows[0]["segments"] == []


def test_annotate_text_ai_marks_sentence_as_error_when_reconstruction_mismatches(monkeypatch):
    tokens = [_ai_tok("komplett anders", "x", function="y")]
    monkeypatch.setattr(gemini_client, "analyze_sentences", _fake_gemini(tokens))
    rows = annotate_text_ai("大きい山です。", gemini_key="dummy", sample=True)
    assert rows[0]["error"]
    assert rows[0]["segments"] == []


def test_annotate_text_ai_calls_gemini_once_with_all_unique_sentences(monkeypatch):
    # Zwei unterschiedliche Sätze, der erste kommt zweimal vor (Zeilenumbruch
    # dazwischen) -> EIN Batch-Aufruf mit beiden eindeutigen Sätzen, nicht
    # drei Einzel-Aufrufe (das war der eigentliche Rate-Limit-Bug).
    calls = []

    def fake_analyze_sentences(sentences, api_key, *, model="gemini-flash-latest", session=None, use_cache=True, **kwargs):
        calls.append(list(sentences))
        return dict.fromkeys(sentences)

    monkeypatch.setattr(gemini_client, "analyze_sentences", fake_analyze_sentences)
    text = "大きい山です。\n大きい山です。\n小さい人です。"
    rows = annotate_text_ai(text, gemini_key="dummy", sample=True)
    assert len(calls) == 1
    assert sorted(calls[0]) == ["大きい山です。", "小さい人です。"]
    assert len(rows) == 3  # ein Eintrag pro Satzvorkommen, auch für den doppelten


def test_annotate_text_has_no_gemini_parameter():
    # "Aus Text" bleibt reine Janome+WaniKani-Analyse, ganz ohne Gemini-Anbindung.
    with pytest.raises(TypeError):
        annotate_text("大きい山です。", sample=True, gemini_key="dummy")


# --------------------------------------------------------------------------- #
# Text-Modus: eigener Beispielsatz überschreibt WaniKanis erste context_sentence
# --------------------------------------------------------------------------- #

def test_build_vocab_card_sentence_override_prepends_own_sentence():
    vocab = {
        "id": 99,
        "data": {
            "characters": "犬",
            "meanings": [{"meaning": "Dog", "primary": True}],
            "readings": [{"reading": "いぬ", "primary": True}],
            "context_sentences": [{"ja": "犬がいます。", "en": "There is a dog."}],
        },
    }
    card = build_vocab_card(vocab, sentence_override={"ja": "私の犬は大きい。", "en": None})
    assert card.sentence_ja == "私の犬は大きい。"
    assert card.sentence_en is None
    assert card.sentence_audio_url is None
    # WaniKanis eigener Satz rutscht komplett nach extra_sentences (nicht verloren).
    assert card.extra_sentences == [
        {"ja": "犬がいます。", "en": "There is a dog.", "audio_url": None}
    ]


def test_build_vocab_card_without_override_keeps_default_behavior():
    vocab = {
        "id": 99,
        "data": {
            "characters": "犬",
            "meanings": [{"meaning": "Dog", "primary": True}],
            "readings": [{"reading": "いぬ", "primary": True}],
            "context_sentences": [{"ja": "犬がいます。", "en": "There is a dog."}],
        },
    }
    card = build_vocab_card(vocab)
    assert card.sentence_ja == "犬がいます。"
    assert card.extra_sentences == []


def test_build_card_sentence_override_applies_to_embedded_vocab():
    kanji = {
        "id": 1,
        "data": {
            "characters": "犬",
            "meanings": [{"meaning": "Dog", "primary": True}],
            "readings": [{"reading": "けん", "primary": True, "type": "onyomi"}],
            "amalgamation_subject_ids": [77],
        },
    }
    vmap = {
        77: {
            "id": 77,
            "data": {
                "characters": "犬",
                "level": 1,
                "meanings": [{"meaning": "Dog", "primary": True}],
                "readings": [{"reading": "いぬ", "primary": True}],
                "context_sentences": [{"ja": "犬がいます。", "en": "There is a dog."}],
            },
        }
    }
    overrides = {77: {"ja": "私の犬は大きい。", "en": None}}
    card = build_card(kanji, vmap, sentence_overrides=overrides)
    assert card.sentence_ja == "私の犬は大きい。"
    assert card.sentence_en is None
    assert card.extra_sentences == [
        {"ja": "犬がいます。", "en": "There is a dog.", "audio_url": None}
    ]


def test_build_card_sentence_overrides_ignores_unrelated_ids():
    kanji = {
        "id": 1,
        "data": {
            "characters": "犬",
            "meanings": [{"meaning": "Dog", "primary": True}],
            "readings": [{"reading": "けん", "primary": True, "type": "onyomi"}],
            "amalgamation_subject_ids": [77],
        },
    }
    vmap = {
        77: {
            "id": 77,
            "data": {
                "characters": "犬",
                "level": 1,
                "meanings": [{"meaning": "Dog", "primary": True}],
                "readings": [{"reading": "いぬ", "primary": True}],
                "context_sentences": [{"ja": "犬がいます。", "en": "There is a dog."}],
            },
        }
    }
    card = build_card(kanji, vmap, sentence_overrides={999: {"ja": "unrelated", "en": None}})
    assert card.sentence_ja == "犬がいます。"


def _word_segments(text: str) -> list[dict]:
    lines = annotate_text(text, sample=True)
    return [s for line in lines for s in line if s["type"] == "word"]


def test_resolve_subject_deck_threads_sentence_overrides():
    from kanji_cards import resolve_subject_deck

    text = "大きい山に人が一人います。"
    words = _word_segments(text)
    ids = [w["id"] for w in words]
    overrides = {
        w["id"]: {"ja": w["sentence"], "en": None} for w in words if w["kind"] == "Vocab"
    }
    deck = resolve_subject_deck(ids, sample=True, sentence_overrides=overrides)
    vocab_cards = {c.subject_id: c for c in deck if isinstance(c, VocabCard)}
    for sid, override in overrides.items():
        assert vocab_cards[sid].sentence_ja == override["ja"]


def test_resolve_subject_deck_normalizes_string_keyed_overrides():
    """Overrides kommen über JSON (Web-API) mit String-Keys an – muss trotzdem greifen."""
    from kanji_cards import resolve_subject_deck

    text = "大きい山に人が一人います。"
    words = _word_segments(text)
    ids = [w["id"] for w in words]
    overrides = {
        w["id"]: {"ja": w["sentence"], "en": None} for w in words if w["kind"] == "Vocab"
    }
    string_keyed = {str(k): v for k, v in overrides.items()}
    deck = resolve_subject_deck(ids, sample=True, sentence_overrides=string_keyed)
    vocab_cards = {c.subject_id: c for c in deck if isinstance(c, VocabCard)}
    for sid, override in overrides.items():
        assert vocab_cards[sid].sentence_ja == override["ja"]


def test_resolve_subject_deck_applies_field_overrides():
    """Manuell im Web-Frontend geänderte Felder (Felder-anpassen-Dialog)
    überschreiben gezielt einzelne Karten-Felder nach dem Bau."""
    from kanji_cards import resolve_subject_deck

    raw = _load_sample_raw()
    kanji_id = int(raw["kanji"][0]["id"])
    deck = resolve_subject_deck(
        [kanji_id], sample=True,
        field_overrides={kanji_id: {"meanings": ["Meine eigene Bedeutung"]}},
    )
    card = next(c for c in deck if getattr(c, "subject_id", None) == kanji_id)
    assert card.meanings == ["Meine eigene Bedeutung"]


def test_resolve_subject_deck_field_overrides_ignore_unknown_keys():
    from kanji_cards import resolve_subject_deck

    raw = _load_sample_raw()
    kanji_id = int(raw["kanji"][0]["id"])
    # "not_a_real_field" existiert auf keiner Dataclass - darf nicht crashen.
    deck = resolve_subject_deck(
        [kanji_id], sample=True,
        field_overrides={str(kanji_id): {"not_a_real_field": "x", "vocab_meaning": "Neu"}},
    )
    card = next(c for c in deck if getattr(c, "subject_id", None) == kanji_id)
    assert card.vocab_meaning == "Neu"
    assert not hasattr(card, "not_a_real_field")


def test_card_details_for_ids_returns_all_fields_with_kind():
    from kanji_cards import card_details_for_ids

    raw = _load_sample_raw()
    kanji_id = int(raw["kanji"][0]["id"])
    radical_id = int(raw["radicals"][0]["id"])
    details = card_details_for_ids([kanji_id, radical_id], sample=True)
    assert details[kanji_id]["kind"] == "Card"
    assert "meanings" in details[kanji_id] and "onyomi" in details[kanji_id]
    assert details[radical_id]["kind"] == "RadicalCard"
    assert "meaning" in details[radical_id]


def test_card_details_for_ids_skips_unknown_ids():
    from kanji_cards import card_details_for_ids

    details = card_details_for_ids([999999999], sample=True)
    assert details == {}


# --------------------------------------------------------------------------- #
# KanaCard: Dictionary-Karten für Wörter ohne WaniKani-Treffer (Text-Modus)
# --------------------------------------------------------------------------- #

def test_kana_card_id_is_stable_and_deterministic():
    assert kana_card_id("しあい") == kana_card_id("しあい")
    assert kana_card_id("しあい") != kana_card_id("べつのことば")
    assert kana_card_id("しあい").startswith("kana_")


def test_build_kana_card_looks_up_jmdict(monkeypatch):
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})
    card = build_kana_card("しあい", sentence="しあいがはじまりました。")
    assert isinstance(card, KanaCard)
    assert card.word == "しあい"
    assert card.kanji_hint == "試合"
    assert card.meaning == "match; game"
    assert card.sentence_ja == "しあいがはじまりました。"
    assert card.sentence_translation is None
    assert card.tags == ["Dictionary"]
    assert card.card_id == kana_card_id("しあい")


def test_build_kana_card_returns_none_when_not_in_dictionary(monkeypatch):
    monkeypatch.setattr(dic, "_index_cache", {})
    assert build_kana_card("ぜんぜんちがう") is None


def test_build_kana_card_translates_sentence_when_deepl_key_given(monkeypatch):
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})
    calls = []

    def fake_translate(text, key, **kwargs):
        calls.append((text, key))
        return "Das Spiel hat begonnen."

    card = build_kana_card(
        "しあい", sentence="しあいがはじまりました。", deepl_key="dummy:fx", translate_fn=fake_translate
    )
    assert card.sentence_translation == "Das Spiel hat begonnen."
    assert calls == [("しあいがはじまりました。", "dummy:fx")]


def test_build_kana_card_skips_translation_without_deepl_key(monkeypatch):
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})
    card = build_kana_card("しあい", sentence="しあいがはじまりました。")
    assert card.sentence_translation is None


# --------------------------------------------------------------------------- #
# build_generic_dictionary_card() – Gemini-Fallback für Nicht-Japanisch
# --------------------------------------------------------------------------- #

def test_build_generic_dictionary_card_uses_gemini_lookup(monkeypatch):
    def fake_lookup_word(word, api_key, *, model=None, session=None, use_cache=True, target_lang_name="", native_lang_name="", has_reading=False):
        assert word == "casa"
        assert target_lang_name == "Spanisch"
        return {"meaning": "house", "reading": None}

    monkeypatch.setattr(gemini_client, "lookup_word", fake_lookup_word)
    card = build_generic_dictionary_card(
        "casa", "La casa es grande.", gemini_key="dummy", target_lang_name="Spanisch", native_lang_name="Deutsch",
    )
    assert isinstance(card, KanaCard)
    assert card.word == "casa"
    assert card.meaning == "house"
    assert card.source == "ai"
    assert card.sentence_ja == "La casa es grande."


def test_build_generic_dictionary_card_returns_none_when_gemini_finds_nothing(monkeypatch):
    monkeypatch.setattr(gemini_client, "lookup_word", lambda *a, **k: None)
    assert build_generic_dictionary_card("qwxyz", gemini_key="dummy") is None


def test_build_kana_card_from_dict_roundtrip():
    d = {
        "id": "kana_abc123",
        "word": "しあい",
        "kanji_hint": "試合",
        "meaning": "match; game",
        "sentence_ja": "しあいがはじまりました。",
        "sentence_translation": "Das Spiel hat begonnen.",
        "tags": ["Dictionary"],
    }
    card = build_kana_card_from_dict(d)
    assert card == KanaCard(
        word="しあい",
        kanji_hint="試合",
        meaning="match; game",
        sentence_ja="しあいがはじまりました。",
        sentence_translation="Das Spiel hat begonnen.",
        tags=["Dictionary"],
        card_id="kana_abc123",
    )


def test_build_ai_kana_card_uses_gemini_meaning_directly():
    card = build_ai_kana_card("入る", meaning="hineingehen", reading="はいる", sentence="高校に入りました。")
    assert isinstance(card, KanaCard)
    assert card.word == "入る"
    assert card.reading == "はいる"
    assert card.meaning == "hineingehen"
    assert card.source == "ai"
    assert card.tags == ["KI"]
    assert card.card_id == ai_kana_card_id("入る")


def test_build_ai_kana_card_carries_sentence_audio_url():
    card = build_ai_kana_card(
        "入る", meaning="hineingehen", sentence="高校に入りました。",
        sentence_audio_url="data:audio/wav;base64,AAAA",
    )
    assert card.sentence_audio_url == "data:audio/wav;base64,AAAA"


def test_build_ai_kana_card_id_differs_from_dictionary_kana_card_id():
    # Eigener ID-Namensraum, damit eine spätere echte Dictionary-Karte für
    # dasselbe Wort nicht mit der KI-Karte kollidiert.
    assert ai_kana_card_id("入る") != kana_card_id("入る")


def test_build_kana_card_from_dict_roundtrip_with_ai_source_and_reading():
    d = {
        "id": "aikana_abc123",
        "word": "入る",
        "reading": "はいる",
        "meaning": "hineingehen",
        "source": "ai",
        "tags": ["KI"],
    }
    card = build_kana_card_from_dict(d)
    assert card == KanaCard(
        word="入る",
        reading="はいる",
        meaning="hineingehen",
        source="ai",
        tags=["KI"],
        card_id="aikana_abc123",
    )


def test_build_kana_card_from_dict_roundtrip_with_sentence_audio_url():
    d = {
        "id": "aikana_abc123",
        "word": "入る",
        "meaning": "hineingehen",
        "source": "ai",
        "sentence_audio_url": "data:audio/wav;base64,AAAA",
    }
    card = build_kana_card_from_dict(d)
    assert card.sentence_audio_url == "data:audio/wav;base64,AAAA"


def test_card_to_dict_serializes_kana_card():
    from kanji_cards import _card_to_dict

    card = KanaCard(
        word="しあい", kanji_hint="試合", meaning="match", sentence_ja="文。",
        sentence_translation="Übersetzung.", tags=["Dictionary"], card_id="kana_x",
    )
    d = _card_to_dict(card)
    assert d["type"] == "kana"
    assert d["word"] == "しあい"
    assert d["kanji_hint"] == "試合"
    assert d["sentence_translation"] == "Übersetzung."


def test_card_to_dict_serializes_vocab_image_fields():
    from kanji_cards import _card_to_dict

    card = VocabCard(
        vocab="家", readings=["いえ"], meanings=["Haus"],
        image_data_uri="data:image/png;base64,AAAA", show_meaning_on_front=True,
    )
    d = _card_to_dict(card)
    assert d["type"] == "vocab"
    assert d["image_data_uri"] == "data:image/png;base64,AAAA"
    assert d["show_meaning_on_front"] is True


def test_card_to_dict_vocab_image_fields_default_none_and_false():
    from kanji_cards import _card_to_dict

    card = VocabCard(vocab="家", readings=["いえ"], meanings=["Haus"])
    d = _card_to_dict(card)
    assert d["image_data_uri"] is None
    assert d["show_meaning_on_front"] is False


# --------------------------------------------------------------------------- #
# _make_client: expliziter Token statt prozessglobaler WANIKANI_API_TOKEN-Var
# (Multi-User-Umbau Phase 3 - siehe README "Multi-User-Architektur")
# --------------------------------------------------------------------------- #

def test_make_client_uses_explicit_token_over_env_var(monkeypatch):
    from kanji_cards import _make_client

    monkeypatch.setenv("WANIKANI_API_TOKEN", "env-token")
    client = _make_client(token="explicit-token")
    assert client.token == "explicit-token"


def test_make_client_falls_back_to_env_var_without_explicit_token(monkeypatch):
    from kanji_cards import _make_client

    monkeypatch.setenv("WANIKANI_API_TOKEN", "env-token")
    client = _make_client()
    assert client.token == "env-token"


def test_make_client_raises_without_token_or_env_var(monkeypatch):
    from kanji_cards import _make_client

    monkeypatch.delenv("WANIKANI_API_TOKEN", raising=False)
    with pytest.raises(WaniKaniError):
        _make_client()


def test_make_client_two_explicit_tokens_do_not_interfere(monkeypatch):
    """Kernfrage des Fixes: zwei "gleichzeitige" Aufrufe mit unterschiedlichen
    Tokens dürfen sich nicht über eine gemeinsame Umgebungsvariable
    beeinflussen - jeder Client behält seinen eigenen Token."""
    from kanji_cards import _make_client

    monkeypatch.delenv("WANIKANI_API_TOKEN", raising=False)
    client_a = _make_client(token="token-a")
    client_b = _make_client(token="token-b")
    assert client_a.token == "token-a"
    assert client_b.token == "token-b"
