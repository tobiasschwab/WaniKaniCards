"""multi-language architecture: native_lang, active_target_lang, target_lang scoping

Revision ID: c7691d3fd577
Revises: edcdc3b0dc70
Create Date: 2026-07-21 09:00:00.000000

Führt das Sprachprofil (Muttersprache + eine aktive Zielsprache, siehe README
"Multi-Language-Architektur") ein und scopet die bisherigen Japanisch-only-
Tabellen (known_words/custom_cards/kana_cards/jobs) nach `target_lang`. Der
WaniKani-Token wandert von `user_settings` (pro Nutzer global) in die neue
Tabelle `user_language_secrets` (pro Nutzer UND Zielsprache), weil er
ausschließlich für die Zielsprache "ja" einen Sinn ergibt.

Kein Projekt mit Produktivdaten bislang (Pre-Launch) - Backfill auf "ja"
trotzdem vorsichtshalber vorhanden, falls doch schon Testdaten existieren.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7691d3fd577'
down_revision: Union[str, Sequence[str], None] = 'edcdc3b0dc70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Hinweis zu den `server_default`-Werten unten: bewusst NICHT anschließend
    per `alter_column(server_default=None)` wieder entfernt (wie in der
    Vorgänger-Migration) - bei SQLite löst `add_column(server_default=X)` +
    `alter_column(server_default=None)` im selben Batch einen Recreate aus,
    dessen INSERT/SELECT die neue Spalte auslässt und bei vorhandenen Zeilen
    mit einer NOT-NULL-Verletzung crasht (live nachgestellt). Der verbleibende
    DB-seitige Default ist harmlos - SQLAlchemy setzt beim Anlegen neuer Zeilen
    ohnehin immer explizit den Python-seitigen Modell-Default.
    """
    bind = op.get_bind()

    # --- users: Muttersprache ------------------------------------------- #
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('native_lang', sa.String(10), nullable=False,
                                       server_default='de'))

    # --- user_settings: aktive Zielsprache + WaniKani-Token auslagern ---- #
    with op.batch_alter_table('user_settings') as batch_op:
        batch_op.add_column(sa.Column('active_target_lang', sa.String(10), nullable=False,
                                       server_default='ja'))

    op.create_table(
        'user_language_secrets',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('target_lang', sa.String(10), primary_key=True),
        sa.Column('wanikani_token_enc', sa.Text(), nullable=True),
        sa.Column('wanikani_username', sa.String(255), nullable=False, server_default=''),
    )

    # Bestehende WaniKani-Tokens/Usernamen 1:1 als target_lang="ja" übernehmen.
    bind.execute(sa.text(
        "INSERT INTO user_language_secrets (user_id, target_lang, wanikani_token_enc, wanikani_username) "
        "SELECT user_id, 'ja', wanikani_token_enc, username FROM user_settings "
        "WHERE wanikani_token_enc IS NOT NULL OR username != ''"
    ))

    with op.batch_alter_table('user_settings') as batch_op:
        batch_op.drop_column('username')
        batch_op.drop_column('wanikani_token_enc')

    # --- known_words: target_lang + zusammengesetzter Unique-Constraint - #
    with op.batch_alter_table('known_words', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('target_lang', sa.String(10), nullable=False,
                                       server_default='ja'))
        batch_op.drop_constraint('uq_known_word_per_user', type_='unique')
        batch_op.create_unique_constraint(
            'uq_known_word_per_user', ['user_id', 'target_lang', 'word_id'],
        )
        batch_op.create_index('ix_known_words_target_lang', ['target_lang'])

    # --- custom_cards: target_lang --------------------------------------- #
    with op.batch_alter_table('custom_cards') as batch_op:
        batch_op.add_column(sa.Column('target_lang', sa.String(10), nullable=False,
                                       server_default='ja'))
        batch_op.create_index('ix_custom_cards_target_lang', ['target_lang'])

    # --- kana_cards: target_lang wird Teil des Primärschlüssels ---------- #
    with op.batch_alter_table('kana_cards', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('target_lang', sa.String(10), nullable=False,
                                       server_default='ja'))
        batch_op.create_primary_key('pk_kana_cards', ['user_id', 'target_lang', 'id'])

    # --- jobs: target_lang ------------------------------------------------ #
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.add_column(sa.Column('target_lang', sa.String(10), nullable=False,
                                       server_default='ja'))
        batch_op.create_index('ix_jobs_target_lang', ['target_lang'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_index('ix_jobs_target_lang')
        batch_op.drop_column('target_lang')

    with op.batch_alter_table('kana_cards', recreate='always') as batch_op:
        batch_op.create_primary_key('pk_kana_cards', ['user_id', 'id'])
        batch_op.drop_column('target_lang')

    with op.batch_alter_table('custom_cards') as batch_op:
        batch_op.drop_index('ix_custom_cards_target_lang')
        batch_op.drop_column('target_lang')

    with op.batch_alter_table('known_words', recreate='always') as batch_op:
        batch_op.drop_index('ix_known_words_target_lang')
        batch_op.drop_constraint('uq_known_word_per_user', type_='unique')
        batch_op.create_unique_constraint('uq_known_word_per_user', ['user_id', 'word_id'])
        batch_op.drop_column('target_lang')

    bind = op.get_bind()
    with op.batch_alter_table('user_settings') as batch_op:
        batch_op.add_column(sa.Column('wanikani_token_enc', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('username', sa.String(255), nullable=False, server_default=''))

    bind.execute(sa.text(
        "UPDATE user_settings SET wanikani_token_enc = ("
        "  SELECT wanikani_token_enc FROM user_language_secrets "
        "  WHERE user_language_secrets.user_id = user_settings.user_id AND target_lang = 'ja'"
        "), username = COALESCE((SELECT wanikani_username FROM user_language_secrets "
        "  WHERE user_language_secrets.user_id = user_settings.user_id AND target_lang = 'ja'), '')"
    ))

    op.drop_table('user_language_secrets')

    with op.batch_alter_table('user_settings') as batch_op:
        batch_op.drop_column('active_target_lang')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('native_lang')
