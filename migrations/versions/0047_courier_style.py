"""Estilo del repartidor en el mapa: couriers.avatar y couriers.avatar_color.

Revision ID: 0047_courier_style
Revises: 0046_table_orders
"""
import sqlalchemy as sa
from alembic import op

revision = '0047_courier_style'
down_revision = '0046_table_orders'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    cols = _cols('couriers')
    with op.batch_alter_table('couriers') as b:
        if 'avatar' not in cols:
            b.add_column(sa.Column('avatar', sa.String(16)))
        if 'avatar_color' not in cols:
            b.add_column(sa.Column('avatar_color', sa.String(9)))


def downgrade() -> None:
    cols = _cols('couriers')
    with op.batch_alter_table('couriers') as b:
        if 'avatar_color' in cols:
            b.drop_column('avatar_color')
        if 'avatar' in cols:
            b.drop_column('avatar')
