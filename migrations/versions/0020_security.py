"""Seguridad del panel.

- users.session_version: al cambiar la contrasena se cierran las sesiones de los otros dispositivos.
- users.totp_*: verificacion en dos pasos (codigo de una app como Google Authenticator) y codigos de recuperacion.
- auth_attempts: intentos fallidos de ingreso guardados en la base (no se pierden al desplegar).

Revision ID: 0020_security
Revises: 0019_product_deleted
"""
import sqlalchemy as sa
from alembic import op

revision = '0020_security'
down_revision = '0019_product_deleted'
branch_labels = None
depends_on = None

USER_COLUMNS = (
    ('session_version', lambda: sa.Column('session_version', sa.Integer(), nullable=False, server_default='1')),
    ('totp_secret_enc', lambda: sa.Column('totp_secret_enc', sa.Text())),
    ('totp_enabled_at', lambda: sa.Column('totp_enabled_at', sa.DateTime())),
    ('totp_last_step', lambda: sa.Column('totp_last_step', sa.Integer())),
    ('recovery_codes', lambda: sa.Column('recovery_codes', sa.Text())),
)


def upgrade() -> None:
    bind = op.get_bind()
    have = {c['name'] for c in sa.inspect(bind).get_columns('users')}
    missing = [make() for name, make in USER_COLUMNS if name not in have]
    if missing:
        with op.batch_alter_table('users') as batch:
            for col in missing:
                batch.add_column(col)
    if 'auth_attempts' not in sa.inspect(bind).get_table_names():
        op.create_table(
            'auth_attempts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('key', sa.String(200), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_auth_attempts_key_created', 'auth_attempts', ['key', 'created_at'])
        op.create_index('ix_auth_attempts_created_at', 'auth_attempts', ['created_at'])


def downgrade() -> None:
    bind = op.get_bind()
    if 'auth_attempts' in sa.inspect(bind).get_table_names():
        op.drop_index('ix_auth_attempts_created_at', table_name='auth_attempts')
        op.drop_index('ix_auth_attempts_key_created', table_name='auth_attempts')
        op.drop_table('auth_attempts')
    have = {c['name'] for c in sa.inspect(bind).get_columns('users')}
    drop = [name for name, _ in USER_COLUMNS if name in have]
    if drop:
        with op.batch_alter_table('users') as batch:
            for name in drop:
                batch.drop_column(name)
