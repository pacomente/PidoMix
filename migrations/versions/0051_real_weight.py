"""Peso real y precio por unidad de medida: order_items.price_per_kg y weight_real_grams; orders.call_if_missing y
weight_status; stores.weight_margin; products.content_amount y content_unit.

Revision ID: 0051_real_weight
Revises: 0050_weight_products
"""
import sqlalchemy as sa
from alembic import op

revision = '0051_real_weight'
down_revision = '0050_weight_products'
branch_labels = None
depends_on = None
COLS = {
    'order_items': (('price_per_kg', sa.Numeric(12, 2), None), ('weight_real_grams', sa.Integer(), None)),
    'orders': (('call_if_missing', sa.Boolean(), sa.false()), ('weight_status', sa.String(10), None)),
    'stores': (('weight_margin', sa.Integer(), None),),
    'products': (('content_amount', sa.Numeric(10, 3), None), ('content_unit', sa.String(4), None)),
}


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table, cols in COLS.items():
        have = _cols(table)
        with op.batch_alter_table(table) as b:
            for name, kind, default in cols:
                if name not in have:
                    b.add_column(sa.Column(name, kind, nullable=default is None, server_default=default))


def downgrade() -> None:
    for table, cols in COLS.items():
        have = _cols(table)
        with op.batch_alter_table(table) as b:
            for name, _, _ in reversed(cols):
                if name in have:
                    b.drop_column(name)
