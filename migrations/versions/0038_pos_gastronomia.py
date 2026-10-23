"""Caja para gastronomía: opciones y aclaraciones en las ventas, número para llamar, para llevar, pago mixto,
comanda en el tablero de cocina, descuentos autorizados por el dueño, retiros e ingresos de efectivo y pedidos por teléfono.

Revision ID: 0038_pos_gastronomia
Revises: 0037_busy_alerts_addresses
"""
import sqlalchemy as sa
from alembic import op

revision = '0038_pos_gastronomia'
down_revision = '0037_busy_alerts_addresses'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


SALE_COLS = [
    ('call_number', lambda: sa.Column('call_number', sa.Integer())),
    ('customer_name', lambda: sa.Column('customer_name', sa.String(60))),
    ('service', lambda: sa.Column('service', sa.String(10))),
    ('payments', lambda: sa.Column('payments', sa.Text())),
    ('kitchen', lambda: sa.Column('kitchen', sa.String(10))),
    ('kitchen_at', lambda: sa.Column('kitchen_at', sa.DateTime())),
    ('approved_by', lambda: sa.Column('approved_by', sa.Integer(), sa.ForeignKey('pos_cashiers.id', name='fk_pos_sales_approved_by'))),
]


def upgrade() -> None:
    have = _cols('pos_sales')
    with op.batch_alter_table('pos_sales') as b:
        for name, col in SALE_COLS:
            if name not in have:
                b.add_column(col())
        if 'kitchen' not in have:
            b.create_index('ix_pos_sales_kitchen', ['store_id', 'kitchen'])
    if 'pos_uuid' not in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.add_column(sa.Column('pos_uuid', sa.String(40)))
            b.create_index('ux_orders_pos_uuid', ['store_id', 'pos_uuid'], unique=True)
    if 'pos_cash_movements' not in _tables():
        op.create_table(
            'pos_cash_movements',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('shift_id', sa.Integer(), sa.ForeignKey('pos_shifts.id'), nullable=False),
            sa.Column('cashier_id', sa.Integer(), sa.ForeignKey('pos_cashiers.id')),
            sa.Column('client_uuid', sa.String(40), nullable=False),
            sa.Column('kind', sa.String(10), nullable=False),
            sa.Column('amount', sa.Numeric(12, 2), nullable=False),
            sa.Column('reason', sa.String(120), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_pos_cash_movements_store_id', 'pos_cash_movements', ['store_id'])
        op.create_index('ix_pos_cash_movements_shift_id', 'pos_cash_movements', ['shift_id'])
        op.create_index('ux_pos_cash_client', 'pos_cash_movements', ['store_id', 'client_uuid'], unique=True)


def downgrade() -> None:
    if 'pos_cash_movements' in _tables():
        op.drop_table('pos_cash_movements')
    if 'pos_uuid' in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.drop_index('ux_orders_pos_uuid')
            b.drop_column('pos_uuid')
    have = _cols('pos_sales')
    with op.batch_alter_table('pos_sales') as b:
        if 'kitchen' in have:
            b.drop_index('ix_pos_sales_kitchen')
        for name, _ in reversed(SALE_COLS):
            if name in have:
                b.drop_column(name)
