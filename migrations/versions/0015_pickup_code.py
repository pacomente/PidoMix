"""Codigo de retiro y pago del cadete de la flota al local.

- orders.pickup_code: 4 numeros; sale en la comanda del local y en la app del cadete asignado.
  El local entrega el pedido solo a quien le muestra ese codigo.
- orders.pickup_paid: efectivo que el cadete de Trappi le pago al local al retirar un pedido que
  el cliente paga en efectivo (despues le cobra al cliente productos + envio).

Revision ID: 0015_pickup_code
Revises: 0014_plan_logistics
"""
import sqlalchemy as sa
from alembic import op

revision = '0015_pickup_code'
down_revision = '0014_plan_logistics'
branch_labels = None
depends_on = None


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('orders')}


def upgrade() -> None:
    have = _columns()
    if 'pickup_code' not in have:
        op.add_column('orders', sa.Column('pickup_code', sa.String(6), nullable=True))
    if 'pickup_paid' not in have:
        op.add_column('orders', sa.Column('pickup_paid', sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    have = _columns()
    with op.batch_alter_table('orders') as batch:
        if 'pickup_paid' in have:
            batch.drop_column('pickup_paid')
        if 'pickup_code' in have:
            batch.drop_column('pickup_code')
