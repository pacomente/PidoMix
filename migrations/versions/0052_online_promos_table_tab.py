"""Promos de la caja también en la app y la cuenta de la mesa para el cliente.

- pos_promos.online: la promo (2x1, combo, happy hour) también vale en los pedidos de la app y la web.
- orders.promo_discount / promo_text: lo que descontaron esas promos (va dentro de discount).
- pos_table_tabs: la cuenta abierta de cada mesa, la sube la caja (el cliente la ve desde el QR).
- table_calls: "Llamar al mozo" / "Pedir la cuenta" desde el QR de la mesa.

Revision ID: 0052_online_promos_table_tab
Revises: 0051_real_weight
"""
import sqlalchemy as sa
from alembic import op

revision = '0052_online_promos_table_tab'
down_revision = '0051_real_weight'
branch_labels = None
depends_on = None
COLS = {
    'pos_promos': (('online', sa.Boolean(), sa.false()),),
    'orders': (('promo_discount', sa.Numeric(12, 2), sa.text('0')), ('promo_text', sa.String(200), None)),
}


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    for table, cols in COLS.items():
        have = _cols(table)
        with op.batch_alter_table(table) as b:
            for name, kind, default in cols:
                if name not in have:
                    b.add_column(sa.Column(name, kind, nullable=default is None, server_default=default))
    have = _tables()
    if 'pos_table_tabs' not in have:
        op.create_table(
            'pos_table_tabs',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
            sa.Column('table_id', sa.Integer(), sa.ForeignKey('pos_tables.id'), nullable=False, unique=True),
            sa.Column('items', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('subtotal', sa.Numeric(12, 2), nullable=False, server_default=sa.text('0')),
            sa.Column('promo_discount', sa.Numeric(12, 2), nullable=False, server_default=sa.text('0')),
            sa.Column('total', sa.Numeric(12, 2), nullable=False, server_default=sa.text('0')),
            sa.Column('opened_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
    if 'table_calls' not in have:
        op.create_table(
            'table_calls',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False, index=True),
            sa.Column('table_id', sa.Integer(), sa.ForeignKey('pos_tables.id'), nullable=False),
            sa.Column('kind', sa.String(10), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('seen_at', sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    have = _tables()
    for t in ('table_calls', 'pos_table_tabs'):
        if t in have:
            op.drop_table(t)
    for table, cols in COLS.items():
        have_cols = _cols(table)
        with op.batch_alter_table(table) as b:
            for name, _, _ in reversed(cols):
                if name in have_cols:
                    b.drop_column(name)
