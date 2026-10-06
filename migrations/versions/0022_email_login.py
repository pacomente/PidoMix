"""Ingreso de clientes con un codigo por email: la cuenta ya no necesita Google (google_sub puede ser nulo).

Revision ID: 0022_email_login
Revises: 0021_client_accounts
"""
import sqlalchemy as sa
from alembic import op

revision = '0022_email_login'
down_revision = '0021_client_accounts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('client_accounts') as batch:
        batch.alter_column('google_sub', existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    # las cuentas que entraron solo con email no tienen google_sub: se les pone uno que no es de Google
    op.execute("UPDATE client_accounts SET google_sub = 'email-' || id WHERE google_sub IS NULL")
    with op.batch_alter_table('client_accounts') as batch:
        batch.alter_column('google_sub', existing_type=sa.String(64), nullable=False)
