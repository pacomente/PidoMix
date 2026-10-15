"""Varios pedidos a la vez para los repartidores propios de cada local.

Revision ID: 0034_own_batch
Revises: 0033_pos_points_pay
"""
import sqlalchemy as sa
from alembic import op

revision = '0034_own_batch'
down_revision = '0033_pos_points_pay'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        if 'own_batch' not in have:
            b.add_column(sa.Column('own_batch', sa.Boolean(), nullable=False, server_default=sa.false()))
        if 'own_batch_max' not in have:
            b.add_column(sa.Column('own_batch_max', sa.Integer(), nullable=False, server_default='2'))
        if 'own_batch_km' not in have:
            b.add_column(sa.Column('own_batch_km', sa.Float(), nullable=False, server_default='1.5'))


def downgrade() -> None:
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for col in ('own_batch_km', 'own_batch_max', 'own_batch'):
            if col in have:
                b.drop_column(col)
