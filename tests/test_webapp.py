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
