"""Niveles de cliente y regalo de cumpleaños: client_accounts.birth_day, birth_month y birth_set_at.

Revision ID: 0049_client_tiers
Revises: 0048_free_shipping
"""
import sqlalchemy as sa
from alembic import op

revision = '0049_client_tiers'
down_revision = '0048_free_shipping'
branch_labels = None
depends_on = None
COLS = (('birth_day', sa.Integer()), ('birth_month', sa.Integer()), ('birth_set_at', sa.DateTime()))


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols('client_accounts')
    with op.batch_alter_table('client_accounts') as b:
        for name, kind in COLS:
            if name not in have:
                b.add_column(sa.Column(name, kind))


def downgrade() -> None:
    have = _cols('client_accounts')
    with op.batch_alter_table('client_accounts') as b:
        for name, _ in reversed(COLS):
            if name in have:
                b.drop_column(name)
