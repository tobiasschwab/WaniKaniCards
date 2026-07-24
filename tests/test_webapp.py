"""Tests für webapp.py – Endpunkte laufen jetzt pro Nutzer über die Datenbank
(siehe models.py) statt über dateibasierte JSON-Dateien. `client`/`db_session`/
`logged_in_user`-Fixtures kommen aus conftest.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import UTC

from sqlalchemy.exc import IntegrityError

from shiori import (
    models,  # noqa: E402
    services,  # noqa: E402
    webapp,  # noqa: E402
)
from shiori.extensions import db  # noqa: E402

# --------------------------------------------------------------------------- #
# _already_exported_ids / _mark_exported (current_user-Scoping)
# --------------------------------------------------------------------------- #

def test_already_exported_ids_only_counts_done_jobs(logged_in_user):
    uid = logged_in_user.id
    db.session.add(models.Job(id="a", user_id=uid, status="done", params={"subject_ids": [1, 2, 3]}))
    db.session.add(models.Job(id="b", user_id=uid, status="error", params={"subject_ids": [4, 5]}))
    db.session.add(models.Job(id="c", user_id=uid, status="queued", params={"subject_ids": [6]}))
    db.session.commit()

    assert webapp._already_exported_ids() == {1, 2, 3}


def test_already_exported_ids_ignores_custom_only_jobs(logged_in_user):
    db.session.add(models.Job(
        id="a", user_id=logged_in_user.id, status="done",
        params={"subject_ids": [], "custom_ids": ["free1"]},
    ))
    db.session.commit()
    assert webapp._already_exported_ids() == set()


def test_already_exported_ids_scoped_to_current_user(logged_in_user, db_session):
    other = models.User(email="other@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    db.session.add(models.Job(id="mine", user_id=logged_in_user.id, status="done", params={"subject_ids": [1]}))
    db.session.add(models.Job(id="theirs", user_id=other.id, status="done", params={"subject_ids": [2]}))
    db.session.commit()

    assert webapp._already_exported_ids() == {1}


def test_mark_exported_flags_matching_cards(logged_in_user):
    db.session.add(models.Job(id="a", user_id=logged_in_user.id, status="done", params={"subject_ids": [1, 2]}))
    db.session.commit()

    cards = [{"id": 1}, {"id": 2}, {"id": 3}]
    marked = webapp._mark_exported(cards)

    assert [c["already_exported"] for c in marked] == [True, True, False]


def test_mark_exported_empty_history_leaves_everything_unmarked(logged_in_user):
    cards = [{"id": 1}, {"id": 2}]
    marked = webapp._mark_exported(cards)
    assert [c["already_exported"] for c in marked] == [False, False]


# --------------------------------------------------------------------------- #
# Manuell als "bekannt" markierte Wörter (KnownWord, pro Nutzer)
# --------------------------------------------------------------------------- #

def test_load_known_defaults_to_empty_set(logged_in_user):
    assert webapp.load_known() == set()


def test_upsert_and_load_known_roundtrip(logged_in_user):
    webapp._upsert_known_word("3", {})
    webapp._upsert_known_word("1", {})
    webapp._upsert_known_word("2", {})
    assert webapp.load_known() == {1, 2, 3}


def test_known_ids_support_mixed_int_and_string(logged_in_user):
    """WaniKani-Subject-IDs (int) und Dictionary-Wörter (kana_… str) landen in
    derselben Tabelle – beide bedeuten „bekannt"."""
    webapp._upsert_known_word("42", {})
    webapp._upsert_known_word("kana_abc123", {})
    assert webapp.load_known() == {42, "kana_abc123"}


def test_known_words_scoped_to_current_user(logged_in_user, db_session):
    other = models.User(email="other2@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    db.session.add(models.KnownWord(user_id=other.id, word_id="99"))
    db.session.commit()

    assert webapp.load_known() == set()  # gehört einem anderen Nutzer


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

def test_api_endpoints_require_login(client):
    """Stichprobe: ohne Session liefern die zentralen Endpunkte 401 statt
    Daten preiszugeben (siehe login_manager.unauthorized_handler)."""
    anon = webapp.app.test_client()
    for method, path in [
        ("get", "/api/config"), ("get", "/api/settings"), ("post", "/api/resolve"),
        ("get", "/api/wortliste"), ("get", "/api/customcards"), ("get", "/api/kanacards"),
        ("get", "/api/jobs"),
    ]:
        r = getattr(anon, method)(path)
        assert r.status_code == 401, f"{method.upper()} {path} sollte 401 liefern"


def test_api_mark_and_unmark_known(client):
    r = client.post("/api/known/42")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "id": 42, "known": True}
    assert models.KnownWord.query.filter_by(user_id=client.test_user_id, word_id="42").count() == 1

    r = client.delete("/api/known/42")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "id": 42, "known": False}
    assert models.KnownWord.query.filter_by(user_id=client.test_user_id, word_id="42").count() == 0


def test_api_mark_known_persists_metadata_for_wortliste(client):
    r = client.post(
        "/api/known/kana_abc123",
        json={"characters": "しあい", "meaning": "match; game", "kind": "Dict", "source": "dictionary"},
    )
    assert r.status_code == 200
    row = models.KnownWord.query.filter_by(user_id=client.test_user_id, word_id="kana_abc123").first()
    assert row.characters == "しあい"
    assert row.meaning == "match; game"

    client.delete("/api/known/kana_abc123")
    assert models.KnownWord.query.filter_by(user_id=client.test_user_id, word_id="kana_abc123").first() is None


def test_api_known_words_isolated_between_users(client, db_session):
    client.post("/api/known/42")

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "other3@example.com", "password": "supersecret123"})
    r = other.get("/api/wortliste?sample=1")
    assert not any(e["id"] == 42 for e in r.get_json()["entries"])


def test_api_text_annotate_returns_lines_and_stats(client):
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


def test_api_text_annotate_marks_manually_known_words(client):
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


def test_api_text_annotate_classifies_dictionary_words(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})

    r = client.post("/api/text-annotate", json={"text": "しあいがはじまりました。", "sample": True})
    assert r.status_code == 200
    data = r.get_json()
    words = [s for line in data["lines"] for s in line if s["type"] == "word"]
    assert len(words) == 1
    assert words[0]["status"] == "unknown"
    assert words[0]["known"] is False
    assert words[0]["manually_known"] is False
    assert words[0]["ready"] is False


def test_api_text_annotate_ready_true_when_dictionary_card_already_created(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})

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


def test_api_text_annotate_shows_card_exists_for_srs_added_but_unreviewed_word(client):
    """Regressionstest für Nutzer-Feedback: eine Karte, die zum Vokabeltrainer
    hinzugefügt, aber noch nie bewertet wurde, soll weder als "unbekannt" noch
    fälschlich schon als "bekannt" gelten - dafür der dritte Status
    "card_exists" ("Karte vorhanden")."""
    first = client.post("/api/text-annotate", json={"text": "大きい", "sample": True}).get_json()
    word = next(s for line in first["lines"] for s in line if s["type"] == "word")

    client.post("/api/srs/add", json={"subject_ids": [word["id"]], "sample": True})

    second = client.post("/api/text-annotate", json={"text": "大きい", "sample": True}).get_json()
    word2 = next(s for line in second["lines"] for s in line if s["type"] == "word")
    assert word2["status"] == "card_exists"
    assert word2["card_exists"] is True
    assert word2["known"] is False  # zählt NICHT als bekannt, solange nie bewertet


def test_api_text_annotate_promotes_to_known_after_first_rating(client):
    """Sobald mindestens eine Prüfrichtung der Karte einmal bewertet wurde,
    gilt sie automatisch als bekannt (ohne manuelles Markieren)."""
    first = client.post("/api/text-annotate", json={"text": "大きい", "sample": True}).get_json()
    word = next(s for line in first["lines"] for s in line if s["type"] == "word")
    client.post("/api/srs/add", json={"subject_ids": [word["id"]], "sample": True})

    row = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id=str(word["id"])).first()
    client.post("/api/srs/answer", json={
        "card_type": "wanikani", "card_id": str(word["id"]), "item_type": row.item_type, "rating": "good",
    })

    second = client.post("/api/text-annotate", json={"text": "大きい", "sample": True}).get_json()
    word2 = next(s for line in second["lines"] for s in line if s["type"] == "word")
    assert word2["status"] == "known"
    assert word2["known"] is True
    assert word2["card_exists"] is False


def test_api_text_annotate_ai_without_key_returns_error(client):
    r = client.post("/api/text-annotate-ai", json={"text": "大きい山です。", "sample": True})
    assert r.status_code == 400
    assert "Gemini" in r.get_json()["error"]


def test_api_text_annotate_ai_passes_settings_key_and_model(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "mykey", "gemini_model": "gemini-pro-latest"})

    seen = {}

    def fake_annotate_text_ai(text, *, gemini_key=None, gemini_model=None, use_cache=True, sample=False, token=None, **kwargs):
        seen["gemini_key"] = gemini_key
        seen["gemini_model"] = gemini_model
        return []

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc, "annotate_text_ai", fake_annotate_text_ai)

    r = client.post("/api/text-annotate-ai", json={"text": "x", "sample": True})
    assert r.status_code == 200
    assert seen["gemini_key"] == "mykey"
    assert seen["gemini_model"] == "gemini-pro-latest"


