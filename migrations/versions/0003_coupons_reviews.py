"""coupons, reviews, store rating and order discount

Revision ID: 0003_coupons_reviews
Revises: 0002_align_schema_with_models
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_coupons_reviews"
down_revision = "0002_align_schema_with_models"
branch_labels = None
depends_on = None


def _table_exists(bind, name) -> bool:
    return name in sa.inspect(bind).get_table_names()


def _column_exists(bind, table, column) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()

    if not _column_exists(bind, 'stores', 'rating_avg'):
        op.add_column('stores', sa.Column('rating_avg', sa.Numeric(3, 2), nullable=False, server_default='0'))
    if not _column_exists(bind, 'stores', 'rating_count'):
        op.add_column('stores', sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'))

    if not _table_exists(bind, 'coupons'):
        op.create_table(
            'coupons',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('code', sa.String(40), nullable=False),
            sa.Column('discount_type', sa.String(10), nullable=False, server_default='percent'),
            sa.Column('discount_value', sa.Numeric(12, 2), nullable=False),
            sa.Column('min_order', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('max_uses', sa.Integer()),
            sa.Column('uses_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('expires_at', sa.DateTime()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_coupons_store_code', 'coupons', ['store_id', 'code'], unique=True)

    if not _column_exists(bind, 'orders', 'coupon_id'):
        with op.batch_alter_table('orders') as batch_op:  # batch: SQLite no hace ALTER de FKs
            batch_op.add_column(sa.Column('coupon_id', sa.Integer(), sa.ForeignKey('coupons.id', name='fk_orders_coupon_id')))
    if not _column_exists(bind, 'orders', 'discount'):
        op.add_column('orders', sa.Column('discount', sa.Numeric(12, 2), nullable=False, server_default='0'))

    if not _table_exists(bind, 'reviews'):
        op.create_table(
            'reviews',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False, unique=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('comment', sa.Text()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )


def downgrade():
    bind = op.get_bind()
    if _table_exists(bind, 'reviews'):
        op.drop_table('reviews')
    if _column_exists(bind, 'orders', 'discount'):
        op.drop_column('orders', 'discount')
    if _column_exists(bind, 'orders', 'coupon_id'):
        op.drop_column('orders', 'coupon_id')
    if _table_exists(bind, 'coupons'):
        op.drop_table('coupons')
    if _column_exists(bind, 'stores', 'rating_count'):
        op.drop_column('stores', 'rating_count')
    if _column_exists(bind, 'stores', 'rating_avg'):
        op.drop_column('stores', 'rating_avg')
