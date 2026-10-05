"""Pedidos que no se pudieron entregar despues de retirarlos.

- orders.delivery_failed_at / delivery_fail_reason: el cadete reporto que no pudo entregar
  (cliente no atiende, direccion incorrecta, rechazo el pedido).
- orders.cancel_resolution: como se resolvio la plata al cancelar un pedido ya retirado:
  returned (el cadete devolvio el pedido y el local le devolvio lo que habia pagado) o
  store_keeps (el local se queda con la plata y el pedido; lo absorbe Trappi).

Revision ID: 0016_failed_delivery
Revises: 0015_pickup_code
"""
import sqlalchemy as sa
from alembic import op

revision = '0016_failed_delivery'
down_revision = '0015_pickup_code'
branch_labels = None
depends_on = None

COLUMNS = (
    ('delivery_failed_at', lambda: sa.Column('delivery_failed_at', sa.DateTime(), nullable=True)),
    ('delivery_fail_reason', lambda: sa.Column('delivery_fail_reason', sa.String(160), nullable=True)),
    ('cancel_resolution', lambda: sa.Column('cancel_resolution', sa.String(20), nullable=True)),
)


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('orders')}


def upgrade() -> None:
    have = _columns()
    for name, column in COLUMNS:
        if name not in have:
            op.add_column('orders', column())


def downgrade() -> None:
    have = _columns()
    with op.batch_alter_table('orders') as batch:
        for name, _ in reversed(COLUMNS):
            if name in have:
                batch.drop_column(name)