def test_api_text_annotate_ai_trusts_any_stored_gemini_model_name(client, monkeypatch):
    # Modelle werden dynamisch bei Google abgefragt (nicht mehr hart codiert) ->
    # jeder gespeicherte "gemini-*"-Name wird 1:1 durchgereicht, auch wenn er
    # nicht in der kleinen AVAILABLE_MODELS-Fallback-Liste steht.
    client.post("/api/settings", json={"gemini_key": "mykey", "gemini_model": "gemini-3-pro-preview"})

    seen = {}

    def fake_annotate_text_ai(text, *, gemini_key=None, gemini_model=None, use_cache=True, sample=False, token=None, **kwargs):
        seen["gemini_model"] = gemini_model
        return []

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc, "annotate_text_ai", fake_annotate_text_ai)

    r = client.post("/api/text-annotate-ai", json={"text": "x", "sample": True})
    assert r.status_code == 200
    assert seen["gemini_model"] == "gemini-3-pro-preview"


def test_api_text_annotate_ai_word_stats_and_ai_source_uses_kanacards(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc

    def fake_annotate_text_ai(text, *, gemini_key=None, gemini_model=None, use_cache=True, sample=False, token=None, **kwargs):
        return [{
            "sentence": "x", "translation": "Übersetzung", "grammar_notes": "Notiz", "error": None,
            "segments": [
                {"type": "word", "source": "ai", "text": "急に", "lemma": "急に", "sentence": "x",
                 "id": kc.ai_kana_card_id("急に"), "kind": "KI", "meaning": "plötzlich",
                 "reading": "きゅうに", "level": None},
            ],
        }]

    monkeypatch.setattr(kc, "annotate_text_ai", fake_annotate_text_ai)

    r = client.post("/api/text-annotate-ai", json={"text": "x", "sample": True})
    data = r.get_json()
    row = data["rows"][0]
    assert row["translation"] == "Übersetzung"
    assert row["grammar_notes"] == "Notiz"
    seg = row["segments"][0]
    assert seg["status"] == "unknown"
    assert seg["ready"] is False
    assert data["stats"]["total"] == 1

    # Karte manuell anlegen -> beim nächsten Aufruf "ready"
    client.post("/api/kanacards", json={"word": "急に", "source": "ai", "meaning": "plötzlich", "reading": "きゅうに"})
    r2 = client.post("/api/text-annotate-ai", json={"text": "x", "sample": True})
    seg2 = r2.get_json()["rows"][0]["segments"][0]
    assert seg2["ready"] is True
    assert seg2["status"] == "known"


# --------------------------------------------------------------------------- #
# Einstellungen (UserSettings, verschlüsselte Secrets)
# --------------------------------------------------------------------------- #

def test_api_settings_get_set_gemini_key_and_model(client):
    r0 = client.get("/api/settings").get_json()
    assert r0["gemini_key_set"] is False
    assert r0["gemini_model"] == "gemini-flash-latest"

    client.post("/api/settings", json={"gemini_key": "sekret", "gemini_model": "gemini-pro-latest"})
    r1 = client.get("/api/settings").get_json()
    assert r1["gemini_key_set"] is True
    assert r1["gemini_key_hint"].endswith("kret")
    assert r1["gemini_model"] == "gemini-pro-latest"


def test_api_settings_secrets_stored_encrypted_not_plaintext(client):
    client.post("/api/settings", json={"token": "supersecrettoken", "deepl_key": "mydeeplkey"})
    settings_row = models.UserSettings.query.filter_by(user_id=client.test_user_id).first()
    secrets_row = models.UserLanguageSecrets.query.filter_by(
        user_id=client.test_user_id, target_lang=settings_row.active_target_lang,
    ).first()
    assert secrets_row.wanikani_token_enc is not None
    assert "supersecrettoken" not in secrets_row.wanikani_token_enc
    assert settings_row.deepl_key_enc is not None
    assert "mydeeplkey" not in settings_row.deepl_key_enc


def test_get_or_create_language_secrets_survives_concurrent_insert_race(client, db_session, monkeypatch):
    """Regressionstest für einen live per Playwright gefundenen Bug: das
    Frontend feuert beim Login mehrere Requests parallel ab (loadSettings()/
    loadLanguages(), keiner wartet auf den anderen). Sehen zwei Requests
    gleichzeitig "Zeile existiert noch nicht", legen beide sie an - der
    Verlierer crashte vorher mit einem UNIQUE-constraint IntegrityError statt
    einfach die vom Gewinner erzeugte Zeile zu lesen."""
    original_commit = db.session.commit
    calls = {"n": 0}

    def racy_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            # Simuliert einen "gewinnenden" nebenläufigen Request, der die
            # Zeile zwischen unserem None-Check und unserem eigenen Commit
            # bereits erfolgreich angelegt hat.
            db.session.rollback()
            db.session.add(models.UserLanguageSecrets(user_id=client.test_user_id, target_lang="ja"))
            original_commit()
            raise IntegrityError("insert", {}, Exception("UNIQUE constraint failed"))
        return original_commit()

    monkeypatch.setattr(db.session, "commit", racy_commit)
    row = services._get_or_create_language_secrets(client.test_user_id, "ja")
    assert row is not None
    assert row.user_id == client.test_user_id


def test_api_settings_get_set_target_lang(client):
    r0 = client.get("/api/settings").get_json()
    assert r0["target_lang"] == "DE"
    assert "EN" in r0["target_langs"]

    client.post("/api/settings", json={"target_lang": "fr"})
    r1 = client.get("/api/settings").get_json()
    assert r1["target_lang"] == "FR"


def test_api_settings_rejects_unknown_target_lang(client):
    client.post("/api/settings", json={"target_lang": "XX"})
    r = client.get("/api/settings").get_json()
    assert r["target_lang"] == "DE"  # ungültiger Wert wird ignoriert, Default bleibt


def test_api_settings_isolated_between_users(client, db_session):
    client.post("/api/settings", json={"gemini_model": "gemini-pro-latest"})

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "other4@example.com", "password": "supersecret123"})
    r = other.get("/api/settings").get_json()
    assert r["gemini_model"] == "gemini-flash-latest"  # unverändert, eigener Datensatz


def test_api_settings_post_ignores_unknown_gemini_model(client):
    client.post("/api/settings", json={"gemini_model": "not-a-real-model"})
    r = client.get("/api/settings").get_json()
    assert r["gemini_model"] == "gemini-flash-latest"  # ungültiger Wert wird ignoriert


def test_api_gemini_models_requires_key(client):
    r = client.post("/api/gemini/models", json={})
    assert r.status_code == 400
    assert "Key" in r.get_json()["error"]


def test_api_gemini_models_uses_stored_key_when_none_provided(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "storedkey"})

    seen = {}

    def fake_list_models(key, *, session=None):
        seen["key"] = key
        return ["gemini-flash-latest", "gemini-3-pro-preview"]

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "list_models", fake_list_models)

    r = client.post("/api/gemini/models", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert seen["key"] == "storedkey"
    assert data["models"] == ["gemini-flash-latest", "gemini-3-pro-preview"]
    assert data["default"] == kc.gemini_client.DEFAULT_MODEL


def test_api_gemini_models_prefers_explicit_key_over_stored(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "storedkey"})

    seen = {}

    def fake_list_models(key, *, session=None):
        seen["key"] = key
        return ["gemini-flash-latest"]

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "list_models", fake_list_models)

    r = client.post("/api/gemini/models", json={"key": "explicitkey"})
    assert r.status_code == 200
    assert seen["key"] == "explicitkey"


def test_api_gemini_models_returns_502_on_invalid_key(client, monkeypatch):
    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "list_models", lambda key, **kw: None)

    r = client.post("/api/gemini/models", json={"key": "badkey"})
    assert r.status_code == 502


def test_api_gemini_models_returns_502_on_empty_result(client, monkeypatch):
    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "list_models", lambda key, **kw: [])

    r = client.post("/api/gemini/models", json={"key": "somekey"})
    assert r.status_code == 502


def test_api_gemini_tts_requires_text(client):
    r = client.post("/api/gemini/tts", json={})
    assert r.status_code == 400


def test_api_gemini_tts_requires_stored_key(client):
    r = client.post("/api/gemini/tts", json={"text": "大きい山です。"})
    assert r.status_code == 400
    assert "Gemini" in r.get_json()["error"]


def test_api_gemini_tts_returns_data_uri(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "synthesize_speech", lambda text, key, **kw: b"RIFF....WAVEfmt ")

    r = client.post("/api/gemini/tts", json={"text": "大きい山です。"})
    assert r.status_code == 200
    assert r.get_json()["audio_data_uri"].startswith("data:audio/wav;base64,")


def test_api_gemini_tts_returns_502_on_synthesis_failure(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "synthesize_speech", lambda text, key, **kw: None)

    r = client.post("/api/gemini/tts", json={"text": "大きい山です。"})
    assert r.status_code == 502


