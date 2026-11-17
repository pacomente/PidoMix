"""Productos por peso y catalogo por rubro: products.sold_by_weight, weight_step, weight_min;
order_items.weight_grams; stores.catalog_style.

Revision ID: 0050_weight_products
Revises: 0049_client_tiers
"""
import sqlalchemy as sa
from alembic import op

revision = '0050_weight_products'
down_revision = '0049_client_tiers'
branch_labels = None
depends_on = None
COLS = {
    'products': (('sold_by_weight', sa.Boolean(), sa.false()), ('weight_step', sa.Integer(), None), ('weight_min', sa.Integer(), None)),
    'order_items': (('weight_grams', sa.Integer(), None),),
    'stores': (('catalog_style', sa.String(10), None),),
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
