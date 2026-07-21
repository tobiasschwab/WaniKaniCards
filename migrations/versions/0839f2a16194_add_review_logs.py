"""add review_logs table (SRS-Vokabeltrainer Phase 4: Dashboard/Tageslimits)

Revision ID: 0839f2a16194
Revises: 37a420d4f9b6
Create Date: 2026-07-21 14:00:00.000000

Grundlage fürs Statistik-Dashboard und die Tageslimits (neue Karten/Tag,
Reviews/Tag) - ohne dieses Log ließe sich weder "wie viele Reviews heute"
noch eine ehrliche Retention-Rate berechnen. Kein Projekt mit
Produktivdaten bislang - keine Backfill-Logik nötig, die Tabelle ist neu.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0839f2a16194'
down_revision: Union[str, Sequence[str], None] = '37a420d4f9b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'review_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('target_lang', sa.String(10), nullable=False),
        sa.Column('card_type', sa.String(16), nullable=False),
        sa.Column('card_id', sa.String(64), nullable=False),
        sa.Column('item_type', sa.String(16), nullable=False),
        sa.Column('rating', sa.String(16), nullable=False),
        sa.Column('was_new', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_review_logs_user_id', 'review_logs', ['user_id'])
    op.create_index(
        'ix_review_logs_reviewed_at', 'review_logs', ['user_id', 'target_lang', 'reviewed_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_review_logs_reviewed_at', table_name='review_logs')
    op.drop_index('ix_review_logs_user_id', table_name='review_logs')
    op.drop_table('review_logs')