def test_api_gemini_generate_image_requires_word(client):
    r = client.post("/api/gemini/generate-image", json={})
    assert r.status_code == 400


def test_api_gemini_generate_image_requires_stored_key(client):
    r = client.post("/api/gemini/generate-image", json={"word": "家", "meaning": "Haus"})
    assert r.status_code == 400
    assert "Gemini" in r.get_json()["error"]


def test_api_gemini_generate_image_returns_data_uri(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "generate_image", lambda word, meaning, key, **kw: (b"pngbytes", "image/png"))

    r = client.post("/api/gemini/generate-image", json={"word": "家", "meaning": "Haus"})
    assert r.status_code == 200
    assert r.get_json()["image_data_uri"].startswith("data:image/png;base64,")


def test_api_gemini_generate_image_returns_502_on_failure(client, monkeypatch):
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "generate_image", lambda word, meaning, key, **kw: None)

    r = client.post("/api/gemini/generate-image", json={"word": "家", "meaning": "Haus"})
    assert r.status_code == 502


# --------------------------------------------------------------------------- #
# Dictionary-Karten (KanaCard) – CRUD über /api/kanacards
# --------------------------------------------------------------------------- #

def test_api_create_kanacard_ai_stores_sentence_audio_url(client):
    r = client.post("/api/kanacards", json={
        "word": "入る", "source": "ai", "meaning": "hineingehen", "reading": "はいる",
        "sentence": "高校に入りました。", "sentence_audio_url": "data:audio/wav;base64,AAAA",
    })
    assert r.status_code == 200
    kid = r.get_json()["id"]
    stored = services.read_kana_for_user(client.test_user_id, kid, "ja")
    assert stored["sentence_audio_url"] == "data:audio/wav;base64,AAAA"


def test_api_create_kanacard_persists_and_returns_descriptor(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match; game"}})

    r = client.post("/api/kanacards", json={"word": "しあい", "sentence": "しあいがはじまりました。"})
    assert r.status_code == 200
    desc = r.get_json()
    assert desc["characters"] == "しあい"
    assert desc["meaning"] == "match; game"
    assert desc["kind"] == "Dict"

    stored = services.read_kana_for_user(client.test_user_id, desc["id"], "ja")
    assert stored["word"] == "しあい"
    assert stored["kanji_hint"] == "試合"
    assert stored["sentence_ja"] == "しあいがはじまりました。"


def test_api_create_kanacard_404_when_not_in_dictionary(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {})

    r = client.post("/api/kanacards", json={"word": "ぜんぜんちがう"})
    assert r.status_code == 404


def test_api_create_kanacard_requires_word(client):
    r = client.post("/api/kanacards", json={})
    assert r.status_code == 400


def test_api_kanacards_list_and_delete(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})

    created = client.post("/api/kanacards", json={"word": "しあい"}).get_json()

    listed = client.get("/api/kanacards").get_json()
    assert any(c["id"] == created["id"] for c in listed)

    r = client.delete(f"/api/kanacards/{created['id']}")
    assert r.status_code == 200
    assert services.read_kana_for_user(client.test_user_id, created["id"], "ja") is None

    assert client.delete(f"/api/kanacards/{created['id']}").status_code == 404


def test_api_delete_kanacard_cleans_up_review_state_and_log(client, monkeypatch):
    """Regressionstest (Architektur-Review): eine gelöschte Karte darf keine
    Datenleiche in ReviewState/ReviewLog hinterlassen - sonst würde sie in
    der Review-Queue als "fällig" weitergeführt, obwohl sie gar nicht mehr
    existiert."""
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})
    created = client.post("/api/kanacards", json={"word": "しあい"}).get_json()
    kid = created["id"]

    client.post("/api/srs/add", json={"kana_ids": [kid]})
    assert models.ReviewState.query.filter_by(user_id=client.test_user_id, card_type="kana", card_id=kid).count() > 0
    models.ReviewLog.query.filter_by(user_id=client.test_user_id, card_type="kana", card_id=kid).first()

    client.delete(f"/api/kanacards/{kid}")

    assert models.ReviewState.query.filter_by(user_id=client.test_user_id, card_type="kana", card_id=kid).count() == 0
    assert models.ReviewLog.query.filter_by(user_id=client.test_user_id, card_type="kana", card_id=kid).count() == 0


def test_api_kanacards_isolated_between_users(client, db_session, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})
    created = client.post("/api/kanacards", json={"word": "しあい"}).get_json()

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "other5@example.com", "password": "supersecret123"})
    assert other.get(f"/api/customcards/{created['id']}").status_code == 404
    assert other.get("/api/kanacards").get_json() == []
    assert other.delete(f"/api/kanacards/{created['id']}").status_code == 404


def test_api_kanacards_same_word_different_users_no_collision(client, db_session, monkeypatch):
    """Zwei Nutzer legen dieselbe Vokabel als Karte an - der zusammengesetzte
    Primärschlüssel (user_id, id) in KanaCard verhindert, dass sich die
    beiden gegenseitig überschreiben (siehe models.KanaCard-Docstring)."""
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {})

    r1 = client.post("/api/kanacards", json={"word": "テスト", "source": "ai", "meaning": "Alice meaning"})
    assert r1.status_code == 200
    kid = r1.get_json()["id"]

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "other6@example.com", "password": "supersecret123"})
    r2 = other.post("/api/kanacards", json={"word": "テスト", "source": "ai", "meaning": "Bob meaning"})
    assert r2.status_code == 200
    assert r2.get_json()["id"] == kid  # gleicher Hash, da wortbasiert

    assert client.get("/api/kanacards").get_json()[0]["meaning"] == "Alice meaning"
    assert other.get("/api/kanacards").get_json()[0]["meaning"] == "Bob meaning"


# --------------------------------------------------------------------------- #
# Eigene Karten (CustomCard) – CRUD über /api/customcards
# --------------------------------------------------------------------------- #

def test_api_customcard_create_read_update_delete(client):
    created = client.post("/api/customcards", json={"front_html": "<b>x</b>", "back_html": "y", "tags": ["Lv 1"]}).get_json()
    cid = created["id"]

    fetched = client.get(f"/api/customcards/{cid}").get_json()
    assert fetched["front_html"] == "<b>x</b>"

    updated = client.post("/api/customcards", json={"id": cid, "front_html": "<b>neu</b>", "back_html": "y", "tags": []}).get_json()
    assert updated["front_html"] == "<b>neu</b>"

    r = client.delete(f"/api/customcards/{cid}")
    assert r.status_code == 200
    assert client.get(f"/api/customcards/{cid}").status_code == 404


def test_api_delete_customcard_cleans_up_review_state_and_log(client):
    """Analog zum kanacards-Pendant oben, für CustomCards."""
    created = client.post("/api/customcards", json={"front_html": "x", "back_html": "y", "tags": []}).get_json()
    cid = created["id"]

    client.post("/api/srs/add", json={"custom_ids": [cid]})
    assert models.ReviewState.query.filter_by(user_id=client.test_user_id, card_type="custom", card_id=cid).count() > 0

    client.delete(f"/api/customcards/{cid}")

    assert models.ReviewState.query.filter_by(user_id=client.test_user_id, card_type="custom", card_id=cid).count() == 0
    assert models.ReviewLog.query.filter_by(user_id=client.test_user_id, card_type="custom", card_id=cid).count() == 0


def test_api_customcard_edit_rejects_foreign_id(client, db_session):
    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "other7@example.com", "password": "supersecret123"})
    foreign = other.post("/api/customcards", json={"front_html": "foreign", "back_html": "y", "tags": []}).get_json()

    r = client.post("/api/customcards", json={"id": foreign["id"], "front_html": "hijacked", "back_html": "y", "tags": []})
    assert r.status_code == 404
    # Fremde Karte bleibt unverändert.
    assert other.get(f"/api/customcards/{foreign['id']}").get_json()["front_html"] == "foreign"


def test_api_customcard_isolated_between_users(client, db_session):
    created = client.post("/api/customcards", json={"front_html": "mine", "back_html": "y", "tags": []}).get_json()

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "other8@example.com", "password": "supersecret123"})
    assert other.get(f"/api/customcards/{created['id']}").status_code == 404
    assert other.get("/api/customcards").get_json() == []
    assert other.delete(f"/api/customcards/{created['id']}").status_code == 404
    # Karte existiert für den Eigentümer weiterhin.
    assert client.get(f"/api/customcards/{created['id']}").status_code == 200


# --------------------------------------------------------------------------- #
# Wortliste: vereinigte Liste aller bekannten Wörter (WaniKani + Dictionary +
# rein manuelle Einträge), filter-/entfernbar über /api/wortliste
# --------------------------------------------------------------------------- #

def test_api_wortliste_combines_wanikani_dictionary_and_manual(client):
    db.session.add(models.Job(id="a", user_id=client.test_user_id, status="done", params={"subject_ids": [2467]}))
    db.session.commit()
    services.write_kana(
        {"id": "kana_x", "word": "しあい", "meaning": "match", "tags": ["Dictionary"]},
        user_id=client.test_user_id,
    )
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


