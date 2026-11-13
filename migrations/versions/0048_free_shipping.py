"""Envío gratis desde un monto (solo locales con cadetería propia): stores.free_shipping_from.

Revision ID: 0048_free_shipping
Revises: 0047_courier_style
"""
import sqlalchemy as sa
from alembic import op

revision = '0048_free_shipping'
down_revision = '0047_courier_style'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if 'free_shipping_from' not in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.add_column(sa.Column('free_shipping_from', sa.Numeric(12, 2)))


def downgrade() -> None:
    if 'free_shipping_from' in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.drop_column('free_shipping_from')
