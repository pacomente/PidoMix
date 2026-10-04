"""logistica (zonas de la flota y tarifas por km), pagos online, movimientos de dinero, rendiciones,
liquidaciones, datos de cobro de repartidores y auditoria

Revision ID: 0013_logistics_payments
Revises: 0012_commercial_plans
Create Date: 2026-10-04

Solo agrega columnas opcionales (o con valor por defecto) y tablas nuevas. No recalcula ni toca
pedidos existentes: los pedidos anteriores quedan sin snapshot logistico y se muestran como antes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_logistics_payments"
down_revision = "0012_commercial_plans"
branch_labels = None
depends_on = None


def store_columns():
    return [
        sa.Column("fleet_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivery_fee_payer", sa.String(10)),
        sa.Column("fee_share_mode", sa.String(10)),
        sa.Column("fee_share_value", sa.Numeric(12, 2)),
        sa.Column("commission_fixed", sa.Numeric(12, 2)),
        sa.Column("commission_min", sa.Numeric(12, 2)),
        sa.Column("commission_max", sa.Numeric(12, 2)),
    ]


def order_columns():
    return [
        sa.Column("delivery_mode", sa.String(10)),
        sa.Column("zone_id", sa.Integer()),
        sa.Column("zone_name", sa.String(120)),
        sa.Column("route_km", sa.Float()),
        sa.Column("route_minutes", sa.Float()),
        sa.Column("route_source", sa.String(20)),
        sa.Column("operational_km", sa.Float()),
        sa.Column("pricing_snapshot", sa.Text()),
        sa.Column("delivery_fee", sa.Numeric(12, 2)),
        sa.Column("delivery_fee_customer", sa.Numeric(12, 2)),
        sa.Column("delivery_fee_merchant", sa.Numeric(12, 2)),
        sa.Column("delivery_fee_trappi", sa.Numeric(12, 2)),
        sa.Column("operating_cost", sa.Numeric(12, 2)),
        sa.Column("courier_pay_breakdown", sa.Text()),
        sa.Column("payment_processing_fee", sa.Numeric(12, 2)),
        sa.Column("payment_status", sa.String(20)),
        sa.Column("cash_pending", sa.Numeric(12, 2)),
        sa.Column("courier_start_lat", sa.Float()),
        sa.Column("courier_start_lng", sa.Float()),
    ]


def courier_columns():
    return [
        sa.Column("cash_limit", sa.Numeric(12, 2)),
        sa.Column("cash_orders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("online_orders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    ]


def _add(inspector, table, columns):
    existing = {c["name"] for c in inspector.get_columns(table)}
    missing = [c for c in columns if c.name not in existing]
    if missing:
        with op.batch_alter_table(table) as batch:
            for column in missing:
                batch.add_column(column)


def _created(name, tables, *columns, indexes=()):
    if name in tables:
        return
    op.create_table(name, *columns)
    for idx_name, cols, unique in indexes:
        op.create_index(idx_name, name, cols, unique=unique)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    _add(inspector, "stores", store_columns())
    _add(inspector, "orders", order_columns())
    _add(inspector, "couriers", courier_columns())
    tables = set(inspector.get_table_names())
    money = lambda name, **kw: sa.Column(name, sa.Numeric(12, 2), **kw)  # noqa: E731
    now = lambda: sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now())  # noqa: E731

    _created("logistics_zones", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("name", sa.String(120), nullable=False),
             sa.Column("description", sa.Text()),
             sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
             sa.Column("color", sa.String(9), nullable=False, server_default="#6C2BD9"),
             sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
             sa.Column("kind", sa.String(10), nullable=False, server_default="radius"),
             sa.Column("center_lat", sa.Float()), sa.Column("center_lng", sa.Float()), sa.Column("radius_km", sa.Float()),
             sa.Column("polygon", sa.Text()),
             sa.Column("max_km", sa.Float()),
             money("base_fee", nullable=False, server_default="0"),
             sa.Column("included_km", sa.Float(), nullable=False, server_default="0"),
             money("per_km", nullable=False, server_default="0"),
             money("min_fee", nullable=False, server_default="0"),
             money("max_fee"),
             money("rounding", nullable=False, server_default="0"),
             sa.Column("days", sa.String(7), nullable=False, server_default="0123456"),
             sa.Column("start_time", sa.String(5)), sa.Column("end_time", sa.String(5)),
             sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
             now(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    _created("logistics_zone_versions", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("zone_id", sa.Integer(), sa.ForeignKey("logistics_zones.id"), nullable=False),
             sa.Column("data", sa.Text(), nullable=False),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
             now(), indexes=[("ix_logistics_zone_versions_zone_id", ["zone_id"], False)])
    _created("mp_accounts", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
             sa.Column("mp_user_id", sa.String(40), nullable=False),
             sa.Column("nickname", sa.String(120)),
             sa.Column("access_token_enc", sa.Text()), sa.Column("refresh_token_enc", sa.Text()),
             sa.Column("public_key", sa.String(120)),
             sa.Column("live_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
             sa.Column("expires_at", sa.DateTime()),
             sa.Column("status", sa.String(15), nullable=False, server_default="connected"),
             sa.Column("connected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
             sa.Column("last_sync_at", sa.DateTime()), sa.Column("last_error", sa.String(255)),
             indexes=[("ix_mp_accounts_store_id", ["store_id"], True), ("ix_mp_accounts_mp_user_id", ["mp_user_id"], False)])
    _created("payments", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
             sa.Column("provider", sa.String(20), nullable=False, server_default="mercadopago"),
             sa.Column("provider_payment_id", sa.String(40)),
             sa.Column("preference_id", sa.String(80)),
             sa.Column("checkout_url", sa.String(1000)),
             sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
             money("amount", nullable=False),
             sa.Column("currency", sa.String(3), nullable=False, server_default="ARS"),
             money("marketplace_fee", nullable=False, server_default="0"),
             money("seller_amount"), money("processing_fee"),
             money("refunded_amount", nullable=False, server_default="0"),
             sa.Column("payment_method", sa.String(40)),
             sa.Column("external_status", sa.String(60)),
             sa.Column("live_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
             sa.Column("approved_at", sa.DateTime()), sa.Column("rejected_at", sa.DateTime()),
             sa.Column("refunded_at", sa.DateTime()), sa.Column("expires_at", sa.DateTime()),
             now(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
             indexes=[("ix_payments_order_id", ["order_id"], False), ("ux_payments_provider_id", ["provider", "provider_payment_id"], True)])
    _created("payment_events", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("provider", sa.String(20), nullable=False, server_default="mercadopago"),
             sa.Column("event_key", sa.String(160), nullable=False, unique=True),
             sa.Column("topic", sa.String(40)), sa.Column("resource_id", sa.String(60)),
             sa.Column("payload", sa.Text()), sa.Column("result", sa.String(255)), now())
    _created("cash_remittances", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
             money("expected", nullable=False), money("received", nullable=False), money("difference", nullable=False),
             sa.Column("order_ids", sa.Text()), sa.Column("receipt", sa.String(1000)), sa.Column("notes", sa.Text()),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), now(),
             indexes=[("ix_cash_remittances_courier_id", ["courier_id"], False)])
    _created("merchant_settlements", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
             money("total", nullable=False),
             sa.Column("entries_count", sa.Integer(), nullable=False, server_default="0"),
             sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
             sa.Column("method", sa.String(40)), sa.Column("receipt", sa.String(1000)), sa.Column("notes", sa.Text()),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), now(), sa.Column("paid_at", sa.DateTime()),
             indexes=[("ix_merchant_settlements_store_id", ["store_id"], False)])
    _created("courier_payout_accounts", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
             sa.Column("holder", sa.String(160), nullable=False),
             sa.Column("provider", sa.String(80)),
             sa.Column("cbu_enc", sa.Text()), sa.Column("cvu_enc", sa.Text()),
             sa.Column("last4", sa.String(4)), sa.Column("alias", sa.String(60)), sa.Column("account_type", sa.String(30)),
             sa.Column("verification", sa.String(12), nullable=False, server_default="pendiente"),
             sa.Column("current", sa.Boolean(), nullable=False, server_default=sa.true()),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), now(),
             indexes=[("ix_courier_payout_accounts_courier_id", ["courier_id"], False)])
    _created("courier_settlements", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id"), nullable=False),
             money("earnings", nullable=False), money("bonuses", nullable=False, server_default="0"),
             money("adjustments", nullable=False, server_default="0"), money("total", nullable=False),
             sa.Column("entries_count", sa.Integer(), nullable=False, server_default="0"),
             sa.Column("method", sa.String(40)), sa.Column("account_masked", sa.String(120)),
             sa.Column("payout_account_id", sa.Integer(), sa.ForeignKey("courier_payout_accounts.id")),
             sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
             sa.Column("receipt", sa.String(1000)), sa.Column("notes", sa.Text()),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), now(), sa.Column("paid_at", sa.DateTime()),
             indexes=[("ix_courier_settlements_courier_id", ["courier_id"], False)])
    _created("ledger_entries", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("account", sa.String(20), nullable=False),
             sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id")),
             sa.Column("courier_id", sa.Integer(), sa.ForeignKey("couriers.id")),
             sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
             sa.Column("kind", sa.String(30), nullable=False),
             money("amount", nullable=False),
             sa.Column("description", sa.String(255)),
             sa.Column("dedupe_key", sa.String(160), unique=True),
             sa.Column("settled", sa.Boolean(), nullable=False, server_default=sa.false()),
             sa.Column("merchant_settlement_id", sa.Integer(), sa.ForeignKey("merchant_settlements.id")),
             sa.Column("courier_settlement_id", sa.Integer(), sa.ForeignKey("courier_settlements.id")),
             sa.Column("remittance_id", sa.Integer(), sa.ForeignKey("cash_remittances.id")),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), now(),
             indexes=[("ix_ledger_entries_account", ["account"], False), ("ix_ledger_entries_store_id", ["store_id"], False),
                      ("ix_ledger_entries_courier_id", ["courier_id"], False), ("ix_ledger_entries_order_id", ["order_id"], False),
                      ("ix_ledger_entries_merchant_settlement_id", ["merchant_settlement_id"], False),
                      ("ix_ledger_entries_courier_settlement_id", ["courier_settlement_id"], False),
                      ("ix_ledger_entries_remittance_id", ["remittance_id"], False)])
    _created("audit_logs", tables,
             sa.Column("id", sa.Integer(), primary_key=True),
             sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
             sa.Column("action", sa.String(60), nullable=False),
             sa.Column("entity", sa.String(40), nullable=False),
             sa.Column("entity_id", sa.String(40)),
             money("amount_old"), money("amount_new"),
             sa.Column("old_value", sa.Text()), sa.Column("new_value", sa.Text()),
             sa.Column("reason", sa.String(255)), sa.Column("ip", sa.String(64)), now(),
             indexes=[("ix_audit_logs_user_id", ["user_id"], False), ("ix_audit_logs_entity", ["entity"], False),
                      ("ix_audit_logs_created_at", ["created_at"], False)])


def downgrade():
    for table in ("audit_logs", "ledger_entries", "courier_settlements", "courier_payout_accounts", "merchant_settlements",
                  "cash_remittances", "payment_events", "payments", "mp_accounts", "logistics_zone_versions", "logistics_zones"):
        op.drop_table(table)
    for table, columns in (("couriers", courier_columns()), ("orders", order_columns()), ("stores", store_columns())):
        with op.batch_alter_table(table) as batch:
            for column in reversed(columns):
                batch.drop_column(column.name)
