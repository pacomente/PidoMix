"""Tarjeta de sellos del local (stores.stamps_*, coupons.account_id, orders.stamp_at, stamp_cards) y
resumen semanal por mail al dueño (stores.weekly_report, stores.weekly_sent_on).

Revision ID: 0041_stamps_weekly
Revises: 0040_whatsapp_agent
"""
import sqlalchemy as sa
from alembic import op

revision = '0041_stamps_weekly'
down_revision = '0040_whatsapp_agent'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


STORE_COLS = [
    ('stamps_goal', lambda: sa.Column('stamps_goal', sa.Integer())),
    ('stamps_reward_type', lambda: sa.Column('stamps_reward_type', sa.String(10), nullable=False, server_default='percent')),
    ('stamps_reward_value', lambda: sa.Column('stamps_reward_value', sa.Numeric(12, 2), nullable=False, server_default='0')),
    ('stamps_min_order', lambda: sa.Column('stamps_min_order', sa.Numeric(12, 2), nullable=False, server_default='0')),
    ('weekly_report', lambda: sa.Column('weekly_report', sa.Boolean(), nullable=False, server_default=sa.true())),
    ('weekly_sent_on', lambda: sa.Column('weekly_sent_on', sa.Date())),
]


def upgrade() -> None:
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for name, col in STORE_COLS:
            if name not in have:
                b.add_column(col())
    if 'account_id' not in _cols('coupons'):
        with op.batch_alter_table('coupons') as b:
            b.add_column(sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', name='fk_coupons_account_id')))
            b.create_index('ix_coupons_account_id', ['account_id'])
    if 'stamp_at' not in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.add_column(sa.Column('stamp_at', sa.DateTime()))
    if 'stamp_cards' not in _tables():
        op.create_table(
            'stamp_cards',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id'), nullable=False),
            sa.Column('stamps', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('rewards', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_stamp_cards_store_id', 'stamp_cards', ['store_id'])
        op.create_index('ix_stamp_cards_account_id', 'stamp_cards', ['account_id'])
        op.create_index('ux_stamp_card', 'stamp_cards', ['store_id', 'account_id'], unique=True)


def downgrade() -> None:
    if 'stamp_cards' in _tables():
        op.drop_table('stamp_cards')
    if 'stamp_at' in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.drop_column('stamp_at')
    if 'account_id' in _cols('coupons'):
        with op.batch_alter_table('coupons') as b:
            b.drop_index('ix_coupons_account_id')
            b.drop_constraint('fk_coupons_account_id', type_='foreignkey')
            b.drop_column('account_id')
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for name, _ in reversed(STORE_COLS):
            if name in have:
                b.drop_column(name)