def test_api_wortliste_ai_sourced_entry_shows_ki_kind_and_sentence_context(client):
    services.write_kana(
        {
            "id": "aikana_x", "word": "入る", "reading": "はいる", "meaning": "hineingehen",
            "source": "ai", "tags": ["KI"], "sentence_ja": "高校に入りました。",
            "sentence_translation": "Ich bin in die Oberschule eingetreten.",
            "sentence_audio_url": "data:audio/wav;base64,AAAA",
        },
        user_id=client.test_user_id,
    )

    r = client.get("/api/wortliste?sample=1")
    data = r.get_json()
    entry = next(e for e in data["entries"] if e["id"] == "aikana_x")
    assert entry["source"] == "ai"
    assert entry["kind"] == "KI"
    assert entry["reading"] == "はいる"
    assert entry["sentence_ja"] == "高校に入りました。"
    assert entry["sentence_translation"] == "Ich bin in die Oberschule eingetreten."
    assert entry["sentence_audio_url"] == "data:audio/wav;base64,AAAA"


def test_api_wortliste_add_manual_then_remove(client):
    entry = client.post("/api/wortliste", json={"characters": "genki", "meaning": "gesund"}).get_json()
    wid = entry["id"]
    assert wid.startswith("manual_")

    listed = client.get("/api/wortliste?sample=1").get_json()
    assert any(e["id"] == wid for e in listed["entries"])

    client.delete(f"/api/known/{wid}")
    listed2 = client.get("/api/wortliste?sample=1").get_json()
    assert not any(e["id"] == wid for e in listed2["entries"])


def test_api_wortliste_add_manual_requires_characters(client):
    r = client.post("/api/wortliste", json={})
    assert r.status_code == 400


def test_api_wortliste_manually_known_wanikani_word_is_removable(client):
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

def test_build_mixed_deck_combines_all_three_sources(logged_in_user):
    uid = logged_in_user.id
    services.write_custom({"id": "free1", "front_html": "<b>x</b>", "back_html": "y", "tags": []}, user_id=uid)
    services.write_kana({"id": "kana_x", "word": "しあい", "meaning": "match", "tags": ["Dictionary"]}, user_id=uid)

    deck = services._build_mixed_deck(
        {
            "subject_ids": [2467],  # 一 (Sample-Daten)
            "custom_ids": ["free1"],
            "kana_ids": ["kana_x"],
            "sample": True,
        },
        uid,
    )
    kinds = {type(c).__name__ for c in deck}
    assert kinds == {"VocabCard", "CustomCard", "KanaCard"}
    assert len(deck) == 3


def test_build_mixed_deck_empty_params_returns_empty_deck(logged_in_user):
    assert services._build_mixed_deck({}, logged_in_user.id) == []


def test_build_mixed_deck_skips_missing_custom_or_kana_ids(logged_in_user):
    deck = services._build_mixed_deck({"custom_ids": ["missing"], "kana_ids": ["missing"]}, logged_in_user.id)
    assert deck == []


def test_build_mixed_deck_applies_field_overrides(logged_in_user):
    deck = services._build_mixed_deck(
        {
            "subject_ids": [2467],  # 一 (Vokabel, Sample-Daten)
            "sample": True,
            "field_overrides": {"2467": {"meanings": ["Eigene Bedeutung"]}},
        },
        logged_in_user.id,
    )
    assert deck[0].meanings == ["Eigene Bedeutung"]


def test_build_mixed_deck_only_sees_own_custom_and_kana_cards(client, db_session):
    """`_build_mixed_deck` bekommt einen expliziten `user_id` - eine fremde
    custom_id/kana_id wird dadurch NICHT gefunden (IDOR-Schutz), selbst wenn
    sie existiert (siehe api_render()-Validierung, die das vorher abfängt)."""
    other = models.User(email="deckowner@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    services.write_custom({"id": "theirs", "front_html": "x", "back_html": "y", "tags": []}, user_id=other.id)

    deck = services._build_mixed_deck({"custom_ids": ["theirs"]}, client.test_user_id)
    assert deck == []


# --------------------------------------------------------------------------- #
# /api/render, Jobs (Ownership-Checks, IDOR-Schutz)
# --------------------------------------------------------------------------- #

def test_api_render_stores_field_overrides_in_job_params(client):
    r = client.post(
        "/api/render",
        json={
            "subject_ids": [2467], "sample": True, "format": "pdf",
            "field_overrides": {"2467": {"meanings": ["Eigene Bedeutung"]}},
        },
    )
    assert r.status_code == 202
    job_id = r.get_json()["id"]
    job = services.read_job(job_id)
    assert job["params"]["field_overrides"] == {"2467": {"meanings": ["Eigene Bedeutung"]}}
    assert job["user_id"] == client.test_user_id


def test_save_subject_override_roundtrip_and_merge(logged_in_user):
    """`save_subject_override` mergt neue Felder in bereits gespeicherte,
    statt sie zu ersetzen - ein zweiter Aufruf mit nur EINEM geänderten Feld
    darf ein zuvor gespeichertes anderes Feld nicht löschen."""
    services.save_subject_override(logged_in_user.id, 2467, {"meanings": ["Eigene Bedeutung"]})
    services.save_subject_override(logged_in_user.id, 2467, {"vocab_meaning": "Zusatz"})
    stored = services.get_subject_overrides(logged_in_user.id, [2467])
    assert stored[2467] == {"meanings": ["Eigene Bedeutung"], "vocab_meaning": "Zusatz"}

    # `None` löscht gezielt EIN Feld wieder.
    services.save_subject_override(logged_in_user.id, 2467, {"meanings": None})
    stored = services.get_subject_overrides(logged_in_user.id, [2467])
    assert stored[2467] == {"vocab_meaning": "Zusatz"}

    # Leert man alle Felder, verschwindet die Zeile ganz statt leer zu bleiben.
    services.save_subject_override(logged_in_user.id, 2467, {"vocab_meaning": None})
    assert models.SubjectFieldOverride.query.filter_by(user_id=logged_in_user.id, subject_id=2467).count() == 0


def test_build_mixed_deck_applies_persisted_subject_overrides(logged_in_user):
    """Dauerhaft gespeicherte Overrides (siehe /api/subject-overrides) wirken
    automatisch auch auf künftige PDF-/Anki-Exports, OHNE dass der Aufrufer
    sie erneut als `field_overrides` mitschicken muss."""
    services.save_subject_override(logged_in_user.id, 2467, {"meanings": ["Persistiert"]})
    deck = services._build_mixed_deck({"subject_ids": [2467], "sample": True}, logged_in_user.id)
    assert deck[0].meanings == ["Persistiert"]


def test_api_subject_overrides_save_and_reflect_in_card_detail(client):
    r = client.post("/api/subject-overrides", json={"subject_id": 2467, "fields": {"meanings": ["Meine Bedeutung"]}})
    assert r.status_code == 200

    detail = client.post("/api/card-detail", json={"subject_ids": [2467], "sample": True}).get_json()
    assert detail["cards"]["2467"]["meanings"] == ["Meine Bedeutung"]


def test_api_subject_overrides_scoped_per_user(client, db_session):
    """Ein Override eines anderen Nutzers darf für DIESEN Nutzer nicht sichtbar
    sein - gilt nur für den eigenen Account, nie global (siehe UI-Feedback:
    "Auch WaniKani-Karten ... nur für den eigenen Account")."""
    other = models.User(email="overridesowner@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    services.save_subject_override(other.id, 2467, {"meanings": ["Fremde Bedeutung"]})

    detail = client.post("/api/card-detail", json={"subject_ids": [2467], "sample": True}).get_json()
    assert detail["cards"]["2467"]["meanings"] != ["Fremde Bedeutung"]


def test_api_edit_kanacard_overwrites_fields_directly(client):
    add = client.post("/api/kanacards", json={"word": "たべる", "source": "ai", "meaning": "essen"})
    kid = add.get_json()["id"]

    r = client.post(f"/api/kanacards/{kid}/edit", json={"fields": {"meaning": "Essen (angepasst)", "meaning_extra": "futtern"}})
    assert r.status_code == 200
    assert r.get_json()["meaning"] == "Essen (angepasst)"

    full = client.get(f"/api/kanacards/{kid}").get_json()
    assert full["meaning"] == "Essen (angepasst)"
    assert full["meaning_extra"] == "futtern"


def test_api_edit_kanacard_rejects_foreign_card(client, db_session):
    other = models.User(email="kanaowner@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    services.write_kana(
        {"id": "theirskana", "word": "x", "meaning": "y", "tags": []}, user_id=other.id, target_lang="ja",
    )
    r = client.post("/api/kanacards/theirskana/edit", json={"fields": {"meaning": "hijacked"}})
    assert r.status_code == 404


def test_api_render_rejects_foreign_custom_id(client, db_session):
    other = models.User(email="rendertheirs@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    services.write_custom({"id": "theirs", "front_html": "x", "back_html": "y", "tags": []}, user_id=other.id)

    r = client.post("/api/render", json={"custom_ids": ["theirs"], "sample": True, "format": "pdf"})
    assert r.status_code == 404
    assert models.Job.query.count() == 0  # kein Job angelegt


def test_api_render_rejects_foreign_kana_id(client, db_session):
    other = models.User(email="renderkana@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    services.write_kana({"id": "kana_theirs", "word": "x", "meaning": "y", "tags": []}, user_id=other.id)

    r = client.post("/api/render", json={"kana_ids": ["kana_theirs"], "sample": True, "format": "pdf"})
    assert r.status_code == 404
    assert models.Job.query.count() == 0


def test_api_render_requires_at_least_one_card(client):
    r = client.post("/api/render", json={"sample": True, "format": "pdf"})
    assert r.status_code == 400


def test_api_jobs_isolated_between_users(client, db_session):
    r = client.post("/api/render", json={"subject_ids": [2467], "sample": True, "format": "pdf"})
    job_id = r.get_json()["id"]

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "jobsother@example.com", "password": "supersecret123"})
    assert other.get(f"/api/jobs/{job_id}").status_code == 404
    assert other.delete(f"/api/jobs/{job_id}").status_code == 404
    assert other.get(f"/api/jobs/{job_id}/pdf").status_code == 404
    assert other.get(f"/api/jobs/{job_id}/apkg").status_code == 404
    assert other.get("/api/jobs").get_json() == []

    # Eigentümer selbst sieht den Job weiterhin.
    assert client.get(f"/api/jobs/{job_id}").status_code == 200


def test_api_delete_job_removes_own_job(client):
    r = client.post("/api/render", json={"subject_ids": [2467], "sample": True, "format": "pdf"})
    job_id = r.get_json()["id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


# --------------------------------------------------------------------------- #
# /api/card-detail, /api/translate
# --------------------------------------------------------------------------- #

def test_api_card_detail_returns_full_fields_for_kanji(client):
    r = client.post("/api/card-detail", json={"subject_ids": [440], "sample": True})  # 一 (Kanji)
    assert r.status_code == 200
    data = r.get_json()["cards"]
    assert "440" in data
    assert data["440"]["kind"] == "Card"
    assert "meanings" in data["440"] and "onyomi" in data["440"]


def test_api_card_detail_skips_unknown_ids(client):
    r = client.post("/api/card-detail", json={"subject_ids": [999999999], "sample": True})
    assert r.status_code == 200
    assert r.get_json()["cards"] == {}


def test_api_translate_requires_deepl_key(client):
    r = client.post("/api/translate", json={"text": "wing"})
    assert r.status_code == 400
    assert "DeepL" in r.get_json()["error"]


def test_api_translate_requires_text(client):
    r = client.post("/api/translate", json={"text": ""})
    assert r.status_code == 400


def test_api_translate_uses_target_lang_and_source_lang(client, monkeypatch):
    client.post("/api/settings", json={"deepl_key": "mykey:fx", "target_lang": "FR"})

    seen = {}

    def fake_translate(text, api_key, *, target_lang="DE", source_lang="JA", session=None):
        seen["args"] = (text, api_key, target_lang, source_lang)
        return "aile"

    monkeypatch.setattr(webapp.kc.dictionary, "translate_sentence", fake_translate)
    r = client.post("/api/translate", json={"text": "wing", "source_lang": "en"})
    assert r.status_code == 200
    assert r.get_json() == {"translation": "aile", "target_lang": "FR"}
    assert seen["args"] == ("wing", "mykey:fx", "FR", "EN")


# --------------------------------------------------------------------------- #
# WaniKani-Token wird explizit durchgereicht statt prozessglobal (Phase 3,
# siehe README "Multi-User-Architektur") - jeder Nutzer bekommt garantiert
# seinen EIGENEN Token an kanji_cards.py übergeben.
# --------------------------------------------------------------------------- #

def test_api_resolve_passes_stored_token_explicitly(client, monkeypatch):
    client.post("/api/settings", json={"token": "alice-token"})

    seen = {}

    def fake_resolve_level(level, deck_types, *, use_cache=True, sample=False, token=None):
        seen["token"] = token
        return []

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc, "resolve_level", fake_resolve_level)

    r = client.post("/api/resolve", json={"mode": "level", "level": 1, "types": ["kanji"], "sample": False})
    assert r.status_code == 200
    assert seen["token"] == "alice-token"


def test_api_resolve_sample_mode_passes_no_token(client, monkeypatch):
    client.post("/api/settings", json={"token": "alice-token"})

    seen = {}

    def fake_resolve_level(level, deck_types, *, use_cache=True, sample=False, token=None):
        seen["token"] = token
        return []

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc, "resolve_level", fake_resolve_level)

    r = client.post("/api/resolve", json={"mode": "level", "level": 1, "types": ["kanji"], "sample": True})
    assert r.status_code == 200
    assert seen["token"] is None


def test_two_users_render_with_their_own_tokens_not_each_others(client, db_session, monkeypatch):
    """Kernszenario des Fixes: zwei Nutzer mit unterschiedlichen Tokens dürfen
    sich nicht gegenseitig beeinflussen, selbst wenn ihre Requests
    "gleichzeitig" (nacheinander im selben Prozess) laufen."""
    client.post("/api/settings", json={"token": "alice-token"})

    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "bobtoken@example.com", "password": "supersecret123"})
    other.post("/api/settings", json={"token": "bob-token"})

    seen_tokens = []

    def fake_resolve_level(level, deck_types, *, use_cache=True, sample=False, token=None):
        seen_tokens.append(token)
        return []

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc, "resolve_level", fake_resolve_level)

    client.post("/api/resolve", json={"mode": "level", "level": 1, "types": ["kanji"], "sample": False})
    other.post("/api/resolve", json={"mode": "level", "level": 1, "types": ["kanji"], "sample": False})

    assert seen_tokens == ["alice-token", "bob-token"]


