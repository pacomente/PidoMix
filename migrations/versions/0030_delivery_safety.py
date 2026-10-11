"""Seguridad de la entrega: llegada del cadete a la puerta, fotos de prueba y chat del pedido.

Revision ID: 0030_delivery_safety
Revises: 0029_surge
"""
import sqlalchemy as sa
from alembic import op

revision = '0030_delivery_safety'
down_revision = '0029_surge'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'order_photos' not in tables:
        op.create_table(
            'order_photos',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
            sa.Column('kind', sa.String(20), nullable=False),
            sa.Column('sender', sa.String(10), nullable=False),
            sa.Column('mime', sa.String(30), nullable=False),
            sa.Column('content', sa.LargeBinary(), nullable=False),
            sa.Column('width', sa.Integer(), nullable=False),
            sa.Column('height', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_order_photos_order_id', 'order_photos', ['order_id'])
        op.create_index('ix_order_photos_created_at', 'order_photos', ['created_at'])
    if 'order_messages' not in tables:
        op.create_table(
            'order_messages',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
            sa.Column('thread', sa.String(10), nullable=False),
            sa.Column('sender', sa.String(10), nullable=False),
            sa.Column('text', sa.Text()),
            sa.Column('photo_id', sa.Integer()),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_order_messages_order_thread', 'order_messages', ['order_id', 'thread', 'id'])
    cols = {c['name'] for c in insp.get_columns('orders')}
    with op.batch_alter_table('orders') as batch:
        if 'courier_arrived_at' not in cols:
            batch.add_column(sa.Column('courier_arrived_at', sa.DateTime()))
        if 'proof_photo_id' not in cols:
            batch.add_column(sa.Column('proof_photo_id', sa.Integer()))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('orders')}
    with op.batch_alter_table('orders') as batch:
        if 'proof_photo_id' in cols:
            batch.drop_column('proof_photo_id')
        if 'courier_arrived_at' in cols:
            batch.drop_column('courier_arrived_at')
    tables = insp.get_table_names()
    if 'order_messages' in tables:
        op.drop_index('ix_order_messages_order_thread', 'order_messages')
        op.drop_table('order_messages')
    if 'order_photos' in tables:
        op.drop_index('ix_order_photos_created_at', 'order_photos')
        op.drop_index('ix_order_photos_order_id', 'order_photos')
        op.drop_table('order_photos')
