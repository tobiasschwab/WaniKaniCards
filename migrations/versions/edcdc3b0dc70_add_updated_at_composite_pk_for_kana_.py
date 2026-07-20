"""add updated_at, composite pk for kana_cards

Revision ID: edcdc3b0dc70
Revises: 0983277a4bb3
Create Date: 2026-07-20 20:35:52.764139

Kein Projekt mit Produktivdaten bislang (Pre-Launch) - deshalb ohne
server_default-Backfill für die neuen NOT-NULL-Spalten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'edcdc3b0dc70'
down_revision: Union[str, Sequence[str], None] = '0983277a4bb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('custom_cards') as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                                       server_default=sa.text('CURRENT_TIMESTAMP')))
        batch_op.alter_column('updated_at', server_default=None)

    # `recreate='always'`: kana_cards braucht zusätzlich einen neuen
    # zusammengesetzten Primärschlüssel (user_id, id) statt id allein (siehe
    # models.py-Kommentar) - SQLite unterstützt PK-Änderungen nur über eine
    # Tabellen-Neuerstellung; auf Postgres wäre ein direktes ALTER TABLE
    # möglich, `recreate='always'` funktioniert aber dialektübergreifend
    # identisch, ohne den (dialektabhängigen) Namen der alten PK-Constraint
    # kennen zu müssen.
    with op.batch_alter_table('kana_cards', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                                       server_default=sa.text('CURRENT_TIMESTAMP')))
        batch_op.alter_column('updated_at', server_default=None)
        batch_op.create_primary_key('pk_kana_cards', ['user_id', 'id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('kana_cards', recreate='always') as batch_op:
        batch_op.create_primary_key('pk_kana_cards', ['id'])
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('custom_cards') as batch_op:
        batch_op.drop_column('updated_at')
