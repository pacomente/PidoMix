"""Cuentas de clientes (entran con Google), el enlace de cada pedido a la cuenta y los pedidos de arrepentimiento.

Revision ID: 0021_client_accounts
Revises: 0020_security
"""
import sqlalchemy as sa
from alembic import op

revision = '0021_client_accounts'
down_revision = '0020_security'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if 'client_accounts' not in sa.inspect(bind).get_table_names():
        op.create_table(
            'client_accounts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('google_sub', sa.String(64), nullable=False),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('name', sa.String(160)),
            sa.Column('first_name', sa.String(100)),
            sa.Column('last_name', sa.String(100)),
            sa.Column('picture_url', sa.String(1000)),
            sa.Column('phone', sa.String(40)),
            sa.Column('address', sa.String(255)),
            sa.Column('reference', sa.String(255)),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('blocked_reason', sa.String(255)),
            sa.Column('session_version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('terms_version', sa.String(20)),
            sa.Column('terms_accepted_at', sa.DateTime()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_login_at', sa.DateTime()),
        )
        op.create_index('ix_client_accounts_google_sub', 'client_accounts', ['google_sub'], unique=True)
        op.create_index('ix_client_accounts_email', 'client_accounts', ['email'])
    if 'withdrawal_requests' not in sa.inspect(bind).get_table_names():
        op.create_table(
            'withdrawal_requests',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('code', sa.String(20), nullable=False),
            sa.Column('name', sa.String(160), nullable=False),
            sa.Column('email', sa.String(255)),
            sa.Column('phone', sa.String(40)),
            sa.Column('order_ref', sa.String(40)),
            sa.Column('detail', sa.Text()),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='SET NULL')),
            sa.Column('status', sa.String(12), nullable=False, server_default='nuevo'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_withdrawal_requests_code', 'withdrawal_requests', ['code'], unique=True)
    if 'account_id' not in {c['name'] for c in sa.inspect(bind).get_columns('orders')}:
        with op.batch_alter_table('orders') as batch:
            batch.add_column(sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', name='fk_orders_account_id'), nullable=True))
            batch.create_index('ix_orders_account_id', ['account_id'])


def downgrade() -> None:
    bind = op.get_bind()
    if 'account_id' in {c['name'] for c in sa.inspect(bind).get_columns('orders')}:
        with op.batch_alter_table('orders') as batch:
            batch.drop_index('ix_orders_account_id')
            batch.drop_constraint('fk_orders_account_id', type_='foreignkey')
            batch.drop_column('account_id')
    if 'withdrawal_requests' in sa.inspect(bind).get_table_names():
        op.drop_index('ix_withdrawal_requests_code', table_name='withdrawal_requests')
        op.drop_table('withdrawal_requests')
    if 'client_accounts' in sa.inspect(bind).get_table_names():
        op.drop_index('ix_client_accounts_email', table_name='client_accounts')
        op.drop_index('ix_client_accounts_google_sub', table_name='client_accounts')
        op.drop_table('client_accounts')
