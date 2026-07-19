"""Tests für dictionary.py (JMdict-Anbindung) – kein Live-Netzwerk, alles gemockt
oder gegen kleine, handgeschriebene Fixtures, die dem echten jmdict-simplified-
Schema entsprechen."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dictionary as dic  # noqa: E402


def _jmdict_fixture() -> dict:
    return {
        "words": [
            {
                "id": "1",
                "kanji": [{"text": "試合", "common": True, "tags": []}],
                "kana": [{"text": "しあい", "common": True, "tags": [], "appliesToKanji": ["*"]}],
                "sense": [
                    {
                        "partOfSpeech": [],
                        "gloss": [
                            {"lang": "eng", "text": "match", "gender": None, "type": None},
                            {"lang": "eng", "text": "game", "gender": None, "type": None},
                            {"lang": "ger", "text": "Spiel", "gender": None, "type": None},
                            {"lang": "ger", "text": "Wettkampf", "gender": None, "type": None},
                        ],
                    }
                ],
            },
            {
                # Kein Kanji – rein kana-basiertes Wort (z. B. eine Partikel-artige Form).
                "id": "2",
                "kanji": [],
                "kana": [{"text": "さあ", "common": True, "tags": [], "appliesToKanji": ["*"]}],
                "sense": [{"partOfSpeech": [], "gloss": [{"lang": "ger", "text": "nun", "gender": None, "type": None}]}],
            },
            {
                # Keine deutsche Bedeutung -> muss übersprungen werden.
                "id": "3",
                "kanji": [{"text": "無し", "common": False, "tags": []}],
                "kana": [{"text": "なし", "common": False, "tags": [], "appliesToKanji": ["*"]}],
                "sense": [{"partOfSpeech": [], "gloss": [{"lang": "eng", "text": "without", "gender": None, "type": None}]}],
            },
            {
                # Zweiter Eintrag mit derselben Lesung wie Wort 1 -> erster gewinnt.
                "id": "4",
                "kanji": [{"text": "仕合", "common": False, "tags": []}],
                "kana": [{"text": "しあい", "common": False, "tags": [], "appliesToKanji": ["*"]}],
                "sense": [{"partOfSpeech": [], "gloss": [{"lang": "ger", "text": "sollte ignoriert werden (Dublette)", "gender": None, "type": None}]}],
            },
            {
                # Viele Glosses -> auf MAX_GLOSSES gekappt.
                "id": "5",
                "kanji": [{"text": "大きい", "common": True, "tags": []}],
                "kana": [{"text": "おおきい", "common": True, "tags": [], "appliesToKanji": ["*"]}],
                "sense": [
                    {
                        "partOfSpeech": [],
                        "gloss": [
                            {"lang": "ger", "text": "groß", "gender": None, "type": None},
                            {"lang": "ger", "text": "riesig", "gender": None, "type": None},
                            {"lang": "ger", "text": "gewaltig", "gender": None, "type": None},
                            {"lang": "ger", "text": "gigantisch", "gender": None, "type": None},
                            {"lang": "ger", "text": "enorm", "gender": None, "type": None},
                            {"lang": "ger", "text": "immens", "gender": None, "type": None},
                        ],
                    }
                ],
            },
        ]
    }


# --------------------------------------------------------------------------- #
# build_reading_index
# --------------------------------------------------------------------------- #

def test_build_reading_index_maps_kana_to_kanji_and_meaning(tmp_path):
    p = tmp_path / "jmdict.json"
    p.write_text(json.dumps(_jmdict_fixture(), ensure_ascii=False), encoding="utf-8")
    index = dic.build_reading_index(p)
    assert index["しあい"] == {"kanji": "試合", "meaning": "Spiel; Wettkampf"}


def test_build_reading_index_handles_kana_only_word_without_kanji(tmp_path):
    p = tmp_path / "jmdict.json"
    p.write_text(json.dumps(_jmdict_fixture(), ensure_ascii=False), encoding="utf-8")
    index = dic.build_reading_index(p)
    assert index["さあ"] == {"kanji": None, "meaning": "nun"}


def test_build_reading_index_skips_words_without_german_gloss(tmp_path):
    p = tmp_path / "jmdict.json"
    p.write_text(json.dumps(_jmdict_fixture(), ensure_ascii=False), encoding="utf-8")
    index = dic.build_reading_index(p)
    assert "なし" not in index


def test_build_reading_index_first_occurrence_wins_for_duplicate_kana(tmp_path):
    p = tmp_path / "jmdict.json"
    p.write_text(json.dumps(_jmdict_fixture(), ensure_ascii=False), encoding="utf-8")
    index = dic.build_reading_index(p)
    assert index["しあい"]["kanji"] == "試合"  # nicht 仕合 (Wort 4)


def test_build_reading_index_limits_glosses_to_max(tmp_path):
    p = tmp_path / "jmdict.json"
    p.write_text(json.dumps(_jmdict_fixture(), ensure_ascii=False), encoding="utf-8")
    index = dic.build_reading_index(p)
    assert index["おおきい"]["meaning"] == "groß; riesig; gewaltig; gigantisch"


# --------------------------------------------------------------------------- #
# _find_asset / download_jmdict (gemockte HTTP-Session)
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, *, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self.ok = status_code < 400
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


class _FakeSession:
    def __init__(self, responses):
        self._responses = responses  # url -> _FakeResp
        self.calls = []
        self.post_calls = []

    def get(self, url, timeout=30, headers=None):
        self.calls.append(url)
        return self._responses.get(url, _FakeResp(status_code=404))

    def post(self, url, headers=None, data=None, timeout=30):
        self.post_calls.append({"url": url, "headers": headers, "data": data})
        return self._responses.get(url, _FakeResp(status_code=404))


def test_find_asset_picks_ger_json_zip_asset():
    release = {
        "assets": [
            {"name": "jmdict-examples-eng-3.6.1.json.zip", "browser_download_url": "https://x/examples.zip"},
            {"name": "jmdict-eng-3.6.1.json.zip", "browser_download_url": "https://x/eng.zip"},
            {"name": "jmdict-ger-3.6.1.json.zip", "browser_download_url": "https://x/ger.zip"},
            {"name": "jmnedict-all-3.6.1.json.zip", "browser_download_url": "https://x/names.zip"},
        ]
    }
    session = _FakeSession({dic._RELEASES_API: _FakeResp(json_data=release)})
    name, url = dic._find_asset(session)
    assert name == "jmdict-ger-3.6.1.json.zip"
    assert url == "https://x/ger.zip"


def test_find_asset_raises_when_no_matching_asset():
    session = _FakeSession({dic._RELEASES_API: _FakeResp(json_data={"assets": []})})
    with pytest.raises(dic.DictionaryError):
        dic._find_asset(session)


def test_find_asset_raises_on_http_error():
    session = _FakeSession({dic._RELEASES_API: _FakeResp(status_code=403)})
    with pytest.raises(dic.DictionaryError):
        dic._find_asset(session)


def test_download_jmdict_extracts_json_from_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(dic, "JMDICT_DIR", tmp_path / "jmdict")
    fixture_bytes = json.dumps(_jmdict_fixture(), ensure_ascii=False).encode("utf-8")
    zip_bytes_path = tmp_path / "src.zip"
    with zipfile.ZipFile(zip_bytes_path, "w") as zf:
        zf.writestr("jmdict-ger-3.6.1.json", fixture_bytes)
    zip_bytes = zip_bytes_path.read_bytes()

    release = {"assets": [{"name": "jmdict-ger-3.6.1.json.zip", "browser_download_url": "https://x/ger.zip"}]}
    session = _FakeSession({
        dic._RELEASES_API: _FakeResp(json_data=release),
        "https://x/ger.zip": _FakeResp(content=zip_bytes),
    })

    json_path = dic.download_jmdict(session=session)
    assert json_path.is_file()
    assert json.loads(json_path.read_text(encoding="utf-8")) == _jmdict_fixture()
    assert (tmp_path / "jmdict" / "jmdict-ger-3.6.1.json.zip").is_file()


def test_download_jmdict_skips_download_if_zip_already_cached(tmp_path, monkeypatch):
    jdir = tmp_path / "jmdict"
    jdir.mkdir()
    fixture_bytes = json.dumps(_jmdict_fixture(), ensure_ascii=False).encode("utf-8")
    zip_path = jdir / "jmdict-ger-3.6.1.json.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("jmdict-ger-3.6.1.json", fixture_bytes)
    monkeypatch.setattr(dic, "JMDICT_DIR", jdir)

    release = {"assets": [{"name": "jmdict-ger-3.6.1.json.zip", "browser_download_url": "https://x/ger.zip"}]}
    session = _FakeSession({dic._RELEASES_API: _FakeResp(json_data=release)})  # kein Eintrag für die Zip-URL!

    json_path = dic.download_jmdict(session=session)
    assert json_path.is_file()
    assert "https://x/ger.zip" not in session.calls  # nicht erneut heruntergeladen


# --------------------------------------------------------------------------- #
# get_index / lookup_reading
# --------------------------------------------------------------------------- #

def test_get_index_uses_cache_file_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(dic, "JMDICT_INDEX_FILE", tmp_path / "jmdict_index.json")
    monkeypatch.setattr(dic, "_index_cache", None)
    (tmp_path / "jmdict_index.json").write_text(
        json.dumps({"しあい": {"kanji": "試合", "meaning": "match"}}), encoding="utf-8"
    )
    index = dic.get_index(session=_FakeSession({}))  # würde bei echtem Zugriff sofort scheitern
    assert index["しあい"]["kanji"] == "試合"


def test_lookup_reading_returns_none_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(dic, "JMDICT_INDEX_FILE", tmp_path / "jmdict_index.json")
    monkeypatch.setattr(dic, "_index_cache", {"しあい": {"kanji": "試合", "meaning": "match"}})
    assert dic.lookup_reading("ぜんぜんちがう") is None


def test_lookup_reading_returns_none_on_dictionary_error(tmp_path, monkeypatch):
    monkeypatch.setattr(dic, "JMDICT_INDEX_FILE", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(dic, "_index_cache", None)

    def _boom(*, session=None):
        raise dic.DictionaryError("kein Netz")

    monkeypatch.setattr(dic, "_load_or_build_index", _boom)
    assert dic.lookup_reading("しあい") is None


# --------------------------------------------------------------------------- #
# translate_sentence (DeepL) – gemockte Session, kein Live-Netzwerk (DeepL ist
# in dieser Sandbox per Egress-Policy geblockt, siehe Session-Notizen)
# --------------------------------------------------------------------------- #

def test_translate_sentence_returns_translation():
    session = _FakeSession({
        dic._DEEPL_FREE_URL: _FakeResp(json_data={"translations": [{"text": "Das Spiel hat begonnen."}]}),
    })
    result = dic.translate_sentence("しあいがはじまりました。", "dummy-key:fx", session=session)
    assert result == "Das Spiel hat begonnen."


def test_translate_sentence_uses_free_endpoint_for_fx_key():
    session = _FakeSession({dic._DEEPL_FREE_URL: _FakeResp(json_data={"translations": [{"text": "x"}]})})
    dic.translate_sentence("text", "abc:fx", session=session)
    assert session.post_calls[0]["url"] == dic._DEEPL_FREE_URL


def test_translate_sentence_uses_pro_endpoint_for_non_fx_key():
    session = _FakeSession({dic._DEEPL_PRO_URL: _FakeResp(json_data={"translations": [{"text": "x"}]})})
    dic.translate_sentence("text", "abc-no-suffix", session=session)
    assert session.post_calls[0]["url"] == dic._DEEPL_PRO_URL


def test_translate_sentence_sends_auth_header_and_payload():
    session = _FakeSession({dic._DEEPL_FREE_URL: _FakeResp(json_data={"translations": [{"text": "x"}]})})
    dic.translate_sentence("しあい", "mykey:fx", target_lang="DE", session=session)
    call = session.post_calls[0]
    assert call["headers"]["Authorization"] == "DeepL-Auth-Key mykey:fx"
    assert call["data"] == {"text": "しあい", "target_lang": "DE", "source_lang": "JA"}


def test_translate_sentence_returns_none_without_text_or_key():
    session = _FakeSession({})
    assert dic.translate_sentence("", "key:fx", session=session) is None
    assert dic.translate_sentence("text", "", session=session) is None
    assert session.post_calls == []


def test_translate_sentence_returns_none_on_http_error():
    session = _FakeSession({dic._DEEPL_FREE_URL: _FakeResp(status_code=403)})
    assert dic.translate_sentence("text", "bad-key:fx", session=session) is None


def test_translate_sentence_returns_none_on_malformed_response():
    session = _FakeSession({dic._DEEPL_FREE_URL: _FakeResp(json_data={"unexpected": "shape"})})
    assert dic.translate_sentence("text", "key:fx", session=session) is None


def test_translate_sentence_returns_none_on_network_error():
    class _ExplodingSession:
        def post(self, *a, **k):
            raise requests.ConnectionError("boom")

    assert dic.translate_sentence("text", "key:fx", session=_ExplodingSession()) is None
