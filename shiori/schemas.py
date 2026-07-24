#!/usr/bin/env python3
"""schemas.py – Pydantic-Request-Body-Validierung für Auth und SRS.

Ersetzt die bisherigen manuellen `body.get()`/`isinstance()`-Prüfungen in
`auth.py`/`srs_api.py` durch deklarative Schemas – zentraler, einheitlich
fehlerbehandelt (siehe `parse_body()`) und mit Typ-Hints für IDE/mypy statt
`dict[str, Any]` an jeder Aufrufstelle.

Bewusst NICHT für `/api/settings`: dessen Semantik ist "unbekannte/ungültige
Felder still ignorieren, Rest der Einstellungen unverändert lassen" (Teil-
Update, siehe `webapp.api_post_settings()`) – das Fail-Fast-Modell von
Pydantic (ein ungültiges Feld lässt die GANZE Validierung scheitern) passt
auf dieses Muster nicht, ohne die bestehende Ignorier-Semantik zu brechen.
Auth/SRS dagegen sind reine "alles oder Fehler"-Endpunkte – dafür ist
Pydantic der richtige Fit.
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8

CardType = Literal["wanikani", "custom", "kana"]
ItemType = Literal["meaning", "reading", "front"]


class ValidationFailed(Exception):
    """Wird von `parse_body()` geworfen, trägt eine bereits nutzerlesbare
    deutsche Fehlermeldung (erste Pydantic-Fehlermeldung, sonst reicht die
    generische Meldung für die 400-Antwort)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


T = TypeVar("T", bound=BaseModel)


def parse_body(model: type[T], body: dict[str, Any]) -> T:
    """`body` (bereits per `request.get_json(silent=True) or {}` geholt)
    gegen `model` validieren. Wirft `ValidationFailed` mit der ersten
    Fehlermeldung statt der vollen Pydantic-`ValidationError` – die
    Aufrufer wollen nur EINE Meldung in `jsonify({"error": ...}), 400`."""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        first = exc.errors()[0]
        message = str(first["ctx"]["error"]) if first.get("type") == "value_error" else first["msg"]
        raise ValidationFailed(message) from exc


class SignupBody(BaseModel):
    email: str
    password: str
    native_lang: str = "de"
    active_target_lang: str = "ja"

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Ungültige E-Mail-Adresse.")
        return v

    @field_validator("password")
    @classmethod
    def _check_password_len(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LEN:
            raise ValueError(f"Passwort muss mindestens {MIN_PASSWORD_LEN} Zeichen haben.")
        return v

    @field_validator("native_lang", "active_target_lang", mode="before")
    @classmethod
    def _normalize_lang(cls, v: Any) -> str:
        return str(v or "").strip().lower()[:10]


class LoginBody(BaseModel):
    email: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, v: Any) -> str:
        return str(v or "").strip().lower()

    @field_validator("password", mode="before")
    @classmethod
    def _stringify_password(cls, v: Any) -> str:
        return str(v or "")


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LEN)


class DeleteAccountBody(BaseModel):
    password: str


class SrsAddBody(BaseModel):
    subject_ids: list[int] = []
    custom_ids: list[str] = []
    kana_ids: list[str] = []
    sample: bool = False

    @field_validator("subject_ids", "custom_ids", "kana_ids", mode="before")
    @classmethod
    def _default_empty(cls, v: Any) -> Any:
        return v if v is not None else []


class SrsCheckBody(BaseModel):
    card_type: CardType
    card_id: str
    item_type: ItemType
    answer: str = ""


class SrsAnswerBody(BaseModel):
    card_type: CardType
    card_id: str
    item_type: ItemType
    rating: Literal["again", "hard", "good", "easy"]


class SrsRemoveBody(BaseModel):
    card_type: CardType
    card_id: str
