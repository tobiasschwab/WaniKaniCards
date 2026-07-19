"""Tests für gemini_client.py – kein Live-Netzwerk, alles gemockt."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gemini_client as gc  # noqa: E402


class _FakeResp:
    def __init__(self, *, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        return self._json


def _gemini_body(tokens, grammar_notes="…", translation_de="…") -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps({
                "tokens": tokens, "grammar_notes": grammar_notes, "translation_de": translation_de,
            }, ensure_ascii=False)}]}}
        ]
    }


class _FakeSession:
    def __init__(self, responses=None, *, error=False):
        self._responses = responses or {}
        self._error = error
        self.calls = []

    def post(self, url, params=None, json=None, timeout=30):
        self.calls.append({"url": url, "params": params, "json": json})
        if self._error:
            raise requests.ConnectionError("boom")
        key = (params or {}).get("key")
        return self._responses.get(key, _FakeResp(status_code=404))


def test_analyze_sentence_returns_parsed_result(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    tokens = [
        {"surface": "しあい", "dictionary_form": "しあい", "function": "Subjekt"},
        {"surface": "が", "dictionary_form": "が", "function": "Partikel"},
    ]
    session = _FakeSession({"dummy": _FakeResp(json_data=_gemini_body(tokens, "Notiz", "Übersetzung"))})
    result = gc.analyze_sentence("しあいが", "dummy", session=session, use_cache=False)
    assert result is not None
    assert result["tokens"] == tokens
    assert result["grammar_notes"] == "Notiz"
    assert result["translation_de"] == "Übersetzung"


def test_analyze_sentence_sends_key_and_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    session = _FakeSession({"mykey": _FakeResp(json_data=_gemini_body([]))})
    gc.analyze_sentence("テスト", "mykey", session=session, use_cache=False)
    call = session.calls[0]
    assert call["params"]["key"] == "mykey"
    assert call["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "テスト" in call["json"]["contents"][0]["parts"][0]["text"]


def test_analyze_sentence_returns_none_without_text_or_key():
    session = _FakeSession({})
    assert gc.analyze_sentence("", "key", session=session, use_cache=False) is None
    assert gc.analyze_sentence("text", "", session=session, use_cache=False) is None
    assert session.calls == []


def test_analyze_sentence_returns_none_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    session = _FakeSession(error=True)
    assert gc.analyze_sentence("テスト", "key", session=session, use_cache=False) is None


def test_analyze_sentence_returns_none_on_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    session = _FakeSession({"key": _FakeResp(status_code=403)})
    assert gc.analyze_sentence("テスト", "key", session=session, use_cache=False) is None


def test_analyze_sentence_returns_none_on_malformed_json_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    bad = _FakeResp(json_data={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
    session = _FakeSession({"key": bad})
    assert gc.analyze_sentence("テスト", "key", session=session, use_cache=False) is None


def test_analyze_sentence_returns_none_on_missing_tokens_field(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    body = _FakeResp(json_data={
        "candidates": [{"content": {"parts": [{"text": json.dumps({"grammar_notes": "x", "translation_de": "y"})}]}}]
    })
    session = _FakeSession({"key": body})
    assert gc.analyze_sentence("テスト", "key", session=session, use_cache=False) is None


def test_analyze_sentence_uses_cache_without_second_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    tokens = [{"surface": "テスト", "dictionary_form": "テスト", "function": "Nomen"}]
    session = _FakeSession({"key": _FakeResp(json_data=_gemini_body(tokens))})
    first = gc.analyze_sentence("テスト", "key", session=session, use_cache=True)
    assert first["tokens"] == tokens
    assert len(session.calls) == 1

    second = gc.analyze_sentence("テスト", "key", session=session, use_cache=True)
    assert second["tokens"] == tokens
    assert len(session.calls) == 1  # kein zweiter Request, aus dem Cache gelesen


def test_analyze_sentence_backoff_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    monkeypatch.setattr(gc.time, "sleep", lambda *_a, **_k: None)

    calls = {"n": 0}

    class _FlakySession:
        def post(self, url, params=None, json=None, timeout=30):
            calls["n"] += 1
            if calls["n"] < 3:
                return _FakeResp(status_code=429)
            return _FakeResp(json_data=_gemini_body([{"surface": "x", "dictionary_form": "x", "function": "y"}]))

    result = gc.analyze_sentence("テスト", "key", session=_FlakySession(), use_cache=False)
    assert result is not None
    assert calls["n"] == 3


def test_server_retry_delay_reads_retry_after_header():
    resp = _FakeResp(status_code=429, headers={"Retry-After": "35"})
    assert gc._server_retry_delay(resp) == 35.0


def test_server_retry_delay_reads_retry_info_detail():
    resp = _FakeResp(status_code=429, json_data={
        "error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41.5s"}]}
    })
    assert gc._server_retry_delay(resp) == 41.5


def test_server_retry_delay_returns_none_without_hints():
    resp = _FakeResp(status_code=429, json_data={"error": {"message": "quota exceeded"}})
    assert gc._server_retry_delay(resp) is None


def test_analyze_sentence_honors_server_retry_delay(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    sleeps = []
    monkeypatch.setattr(gc.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    class _FlakySession:
        def post(self, url, params=None, json=None, timeout=30):
            calls["n"] += 1
            if calls["n"] < 2:
                return _FakeResp(status_code=429, headers={"Retry-After": "12"})
            return _FakeResp(json_data=_gemini_body([{"surface": "x", "dictionary_form": "x", "function": "y"}]))

    result = gc.analyze_sentence("テスト", "key", session=_FlakySession(), use_cache=False)
    assert result is not None
    assert sleeps == [12.0]  # server-empfohlene Wartezeit statt der geratenen 2s


def test_analyze_sentence_gives_up_after_max_total_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    monkeypatch.setattr(gc.time, "sleep", lambda *_a, **_k: None)

    class _AlwaysRateLimited:
        def post(self, url, params=None, json=None, timeout=30):
            return _FakeResp(status_code=429, headers={"Retry-After": "9999"})

    result = gc.analyze_sentence("テスト", "key", session=_AlwaysRateLimited(), use_cache=False)
    assert result is None  # gibt irgendwann auf statt einen Satz ewig zu blockieren
