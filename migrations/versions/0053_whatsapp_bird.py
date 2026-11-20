"""Agente de WhatsApp también por Bird (proveedor oficial de WhatsApp, sin app propia en Meta).

- stores.wa_provider: 'bird' cuando el número del local está en el workspace de Bird de Trappi.
- wa_conversations.wa_id: 20 -> 64, porque Bird puede mandar el id de WhatsApp del cliente sin número (BSUID).

Revision ID: 0053_whatsapp_bird
Revises: 0052_online_promos_table_tab
"""
import sqlalchemy as sa
from alembic import op

revision = '0053_whatsapp_bird'
down_revision = '0052_online_promos_table_tab'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if 'wa_provider' not in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.add_column(sa.Column('wa_provider', sa.String(10), nullable=True))
    with op.batch_alter_table('wa_conversations') as b:
        b.alter_column('wa_id', existing_type=sa.String(20), type_=sa.String(64), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('wa_conversations') as b:
        b.alter_column('wa_id', existing_type=sa.String(64), type_=sa.String(20), existing_nullable=False)
    if 'wa_provider' in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.drop_column('wa_provider')
