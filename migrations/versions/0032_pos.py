"""Caja (punto de venta): cajeros, turnos, ventas del mostrador, QR de Puntos Trappi y código de barras.

Revision ID: 0032_pos
Revises: 0031_coupon_auto
"""
import sqlalchemy as sa
from alembic import op

revision = '0032_pos'
down_revision = '0031_coupon_auto'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    st = _cols('stores')
    with op.batch_alter_table('stores') as b:
        if 'pos_enabled' not in st: b.add_column(sa.Column('pos_enabled', sa.Boolean()))
        if 'pos_commission_percent' not in st: b.add_column(sa.Column('pos_commission_percent', sa.Numeric(5, 2)))
        if 'pos_monthly_fee' not in st: b.add_column(sa.Column('pos_monthly_fee', sa.Numeric(12, 2)))
        if 'pos_device_version' not in st: b.add_column(sa.Column('pos_device_version', sa.Integer(), nullable=False, server_default='1'))
    if 'barcode' not in _cols('products'):
        with op.batch_alter_table('products') as b:
            b.add_column(sa.Column('barcode', sa.String(40)))
        op.create_index('ix_products_barcode', 'products', ['barcode'])
    if 'pos_cashiers' not in tables:
        op.create_table('pos_cashiers',
                        sa.Column('id', sa.Integer(), primary_key=True),
                        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
                        sa.Column('name', sa.String(60), nullable=False),
                        sa.Column('pin_hash', sa.String(255), nullable=False),
                        sa.Column('is_owner', sa.Boolean(), nullable=False, server_default=sa.false()),
                        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
                        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    if 'pos_shifts' not in tables:
        op.create_table('pos_shifts',
                        sa.Column('id', sa.Integer(), primary_key=True),
                        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
                        sa.Column('opened_by', sa.Integer(), sa.ForeignKey('pos_cashiers.id')),
                        sa.Column('closed_by', sa.Integer(), sa.ForeignKey('pos_cashiers.id')),
                        sa.Column('opened_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
                        sa.Column('closed_at', sa.DateTime()),
                        sa.Column('opening_cash', sa.Numeric(12, 2), nullable=False, server_default='0'),
                        sa.Column('counted_cash', sa.Numeric(12, 2)),
                        sa.Column('expected_cash', sa.Numeric(12, 2)),
                        sa.Column('totals', sa.Text()))
    if 'pos_sales' not in tables:
        op.create_table('pos_sales',
                        sa.Column('id', sa.Integer(), primary_key=True),
                        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
                        sa.Column('shift_id', sa.Integer(), sa.ForeignKey('pos_shifts.id'), index=True),
                        sa.Column('cashier_id', sa.Integer(), sa.ForeignKey('pos_cashiers.id')),
                        sa.Column('client_uuid', sa.String(40), nullable=False),
                        sa.Column('number', sa.Integer(), nullable=False),
                        sa.Column('items', sa.Text(), nullable=False),
                        sa.Column('subtotal', sa.Numeric(12, 2), nullable=False),
                        sa.Column('discount', sa.Numeric(12, 2), nullable=False, server_default='0'),
                        sa.Column('total', sa.Numeric(12, 2), nullable=False),
                        sa.Column('payment_method', sa.String(20), nullable=False),
                        sa.Column('paid_with', sa.Numeric(12, 2)),
                        sa.Column('points', sa.Integer(), nullable=False, server_default='0'),
                        sa.Column('commission', sa.Numeric(12, 2), nullable=False, server_default='0'),
                        sa.Column('voided', sa.Boolean(), nullable=False, server_default=sa.false()),
                        sa.Column('sold_at', sa.DateTime(), nullable=False),
                        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
        op.create_index('ux_pos_sales_client', 'pos_sales', ['store_id', 'client_uuid'], unique=True)
    if 'points_claims' not in tables:
        op.create_table('points_claims',
                        sa.Column('id', sa.Integer(), primary_key=True),
                        sa.Column('code', sa.String(24), nullable=False, unique=True, index=True),
                        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
                        sa.Column('sale_id', sa.Integer(), sa.ForeignKey('pos_sales.id'), nullable=False, index=True),
                        sa.Column('points', sa.Integer(), nullable=False),
                        sa.Column('expires_at', sa.DateTime(), nullable=False),
                        sa.Column('claimed_by', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='SET NULL')),
                        sa.Column('claimed_at', sa.DateTime()),
                        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    for t in ('points_claims', 'pos_sales', 'pos_shifts', 'pos_cashiers'):
        if t in tables:
            op.drop_table(t)
    if 'barcode' in _cols('products'):
        op.drop_index('ix_products_barcode', table_name='products')
        with op.batch_alter_table('products') as b:
            b.drop_column('barcode')
    st = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for c in ('pos_device_version', 'pos_monthly_fee', 'pos_commission_percent', 'pos_enabled'):
            if c in st: b.drop_column(c)
