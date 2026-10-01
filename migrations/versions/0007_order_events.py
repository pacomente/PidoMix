"""historial de estados de pedidos

Revision ID: 0007_order_events
Revises: 0006_review_replies
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_order_events"
down_revision = "0006_review_replies"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'order_events' in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        'order_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_order_events_order_id', 'order_events', ['order_id'])
    # Pedidos existentes: se reconstruye lo que se sabe (alta y estado actual).
    op.execute("INSERT INTO order_events (order_id, status, created_at) SELECT id, 'PENDIENTE', created_at FROM orders")
    op.execute("INSERT INTO order_events (order_id, status, created_at) SELECT id, CAST(status AS VARCHAR(20)), updated_at FROM orders WHERE CAST(status AS VARCHAR(20)) <> 'PENDIENTE'")


def downgrade():
    op.drop_index('ix_order_events_order_id', table_name='order_events')
    op.drop_table('order_events')
