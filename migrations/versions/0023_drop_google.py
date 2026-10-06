"""Sin ingreso con Google: se borra el id de Google de las cuentas (los clientes entran con un codigo por email).

Revision ID: 0023_drop_google
Revises: 0022_email_login
"""
import sqlalchemy as sa
from alembic import op

revision = '0023_drop_google'
down_revision = '0022_email_login'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('client_accounts')}
    if 'google_sub' not in columns:
        return
    if 'ix_client_accounts_google_sub' in {i['name'] for i in sa.inspect(bind).get_indexes('client_accounts')}:
        op.drop_index('ix_client_accounts_google_sub', table_name='client_accounts')
    with op.batch_alter_table('client_accounts') as batch:
        batch.drop_column('google_sub')


def downgrade() -> None:
    with op.batch_alter_table('client_accounts') as batch:
        batch.add_column(sa.Column('google_sub', sa.String(64), nullable=True))
    op.create_index('ix_client_accounts_google_sub', 'client_accounts', ['google_sub'], unique=True)
