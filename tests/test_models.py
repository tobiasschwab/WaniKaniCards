"""Tests für models.py – SQLAlchemy-Schema des Multi-User-Fundaments.

Nutzt die `db_session`-Fixture aus conftest.py (frische Tabellen pro Test,
temporäre SQLite-Datei statt der echten Entwicklungs-DB).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy.exc import IntegrityError

from models import CustomCard, Job, KanaCard, KnownWord, User, UserSettings


def test_user_password_hash_roundtrip(db_session):
    user = User(email="a@example.com")
    user.set_password("supersecret123")
    db_session.session.add(user)
    db_session.session.commit()

    assert user.password_hash != "supersecret123"
    assert user.check_password("supersecret123") is True
    assert user.check_password("wrong") is False


def test_user_email_must_be_unique(db_session):
    u1 = User(email="dup@example.com")
    u1.set_password("x")
    db_session.session.add(u1)
    db_session.session.commit()

    u2 = User(email="dup@example.com")
    u2.set_password("y")
    db_session.session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.session.commit()


def test_user_settings_one_to_one_and_cascade_delete(db_session):
    user = User(email="b@example.com")
    user.set_password("x")
    db_session.session.add(user)
    db_session.session.flush()
    settings = UserSettings(user_id=user.id, gemini_model="gemini-flash-latest", target_lang="DE")
    db_session.session.add(settings)
    db_session.session.commit()

    assert user.settings.target_lang == "DE"

    db_session.session.delete(user)
    db_session.session.commit()
    assert UserSettings.query.filter_by(user_id=user.id).first() is None


def test_known_word_unique_per_user(db_session):
    user = User(email="c@example.com")
    user.set_password("x")
    db_session.session.add(user)
    db_session.session.flush()

    db_session.session.add(KnownWord(user_id=user.id, word_id="440", characters="一", meaning="one"))
    db_session.session.commit()

    db_session.session.add(KnownWord(user_id=user.id, word_id="440", characters="一", meaning="one"))
    with pytest.raises(IntegrityError):
        db_session.session.commit()


def test_known_word_same_word_id_allowed_for_different_users(db_session):
    u1 = User(email="d1@example.com"); u1.set_password("x")
    u2 = User(email="d2@example.com"); u2.set_password("x")
    db_session.session.add_all([u1, u2])
    db_session.session.flush()

    db_session.session.add(KnownWord(user_id=u1.id, word_id="440"))
    db_session.session.add(KnownWord(user_id=u2.id, word_id="440"))
    db_session.session.commit()  # darf NICHT scheitern - unterschiedliche Nutzer

    assert KnownWord.query.filter_by(word_id="440").count() == 2


def test_custom_card_gets_generated_id(db_session):
    user = User(email="e@example.com"); user.set_password("x")
    db_session.session.add(user)
    db_session.session.flush()

    card = CustomCard(user_id=user.id, front_html="<b>Front</b>", back_html="Back", tags=["Lv 5"])
    db_session.session.add(card)
    db_session.session.commit()

    assert card.id  # automatisch vergeben (default=_new_id)
    assert card.tags == ["Lv 5"]


def test_kana_card_requires_explicit_id(db_session):
    """KanaCard nutzt KEIN default=_new_id - die ID ist ein stabiler Hash des
    Worts (kc.kana_card_id()), damit derselbe Text-Fund dieselbe Karte trifft."""
    user = User(email="f@example.com"); user.set_password("x")
    db_session.session.add(user)
    db_session.session.flush()

    card = KanaCard(id="kana_abcdef", user_id=user.id, word="しあい", meaning="match")
    db_session.session.add(card)
    db_session.session.commit()

    assert db_session.session.get(KanaCard, "kana_abcdef").word == "しあい"


def test_job_stores_params_as_json(db_session):
    user = User(email="g@example.com"); user.set_password("x")
    db_session.session.add(user)
    db_session.session.flush()

    job = Job(user_id=user.id, title="5 Karten", status="queued", params={"subject_ids": [1, 2, 3]})
    db_session.session.add(job)
    db_session.session.commit()

    fetched = db_session.session.get(Job, job.id)
    assert fetched.params == {"subject_ids": [1, 2, 3]}
    assert fetched.status == "queued"
