"""Pedidos desde la mesa (QR): pos_tables.qr_code, orders.table_name y la comision propia (stores.table_commission_percent).

Revision ID: 0046_table_orders
Revises: 0045_menu_3d
"""
import sqlalchemy as sa
from alembic import op

revision = '0046_table_orders'
down_revision = '0045_menu_3d'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if 'qr_code' not in _cols('pos_tables'):
        with op.batch_alter_table('pos_tables') as b:
            b.add_column(sa.Column('qr_code', sa.String(16)))
            b.create_unique_constraint('uq_pos_tables_qr_code', ['qr_code'])
    if 'table_name' not in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.add_column(sa.Column('table_name', sa.String(40)))
    if 'table_commission_percent' not in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.add_column(sa.Column('table_commission_percent', sa.Numeric(5, 2)))


def downgrade() -> None:
    if 'table_commission_percent' in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.drop_column('table_commission_percent')
    if 'table_name' in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.drop_column('table_name')
    if 'qr_code' in _cols('pos_tables'):
        with op.batch_alter_table('pos_tables') as b:
            b.drop_constraint('uq_pos_tables_qr_code', type_='unique')
            b.drop_column('qr_code')
