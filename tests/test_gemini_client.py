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


def _batch_body(items: list[tuple[str, list, str, str]]) -> dict:
    """Baut eine Fake-Gemini-Antwort im Batch-Schema: `items` sind
    (satz, tokens, grammar_notes, translation)-Tupel."""
    sentences = [
        {"sentence": s, "tokens": tokens, "grammar_notes": notes, "translation": trans}
        for s, tokens, notes, trans in items
    ]
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps({"sentences": sentences}, ensure_ascii=False)}]}}
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

    def get(self, url, params=None, timeout=30):
        self.calls.append({"url": url, "params": params})
        if self._error:
            raise requests.ConnectionError("boom")
        key = (params or {}).get("key")
        return self._responses.get(key, _FakeResp(status_code=404))


# --------------------------------------------------------------------------- #
# analyze_sentence (dünner Wrapper um analyze_sentences)
# --------------------------------------------------------------------------- #

def test_analyze_sentence_returns_parsed_result(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    tokens = [
        {"surface": "しあい", "dictionary_form": "しあい", "function": "Subjekt"},
        {"surface": "が", "dictionary_form": "が", "function": "Partikel"},
    ]
    body = _batch_body([("しあいが", tokens, "Notiz", "Übersetzung")])
    session = _FakeSession({"dummy": _FakeResp(json_data=body)})
    result = gc.analyze_sentence("しあいが", "dummy", session=session, use_cache=False)
    assert result is not None
    assert result["tokens"] == tokens
    assert result["grammar_notes"] == "Notiz"
    assert result["translation"] == "Übersetzung"


def test_analyze_sentence_sends_key_and_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    session = _FakeSession({"mykey": _FakeResp(json_data=_batch_body([("テスト", [], "", "")]))})
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


def test_analyze_sentence_returns_none_when_missing_from_response(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    # Antwort enthält "sentences", aber nicht den angefragten Satz.
    body = _batch_body([("ein anderer Satz", [{"surface": "x", "dictionary_form": "x", "function": "y"}], "", "")])
    session = _FakeSession({"key": _FakeResp(json_data=body)})
    assert gc.analyze_sentence("テスト", "key", session=session, use_cache=False) is None


def test_analyze_sentence_uses_cache_without_second_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    tokens = [{"surface": "テスト", "dictionary_form": "テスト", "function": "Nomen"}]
    session = _FakeSession({"key": _FakeResp(json_data=_batch_body([("テスト", tokens, "", "")]))})
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
            tokens = [{"surface": "x", "dictionary_form": "x", "function": "y"}]
            return _FakeResp(json_data=_batch_body([("テスト", tokens, "", "")]))

    result = gc.analyze_sentence("テスト", "key", session=_FlakySession(), use_cache=False)
    assert result is not None
    assert calls["n"] == 3


# --------------------------------------------------------------------------- #
# analyze_sentences (Batch: mehrere Sätze in einem Request)
# --------------------------------------------------------------------------- #

def test_analyze_sentences_sends_single_request_for_multiple_sentences(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    items = [
        ("大きい山です。", [{"surface": "大きい", "dictionary_form": "大きい", "function": "Adjektiv"}], "N1", "T1"),
        ("小さい猫です。", [{"surface": "小さい", "dictionary_form": "小さい", "function": "Adjektiv"}], "N2", "T2"),
    ]
    session = _FakeSession({"key": _FakeResp(json_data=_batch_body(items))})
    results = gc.analyze_sentences(["大きい山です。", "小さい猫です。"], "key", session=session, use_cache=False)
    assert len(session.calls) == 1  # EIN Request für beide Sätze
    assert results["大きい山です。"]["grammar_notes"] == "N1"
    assert results["小さい猫です。"]["translation"] == "T2"


def test_analyze_sentences_deduplicates_repeated_sentences(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    items = [("テスト", [{"surface": "テスト", "dictionary_form": "テスト", "function": "Nomen"}], "", "")]
    session = _FakeSession({"key": _FakeResp(json_data=_batch_body(items))})
    results = gc.analyze_sentences(["テスト", "テスト", "テスト"], "key", session=session, use_cache=False)
    assert len(session.calls) == 1
    call_text = session.calls[0]["json"]["contents"][0]["parts"][0]["text"]
    assert call_text.count("テスト") == 1  # nur einmal im Prompt gelistet
    assert results["テスト"] is not None


def test_analyze_sentences_marks_missing_sentence_as_none(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    # Antwort enthält nur einen der zwei angefragten Sätze.
    items = [("大きい山です。", [{"surface": "x", "dictionary_form": "x", "function": "y"}], "", "")]
    session = _FakeSession({"key": _FakeResp(json_data=_batch_body(items))})
    results = gc.analyze_sentences(["大きい山です。", "小さい猫です。"], "key", session=session, use_cache=False)
    assert results["大きい山です。"] is not None
    assert results["小さい猫です。"] is None  # fehlt in der Antwort -> Fallback auf Janome


def test_analyze_sentences_uses_per_sentence_cache_and_only_fetches_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    cached_tokens = [{"surface": "既存", "dictionary_form": "既存", "function": "Nomen"}]
    gc._write_cache("既存の文。", "gemini-flash-latest:Japanisch", {"tokens": cached_tokens, "grammar_notes": "", "translation": ""})

    items = [("新しい文。", [{"surface": "新", "dictionary_form": "新しい", "function": "Adjektiv"}], "", "")]
    session = _FakeSession({"key": _FakeResp(json_data=_batch_body(items))})
    results = gc.analyze_sentences(["既存の文。", "新しい文。"], "key", session=session, use_cache=True)

    assert len(session.calls) == 1
    call_text = session.calls[0]["json"]["contents"][0]["parts"][0]["text"]
    assert "既存の文。" not in call_text  # bereits gecacht -> nicht erneut angefragt
    assert "新しい文。" in call_text
    assert results["既存の文。"]["tokens"] == cached_tokens
    assert results["新しい文。"] is not None


def test_analyze_sentences_returns_empty_dict_for_empty_input():
    session = _FakeSession({})
    assert gc.analyze_sentences([], "key", session=session, use_cache=False) == {}
    assert session.calls == []


def test_analyze_sentences_returns_none_for_all_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    results = gc.analyze_sentences(["a", "b"], "", use_cache=False)
    assert results == {"a": None, "b": None}


def test_analyze_sentences_chunks_large_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    monkeypatch.setattr(gc, "_BATCH_CHUNK_SIZE", 2)
    sentences = ["文1", "文2", "文3", "文4", "文5"]

    class _CountingSession:
        def __init__(self):
            self.calls = []

        def post(self, url, params=None, json=None, timeout=30):
            self.calls.append(json)
            text = json["contents"][0]["parts"][0]["text"]
            items = [(s, [{"surface": s, "dictionary_form": s, "function": "x"}], "", "") for s in sentences if s in text]
            return _FakeResp(json_data=_batch_body(items))

    session = _CountingSession()
    results = gc.analyze_sentences(sentences, "key", session=session, use_cache=False)
    assert len(session.calls) == 3  # 5 Sätze / Chunkgröße 2 -> 3 Requests
    assert all(results[s] is not None for s in sentences)


# --------------------------------------------------------------------------- #
# _server_retry_delay / Backoff
# --------------------------------------------------------------------------- #

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
            tokens = [{"surface": "x", "dictionary_form": "x", "function": "y"}]
            return _FakeResp(json_data=_batch_body([("テスト", tokens, "", "")]))

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


def test_analyze_sentence_retries_once_after_read_timeout_then_succeeds(tmp_path, monkeypatch):
    # Regressionstest: ein einzelner ReadTimeout (z. B. bei einem langsamen
    # Batch) darf nicht sofort endgültig aufgeben - ein zweiter Versuch
    # schlägt bei Gemini oft durch.
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    monkeypatch.setattr(gc.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    class _TimesOutOnce:
        def post(self, url, params=None, json=None, timeout=30):
            calls["n"] += 1
            if calls["n"] < 2:
                raise requests.ReadTimeout("timed out")
            tokens = [{"surface": "x", "dictionary_form": "x", "function": "y"}]
            return _FakeResp(json_data=_batch_body([("テスト", tokens, "", "")]))

    result = gc.analyze_sentence("テスト", "key", session=_TimesOutOnce(), use_cache=False)
    assert result is not None
    assert calls["n"] == 2


def test_analyze_sentence_gives_up_after_second_read_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    monkeypatch.setattr(gc.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    class _AlwaysTimesOut:
        def post(self, url, params=None, json=None, timeout=30):
            calls["n"] += 1
            raise requests.ReadTimeout("timed out")

    result = gc.analyze_sentence("テスト", "key", session=_AlwaysTimesOut(), use_cache=False)
    assert result is None
    assert calls["n"] == 2  # ein Versuch + genau ein Retry, dann endgültig aufgeben


def test_batch_read_timeout_scales_with_sentence_count():
    assert gc._batch_read_timeout(1) == (10, 68.0)
    assert gc._batch_read_timeout(19) == (10, 212.0)
    # gedeckelt, damit ein Request nie unbegrenzt lange auf Antwort wartet
    assert gc._batch_read_timeout(100) == (10, 280.0)


def test_analyze_sentences_passes_scaled_timeout_to_session(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "gemini")
    seen_timeouts = []

    class _RecordingSession:
        def post(self, url, params=None, json=None, timeout=30):
            seen_timeouts.append(timeout)
            tokens = [{"surface": "x", "dictionary_form": "x", "function": "y"}]
            return _FakeResp(json_data=_batch_body([("テスト", tokens, "", "")]))

    gc.analyze_sentences(["テスト"], "key", session=_RecordingSession(), use_cache=False)
    assert seen_timeouts == [gc._batch_read_timeout(1)]


# --------------------------------------------------------------------------- #
# list_models
# --------------------------------------------------------------------------- #

def _models_body(names_and_methods: list[tuple[str, list[str]]]) -> dict:
    return {"models": [{"name": f"models/{n}", "supportedGenerationMethods": methods} for n, methods in names_and_methods]}


def test_list_models_returns_gemini_text_models_supporting_generate_content():
    body = _models_body([
        ("gemini-flash-latest", ["generateContent"]),
        ("gemini-pro-latest", ["generateContent"]),
        ("gemini-2.5-flash-image", ["generateContent"]),  # ausgeschlossen (Bild-Modell)
        ("gemini-embedding-001", ["embedContent"]),  # kein generateContent
        ("gemma-4-26b-a4b-it", ["generateContent"]),  # kein "gemini-"
    ])
    session = _FakeSession({"key": _FakeResp(json_data=body)})
    models = gc.list_models("key", session=session)
    assert models == ["gemini-flash-latest", "gemini-pro-latest"]


def test_list_models_returns_none_without_key():
    assert gc.list_models("", session=_FakeSession({})) is None


def test_list_models_returns_none_on_network_error():
    assert gc.list_models("key", session=_FakeSession(error=True)) is None


def test_list_models_returns_none_on_http_error():
    session = _FakeSession({"key": _FakeResp(status_code=403)})
    assert gc.list_models("key", session=session) is None


# --------------------------------------------------------------------------- #
# synthesize_speech (Text-to-Speech, KI-Modus: Original-Satz vorlesen)
# --------------------------------------------------------------------------- #

def _tts_body(pcm: bytes, *, mime="audio/L16;rate=24000") -> dict:
    import base64
    b64 = base64.b64encode(pcm).decode("ascii")
    return {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": mime, "data": b64}}]}}
        ]
    }


def test_synthesize_speech_wraps_pcm_into_playable_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_TTS_CACHE_DIR", tmp_path / "gemini_tts")
    pcm = b"\x01\x02" * 10
    session = _FakeSession({"key": _FakeResp(json_data=_tts_body(pcm))})
    wav = gc.synthesize_speech("大きい山です。", "key", session=session, use_cache=False)
    assert wav is not None
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav.endswith(pcm)


def test_synthesize_speech_returns_none_without_text_or_key():
    assert gc.synthesize_speech("", "key", session=_FakeSession({})) is None
    assert gc.synthesize_speech("x", "", session=_FakeSession({})) is None


def test_synthesize_speech_returns_none_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_TTS_CACHE_DIR", tmp_path / "gemini_tts")
    assert gc.synthesize_speech("テスト", "key", session=_FakeSession(error=True), use_cache=False) is None


def test_synthesize_speech_returns_none_on_malformed_response(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_TTS_CACHE_DIR", tmp_path / "gemini_tts")
    session = _FakeSession({"key": _FakeResp(json_data={"candidates": []})})
    assert gc.synthesize_speech("テスト", "key", session=session, use_cache=False) is None


def test_synthesize_speech_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_TTS_CACHE_DIR", tmp_path / "gemini_tts")
    pcm = b"\x03\x04" * 5
    session = _FakeSession({"key": _FakeResp(json_data=_tts_body(pcm))})
    first = gc.synthesize_speech("同じ文。", "key", session=session, use_cache=True)
    assert len(session.calls) == 1
    second = gc.synthesize_speech("同じ文。", "key", session=session, use_cache=True)
    assert len(session.calls) == 1  # kein zweiter Request nötig
    assert first == second


# --------------------------------------------------------------------------- #
# transcribe_image (OCR für PDF-Seiten ohne Textlayer / hochgeladene Bilder)
# --------------------------------------------------------------------------- #

def _ocr_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_transcribe_image_returns_text(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_OCR_CACHE_DIR", tmp_path / "gemini_ocr")
    session = _FakeSession({"key": _FakeResp(json_data=_ocr_body("大きい山です。"))})
    text = gc.transcribe_image(b"\x89PNG...", "key", session=session, use_cache=False)
    assert text == "大きい山です。"


def test_transcribe_image_sends_inline_image_data(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_OCR_CACHE_DIR", tmp_path / "gemini_ocr")
    session = _FakeSession({"key": _FakeResp(json_data=_ocr_body("x"))})
    gc.transcribe_image(b"rawbytes", "key", mime_type="image/jpeg", session=session, use_cache=False)
    sent = session.calls[0]["json"]
    part = sent["contents"][0]["parts"][1]
    assert part["inlineData"]["mimeType"] == "image/jpeg"
    import base64
    assert base64.b64decode(part["inlineData"]["data"]) == b"rawbytes"


def test_transcribe_image_returns_none_without_image_or_key():
    assert gc.transcribe_image(b"", "key", session=_FakeSession({})) is None
    assert gc.transcribe_image(b"x", "", session=_FakeSession({})) is None


def test_transcribe_image_returns_none_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_OCR_CACHE_DIR", tmp_path / "gemini_ocr")
    assert gc.transcribe_image(b"x", "key", session=_FakeSession(error=True), use_cache=False) is None


def test_transcribe_image_returns_none_on_malformed_response(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_OCR_CACHE_DIR", tmp_path / "gemini_ocr")
    session = _FakeSession({"key": _FakeResp(json_data={"candidates": []})})
    assert gc.transcribe_image(b"x", "key", session=session, use_cache=False) is None


def test_transcribe_image_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "_OCR_CACHE_DIR", tmp_path / "gemini_ocr")
    session = _FakeSession({"key": _FakeResp(json_data=_ocr_body("同じ画像。"))})
    first = gc.transcribe_image(b"sameimage", "key", session=session, use_cache=True)
    assert len(session.calls) == 1
    second = gc.transcribe_image(b"sameimage", "key", session=session, use_cache=True)
    assert len(session.calls) == 1  # kein zweiter Request nötig
    assert first == second == "同じ画像。"


# --------------------------------------------------------------------------- #
# generate_image (Bildkarten-Feature: Clipart-Bild per Gemini)
# --------------------------------------------------------------------------- #

def _image_gen_body(image_b64: str, mime_type: str = "image/png") -> dict:
    return {
        "candidates": [
            {"content": {"parts": [
                {"text": "hier ist dein Bild"},
                {"inlineData": {"mimeType": mime_type, "data": image_b64}},
            ]}}
        ]
    }


def test_generate_image_returns_bytes_and_mime_type():
    import base64
    b64 = base64.b64encode(b"fake-png-bytes").decode("ascii")
    session = _FakeSession({"key": _FakeResp(json_data=_image_gen_body(b64, "image/png"))})
    result = gc.generate_image("家", "Haus", "key", session=session)
    assert result == (b"fake-png-bytes", "image/png")


def test_generate_image_sends_word_and_meaning_in_prompt():
    import base64
    b64 = base64.b64encode(b"x").decode("ascii")
    session = _FakeSession({"key": _FakeResp(json_data=_image_gen_body(b64))})
    gc.generate_image("家", "Haus", "key", session=session)
    sent = session.calls[0]["json"]
    prompt = sent["contents"][0]["parts"][0]["text"]
    assert "家" in prompt and "Haus" in prompt
    assert sent["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]


def test_generate_image_returns_none_without_word_or_key():
    assert gc.generate_image("", "Haus", "key", session=_FakeSession({})) is None
    assert gc.generate_image("家", "Haus", "", session=_FakeSession({})) is None


def test_generate_image_returns_none_on_network_error():
    assert gc.generate_image("家", "Haus", "key", session=_FakeSession(error=True)) is None


def test_generate_image_returns_none_on_malformed_response():
    session = _FakeSession({"key": _FakeResp(json_data={"candidates": []})})
    assert gc.generate_image("家", "Haus", "key", session=session) is None


def test_generate_image_returns_none_when_response_has_no_image_part():
    session = _FakeSession({"key": _FakeResp(json_data={
        "candidates": [{"content": {"parts": [{"text": "kein Bild, sorry"}]}}]
    })})
    assert gc.generate_image("家", "Haus", "key", session=session) is None


def test_generate_image_is_not_cached_across_calls():
    """Anders als transcribe_image/synthesize_speech: jeder Aufruf muss
    tatsächlich einen neuen Request auslösen ("Neu generieren" im Frontend)."""
    import base64
    b64 = base64.b64encode(b"x").decode("ascii")
    session = _FakeSession({"key": _FakeResp(json_data=_image_gen_body(b64))})
    gc.generate_image("家", "Haus", "key", session=session)
    gc.generate_image("家", "Haus", "key", session=session)
    assert len(session.calls) == 2
