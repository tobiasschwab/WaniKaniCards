"""Tests für schemas.py – Pydantic-Request-Body-Validierung (Auth/SRS)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shiori import schemas


def test_signup_body_normalizes_email_and_langs():
    data = schemas.parse_body(schemas.SignupBody, {
        "email": " Test@Example.COM ", "password": "supersecret123",
        "native_lang": "EN", "active_target_lang": "ES",
    })
    assert data.email == "test@example.com"
    assert data.native_lang == "en"
    assert data.active_target_lang == "es"


def test_signup_body_defaults_langs_when_missing():
    data = schemas.parse_body(schemas.SignupBody, {"email": "a@b.de", "password": "supersecret123"})
    assert data.native_lang == "de"
    assert data.active_target_lang == "ja"


def test_signup_body_rejects_invalid_email():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SignupBody, {"email": "not-an-email", "password": "supersecret123"})


def test_signup_body_rejects_short_password():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SignupBody, {"email": "a@b.de", "password": "short"})


def test_signup_body_rejects_missing_fields():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SignupBody, {})


def test_change_password_body_rejects_short_new_password():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.ChangePasswordBody, {"current_password": "x", "new_password": "short"})


def test_srs_add_body_defaults_to_empty_lists():
    data = schemas.parse_body(schemas.SrsAddBody, {})
    assert data.subject_ids == []
    assert data.custom_ids == []
    assert data.kana_ids == []
    assert data.sample is False


def test_srs_add_body_rejects_non_integer_subject_id():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SrsAddBody, {"subject_ids": ["not-an-int"]})


def test_srs_check_body_rejects_unknown_card_type():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SrsCheckBody, {
            "card_type": "bogus", "card_id": "1", "item_type": "meaning", "answer": "x",
        })


def test_srs_answer_body_rejects_unknown_rating():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SrsAnswerBody, {
            "card_type": "wanikani", "card_id": "1", "item_type": "meaning", "rating": "excellent",
        })


def test_srs_remove_body_requires_card_id():
    with pytest.raises(schemas.ValidationFailed):
        schemas.parse_body(schemas.SrsRemoveBody, {"card_type": "wanikani"})