# --------------------------------------------------------------------------- #
# Multi-Language-Architektur: /api/languages, /api/settings/language,
# target_lang-Isolation, WK-only-Endpunkte für Nicht-Japanisch
# --------------------------------------------------------------------------- #

def test_api_languages_returns_japanese_capabilities_by_default(client):
    r = client.get("/api/languages")
    assert r.status_code == 200
    data = r.get_json()
    assert data["native_lang"] == "de"
    assert data["active_target_lang"] == "ja"
    caps = data["active_capabilities"]
    assert caps["has_content_provider"] is True
    assert caps["reading_labels"] == ["Onyomi", "Kunyomi"]
    assert caps["has_furigana"] is True
    assert caps["has_offline_tokenizer"] is True
    codes = {lang["code"] for lang in data["supported_target_langs"]}
    assert {"ja", "en", "es"}.issubset(codes)


def test_api_languages_returns_generic_capabilities_for_other_language(client):
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    data = client.get("/api/languages").get_json()
    assert data["active_target_lang"] == "es"
    caps = data["active_capabilities"]
    assert caps["has_content_provider"] is False
    assert caps["reading_labels"] == []
    assert caps["has_furigana"] is False
    assert caps["has_offline_tokenizer"] is False


def test_api_settings_language_switches_native_and_target(client):
    r = client.post("/api/settings/language", json={"native_lang": "en", "active_target_lang": "es"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "native_lang": "en", "active_target_lang": "es"}

    me = client.get("/api/auth/me").get_json()
    assert me["native_lang"] == "en"
    assert me["active_target_lang"] == "es"


def test_api_settings_language_partial_update_keeps_other_field(client):
    client.post("/api/settings/language", json={"active_target_lang": "fr"})
    r = client.post("/api/settings/language", json={"native_lang": "en"})
    assert r.get_json() == {"ok": True, "native_lang": "en", "active_target_lang": "fr"}


def test_api_settings_language_rejects_non_string(client):
    r = client.post("/api/settings/language", json={"native_lang": 123})
    assert r.status_code == 400


def test_target_lang_isolates_custom_cards_between_languages(client):
    client.post("/api/customcards", json={"front_html": "<div>ja-karte</div>", "back_html": "<div>b</div>"})
    assert len(client.get("/api/customcards").get_json()) == 1

    client.post("/api/settings/language", json={"active_target_lang": "es"})
    assert client.get("/api/customcards").get_json() == []

    client.post("/api/settings/language", json={"active_target_lang": "ja"})
    cards = client.get("/api/customcards").get_json()
    assert len(cards) == 1
    assert cards[0]["characters"] == "ja-kar"  # _custom_descriptor kürzt auf 6 Zeichen


def test_target_lang_isolates_known_words_between_languages(client):
    client.post("/api/known/42")
    known = models.KnownWord.query.filter_by(user_id=client.test_user_id, target_lang="ja").all()
    assert {int(r.word_id) for r in known} == {42}

    client.post("/api/settings/language", json={"active_target_lang": "es"})
    known_es = models.KnownWord.query.filter_by(user_id=client.test_user_id, target_lang="es").all()
    assert known_es == []

    # Über die WaniKani-Wortliste sichtbar geprüft statt webapp.load_known()
    # direkt (das braucht current_user, also einen aktiven Request-Kontext).
    r = client.get("/api/wortliste?sample=1")
    entries = r.get_json()["entries"]
    assert not any(e["id"] == 42 for e in entries)  # aktiv ist jetzt "es"

    client.post("/api/settings/language", json={"active_target_lang": "ja"})
    r = client.get("/api/wortliste?sample=1")
    entries = r.get_json()["entries"]
    assert any(e["id"] == 42 and e.get("manually_known") for e in entries)


def test_target_lang_isolates_kana_cards_between_languages(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})

    created = client.post("/api/kanacards", json={"word": "しあい"}).get_json()
    assert any(c["id"] == created["id"] for c in client.get("/api/kanacards").get_json())

    client.post("/api/settings/language", json={"active_target_lang": "es"})
    assert client.get("/api/kanacards").get_json() == []

    client.post("/api/settings/language", json={"active_target_lang": "ja"})
    assert any(c["id"] == created["id"] for c in client.get("/api/kanacards").get_json())


