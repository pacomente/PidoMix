"""Agente de WhatsApp de cada local: conexion del numero (stores.wa_*), conversaciones y mensajes,
y el pedido que armo el agente (orders.wa_conversation_id).

Revision ID: 0040_whatsapp_agent
Revises: 0039_pos_salon
"""
import sqlalchemy as sa
from alembic import op

revision = '0040_whatsapp_agent'
down_revision = '0039_pos_salon'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


STORE_COLS = [
    ('wa_enabled', lambda: sa.Column('wa_enabled', sa.Boolean(), nullable=False, server_default=sa.false())),
    ('wa_phone_id', lambda: sa.Column('wa_phone_id', sa.String(40))),
    ('wa_waba_id', lambda: sa.Column('wa_waba_id', sa.String(40))),
    ('wa_number', lambda: sa.Column('wa_number', sa.String(30))),
    ('wa_token', lambda: sa.Column('wa_token', sa.Text())),
    ('wa_connected_at', lambda: sa.Column('wa_connected_at', sa.DateTime())),
    ('wa_agent_on', lambda: sa.Column('wa_agent_on', sa.Boolean(), nullable=False, server_default=sa.true())),
    ('wa_alerts', lambda: sa.Column('wa_alerts', sa.Text())),
]


def upgrade() -> None:
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        for name, col in STORE_COLS:
            if name not in have:
                b.add_column(col())
        if 'wa_phone_id' not in have:
            b.create_unique_constraint('uq_stores_wa_phone_id', ['wa_phone_id'])
    tables = _tables()
    if 'wa_conversations' not in tables:
        op.create_table(
            'wa_conversations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('wa_id', sa.String(20), nullable=False),
            sa.Column('name', sa.String(80)),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id')),
            sa.Column('mode', sa.String(10), nullable=False, server_default='agent'),
            sa.Column('needs', sa.String(10)),
            sa.Column('needs_note', sa.String(200)),
            sa.Column('cart', sa.Text()),
            sa.Column('plan', sa.Text()),
            sa.Column('history', sa.Text()),
            sa.Column('last_in_at', sa.DateTime()),
            sa.Column('last_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_wa_conversations_store_id', 'wa_conversations', ['store_id'])
        op.create_index('ix_wa_conversations_account_id', 'wa_conversations', ['account_id'])
        op.create_index('ux_wa_conv_store_wa', 'wa_conversations', ['store_id', 'wa_id'], unique=True)
    if 'wa_messages' not in tables:
        op.create_table(
            'wa_messages',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('conversation_id', sa.Integer(), sa.ForeignKey('wa_conversations.id'), nullable=False),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('direction', sa.String(3), nullable=False),
            sa.Column('author', sa.String(10), nullable=False),
            sa.Column('text', sa.Text(), nullable=False, server_default=''),
            sa.Column('wa_message_id', sa.String(120), unique=True),
            sa.Column('status', sa.String(12)),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_wa_messages_conversation_id', 'wa_messages', ['conversation_id'])
        op.create_index('ix_wa_messages_store_id', 'wa_messages', ['store_id'])
    if 'wa_conversation_id' not in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.add_column(sa.Column('wa_conversation_id', sa.Integer(), sa.ForeignKey('wa_conversations.id', name='fk_orders_wa_conversation_id')))
            b.create_index('ix_orders_wa_conversation_id', ['wa_conversation_id'])


def downgrade() -> None:
    if 'wa_conversation_id' in _cols('orders'):
        with op.batch_alter_table('orders') as b:
            b.drop_index('ix_orders_wa_conversation_id')
            b.drop_constraint('fk_orders_wa_conversation_id', type_='foreignkey')
            b.drop_column('wa_conversation_id')
    tables = _tables()
    if 'wa_messages' in tables:
        op.drop_table('wa_messages')
    if 'wa_conversations' in tables:
        op.drop_table('wa_conversations')
    have = _cols('stores')
    with op.batch_alter_table('stores') as b:
        if 'wa_phone_id' in have:
            b.drop_constraint('uq_stores_wa_phone_id', type_='unique')
        for name, _ in reversed(STORE_COLS):
            if name in have:
                b.drop_column(name)
