"""Cupones automáticos: se muestran en la tienda y se aplican solos en el checkout.

Revision ID: 0031_coupon_auto
Revises: 0030_delivery_safety
"""
import sqlalchemy as sa
from alembic import op

revision = '0031_coupon_auto'
down_revision = '0030_delivery_safety'
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('coupons')}
    if 'auto_apply' not in cols:
        with op.batch_alter_table('coupons') as batch:
            batch.add_column(sa.Column('auto_apply', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('coupons')}
    if 'auto_apply' in cols:
        with op.batch_alter_table('coupons') as batch:
            batch.drop_column('auto_apply')
