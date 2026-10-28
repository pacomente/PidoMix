"""Reclamos por pedido (order_claims) e "Invitá a un amigo" (client_accounts.referral_*).

Revision ID: 0042_claims_referrals
Revises: 0041_stamps_weekly
"""
import sqlalchemy as sa
from alembic import op

revision = '0042_claims_referrals'
down_revision = '0041_stamps_weekly'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols('client_accounts')
    with op.batch_alter_table('client_accounts') as b:
        if 'referral_code' not in have:
            b.add_column(sa.Column('referral_code', sa.String(12)))
            b.create_unique_constraint('uq_client_accounts_referral_code', ['referral_code'])
        if 'referred_by_id' not in have:
            b.add_column(sa.Column('referred_by_id', sa.Integer(), sa.ForeignKey('client_accounts.id', name='fk_client_accounts_referred_by_id')))
            b.create_index('ix_client_accounts_referred_by_id', ['referred_by_id'])
        if 'referral_rewarded_at' not in have:
            b.add_column(sa.Column('referral_rewarded_at', sa.DateTime()))
    if 'order_claims' not in _tables():
        op.create_table(
            'order_claims',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False, unique=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id')),
            sa.Column('reason', sa.String(20), nullable=False),
            sa.Column('text', sa.Text()),
            sa.Column('photo_id', sa.Integer(), sa.ForeignKey('order_photos.id', ondelete='SET NULL')),
            sa.Column('status', sa.String(12), nullable=False, server_default='abierto'),
            sa.Column('resolution', sa.String(12)),
            sa.Column('points', sa.Integer()),
            sa.Column('coupon_id', sa.Integer(), sa.ForeignKey('coupons.id')),
            sa.Column('store_note', sa.Text()),
            sa.Column('answer', sa.Text()),
            sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('resolved_at', sa.DateTime()),
        )
        op.create_index('ix_order_claims_store_id', 'order_claims', ['store_id'])
        op.create_index('ix_order_claims_account_id', 'order_claims', ['account_id'])
        op.create_index('ix_order_claims_created_at', 'order_claims', ['created_at'])


def downgrade() -> None:
    if 'order_claims' in _tables():
        op.drop_table('order_claims')
    have = _cols('client_accounts')
    with op.batch_alter_table('client_accounts') as b:
        if 'referral_rewarded_at' in have:
            b.drop_column('referral_rewarded_at')
        if 'referred_by_id' in have:
            b.drop_index('ix_client_accounts_referred_by_id')
            b.drop_constraint('fk_client_accounts_referred_by_id', type_='foreignkey')
            b.drop_column('referred_by_id')
        if 'referral_code' in have:
            b.drop_constraint('uq_client_accounts_referral_code', type_='unique')
            b.drop_column('referral_code')
