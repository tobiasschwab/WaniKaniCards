#!/usr/bin/env python3
"""models.py – SQLAlchemy-Datenmodell für den Multi-User-Betrieb.

Phase 1 des SaaS-Umbaus (siehe README-Abschnitt "Multi-User-Architektur"):
ersetzt schrittweise die bisherigen JSON-Dateien pro Installation
(settings.json, known.json/known_meta.json, customcards/*.json,
kanacards/*.json, jobs/*.json) durch pro-Nutzer-Zeilen in einer relationalen
Datenbank. Diese Datei definiert nur das Schema + Auth-Grundlagen (User);
die bestehenden webapp.py-Endpunkte laufen vorerst WEITER auf den JSON-
Dateien (Migration der Endpunkte selbst ist Phase 2).

Bewusst `db.JSON` (portabler SQLAlchemy-Typ) statt `postgresql.JSONB`: läuft
damit unverändert auch gegen SQLite (Tests, lokale Entwicklung ohne
Postgres-Service), während echtes Postgres in Produktion trotzdem einen
JSON/JSONB-kompatiblen Spaltentyp anlegt – kein separater Postgres-Dialekt-
Import nötig.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    """Kurze, URL-sichere ID für Job-/Karten-Primärschlüssel (analog zu den
    bisherigen `uuid.uuid4().hex[:12]`-IDs in webapp.py)."""
    return uuid.uuid4().hex[:12]


class User(UserMixin, db.Model):
    """Ein Nutzerkonto – E-Mail/Passwort statt WaniKani-Token als Login-
    Credential (der WaniKani-Token ist ein Nutzungs-Detail, das erst NACH
    dem Login in den Einstellungen hinterlegt wird, siehe UserSettings)."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    # Muttersprache (ISO 639-1, z. B. "de"/"en") – Basis für Übersetzungen/
    # Bedeutungen UND (siehe web/i18n/) die Oberflächensprache. Getrennt von
    # `UserSettings.active_target_lang` (der gerade gelernten Sprache):
    # Muttersprache ändert sich praktisch nie, die Zielsprache wird bewusst
    # häufig gewechselt (siehe README "Multi-Language-Architektur").
    native_lang = db.Column(db.String(10), nullable=False, default="de")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    settings = db.relationship(
        "UserSettings", back_populates="user", uselist=False,
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:  # pragma: no cover - nur fürs Debugging
        return f"<User {self.email!r}>"


class UserSettings(db.Model):
    """Pro-Nutzer-Pendant zu settings.json.

    Secrets (`*_enc`-Spalten) liegen verschlüsselt (siehe crypto.py) statt im
    Klartext wie in der alten Datei – Verschlüsselung/Entschlüsselung passiert
    bewusst NICHT hier im Modell, sondern in der Endpunkt-Schicht (Phase 2),
    damit dieses Modul ohne einen gesetzten WKCARDS_SECRET_KEY importierbar
    bleibt (z. B. für Migrationen, die nur das Schema anlegen)."""

    __tablename__ = "user_settings"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    deepl_key_enc = db.Column(db.Text, nullable=True)
    gemini_key_enc = db.Column(db.Text, nullable=True)
    gemini_model = db.Column(db.String(100), nullable=False, default="gemini-flash-latest")
    target_lang = db.Column(db.String(10), nullable=False, default="DE")
    # Aktuell gewählte LERNsprache (ISO 639-1, z. B. "ja"/"en"/"es") - der
    # Nutzer hat genau eine aktive Zielsprache zur Zeit, kann aber jederzeit
    # wechseln (siehe README "Multi-Language-Architektur"). Nicht zu
    # verwechseln mit `target_lang` oben (DeepL-Ausgabesprachcode) oder
    # `User.native_lang` (Muttersprache). Bestimmt u. a., welches
    # `languages.LanguagePack` aktiv ist und filtert KnownWord/CustomCard/
    # KanaCard/Job nach `target_lang`.
    active_target_lang = db.Column(db.String(10), nullable=False, default="ja")
    # Level/Format/Layout/Paper/Duplex/CutMarks/Hole – dieselbe Struktur wie
    # bisher settings["defaults"].
    defaults = db.Column(db.JSON, nullable=False, default=dict)

    user = db.relationship("User", back_populates="settings")


class UserLanguageSecrets(db.Model):
    """Pro-Nutzer-UND-Zielsprache-Secrets – aktuell nur der WaniKani-Token +
    Username, weil WaniKani ausschließlich für Japanisch relevant ist (siehe
    `languages.japanese.JapanesePack`). Bewusst eine EIGENE Tabelle statt
    Spalten auf `UserSettings`: Letztere ist pro Nutzer global (ein Gemini-/
    DeepL-Key gilt für alle Zielsprachen), während der WaniKani-Token nur für
    genau die Zielsprache "ja" einen Sinn ergibt. Künftige sprachspezifische
    Secrets (z. B. ein anderer Content-Provider für eine andere Sprache)
    landen als weitere Spalten hier, nicht auf `UserSettings`."""

    __tablename__ = "user_language_secrets"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    target_lang = db.Column(db.String(10), primary_key=True)
    wanikani_token_enc = db.Column(db.Text, nullable=True)
    wanikani_username = db.Column(db.String(255), nullable=False, default="")


class KnownWord(db.Model):
    """Pro-Nutzer-Pendant zu known.json/known_meta.json – ein Wort, das
    manuell als bekannt markiert wurde, ohne dass dafür zwingend eine Karte
    existiert (siehe webapp.load_known/load_known_meta)."""

    __tablename__ = "known_words"
    __table_args__ = (
        db.UniqueConstraint("user_id", "target_lang", "word_id", name="uq_known_word_per_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Zu welcher Zielsprache dieses Wort gehört (siehe README "Multi-Language-
    # Architektur") - Bestandsdaten wurden per Migration auf "ja" befüllt.
    target_lang = db.Column(db.String(10), nullable=False, default="ja", index=True)
    word_id = db.Column(db.String(64), nullable=False)
    characters = db.Column(db.String(255), nullable=False, default="")
    meaning = db.Column(db.String(255), nullable=False, default="")
    kind = db.Column(db.String(64), nullable=False, default="")
    level = db.Column(db.Integer, nullable=True)
    source = db.Column(db.String(32), nullable=False, default="manual")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)


class CustomCard(db.Model):
    """Pro-Nutzer-Pendant zu customcards/*.json (Frei-erstellen-Modus)."""

    __tablename__ = "custom_cards"

    id = db.Column(db.String(32), primary_key=True, default=_new_id)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_lang = db.Column(db.String(10), nullable=False, default="ja", index=True)
    front_html = db.Column(db.Text, nullable=False, default="")
    back_html = db.Column(db.Text, nullable=False, default="")
    tags = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    # Bei jedem Speichern aktualisiert (Card-Editor kann bestehende Karten
    # überschreiben) - treibt die "zuletzt bearbeitet zuerst"-Sortierung im
    # Verlauf, analog zum bisherigen "updated_at" in customcards/*.json.
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class KanaCard(db.Model):
    """Pro-Nutzer-Pendant zu kanacards/*.json (Dictionary-/KI-Karten aus dem
    Text-Modus, siehe kc.KanaCard/dictionary.py).

    Zusammengesetzter Primärschlüssel `(user_id, id)` statt `id` allein: die
    ID ist ein reiner Wort-Hash (`kc.kana_card_id()`), unabhängig vom Nutzer –
    zwei verschiedene Nutzer, die dasselbe Wort im Text-Modus als Karte
    anlegen, bekämen sonst denselben Primärschlüssel und würden sich
    gegenseitig die Karte überschreiben."""

    __tablename__ = "kana_cards"
    __table_args__ = (db.PrimaryKeyConstraint("user_id", "target_lang", "id"),)

    # Bewusst KEIN default=_new_id: die ID ist ein stabiler Hash des Worts
    # (kc.kana_card_id()), damit derselbe Text-Fund für DENSELBEN Nutzer immer
    # dieselbe Karte referenziert statt Duplikate anzulegen - das Erzeugen der
    # ID bleibt Aufgabe der Endpunkt-Schicht, nicht des Modells.
    id = db.Column(db.String(64), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Teil des Primärschlüssels (nicht nur ein Filter-Feld): derselbe
    # Wort-Hash könnte über verschiedene Zielsprachen hinweg kollidieren.
    target_lang = db.Column(db.String(10), nullable=False, default="ja")
    word = db.Column(db.String(255), nullable=False, default="")
    kanji_hint = db.Column(db.String(255), nullable=True)
    reading = db.Column(db.String(255), nullable=True)
    meaning = db.Column(db.String(255), nullable=False, default="")
    meaning_extra = db.Column(db.String(255), nullable=True)
    # Name historisch aus der Japanisch-only-Zeit ("ja"), wird seit dem
    # Multi-Language-Umbau generisch als "Beispielsatz in der Zielsprache"
    # genutzt (auch für Nicht-Japanisch-Sprachen) - Umbenennen der Spalte
    # selbst hätte nur kosmetischen Wert, aber Migrationsaufwand.
    sentence_ja = db.Column(db.Text, nullable=True)
    sentence_translation = db.Column(db.Text, nullable=True)
    sentence_audio_url = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(32), nullable=False, default="dictionary")
    tags = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SubjectFieldOverride(db.Model):
    """Pro-Nutzer, persistente Feld-Überschreibungen für ein WaniKani-Subject
    (Kanji/Vokabel/Radical) – Grundlage für den „Felder manuell anpassen"-
    Dialog (bisher nur ephemer im `field_overrides`-Request-Parameter, siehe
    `kc._apply_field_overrides()`), jetzt zusätzlich dauerhaft gespeichert,
    damit Änderungen (z. B. während des Übens im Vokabeltrainer) auch nach
    einem Reload sichtbar bleiben und in künftige PDF-/Anki-Exports desselben
    Nutzers einfließen (siehe `services._build_mixed_deck()`). Gilt nur für
    den eigenen Account, nie global.

    `fields` hält dieselbe Struktur wie das bisherige `field_overrides[id]`
    (`{feldname: neuer_wert, …}`), Gültigkeit der Feldnamen wird erst beim
    Anwenden geprüft (`kc._apply_field_overrides()`), nicht hier im Modell."""

    __tablename__ = "subject_field_overrides"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    subject_id = db.Column(db.Integer, primary_key=True)
    fields = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class Job(db.Model):
    """Pro-Nutzer-Pendant zu jobs/*.json (Render-Verlauf, siehe
    webapp.write_job/read_job)."""

    __tablename__ = "jobs"

    id = db.Column(db.String(32), primary_key=True, default=_new_id)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_lang = db.Column(db.String(10), nullable=False, default="ja", index=True)
    title = db.Column(db.String(255), nullable=False, default="")
    status = db.Column(db.String(32), nullable=False, default="queued")
    params = db.Column(db.JSON, nullable=False, default=dict)
    filename = db.Column(db.String(255), nullable=True)
    n_cards = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)


class ReviewState(db.Model):
    """Ein SRS-Lernstand (FSRS, siehe srs.py) für EINE Prüfrichtung EINER
    Karte – Vokabeltrainer-Fundament, unabhängig vom PDF-/Anki-Export
    (siehe README-Roadmap "SRS-Vokabeltrainer"). Statt einer eigenen
    Karten-Tabelle zeigt jede Zeile per `(card_type, card_id)` auf eine der
    drei bestehenden, heterogenen Kartenquellen (WaniKani-Subject-ID,
    CustomCard.id, KanaCard.id) – keine Datenduplizierung.

    `item_type` bildet WaniKanis eigenes Verhalten nach: ein Kanji/eine
    Vokabel bekommt ZWEI unabhängige Zeilen ("meaning" + "reading"), eine
    Custom-/Dictionary-Karte nur eine ("front" bzw. "meaning") – jede
    Prüfrichtung hat ihren eigenen Fortschritt, nicht nur die Karte als
    Ganzes.

    `fsrs_state` ist die serialisierte `fsrs.Card` (siehe `srs.py`,
    `Card.to_dict()`/`from_dict()`) – die eigentliche Scheduling-Mathematik
    kommt vollständig aus der `fsrs`-Bibliothek, nicht selbst nachgebaut.
    `due_at` ist zusätzlich eine EIGENE, indizierte Spalte (redundant zum
    `due`-Feld in `fsrs_state`), damit die Warteschlangen-Abfrage
    ("welche Karten sind fällig") nicht jede Zeile deserialisieren muss."""

    __tablename__ = "review_states"
    __table_args__ = (
        db.PrimaryKeyConstraint("user_id", "target_lang", "card_type", "card_id", "item_type"),
        db.Index("ix_review_states_due", "user_id", "target_lang", "due_at"),
    )

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    target_lang = db.Column(db.String(10), nullable=False)
    card_type = db.Column(db.String(16), nullable=False)  # "wanikani" | "custom" | "kana"
    card_id = db.Column(db.String(64), nullable=False)
    item_type = db.Column(db.String(16), nullable=False)  # "meaning" | "reading" | "front"
    fsrs_state = db.Column(db.JSON, nullable=False, default=dict)
    due_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    last_reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Eigene Zähler (die fsrs-Bibliothek selbst hält das nicht dauerhaft im
    # Card-Objekt) - fürs künftige Statistik-Dashboard (Phase 4), schon
    # jetzt mitgeführt, da beim Review ohnehin bekannt.
    reps = db.Column(db.Integer, nullable=False, default=0)
    lapses = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)


class ReviewLog(db.Model):
    """Ein Eintrag pro tatsächlich abgeschickter Bewertung (`/api/srs/answer`)
    – Grundlage fürs Statistik-Dashboard (Tageslimits, Retention, siehe
    README "Vokabeltrainer"). Getrennt von `ReviewState` (das nur den
    AKTUELLEN FSRS-Zustand hält, keine Historie): ohne dieses Log ließe sich
    weder "wie viele Reviews heute schon gemacht" noch eine ehrliche
    Retention-Rate (Anteil NICHT "again" bewerteter Reviews) berechnen –
    beides wäre nur grob aus `ReviewState.reps`/`lapses` schätzbar."""

    __tablename__ = "review_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    target_lang = db.Column(db.String(10), nullable=False)
    card_type = db.Column(db.String(16), nullable=False)
    card_id = db.Column(db.String(64), nullable=False)
    item_type = db.Column(db.String(16), nullable=False)
    rating = db.Column(db.String(16), nullable=False)  # "again" | "hard" | "good" | "easy"
    # War die Karte VOR dieser Bewertung noch nie beantwortet (reps==0)?
    # Treibt den "neue Karten/Tag"-Teil des Tageslimits getrennt vom
    # "Reviews/Tag"-Teil (siehe api_srs_queue()).
    was_new = db.Column(db.Boolean, nullable=False, default=False)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, index=True)
