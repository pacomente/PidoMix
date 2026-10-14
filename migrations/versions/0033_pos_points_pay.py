"""Pagar con Puntos Trappi en el mostrador: QR fijo del local y pedidos de pago desde la caja.

Revision ID: 0033_pos_points_pay
Revises: 0032_pos
"""
import sqlalchemy as sa
from alembic import op

revision = '0033_pos_points_pay'
down_revision = '0032_pos'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if 'pos_counter_code' not in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.add_column(sa.Column('pos_counter_code', sa.String(16)))
            b.create_unique_constraint('uq_stores_pos_counter_code', ['pos_counter_code'])
    if 'points_payments' not in tables:
        op.create_table('points_payments',
                        sa.Column('id', sa.Integer(), primary_key=True),
                        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
                        sa.Column('cashier_id', sa.Integer(), sa.ForeignKey('pos_cashiers.id')),
                        sa.Column('code', sa.String(8), nullable=False),
                        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
                        sa.Column('status', sa.String(16), nullable=False, server_default='pending', index=True),
                        sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='SET NULL'), index=True),
                        sa.Column('points', sa.Integer(), nullable=False, server_default='0'),
                        sa.Column('discount', sa.Numeric(12, 2), nullable=False, server_default='0'),
                        sa.Column('trappi_part', sa.Numeric(12, 2), nullable=False, server_default='0'),
                        sa.Column('sale_id', sa.Integer()),
                        sa.Column('expires_at', sa.DateTime(), nullable=False),
                        sa.Column('confirmed_at', sa.DateTime()),
                        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    sc = _cols('pos_sales')
    with op.batch_alter_table('pos_sales') as b:
        if 'points_discount' not in sc:
            b.add_column(sa.Column('points_discount', sa.Numeric(12, 2), nullable=False, server_default='0'))
        if 'points_payment_id' not in sc:
            b.add_column(sa.Column('points_payment_id', sa.Integer()))
            b.create_foreign_key('fk_pos_sales_points_payment', 'points_payments', ['points_payment_id'], ['id'])


def downgrade() -> None:
    sc = _cols('pos_sales')
    with op.batch_alter_table('pos_sales') as b:
        if 'points_payment_id' in sc:
            b.drop_constraint('fk_pos_sales_points_payment', type_='foreignkey')
            b.drop_column('points_payment_id')
        if 'points_discount' in sc:
            b.drop_column('points_discount')
    if 'points_payments' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('points_payments')
    if 'pos_counter_code' in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.drop_constraint('uq_stores_pos_counter_code', type_='unique')
            b.drop_column('pos_counter_code')
