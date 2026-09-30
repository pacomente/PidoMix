"""store sections and product modifiers (extras/personalizacion)

Revision ID: 0004_sections_modifiers
Revises: 0003_coupons_reviews
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_sections_modifiers"
down_revision = "0003_coupons_reviews"
branch_labels = None
depends_on = None


def _table_exists(bind, name) -> bool:
    return name in sa.inspect(bind).get_table_names()


def _column_exists(bind, table, column) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, 'store_sections'):
        op.create_table(
            'store_sections',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    if not _column_exists(bind, 'products', 'section_id'):
        op.add_column('products', sa.Column('section_id', sa.Integer(), sa.ForeignKey('store_sections.id')))

    if not _table_exists(bind, 'modifier_groups'):
        op.create_table(
            'modifier_groups',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('min_select', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_select', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        )

    if not _table_exists(bind, 'modifier_options'):
        op.create_table(
            'modifier_options',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('modifier_groups.id'), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('price_extra', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        )

    if not _column_exists(bind, 'order_items', 'modifiers_text'):
        op.add_column('order_items', sa.Column('modifiers_text', sa.String(500)))


def downgrade():
    bind = op.get_bind()
    if _column_exists(bind, 'order_items', 'modifiers_text'):
        op.drop_column('order_items', 'modifiers_text')
    if _table_exists(bind, 'modifier_options'):
        op.drop_table('modifier_options')
    if _table_exists(bind, 'modifier_groups'):
        op.drop_table('modifier_groups')
    if _column_exists(bind, 'products', 'section_id'):
        op.drop_column('products', 'section_id')
    if _table_exists(bind, 'store_sections'):
        op.drop_table('store_sections')
