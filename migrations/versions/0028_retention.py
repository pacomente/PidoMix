"""Retencion: descuentos de Trappi para que el cliente vuelva, con presupuesto, y permiso para mandarle novedades.

Revision ID: 0028_retention
Revises: 0027_loyalty
"""
import sqlalchemy as sa
from alembic import op

revision = '0028_retention'
down_revision = '0027_loyalty'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'retention_vouchers' not in insp.get_table_names():
        op.create_table(
            'retention_vouchers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('reason', sa.String(20), nullable=False),
            sa.Column('amount', sa.Numeric(12, 2), nullable=False),
            sa.Column('min_order', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('status', sa.String(10), nullable=False, server_default='activo'),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('order_id', sa.Integer()),
            sa.Column('used_amount', sa.Numeric(12, 2)),
            sa.Column('used_at', sa.DateTime()),
            sa.Column('note', sa.String(255)),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_retention_vouchers_account_id', 'retention_vouchers', ['account_id'])
        op.create_index('ix_retention_vouchers_status', 'retention_vouchers', ['status'])
        op.create_index('ix_retention_vouchers_created_at', 'retention_vouchers', ['created_at'])
    columns = {c['name'] for c in insp.get_columns('orders')}
    with op.batch_alter_table('orders') as batch:
        if 'voucher_id' not in columns:
            batch.add_column(sa.Column('voucher_id', sa.Integer()))
            batch.create_index('ix_orders_voucher_id', ['voucher_id'])
        if 'voucher_discount' not in columns:
            batch.add_column(sa.Column('voucher_discount', sa.Numeric(12, 2)))
    acols = {c['name'] for c in insp.get_columns('client_accounts')}
    with op.batch_alter_table('client_accounts') as batch:
        if 'marketing_opt_in' not in acols:
            batch.add_column(sa.Column('marketing_opt_in', sa.Boolean(), nullable=False, server_default=sa.false()))
        if 'last_retention_at' not in acols:
            batch.add_column(sa.Column('last_retention_at', sa.DateTime()))


def downgrade() -> None:
    with op.batch_alter_table('client_accounts') as batch:
        batch.drop_column('last_retention_at')
        batch.drop_column('marketing_opt_in')
    with op.batch_alter_table('orders') as batch:
        batch.drop_index('ix_orders_voucher_id')
        batch.drop_column('voucher_discount')
        batch.drop_column('voucher_id')
    op.drop_index('ix_retention_vouchers_created_at', 'retention_vouchers')
    op.drop_index('ix_retention_vouchers_status', 'retention_vouchers')
    op.drop_index('ix_retention_vouchers_account_id', 'retention_vouchers')
    op.drop_table('retention_vouchers')
