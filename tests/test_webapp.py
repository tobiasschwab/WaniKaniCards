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


# --------------------------------------------------------------------------- #
# Flask-Endpunkte: /api/known, /api/text-annotate (Sample-Modus, keine Netzwerk-
# Abhängigkeit)
# --------------------------------------------------------------------------- #

def test_api_mark_and_unmark_known(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "KNOWN_FILE", tmp_path / "known.json")
    client = webapp.app.test_client()

    r = client.post("/api/known/42")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "id": 42, "known": True}
    assert webapp.load_known() == {42}

    r = client.delete("/api/known/42")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "id": 42, "known": False}
    assert webapp.load_known() == set()


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
    assert word2["manually_known"] is True
    assert word2["known"] is True
    assert second["stats"]["percent"] == 100.0
