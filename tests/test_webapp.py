"""Tests für webapp.py-Hilfsfunktionen (keine Netzwerk-/Flask-Server-Abhängigkeit)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webapp  # noqa: E402


def _job(job_id: str, status: str, subject_ids: list[int]) -> dict:
    return {
        "id": job_id,
        "status": status,
        "params": {"subject_ids": subject_ids},
        "created_at": "2024-01-01T00:00:00+00:00",
    }


def test_already_exported_ids_only_counts_done_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path)
    webapp.write_job(_job("a", "done", [1, 2, 3]))
    webapp.write_job(_job("b", "error", [4, 5]))
    webapp.write_job(_job("c", "queued", [6]))

    assert webapp._already_exported_ids() == {1, 2, 3}


def test_already_exported_ids_ignores_custom_only_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path)
    job = _job("a", "done", [])
    job["params"]["custom_ids"] = ["free1"]
    webapp.write_job(job)

    assert webapp._already_exported_ids() == set()


def test_mark_exported_flags_matching_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path)
    webapp.write_job(_job("a", "done", [1, 2]))

    cards = [{"id": 1}, {"id": 2}, {"id": 3}]
    marked = webapp._mark_exported(cards)

    assert [c["already_exported"] for c in marked] == [True, True, False]


def test_mark_exported_empty_history_leaves_everything_unmarked(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path)
    cards = [{"id": 1}, {"id": 2}]
    marked = webapp._mark_exported(cards)
    assert [c["already_exported"] for c in marked] == [False, False]


# --------------------------------------------------------------------------- #
# Manuell als "bekannt" markierte Wörter (data/known.json)
# --------------------------------------------------------------------------- #

def test_load_known_defaults_to_empty_set(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    assert webapp.load_known() == set()


def test_save_and_load_known_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    webapp.save_known({3, 1, 2})
    assert webapp.load_known() == {1, 2, 3}


def test_load_known_ignores_corrupt_file(tmp_path, monkeypatch):
    known_file = tmp_path / "known.json"
    known_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(webapp, "KNOWN_FILE", known_file)
    assert webapp.load_known() == set()


def test_known_ids_support_mixed_int_and_string(tmp_path, monkeypatch):
    """WaniKani-Subject-IDs (int) und Dictionary-Wörter (kana_… str) landen
    in derselben Datei – beide bedeuten „bekannt"."""
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    webapp.save_known({42, "kana_abc123"})
    assert webapp.load_known() == {42, "kana_abc123"}


def test_coerce_known_id_digit_string_becomes_int():
    assert webapp._coerce_known_id("42") == 42
    assert isinstance(webapp._coerce_known_id("42"), int)


def test_coerce_known_id_kana_id_stays_string():
    assert webapp._coerce_known_id("kana_abc123") == "kana_abc123"
    assert isinstance(webapp._coerce_known_id("kana_abc123"), str)


# --------------------------------------------------------------------------- #
# Flask-Endpunkte: /api/known, /api/text-annotate (Sample-Modus, keine Netzwerk-
# Abhängigkeit)
# --------------------------------------------------------------------------- #

def test_api_mark_and_unmark_known(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KNOWN_META_FILE", tmp_path / "known_meta.json")
    client = webapp.app.test_client()

    r = client.post("/api/known/42")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "id": 42, "known": True}
    assert webapp.load_known() == {42}

    r = client.delete("/api/known/42")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "id": 42, "known": False}
    assert webapp.load_known() == set()


