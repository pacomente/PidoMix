"""pago del pedido (efectivo/transferencia, pagado o no) y PIN de entrega

Revision ID: 0011_payment_pin
Revises: 0010_couriers
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_payment_pin"
down_revision = "0010_couriers"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("orders")}
    with op.batch_alter_table("orders") as batch:
        if "cash_with" not in columns:
            batch.add_column(sa.Column("cash_with", sa.Numeric(12, 2), nullable=True))
        if "paid_at" not in columns:
            batch.add_column(sa.Column("paid_at", sa.DateTime(), nullable=True))
        if "paid_by" not in columns:
            batch.add_column(sa.Column("paid_by", sa.String(20), nullable=True))
        if "delivery_pin" not in columns:
            batch.add_column(sa.Column("delivery_pin", sa.String(6), nullable=True))
    # los pedidos viejos se coordinaban por WhatsApp y se pagaban al recibir
    op.execute("UPDATE orders SET payment_method = 'efectivo' WHERE payment_method = 'whatsapp' OR payment_method IS NULL")
    if "transfer_alias" not in {c["name"] for c in inspector.get_columns("stores")}:
        with op.batch_alter_table("stores") as batch:
            batch.add_column(sa.Column("transfer_alias", sa.String(120), nullable=True))


def downgrade():
    with op.batch_alter_table("stores") as batch:
        batch.drop_column("transfer_alias")
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("delivery_pin")
        batch.drop_column("paid_by")
        batch.drop_column("paid_at")
        batch.drop_column("cash_with")