def test_target_lang_isolates_jobs_between_languages(client, db_session):
    db.session.add(models.Job(id="ja-job", user_id=client.test_user_id, target_lang="ja", status="done"))
    db.session.add(models.Job(id="es-job", user_id=client.test_user_id, target_lang="es", status="done"))
    db.session.commit()

    assert [j["id"] for j in client.get("/api/jobs").get_json()] == ["ja-job"]

    client.post("/api/settings/language", json={"active_target_lang": "es"})
    assert [j["id"] for j in client.get("/api/jobs").get_json()] == ["es-job"]


def test_wk_only_endpoints_blocked_for_non_japanese(client):
    client.post("/api/settings/language", json={"active_target_lang": "es"})

    r = client.post("/api/resolve", json={"mode": "level", "level": 1, "sample": True})
    assert r.status_code == 400
    assert "Japanisch" in r.get_json()["error"]

    r = client.post("/api/card-detail", json={"subject_ids": [1], "sample": True})
    assert r.status_code == 400

    r = client.post("/api/test-token", json={"token": "x"})
    assert r.status_code == 400

    r = client.post("/api/text-annotate", json={"text": "hola", "sample": True})
    assert r.status_code == 400


def test_wk_only_endpoints_work_normally_for_japanese(client):
    """Regressionstest: die Gating-Checks dürfen den Default-Fall (aktive
    Zielsprache = Japanisch) nicht versehentlich mitblockieren."""
    r = client.post("/api/resolve", json={"mode": "level", "level": 1, "types": ["kanji"], "sample": True})
    assert r.status_code == 200
    r = client.post("/api/text-annotate", json={"text": "大きい山です。", "sample": True})
    assert r.status_code == 200


def test_api_create_kanacard_uses_gemini_fallback_for_non_japanese(client, monkeypatch):
    """Für Zielsprachen ohne JMdict-Äquivalent übernimmt Gemini die
    Wörterbuch-Funktion (siehe kc.build_generic_dictionary_card)."""
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc

    def fake_lookup(word, api_key, *, model=None, session=None, use_cache=True, target_lang_name="", native_lang_name="", has_reading=False):
        assert target_lang_name == "Spanisch"
        return {"meaning": "house", "reading": None}

    monkeypatch.setattr(kc.gemini_client, "lookup_word", fake_lookup)

    r = client.post("/api/kanacards", json={"word": "casa"})
    assert r.status_code == 200
    desc = r.get_json()
    assert desc["characters"] == "casa"
    assert desc["meaning"] == "house"
    assert desc["kind"] == "KI"

    stored = services.read_kana_for_user(client.test_user_id, desc["id"], "es")
    assert stored["word"] == "casa"
    assert stored["source"] == "ai"


def test_api_create_kanacard_requires_gemini_key_for_non_japanese(client):
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    r = client.post("/api/kanacards", json={"word": "casa"})
    assert r.status_code == 400
    assert "Gemini" in r.get_json()["error"]


def test_api_create_kanacard_404_when_gemini_finds_nothing_for_non_japanese(client, monkeypatch):
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    client.post("/api/settings", json={"gemini_key": "mykey"})

    from shiori import kanji_cards as kc
    monkeypatch.setattr(kc.gemini_client, "lookup_word", lambda *a, **k: None)

    r = client.post("/api/kanacards", json={"word": "qwxyz"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Vokabeltrainer (SRS, Fundament): /api/srs/add, /api/srs/queue
# --------------------------------------------------------------------------- #

def test_api_srs_add_requires_at_least_one_card(client):
    r = client.post("/api/srs/add", json={})
    assert r.status_code == 400


def test_api_srs_add_kanji_creates_meaning_and_reading_rows(client):
    r = client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "added": 2}

    rows = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="440").all()
    assert {row.item_type for row in rows} == {"meaning", "reading"}
    assert all(row.card_type == "wanikani" for row in rows)
    assert all(row.reps == 0 for row in rows)


def test_api_srs_add_radical_creates_only_meaning_row(client):
    r = client.post("/api/srs/add", json={"subject_ids": [1], "sample": True})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "added": 1}

    rows = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="1").all()
    assert [row.item_type for row in rows] == ["meaning"]


def test_api_srs_add_is_idempotent_and_keeps_existing_progress(client, db_session):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    row = models.ReviewState.query.filter_by(
        user_id=client.test_user_id, card_id="440", item_type="meaning",
    ).first()
    row.reps = 7
    db_session.session.commit()

    r = client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    assert r.get_json() == {"ok": True, "added": 0}  # beide Zeilen existieren schon

    row = models.ReviewState.query.filter_by(
        user_id=client.test_user_id, card_id="440", item_type="meaning",
    ).first()
    assert row.reps == 7  # Fortschritt NICHT zurückgesetzt


def test_api_srs_add_custom_card_creates_front_row(client):
    created = client.post("/api/customcards", json={"front_html": "<div>x</div>", "back_html": "<div>y</div>"}).get_json()
    r = client.post("/api/srs/add", json={"custom_ids": [created["id"]]})
    assert r.get_json() == {"ok": True, "added": 1}
    row = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_type="custom").first()
    assert row.item_type == "front"


def test_api_srs_add_custom_card_rejects_foreign_ownership(client, db_session):
    other = models.User(email="srsother@example.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()
    db.session.add(models.CustomCard(id="foreign1", user_id=other.id, front_html="x", back_html="y"))
    db.session.commit()

    r = client.post("/api/srs/add", json={"custom_ids": ["foreign1"]})
    assert r.status_code == 404


def test_api_srs_add_kana_card_reading_depends_on_record(client, monkeypatch):
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})
    created = client.post("/api/kanacards", json={"word": "しあい"}).get_json()

    r = client.post("/api/srs/add", json={"kana_ids": [created["id"]]})
    assert r.status_code == 200
    rows = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_type="kana").all()
    # "しあい" hat aus dem Dictionary-Eintrag keine gesonderte Lesung (nur kanji_hint/meaning) -> nur "meaning"
    assert [row.item_type for row in rows] == ["meaning"]


def test_api_srs_add_blocked_for_wanikani_subjects_in_non_japanese(client):
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    r = client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    assert r.status_code == 400


def test_api_srs_queue_lists_due_new_cards_and_respects_limit(client):
    client.post("/api/srs/add", json={"subject_ids": [440, 1], "sample": True})
    r = client.get("/api/srs/queue")
    assert r.status_code == 200
    data = r.get_json()
    assert data["due_total"] == 3  # 440: meaning+reading, 1: meaning
    assert len(data["items"]) == 3
    assert all(item["is_new"] for item in data["items"])
    fronts = {item["front"] for item in data["items"]}
    # Ohne gespeicherten Token muss die Vorschau auf die Sample-Registry
    # zurückfallen (Demo-Modus) statt bei "?" zu landen - Regressionstest für
    # einen live gefundenen Bug (sample-Flag wurde nicht durchgereicht).
    assert fronts == {"一"}

    r2 = client.get("/api/srs/queue?limit=1")
    assert len(r2.get_json()["items"]) == 1
    assert r2.get_json()["due_total"] == 3


def test_api_srs_queue_isolated_between_target_languages(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    r = client.get("/api/srs/queue")
    assert r.get_json() == {"items": [], "due_total": 0}


def test_api_srs_queue_excludes_not_yet_due_cards(client, db_session):
    from datetime import datetime, timedelta
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    rows = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="440").all()
    for row in rows:
        row.due_at = datetime.now(UTC) + timedelta(days=5)
    db_session.session.commit()

    r = client.get("/api/srs/queue")
    assert r.get_json() == {"items": [], "due_total": 0}


# --------------------------------------------------------------------------- #
# Vokabeltrainer (SRS, Fundament): /api/srs/check, /api/srs/answer
# --------------------------------------------------------------------------- #

def test_api_srs_check_returns_correct_for_matching_meaning(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    r = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "meaning", "answer": "one",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["correct"] is True
    assert "one" in data["accepted_answers"]
    assert data["suggested_rating"] == "good"


def test_api_srs_check_tolerates_small_typo(client):
    """Tippfehler-Toleranz gilt erst ab 4 normalisierten Zeichen (siehe
    _match_quality()) - "Person" (id 449) ist dafür lang genug, "One" (id
    440) mit nur 3 Zeichen wäre zu kurz für Toleranz. Ein nur mit Toleranz
    akzeptierter Treffer schlägt „hard" statt „good" vor (ehrlicher)."""
    client.post("/api/srs/add", json={"subject_ids": [449], "sample": True})
    r = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "449", "item_type": "meaning", "answer": "Persen",
    })
    data = r.get_json()
    assert data["correct"] is True
    assert data["suggested_rating"] == "hard"


