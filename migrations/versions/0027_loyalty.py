"""Puntos Trappi: movimientos de puntos por cliente y el canje en cada pedido.

Revision ID: 0027_loyalty
Revises: 0026_search_logs
"""
import sqlalchemy as sa
from alembic import op

revision = '0027_loyalty'
down_revision = '0026_search_logs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'loyalty_entries' not in insp.get_table_names():
        op.create_table(
            'loyalty_entries',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id')),
            sa.Column('kind', sa.String(10), nullable=False),
            sa.Column('points', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Numeric(12, 2)),
            sa.Column('expires_at', sa.DateTime()),
            sa.Column('note', sa.String(255)),
            sa.Column('dedupe_key', sa.String(80), unique=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_loyalty_entries_account_id', 'loyalty_entries', ['account_id'])
        op.create_index('ix_loyalty_entries_order_id', 'loyalty_entries', ['order_id'])
    columns = {c['name'] for c in insp.get_columns('orders')}
    with op.batch_alter_table('orders') as batch:
        if 'points_used' not in columns:
            batch.add_column(sa.Column('points_used', sa.Integer()))
        if 'points_discount' not in columns:
            batch.add_column(sa.Column('points_discount', sa.Numeric(12, 2)))


def downgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('points_discount')
        batch.drop_column('points_used')
    op.drop_index('ix_loyalty_entries_order_id', 'loyalty_entries')
    op.drop_index('ix_loyalty_entries_account_id', 'loyalty_entries')
    op.drop_table('loyalty_entries')
