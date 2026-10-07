"""Recomendado para vos: el cliente puede apagar las recomendaciones con sus datos.

Revision ID: 0025_personalize
Revises: 0024_order_origin
"""
import sqlalchemy as sa
from alembic import op

revision = '0025_personalize'
down_revision = '0024_order_origin'
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('client_accounts')}
    if 'personalize' not in columns:
        with op.batch_alter_table('client_accounts') as batch:
            batch.add_column(sa.Column('personalize', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table('client_accounts') as batch:
        batch.drop_column('personalize')