def test_api_srs_check_exact_match_suggests_good(client):
    """Ein exakter Treffer (ohne Tippfehler) schlägt weiterhin „good" vor -
    Abgrenzung zum Fuzzy-Treffer oben."""
    client.post("/api/srs/add", json={"subject_ids": [449], "sample": True})
    r = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "449", "item_type": "meaning", "answer": "person",
    })
    assert r.get_json()["suggested_rating"] == "good"


def test_api_srs_check_returns_incorrect_for_wrong_meaning(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    r = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "meaning", "answer": "banana",
    })
    data = r.get_json()
    assert data["correct"] is False
    assert data["suggested_rating"] == "again"


def test_api_srs_check_reading_uses_onyomi_and_kunyomi(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    r = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "reading", "answer": "いち",
    })
    assert r.get_json()["correct"] is True
    r2 = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "reading", "answer": "ひと",
    })
    assert r2.get_json()["correct"] is True  # kunyomi ebenfalls akzeptiert


def test_api_srs_check_kana_card_splits_semicolon_separated_synonyms(client, monkeypatch):
    """Regressionstest: eine Dictionary-/KI-Karte mit mehreren durch "; "
    getrennten Synonymen (z. B. "Kuchen; Torte; Biskuit; Backwerk") darf nicht
    als EINE Antwort verlangt werden - jedes einzelne Synonym muss für sich
    als richtig zählen (siehe _split_answer_synonyms())."""
    from shiori import dictionary as dic
    monkeypatch.setattr(dic, "_index_cache", {"けーき": {"kanji": None, "meaning": "Kuchen; Torte; Biskuit; Backwerk"}})
    created = client.post("/api/kanacards", json={"word": "けーき"}).get_json()
    client.post("/api/srs/add", json={"kana_ids": [created["id"]]})

    for word in ("Kuchen", "Torte", "Biskuit", "Backwerk"):
        r = client.post("/api/srs/check", json={
            "card_type": "kana", "card_id": created["id"], "item_type": "meaning", "answer": word,
        })
        assert r.get_json()["correct"] is True, f"{word!r} sollte als richtig gelten"

    r = client.post("/api/srs/check", json={
        "card_type": "kana", "card_id": created["id"], "item_type": "meaning",
        "answer": "Kuchen; Torte; Biskuit; Backwerk",
    })
    assert r.get_json()["correct"] is False  # die volle Aufzählung ist NICHT die erwartete Eingabe


def test_api_srs_check_returns_ungraded_for_custom_card(client):
    created = client.post("/api/customcards", json={"front_html": "<div>x</div>", "back_html": "<div>y</div>"}).get_json()
    client.post("/api/srs/add", json={"custom_ids": [created["id"]]})
    r = client.post("/api/srs/check", json={
        "card_type": "custom", "card_id": created["id"], "item_type": "front", "answer": "irrelevant",
    })
    assert r.get_json() == {"correct": None, "accepted_answers": [], "suggested_rating": None}


def test_api_srs_check_404_when_card_not_in_queue(client):
    r = client.post("/api/srs/check", json={
        "card_type": "wanikani", "card_id": "999999", "item_type": "meaning", "answer": "x",
    })
    assert r.status_code == 404


def test_api_srs_answer_updates_fsrs_state_and_advances_due_date(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    row = models.ReviewState.query.filter_by(
        user_id=client.test_user_id, card_id="440", item_type="meaning",
    ).first()
    original_due = row.due_at

    r = client.post("/api/srs/answer", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["reps"] == 1
    assert data["lapses"] == 0

    db.session.refresh(row)
    assert row.due_at > original_due
    assert row.reps == 1


def test_api_srs_answer_rejects_unknown_rating(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    r = client.post("/api/srs/answer", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "excellent",
    })
    assert r.status_code == 400


def test_api_srs_answer_404_when_card_not_in_queue(client):
    r = client.post("/api/srs/answer", json={
        "card_type": "wanikani", "card_id": "999999", "item_type": "meaning", "rating": "good",
    })
    assert r.status_code == 404


def test_api_srs_answer_isolated_between_target_languages(client):
    """Dieselbe (card_type, card_id, item_type) darf in einer ANDEREN
    Zielsprache nicht existieren/beeinflussbar sein, auch wenn zufällig
    dieselbe card_id verwendet wird."""
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    client.post("/api/settings/language", json={"active_target_lang": "es"})

    r = client.post("/api/srs/answer", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good",
    })
    assert r.status_code == 404  # in "es" wurde die Karte nie hinzugefügt


# --------------------------------------------------------------------------- #
# Vokabeltrainer (SRS, Fundament): Tageslimits (/api/srs/queue) + Dashboard
# (/api/srs/stats)
# --------------------------------------------------------------------------- #

def test_api_srs_answer_creates_review_log_entry(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    client.post("/api/srs/answer", json={
        "card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good",
    })
    log = models.ReviewLog.query.filter_by(user_id=client.test_user_id).first()
    assert log is not None
    assert log.rating == "good"
    assert log.was_new is True  # reps war 0 vor dieser Bewertung
    assert log.card_type == "wanikani" and log.card_id == "440"


def test_api_srs_answer_second_review_is_not_new(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    body = {"card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good"}
    client.post("/api/srs/answer", json=body)  # erste Bewertung -> was_new True
    client.post("/api/srs/answer", json=body)  # zweite -> was_new False

    logs = models.ReviewLog.query.filter_by(user_id=client.test_user_id).order_by(models.ReviewLog.id).all()
    assert [log.was_new for log in logs] == [True, False]


def test_api_srs_queue_respects_new_per_day_limit(client):
    client.post("/api/settings", json={"defaults": {"srs_new_per_day": 1}})
    client.post("/api/srs/add", json={"subject_ids": [440, 1], "sample": True})  # 3 neue Zeilen

    r = client.get("/api/srs/queue")
    data = r.get_json()
    assert data["due_total"] == 3  # tatsächlich fällig, unabhängig vom Limit
    assert len(data["items"]) == 1  # aber nur 1 neue Karte pro Tag erlaubt


def test_api_srs_queue_new_limit_does_not_affect_already_reviewed_cards(client):
    """Das "neue Karten"-Limit betrifft nur reps==0 - einmal beantwortete
    Karten (jetzt "Review"-Status) zählen gegen das Reviews-Limit, nicht
    gegen das Neue-Karten-Limit."""
    client.post("/api/settings", json={"defaults": {"srs_new_per_day": 0, "srs_reviews_per_day": 200}})
    client.post("/api/srs/add", json={"subject_ids": [1], "sample": True})  # 1 Zeile (Radical, nur meaning)
    row = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="1").first()
    row.reps = 1  # simuliert: schon einmal beantwortet
    db.session.commit()

    r = client.get("/api/srs/queue")
    data = r.get_json()
    assert len(data["items"]) == 1  # srs_new_per_day=0 blockiert nur NEUE Karten


def test_api_settings_rejects_non_numeric_daily_limit(client):
    """Regressionstest: ein ungültiger Tageslimit-Wert wurde früher blind in
    die Settings übernommen und crashte erst später beim Abruf der
    Review-Queue (api_srs_queue) mit einem 500er statt hier mit einem
    verständlichen 400er abgewiesen zu werden."""
    r = client.post("/api/settings", json={"defaults": {"srs_new_per_day": "viel"}})
    assert r.status_code == 400

    r = client.post("/api/settings", json={"defaults": {"srs_reviews_per_day": None}})
    assert r.status_code == 400


def test_api_srs_queue_survives_invalid_daily_limit_in_settings(client):
    """Auch wenn ein ungültiger Wert (z.B. durch direkten DB-Zugriff oder
    einen alten Datenstand) in den Settings landet, darf die Queue nicht
    mit einem 500er abstürzen, sondern soll auf den Default zurückfallen."""
    row = models.UserSettings.query.filter_by(user_id=client.test_user_id).first()
    row.defaults = {**(row.defaults or {}), "srs_new_per_day": "viel"}
    db.session.commit()

    r = client.get("/api/srs/queue")
    assert r.status_code == 200


def test_api_srs_queue_respects_reviews_per_day_limit(client, db_session):
    """`srs_reviews_per_day` deckelt Karten, die schon mindestens einmal
    beantwortet wurden (reps > 0) - neue Karten laufen über ihr eigenes
    Limit (`srs_new_per_day`, siehe Test oben)."""
    client.post("/api/settings", json={"defaults": {"srs_new_per_day": 200, "srs_reviews_per_day": 1}})
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})  # meaning + reading
    for row in models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="440").all():
        row.reps = 1
    db_session.session.commit()

    r = client.get("/api/srs/queue")
    assert len(r.get_json()["items"]) == 1


def test_api_srs_stats_counts_reviews_and_new_today(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    rows = models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="440").all()
    for row in rows:
        client.post("/api/srs/answer", json={
            "card_type": "wanikani", "card_id": "440", "item_type": row.item_type, "rating": "good",
        })

    r = client.get("/api/srs/stats")
    data = r.get_json()
    assert data["reviews_today"] == 2
    assert data["new_today"] == 2
    assert data["total_cards"] == 2


