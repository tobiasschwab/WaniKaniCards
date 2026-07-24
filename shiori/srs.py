#!/usr/bin/env python3
"""srs.py – FSRS-Wrapper für den Vokabeltrainer (Fundament, siehe README-
Roadmap "SRS-Vokabeltrainer").

Die eigentliche Scheduling-Mathematik (wann ist eine Karte als Nächstes
fällig, wie verändert eine Bewertung Stabilität/Schwierigkeit) kommt
vollständig aus der `fsrs`-Bibliothek (Free Spaced Repetition Scheduler,
der Nachfolger von Ankis klassischem SM-2-Algorithmus, seit Anki 23.10
Standard) – dieses Modul übersetzt nur zwischen unserer Datenbank-Zeile
(`models.ReviewState.fsrs_state`, ein reines JSON-Dict) und den
`fsrs.Card`-Objekten der Bibliothek, plus eine kleine Rating-Namens-
Übersetzung ("again"/"hard"/"good"/"easy" statt des Enums direkt), damit
der Rest der App die Bibliothek nicht direkt importieren muss.

Bewusst EIN gemeinsamer `Scheduler` mit den Standard-Parametern der
Bibliothek (Default `desired_retention=0.9`, wie bei Anki) - keine
Personalisierung pro Nutzer in dieser Phase."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import fsrs

if TYPE_CHECKING:
    from . import models

_SCHEDULER = fsrs.Scheduler()

_RATINGS: dict[str, fsrs.Rating] = {
    "again": fsrs.Rating.Again,
    "hard": fsrs.Rating.Hard,
    "good": fsrs.Rating.Good,
    "easy": fsrs.Rating.Easy,
}


class SrsError(Exception):
    """Verständlicher Fehler ohne Stacktrace (z. B. unbekannter Rating-Name)."""


def _now() -> datetime:
    return datetime.now(UTC)


def new_review_state() -> dict[str, Any]:
    """Frischer Lernstand für eine neu hinzugefügte Karte/Prüfrichtung –
    sofort fällig (`due_at` = jetzt), wie eine "neue" Karte bei Anki/
    WaniKani. `reps`/`lapses` starten bei 0."""
    card = fsrs.Card()
    return {
        "fsrs_state": card.to_dict(),
        "due_at": card.due,
        "last_reviewed_at": None,
        "reps": 0,
        "lapses": 0,
    }


def review(state: dict[str, Any], rating: str, *, review_datetime: datetime | None = None) -> dict[str, Any]:
    """Eine Bewertung ("again"/"hard"/"good"/"easy") verarbeiten und den
    aktualisierten Lernstand zurückgeben (gleiche Form wie
    `new_review_state()` - direkt auf die DB-Spalten von
    `models.ReviewState` abbildbar).

    `lapses` wird hochgezählt, wenn eine Karte, die bereits im Review-Status
    war (nicht mehr "Learning"), mit "again" bewertet wird - ein echtes
    "Vergessen" nach vorherigem Erfolg, nicht nur ein normaler Lernschritt."""
    try:
        fsrs_rating = _RATINGS[rating]
    except KeyError:
        raise SrsError(f"Unbekannte Bewertung: {rating!r} (erwartet: again/hard/good/easy)") from None

    card = fsrs.Card.from_dict(state["fsrs_state"])
    was_review_state = card.state == fsrs.State.Review

    updated_card, _log = _SCHEDULER.review_card(
        card, fsrs_rating, review_datetime=review_datetime or _now(),
    )

    lapses = state.get("lapses", 0)
    if fsrs_rating == fsrs.Rating.Again and was_review_state:
        lapses += 1

    return {
        "fsrs_state": updated_card.to_dict(),
        "due_at": updated_card.due,
        "last_reviewed_at": updated_card.last_review,
        "reps": state.get("reps", 0) + 1,
        "lapses": lapses,
    }


def state_from_row(row: models.ReviewState) -> dict[str, Any]:
    """`ReviewState`-Zeile in die Dict-Form bringen, die `review()` erwartet."""
    return {
        "fsrs_state": row.fsrs_state,
        "due_at": row.due_at,
        "last_reviewed_at": row.last_reviewed_at,
        "reps": row.reps,
        "lapses": row.lapses,
    }


def apply_state_to_row(row: models.ReviewState, state: dict[str, Any]) -> None:
    """Umgekehrte Richtung: Ergebnis von `new_review_state()`/`review()` auf
    eine (neue oder bestehende) `ReviewState`-Zeile übertragen. Committen
    bleibt Aufgabe des Aufrufers (konsistent mit dem restlichen Projekt,
    siehe z. B. `webapp.write_job()`)."""
    row.fsrs_state = state["fsrs_state"]
    row.due_at = state["due_at"]
    row.last_reviewed_at = state["last_reviewed_at"]
    row.reps = state["reps"]
    row.lapses = state["lapses"]
