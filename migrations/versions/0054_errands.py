"""Trappi Mandados: pedidos que se retiran en una dirección (no en un local).

- orders.pickup_address / pickup_lat / pickup_lng: dónde se retira.
- orders.errand: JSON con qué es, el tamaño, quién entrega y quién recibe.

Revision ID: 0054_errands
Revises: 0053_whatsapp_bird
"""
import sqlalchemy as sa
from alembic import op

revision = '0054_errands'
down_revision = '0053_whatsapp_bird'
branch_labels = None
depends_on = None
COLS = (('pickup_address', sa.String(255)), ('pickup_lat', sa.Float()), ('pickup_lng', sa.Float()), ('errand', sa.Text()))


def upgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('orders')}
    with op.batch_alter_table('orders') as b:
        for name, kind in COLS:
            if name not in have:
                b.add_column(sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('orders')}
    with op.batch_alter_table('orders') as b:
        for name, _ in COLS:
            if name in have:
                b.drop_column(name)
