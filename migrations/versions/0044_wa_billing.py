"""Cobro por mensaje del agente de WhatsApp: numeros en la cuenta de Trappi (stores.wa_trappi), cargo por local
(stores.wa_message_price) y mensajes ya cobrados (wa_messages.billed_at).

Revision ID: 0044_wa_billing
Revises: 0043_order_push
"""
import sqlalchemy as sa
from alembic import op

revision = '0044_wa_billing'
down_revision = '0043_order_push'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        if 'wa_trappi' not in have:
            b.add_column(sa.Column('wa_trappi', sa.Boolean(), nullable=False, server_default=sa.false()))
        if 'wa_message_price' not in have:
            b.add_column(sa.Column('wa_message_price', sa.Numeric(12, 2)))
    if 'billed_at' not in _cols('wa_messages'):
        with op.batch_alter_table('wa_messages') as b:
            b.add_column(sa.Column('billed_at', sa.DateTime()))


def downgrade() -> None:
    if 'billed_at' in _cols('wa_messages'):
        with op.batch_alter_table('wa_messages') as b:
            b.drop_column('billed_at')
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for name in ('wa_message_price', 'wa_trappi'):
            if name in have:
                b.drop_column(name)
