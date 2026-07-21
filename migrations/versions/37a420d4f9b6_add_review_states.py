"""add review_states table (SRS-Vokabeltrainer, FSRS)

Revision ID: 37a420d4f9b6
Revises: c7691d3fd577
Create Date: 2026-07-21 12:00:00.000000

Legt die Grundlage für den Vokabeltrainer an (siehe README-Roadmap
"SRS-Vokabeltrainer"): pro Nutzer/Zielsprache/Karte/Prüfrichtung ein
FSRS-Lernstand. Kein Projekt mit Produktivdaten bislang - keine
Backfill-Logik nötig, die Tabelle ist komplett neu.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37a420d4f9b6'
down_revision: Union[str, Sequence[str], None] = 'c7691d3fd577'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'review_states',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('target_lang', sa.String(10), primary_key=True),
        sa.Column('card_type', sa.String(16), primary_key=True),
        sa.Column('card_id', sa.String(64), primary_key=True),
        sa.Column('item_type', sa.String(16), primary_key=True),
        sa.Column('fsrs_state', sa.JSON(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lapses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index(
        'ix_review_states_due', 'review_states', ['user_id', 'target_lang', 'due_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_review_states_due', table_name='review_states')
    op.drop_table('review_states')
