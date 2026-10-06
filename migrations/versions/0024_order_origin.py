"""Desde donde se hizo cada pedido (web o app) y la IP, para el control de clientes del panel.

Revision ID: 0024_order_origin
Revises: 0023_drop_google
"""
import sqlalchemy as sa
from alembic import op

revision = '0024_order_origin'
down_revision = '0023_drop_google'
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('orders')}
    with op.batch_alter_table('orders') as batch:
        if 'ip' not in columns:
            batch.add_column(sa.Column('ip', sa.String(64)))
        if 'origin' not in columns:
            batch.add_column(sa.Column('origin', sa.String(10)))


def downgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        batch.drop_column('origin')
        batch.drop_column('ip')
