"""Estoy a full (demora/pausa del local), avisos al dueño, pedidos programados y direcciones guardadas.

Revision ID: 0037_busy_alerts_addresses
Revises: 0036_merchant_applications
"""
import sqlalchemy as sa
from alembic import op

revision = '0037_busy_alerts_addresses'
down_revision = '0036_merchant_applications'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


STORE_COLS = [
    ('busy_minutes', lambda: sa.Column('busy_minutes', sa.Integer())),
    ('busy_until', lambda: sa.Column('busy_until', sa.DateTime())),
    ('paused_until', lambda: sa.Column('paused_until', sa.DateTime())),
    ('alert_new_order', lambda: sa.Column('alert_new_order', sa.Boolean(), nullable=False, server_default=sa.true())),
    ('alert_late', lambda: sa.Column('alert_late', sa.Boolean(), nullable=False, server_default=sa.true())),
    ('alert_summary', lambda: sa.Column('alert_summary', sa.Boolean(), nullable=False, server_default=sa.true())),
    ('summary_sent_on', lambda: sa.Column('summary_sent_on', sa.Date())),
]


def upgrade() -> None:
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for name, col in STORE_COLS:
            if name not in have:
                b.add_column(col())
    have = _cols('orders')
    with op.batch_alter_table('orders') as b:
        if 'scheduled_for' not in have:
            b.add_column(sa.Column('scheduled_for', sa.DateTime()))
            b.create_index('ix_orders_scheduled_for', ['scheduled_for'])
        for name in ('store_notified_at', 'store_alerted_at'):
            if name not in have:
                b.add_column(sa.Column(name, sa.DateTime()))
        if 'stock_reserved' not in have:
            b.add_column(sa.Column('stock_reserved', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'stock_before_out' not in _cols('products'):
        with op.batch_alter_table('products') as b:
            b.add_column(sa.Column('stock_before_out', sa.Integer()))
    tables = _tables()
    if 'store_push_subscriptions' not in tables:
        op.create_table(
            'store_push_subscriptions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
            sa.Column('endpoint', sa.String(1000), nullable=False, unique=True),
            sa.Column('p256dh', sa.String(255), nullable=False), sa.Column('auth', sa.String(255), nullable=False),
            sa.Column('label', sa.String(120)), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('last_ok_at', sa.DateTime()),
        )
        op.create_index('ix_store_push_subscriptions_store_id', 'store_push_subscriptions', ['store_id'])
    if 'client_addresses' not in tables:
        op.create_table(
            'client_addresses',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('label', sa.String(40), nullable=False), sa.Column('address', sa.String(255), nullable=False),
            sa.Column('reference', sa.String(255)), sa.Column('lat', sa.Float()), sa.Column('lng', sa.Float()),
            sa.Column('icon', sa.String(12), nullable=False, server_default='home'),
            sa.Column('last_used_at', sa.DateTime()), sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_client_addresses_account_id', 'client_addresses', ['account_id'])


def downgrade() -> None:
    tables = _tables()
    for t in ('client_addresses', 'store_push_subscriptions'):
        if t in tables:
            op.drop_table(t)
    have = _cols('orders')
    with op.batch_alter_table('orders') as b:
        if 'scheduled_for' in have:
            b.drop_index('ix_orders_scheduled_for')
            b.drop_column('scheduled_for')
        for name in ('store_notified_at', 'store_alerted_at', 'stock_reserved'):
            if name in have:
                b.drop_column(name)
    if 'stock_before_out' in _cols('products'):
        with op.batch_alter_table('products') as b:
            b.drop_column('stock_before_out')
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for name, _ in reversed(STORE_COLS):
            if name in have:
                b.drop_column(name)