def test_api_mark_known_persists_metadata_for_wortliste(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KNOWN_META_FILE", tmp_path / "known_meta.json")
    client = webapp.app.test_client()

    r = client.post(
        "/api/known/kana_abc123",
        json={"characters": "しあい", "meaning": "match; game", "kind": "Dict", "source": "dictionary"},
    )
    assert r.status_code == 200
    meta = webapp.load_known_meta()
    assert meta["kana_abc123"]["characters"] == "しあい"
    assert meta["kana_abc123"]["meaning"] == "match; game"

    client.delete("/api/known/kana_abc123")
    assert webapp.load_known_meta() == {}


def test_api_text_annotate_returns_lines_and_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    (tmp_path / "jobs").mkdir()
    client = webapp.app.test_client()

    r = client.post(
        "/api/text-annotate",
        json={"text": "大きい山に人が一人います。", "sample": True},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert "lines" in data and "stats" in data
    words = [s for line in data["lines"] for s in line if s["type"] == "word"]
    assert words
    assert all(w["known"] is False for w in words)  # nichts exportiert/markiert
    assert data["stats"]["total"] == len(words)
    assert data["stats"]["known"] == 0
    assert data["stats"]["percent"] == 0.0


def test_api_text_annotate_marks_manually_known_words(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    (tmp_path / "jobs").mkdir()
    client = webapp.app.test_client()

    first = client.post(
        "/api/text-annotate", json={"text": "大きい", "sample": True}
    ).get_json()
    word = next(s for line in first["lines"] for s in line if s["type"] == "word")
    client.post(f"/api/known/{word['id']}")

    second = client.post(
        "/api/text-annotate", json={"text": "大きい", "sample": True}
    ).get_json()
    word2 = next(s for line in second["lines"] for s in line if s["type"] == "word")
    assert word2["status"] == "known"
    assert word2["known"] is True
    assert word2["manually_known"] is True
    assert second["stats"]["percent"] == 100.0


def test_api_text_annotate_classifies_dictionary_words(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "kanacards").mkdir()
    import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})

    client = webapp.app.test_client()
    r = client.post("/api/text-annotate", json={"text": "しあいがはじまりました。", "sample": True})
    assert r.status_code == 200
    data = r.get_json()
    words = [s for line in data["lines"] for s in line if s["type"] == "word"]
    assert len(words) == 1
    assert words[0]["status"] == "unknown"
    assert words[0]["known"] is False
    assert words[0]["manually_known"] is False
    assert words[0]["ready"] is False


def test_api_text_annotate_ready_true_when_dictionary_card_already_created(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "kanacards").mkdir()
    import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})

    client = webapp.app.test_client()
    first = client.post("/api/text-annotate", json={"text": "しあいがはじまりました。", "sample": True}).get_json()
    word = next(s for line in first["lines"] for s in line if s["type"] == "word")
    client.post("/api/kanacards", json={"word": "しあい"})

    second = client.post("/api/text-annotate", json={"text": "しあいがはじまりました。", "sample": True}).get_json()
    word2 = next(s for line in second["lines"] for s in line if s["type"] == "word")
    assert word2["id"] == word["id"]
    assert word2["ready"] is True
    assert word2["manually_known"] is False
    assert word2["status"] == "known"
    assert word2["known"] is True


def test_api_text_annotate_use_gemini_without_key_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "jobs").mkdir()
    client = webapp.app.test_client()

    r = client.post("/api/text-annotate", json={"text": "大きい山です。", "sample": True, "use_gemini": True})
    assert r.status_code == 400
    assert "Gemini" in r.get_json()["error"]


def test_api_text_annotate_use_gemini_passes_settings_key_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "jobs").mkdir()
    client = webapp.app.test_client()
    client.post("/api/settings", json={"gemini_key": "mykey", "gemini_model": "gemini-2.5-pro"})

    seen = {}

    def fake_annotate_text(text, *, use_cache=True, sample=False, gemini_key=None, gemini_model=None):
        seen["gemini_key"] = gemini_key
        seen["gemini_model"] = gemini_model
        return [[]]

    import kanji_cards as kc
    monkeypatch.setattr(kc, "annotate_text", fake_annotate_text)

    r = client.post("/api/text-annotate", json={"text": "x", "sample": True, "use_gemini": True})
    assert r.status_code == 200
    assert seen["gemini_key"] == "mykey"
    assert seen["gemini_model"] == "gemini-2.5-pro"