def test_api_srs_stats_retention_reflects_again_ratings(client):
    client.post("/api/srs/add", json={"subject_ids": [440, 1], "sample": True})
    client.post("/api/srs/answer", json={"card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good"})
    client.post("/api/srs/answer", json={"card_type": "wanikani", "card_id": "440", "item_type": "reading", "rating": "again"})
    client.post("/api/srs/answer", json={"card_type": "wanikani", "card_id": "1", "item_type": "meaning", "rating": "easy"})

    r = client.get("/api/srs/stats")
    data = r.get_json()
    # 2 von 3 NICHT "again" -> 66.7%
    assert data["retention_7d"] == 66.7


def test_api_srs_stats_retention_none_without_reviews(client):
    r = client.get("/api/srs/stats")
    assert r.get_json()["retention_7d"] is None


def test_api_srs_stats_by_stage_counts_new_and_reviewed_separately(client):
    client.post("/api/srs/add", json={"subject_ids": [1], "sample": True})  # bleibt "new"
    client.post("/api/srs/add", json={"custom_ids": [
        client.post("/api/customcards", json={"front_html": "<div>x</div>", "back_html": "<div>y</div>"}).get_json()["id"],
    ]})
    custom_id = models.CustomCard.query.filter_by(user_id=client.test_user_id).first().id
    client.post("/api/srs/answer", json={"card_type": "custom", "card_id": custom_id, "item_type": "front", "rating": "good"})

    r = client.get("/api/srs/stats")
    data = r.get_json()
    assert data["by_stage"]["new"] == 1  # das Radical wurde nie beantwortet
    assert data["by_stage"]["learning"] == 1  # Custom-Karte nach 1x "good" noch im Learning-Status
    assert data["total_cards"] == 2


def test_api_srs_stats_isolated_between_target_languages(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    client.post("/api/settings/language", json={"active_target_lang": "es"})
    r = client.get("/api/srs/stats")
    data = r.get_json()
    assert data["total_cards"] == 0
    assert data["reviews_today"] == 0


# --------------------------------------------------------------------------- #
# Streak + Aktivitäts-Heatmap (/api/srs/stats: streak_days/activity)
# --------------------------------------------------------------------------- #

def test_compute_streak_counts_consecutive_days_ending_today():
    from datetime import date

    from shiori import srs_api
    today = date(2026, 7, 21)
    days = {"2026-07-21", "2026-07-20", "2026-07-19", "2026-07-16"}  # Lücke am 17./18.
    assert srs_api._compute_streak(days, today) == 3


def test_compute_streak_not_broken_by_missing_today():
    """Heute (noch) nichts gelernt bricht den Streak nicht - der Tag ist noch
    nicht vorbei (Duolingo-/WaniKani-Semantik)."""
    from datetime import date

    from shiori import srs_api
    today = date(2026, 7, 21)
    days = {"2026-07-20", "2026-07-19"}
    assert srs_api._compute_streak(days, today) == 2


def test_compute_streak_zero_after_full_missed_day():
    from datetime import date

    from shiori import srs_api
    today = date(2026, 7, 21)
    days = {"2026-07-18", "2026-07-17"}  # vorgestern zuletzt gelernt
    assert srs_api._compute_streak(days, today) == 0


def test_api_srs_stats_includes_streak_and_activity(client):
    from datetime import datetime
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    client.post("/api/srs/answer", json={"card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good"})

    data = client.get("/api/srs/stats").get_json()
    assert data["streak_days"] == 1
    today = datetime.now(UTC).date().isoformat()
    assert data["activity"] == {today: 1}


def test_api_srs_stats_streak_spans_yesterday(client, db_session):
    from datetime import datetime, timedelta
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    client.post("/api/srs/answer", json={"card_type": "wanikani", "card_id": "440", "item_type": "meaning", "rating": "good"})
    # Einen Log-Eintrag künstlich auf gestern zurückdatieren.
    log = models.ReviewLog(
        user_id=client.test_user_id, target_lang="ja", card_type="wanikani",
        card_id="440", item_type="reading", rating="good", was_new=True,
        reviewed_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.session.add(log)
    db.session.commit()

    data = client.get("/api/srs/stats").get_json()
    assert data["streak_days"] == 2
    assert len(data["activity"]) == 2


# --------------------------------------------------------------------------- #
# SRS-Karten-Browser + Entfernen (/api/srs/cards, /api/srs/remove)
# --------------------------------------------------------------------------- #

def test_api_srs_cards_lists_grouped_by_card(client):
    # 440 = Vokabel -> zwei Prüfrichtungen (meaning + reading) = EINE Karte.
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    r = client.get("/api/srs/cards")
    data = r.get_json()
    assert data["total"] == 1
    card = data["cards"][0]
    assert card["card_type"] == "wanikani"
    assert card["card_id"] == "440"
    assert card["items"] == 2  # meaning + reading zusammengefasst
    assert card["due_now"] is True


def test_api_srs_remove_deletes_card_from_queue(client):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    assert models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="440").count() == 2

    r = client.post("/api/srs/remove", json={"card_type": "wanikani", "card_id": "440"})
    assert r.status_code == 200
    assert r.get_json()["removed"] == 2
    assert models.ReviewState.query.filter_by(user_id=client.test_user_id, card_id="440").count() == 0
    # Aus der Warteschlange verschwunden.
    assert client.get("/api/srs/queue").get_json()["due_total"] == 0


def test_api_srs_remove_unknown_card_returns_404(client):
    r = client.post("/api/srs/remove", json={"card_type": "wanikani", "card_id": "99999"})
    assert r.status_code == 404


def test_api_srs_remove_requires_fields(client):
    r = client.post("/api/srs/remove", json={"card_type": "wanikani"})
    assert r.status_code == 400


def test_api_srs_cards_isolated_between_users(client, db_session):
    client.post("/api/srs/add", json={"subject_ids": [440], "sample": True})
    other = webapp.app.test_client()
    other.post("/api/auth/signup", json={"email": "srsother@example.com", "password": "supersecret123"})
    assert other.get("/api/srs/cards").get_json()["total"] == 0
    # Fremdes Entfernen findet die Karte nicht.
    assert other.post("/api/srs/remove", json={"card_type": "wanikani", "card_id": "440"}).status_code == 404
    # Eigentümer hat die Karte weiterhin.
    assert client.get("/api/srs/cards").get_json()["total"] == 1


# --------------------------------------------------------------------------- #
# Statische Datei-Route – Path-Traversal-Härtung
# --------------------------------------------------------------------------- #

def test_static_files_serves_existing_file(client):
    r = client.get("/app.js")
    assert r.status_code == 200


def test_static_files_rejects_path_traversal(client):
    r = client.get("/../webapp.py")
    assert r.status_code == 404


def test_static_files_rejects_encoded_path_traversal(client):
    r = client.get("/%2e%2e/webapp.py")
    assert r.status_code == 404


def test_static_files_404_for_missing_file(client):
    r = client.get("/does-not-exist.xyz")
    assert r.status_code == 404


def test_vendor_route_serves_wanakana(client):
    r = client.get("/vendor/wanakana.min.js")
    assert r.status_code == 200


def test_pwa_manifest_served_with_correct_mimetype(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.content_type
    data = r.get_json(force=True)
    assert data["short_name"] == "Shiori"
    assert any(i["sizes"] == "512x512" for i in data["icons"])


def test_pwa_service_worker_and_icons_served(client):
    assert client.get("/sw.js").status_code == 200
    assert client.get("/icon-192.png").status_code == 200
    assert client.get("/icon-512.png").status_code == 200
    assert client.get("/apple-touch-icon.png").status_code == 200


def test_vendor_route_rejects_path_traversal(client):
    r = client.get("/vendor/../webapp.py")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Security-Header (auf jeder Antwort, siehe webapp._security_headers)
# --------------------------------------------------------------------------- #

def test_security_headers_present_on_static_response(client):
    r = client.get("/app.js")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_security_headers_present_on_api_response(client):
    r = client.get("/api/config")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_session_cookie_hardening_configured():
    assert webapp.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert webapp.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


# --------------------------------------------------------------------------- #
# API-Dokumentation (Swagger/OpenAPI, siehe flasgger)
# --------------------------------------------------------------------------- #

def test_swagger_ui_served(client):
    r = client.get("/api/docs/")
    assert r.status_code == 200
    assert b"swagger" in r.data.lower()


def test_openapi_spec_has_no_undocumented_routes(client):
    """Jede Route soll eine YAML-Docstring haben (siehe die einzelnen
    Endpunkte) - dieser Test verhindert, dass ein künftiger Endpunkt
    versehentlich ohne Doku bleibt."""
    spec = client.get("/apispec_1.json").get_json()
    undocumented = [
        f"{method.upper()} {path}"
        for path, methods in spec["paths"].items()
        for method, info in methods.items()
        if not info.get("summary") and not info.get("description")
    ]
    assert not undocumented, f"Undokumentierte Endpunkte: {undocumented}"
