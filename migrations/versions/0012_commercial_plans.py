"""modelo comercial: plan de cada comercio, condiciones en cada pedido, historial y abonos

Revision ID: 0012_commercial_plans
Revises: 0011_payment_pin
Create Date: 2026-10-04

Solo agrega columnas (todas opcionales o con valor por defecto) y dos tablas nuevas: no toca ni
recalcula pedidos existentes. Los comercios actuales quedan "activos" y sin plan asignado, con el
mismo comportamiento de hoy (sin comision), hasta que el administrador les asigne uno.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_commercial_plans"
down_revision = "0011_payment_pin"
branch_labels = None
depends_on = None


def store_columns():
    return [
        sa.Column("plan", sa.String(30), nullable=True),
        sa.Column("monthly_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("commission_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("logistics", sa.String(10), nullable=True),
        sa.Column("account_status", sa.String(20), nullable=False, server_default="activo"),
        sa.Column("plan_started_at", sa.DateTime(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("owner_name", sa.String(160), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("commercial_notes", sa.Text(), nullable=True),
    ]


def order_columns():
    return [
        sa.Column("plan", sa.String(30), nullable=True),
        sa.Column("commission_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("logistics", sa.String(10), nullable=True),
        sa.Column("store_net", sa.Numeric(12, 2), nullable=True),
        sa.Column("trappi_income", sa.Numeric(12, 2), nullable=True),
    ]


def _add(inspector, table, columns):
    existing = {c["name"] for c in inspector.get_columns(table)}
    missing = [c for c in columns if c.name not in existing]
    if missing:
        with op.batch_alter_table(table) as batch:
            for column in missing:
                batch.add_column(column)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    _add(inspector, "stores", store_columns())
    _add(inspector, "orders", order_columns())
    tables = inspector.get_table_names()
    if "store_plan_changes" not in tables:
        op.create_table(
            "store_plan_changes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
            sa.Column("from_plan", sa.String(30)),
            sa.Column("to_plan", sa.String(30)),
            sa.Column("monthly_fee", sa.Numeric(12, 2)),
            sa.Column("commission_rate", sa.Numeric(5, 2)),
            sa.Column("logistics", sa.String(10)),
            sa.Column("note", sa.String(255)),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_store_plan_changes_store_id", "store_plan_changes", ["store_id"])
    if "subscription_payments" not in tables:
        op.create_table(
            "subscription_payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="pendiente"),
            sa.Column("paid_at", sa.DateTime()),
            sa.Column("note", sa.String(255)),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_subscription_payments_store_id", "subscription_payments", ["store_id"])
        op.create_index("ux_subscription_store_period", "subscription_payments", ["store_id", "period"], unique=True)


def downgrade():
    op.drop_table("subscription_payments")
    op.drop_table("store_plan_changes")
    with op.batch_alter_table("orders") as batch:
        for column in reversed(order_columns()):
            batch.drop_column(column.name)
    with op.batch_alter_table("stores") as batch:
        for column in reversed(store_columns()):
            batch.drop_column(column.name)
