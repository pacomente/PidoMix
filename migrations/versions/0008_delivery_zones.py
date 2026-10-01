"""zonas de entrega y geolocalizacion

Revision ID: 0008_delivery_zones
Revises: 0007_order_events
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_delivery_zones"
down_revision = "0007_order_events"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    for table, cols in (("stores", ("lat", "lng")), ("orders", ("lat", "lng", "distance_km"))):
        existing = _columns(bind, table)
        for col in cols:
            if col not in existing:
                op.add_column(table, sa.Column(col, sa.Float()))
    if "delivery_zones" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "delivery_zones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
            sa.Column("max_km", sa.Numeric(5, 2), nullable=False),
            sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        )
        op.create_index("ix_delivery_zones_store_id", "delivery_zones", ["store_id"])


def downgrade():
    op.drop_index("ix_delivery_zones_store_id", table_name="delivery_zones")
    op.drop_table("delivery_zones")
    for table, cols in (("orders", ("distance_km", "lng", "lat")), ("stores", ("lng", "lat"))):
        with op.batch_alter_table(table) as batch_op:
            for col in cols:
                batch_op.drop_column(col)