def test_api_text_annotate_gemini_grammar_only_word_excluded_from_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "jobs").mkdir()
    client = webapp.app.test_client()
    client.post("/api/settings", json={"gemini_key": "mykey"})

    def fake_annotate_text(text, *, use_cache=True, sample=False, gemini_key=None, gemini_model=None):
        return [[
            {"type": "word", "source": "gemini", "text": "が", "lemma": "が", "sentence": "x",
             "id": None, "kind": "Grammatik", "meaning": "Partikel", "level": None},
        ]]

    import kanji_cards as kc
    monkeypatch.setattr(kc, "annotate_text", fake_annotate_text)

    r = client.post("/api/text-annotate", json={"text": "x", "sample": True, "use_gemini": True})
    data = r.get_json()
    seg = data["lines"][0][0]
    assert seg["status"] == "info"
    assert seg["known"] is False
    assert data["stats"]["total"] == 0  # zählt nicht mit (keine Vokabel, nur Grammatik-Info)


def test_api_settings_get_set_gemini_key_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    client = webapp.app.test_client()

    r0 = client.get("/api/settings").get_json()
    assert r0["gemini_key_set"] is False
    assert r0["gemini_model"] == "gemini-2.5-flash"

    client.post("/api/settings", json={"gemini_key": "sekret", "gemini_model": "gemini-2.5-pro"})
    r1 = client.get("/api/settings").get_json()
    assert r1["gemini_key_set"] is True
    assert r1["gemini_key_hint"].endswith("kret")
    assert r1["gemini_model"] == "gemini-2.5-pro"


def test_api_settings_post_ignores_unknown_gemini_model(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    client = webapp.app.test_client()
    client.post("/api/settings", json={"gemini_model": "not-a-real-model"})
    r = client.get("/api/settings").get_json()
    assert r["gemini_model"] == "gemini-2.5-flash"  # ungültiger Wert wird ignoriert


# --------------------------------------------------------------------------- #
# Dictionary-Karten (kanacards/) – CRUD über /api/kanacards
# --------------------------------------------------------------------------- #

def test_api_create_kanacard_persists_and_returns_descriptor(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "kanacards").mkdir()
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})

    client = webapp.app.test_client()
    r = client.post("/api/kanacards", json={"word": "しあい", "sentence": "しあいがはじまりました。"})
    assert r.status_code == 200
    desc = r.get_json()
    assert desc["characters"] == "しあい"
    assert desc["meaning"] == "match; game"
    assert desc["kind"] == "Dict"

    stored = webapp.read_kana(desc["id"])
    assert stored["word"] == "しあい"
    assert stored["kanji_hint"] == "試合"
    assert stored["sentence_ja"] == "しあいがはじまりました。"


def test_api_create_kanacard_404_when_not_in_dictionary(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "kanacards").mkdir()
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {})

    client = webapp.app.test_client()
    r = client.post("/api/kanacards", json={"word": "ぜんぜんちがう"})
    assert r.status_code == 404


def test_api_create_kanacard_requires_word(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "kanacards").mkdir()
    client = webapp.app.test_client()
    r = client.post("/api/kanacards", json={})
    assert r.status_code == 400


def test_api_kanacards_list_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "kanacards").mkdir()
    monkeypatch.setattr(webapp, "SETTINGS_FILE", tmp_path / "settings.json")
    import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})

    client = webapp.app.test_client()
    created = client.post("/api/kanacards", json={"word": "しあい"}).get_json()

    listed = client.get("/api/kanacards").get_json()
    assert any(c["id"] == created["id"] for c in listed)

    r = client.delete(f"/api/kanacards/{created['id']}")
    assert r.status_code == 200
    assert webapp.read_kana(created["id"]) is None

    assert client.delete(f"/api/kanacards/{created['id']}").status_code == 404


# --------------------------------------------------------------------------- #
# Wortliste: vereinigte Liste aller bekannten Wörter (WaniKani + Dictionary +
# rein manuelle Einträge), filter-/entfernbar über /api/wortliste
# --------------------------------------------------------------------------- #

