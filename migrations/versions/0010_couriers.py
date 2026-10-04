"""repartidores, ofertas de viajes y repartidor asignado a cada pedido

Revision ID: 0010_couriers
Revises: 0009_push_tokens
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_couriers"
down_revision = "0009_push_tokens"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "couriers" not in tables:
        op.create_table(
            "couriers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("phone", sa.String(40), nullable=False),
            sa.Column("pin_hash", sa.String(255), nullable=False),
            sa.Column("vehicle", sa.String(20), nullable=False, server_default="moto"),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("lat", sa.Float()),
            sa.Column("lng", sa.Float()),
            sa.Column("location_at", sa.DateTime()),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("push_token", sa.String(512)),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_couriers_phone", "couriers", ["phone"], unique=True)
        op.create_index("ix_couriers_store_id", "couriers", ["store_id"])
    if "delivery_offers" not in tables:
        op.create_table(
            "delivery_offers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
            sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_delivery_offers_order_id", "delivery_offers", ["order_id"])
        op.create_index("ix_delivery_offers_courier_status", "delivery_offers", ["courier_id", "status"])
    columns = {c["name"] for c in sa.inspect(bind).get_columns("orders")}
    with op.batch_alter_table("orders") as batch:
        if "courier_id" not in columns:
            batch.add_column(sa.Column("courier_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_orders_courier_id", "couriers", ["courier_id"], ["id"])
            batch.create_index("ix_orders_courier_id", ["courier_id"])
        if "courier_assigned_at" not in columns:
            batch.add_column(sa.Column("courier_assigned_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_courier_id")
        batch.drop_constraint("fk_orders_courier_id", type_="foreignkey")
        batch.drop_column("courier_assigned_at")
        batch.drop_column("courier_id")
    op.drop_table("delivery_offers")
    op.drop_table("couriers")
