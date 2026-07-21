"""Tests für srs.py – FSRS-Wrapper des Vokabeltrainer-Fundaments (keine
DB, keine Flask-App nötig: reine Algorithmus-/Serialisierungslogik)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fsrs
import srs


def test_new_review_state_is_due_immediately():
    state = srs.new_review_state()
    now = datetime.now(timezone.utc)
    assert state["due_at"] <= now + timedelta(seconds=1)
    assert state["reps"] == 0
    assert state["lapses"] == 0
    assert state["last_reviewed_at"] is None
    assert isinstance(state["fsrs_state"], dict)


def test_review_good_pushes_due_date_into_future_and_increments_reps():
    state = srs.new_review_state()
    now = datetime.now(timezone.utc)
    updated = srs.review(state, "good", review_datetime=now)
    assert updated["due_at"] > now
    assert updated["reps"] == 1
    assert updated["last_reviewed_at"] == now


def test_review_rejects_unknown_rating():
    state = srs.new_review_state()
    with pytest.raises(srs.SrsError):
        srs.review(state, "excellent")


def test_review_again_on_fresh_card_does_not_count_as_lapse():
    """Ein "again" auf einer brandneuen Karte ist ein normaler Lernschritt,
    kein "Vergessen" nach vorherigem Erfolg - `lapses` darf nicht hochgezählt
    werden (siehe srs.review()-Docstring)."""
    state = srs.new_review_state()
    updated = srs.review(state, "again")
    assert updated["lapses"] == 0


def test_review_again_after_reaching_review_state_counts_as_lapse():
    """Regressionstest fürs eigentliche FSRS-"Vergessen": erst mehrfach
    "good" bewerten, bis die Karte den Review-Status erreicht (nicht mehr
    Learning), dann "again" - das MUSS einen Lapse zählen."""
    state = srs.new_review_state()
    now = datetime.now(timezone.utc)
    for _ in range(5):
        state = srs.review(state, "good", review_datetime=now)
        now = state["due_at"] + timedelta(seconds=1)
    card = fsrs.Card.from_dict(state["fsrs_state"])
    assert card.state == fsrs.State.Review  # Testannahme: nach 5x "good" im Review-Status

    lapsed = srs.review(state, "again", review_datetime=now)
    assert lapsed["lapses"] == 1
    assert lapsed["reps"] == state["reps"] + 1


def test_review_hard_and_easy_produce_different_intervals():
    """Grobe Sanity-Check, dass die vier Bewertungen tatsächlich
    unterschiedliches Scheduling auslösen (keine Fake-/No-Op-Anbindung)."""
    now = datetime.now(timezone.utc)
    hard_due = srs.review(srs.new_review_state(), "hard", review_datetime=now)["due_at"]
    easy_due = srs.review(srs.new_review_state(), "easy", review_datetime=now)["due_at"]
    assert easy_due > hard_due


def test_state_roundtrip_via_row_helpers():
    """`state_from_row()`/`apply_state_to_row()` müssen verlustfrei
    zusammenpassen (Grundlage für die spätere DB-Persistenz)."""

    class _FakeRow:
        pass

    row = _FakeRow()
    initial = srs.new_review_state()
    srs.apply_state_to_row(row, initial)

    assert row.fsrs_state == initial["fsrs_state"]
    assert row.due_at == initial["due_at"]
    assert row.reps == 0
    assert row.lapses == 0

    reconstructed = srs.state_from_row(row)
    updated = srs.review(reconstructed, "good")
    srs.apply_state_to_row(row, updated)
    assert row.reps == 1
    assert row.due_at == updated["due_at"]