def test_api_wortliste_combines_wanikani_dictionary_and_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KNOWN_META_FILE", tmp_path / "known_meta.json")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "kanacards").mkdir()
    client = webapp.app.test_client()

    webapp.write_job(_job("a", "done", [2467]))  # 一 (Sample-Daten) – über Export bekannt
    webapp.write_kana({"id": "kana_x", "word": "しあい", "meaning": "match", "tags": ["Dictionary"], "updated_at": "x"})
    client.post("/api/wortliste", json={"characters": "genki", "meaning": "gesund/munter"})

    r = client.get("/api/wortliste?sample=1")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 3
    assert {e["source"] for e in data["entries"]} == {"wanikani", "dictionary", "manual"}

    wk = next(e for e in data["entries"] if e["source"] == "wanikani")
    assert wk["id"] == 2467
    assert wk["characters"] == "一"
    assert wk["already_exported"] is True
    assert wk["removable"] is False  # nur exportiert, nicht manuell markiert

    dct = next(e for e in data["entries"] if e["source"] == "dictionary")
    assert dct["characters"] == "しあい"
    assert dct["card_created"] is True
    assert dct["removable"] is True  # Dictionary-Karten lassen sich immer löschen (kein Export-Verlauf)

    man = next(e for e in data["entries"] if e["source"] == "manual")
    assert man["characters"] == "genki"
    assert man["meaning"] == "gesund/munter"
    assert man["removable"] is True


def test_api_wortliste_add_manual_then_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KNOWN_META_FILE", tmp_path / "known_meta.json")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "kanacards").mkdir()
    client = webapp.app.test_client()

    entry = client.post("/api/wortliste", json={"characters": "genki", "meaning": "gesund"}).get_json()
    wid = entry["id"]
    assert wid.startswith("manual_")

    listed = client.get("/api/wortliste?sample=1").get_json()
    assert any(e["id"] == wid for e in listed["entries"])

    client.delete(f"/api/known/{wid}")
    listed2 = client.get("/api/wortliste?sample=1").get_json()
    assert not any(e["id"] == wid for e in listed2["entries"])


def test_api_wortliste_add_manual_requires_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KNOWN_META_FILE", tmp_path / "known_meta.json")
    client = webapp.app.test_client()
    r = client.post("/api/wortliste", json={})
    assert r.status_code == 400


def test_api_wortliste_manually_known_wanikani_word_is_removable(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    monkeypatch.setattr(webapp, "KNOWN_META_FILE", tmp_path / "known_meta.json")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "kanacards").mkdir()
    client = webapp.app.test_client()

    client.post(
        "/api/known/2467",
        json={"characters": "一", "meaning": "one", "kind": "Kanji", "level": 1, "source": "wanikani"},
    )
    data = client.get("/api/wortliste?sample=1").get_json()
    wk = next(e for e in data["entries"] if e["source"] == "wanikani")
    assert wk["manually_known"] is True
    assert wk["already_exported"] is False
    assert wk["removable"] is True


# --------------------------------------------------------------------------- #
# _build_mixed_deck: WaniKani + Custom + Dictionary in einem Export kombinieren
# --------------------------------------------------------------------------- #

def test_build_mixed_deck_combines_all_three_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "CUSTOM_DIR", tmp_path / "customcards")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "customcards").mkdir()
    (tmp_path / "kanacards").mkdir()

    webapp.write_custom({"id": "free1", "front_html": "<b>x</b>", "back_html": "y", "tags": []})
    webapp.write_kana({"id": "kana_x", "word": "しあい", "meaning": "match", "tags": ["Dictionary"]})

    deck = webapp._build_mixed_deck(
        {
            "subject_ids": [2467],  # 一 (Sample-Daten)
            "custom_ids": ["free1"],
            "kana_ids": ["kana_x"],
            "sample": True,
        }
    )
    kinds = {type(c).__name__ for c in deck}
    assert kinds == {"VocabCard", "CustomCard", "KanaCard"}
    assert len(deck) == 3


def test_build_mixed_deck_empty_params_returns_empty_deck():
    assert webapp._build_mixed_deck({}) == []


def test_build_mixed_deck_skips_missing_custom_or_kana_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "CUSTOM_DIR", tmp_path / "customcards")
    monkeypatch.setattr(webapp, "KANA_DIR", tmp_path / "kanacards")
    (tmp_path / "customcards").mkdir()
    (tmp_path / "kanacards").mkdir()
    deck = webapp._build_mixed_deck({"custom_ids": ["missing"], "kana_ids": ["missing"]})
    assert deck == []
