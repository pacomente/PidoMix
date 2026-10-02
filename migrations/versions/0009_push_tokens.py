"""tokens de notificaciones push de la app movil

Revision ID: 0009_push_tokens
Revises: 0008_delivery_zones
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_push_tokens"
down_revision = "0008_delivery_zones"
branch_labels = None
depends_on = None


def upgrade():
    if "push_tokens" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False, server_default="android"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_push_tokens_order_id", "push_tokens", ["order_id"])
    op.create_index("ux_push_tokens_order_token", "push_tokens", ["order_id", "token"], unique=True)


def downgrade():
    op.drop_index("ux_push_tokens_order_token", table_name="push_tokens")
    op.drop_index("ix_push_tokens_order_id", table_name="push_tokens")
    op.drop_table("push_tokens")
