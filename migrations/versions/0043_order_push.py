"""Avisos del pedido al navegador del cliente (order_push_subscriptions).

Revision ID: 0043_order_push
Revises: 0042_claims_referrals
"""
import sqlalchemy as sa
from alembic import op

revision = '0043_order_push'
down_revision = '0042_claims_referrals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'order_push_subscriptions' not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            'order_push_subscriptions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
            sa.Column('endpoint', sa.String(1000), nullable=False),
            sa.Column('p256dh', sa.String(255), nullable=False),
            sa.Column('auth', sa.String(255), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_order_push_subscriptions_order_id', 'order_push_subscriptions', ['order_id'])
        op.create_index('ux_order_push', 'order_push_subscriptions', ['order_id', 'endpoint'], unique=True)


def downgrade() -> None:
    if 'order_push_subscriptions' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('order_push_subscriptions')
