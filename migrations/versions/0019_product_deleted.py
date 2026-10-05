"""Productos eliminados por el local.

products.deleted: el local elimino el producto. Si nunca se vendio se borra de verdad; si ya
tiene pedidos, se marca eliminado (no se muestra en ningun lado) para no romper esos pedidos.

Revision ID: 0019_product_deleted
Revises: 0018_settlement_cash_offset
"""
import sqlalchemy as sa
from alembic import op

revision = '0019_product_deleted'
down_revision = '0018_settlement_cash_offset'
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('products')}
    if 'deleted' not in have:
        with op.batch_alter_table('products') as batch:
            batch.add_column(sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('products')}
    if 'deleted' in have:
        with op.batch_alter_table('products') as batch:
            batch.drop_column('deleted')
