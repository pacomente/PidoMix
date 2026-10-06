"""Verify that the deployed PostgreSQL schema is ready for PidoMix.

This command is intentionally separate from the seed: Alembic owns schema
creation, and this module only proves that Alembic reached the expected head
and that the tables used by the application exist before the seed runs.
"""

from pathlib import Path
from urllib.parse import urlsplit

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from .config import settings
from .db import engine, normalize_database_url


REQUIRED_TABLES = {
    "users",
    "stores",
    "store_categories",
    "categories",
    "products",
    "banners",
    "store_hours",
    "customers",
    "orders",
    "order_items",
    "settings",
    "coupons",
    "reviews",
    "store_sections",
    "modifier_groups",
    "modifier_options",
    "store_plan_changes",
    "subscription_payments",
    "logistics_zones",
    "logistics_zone_versions",
    "mp_accounts",
    "payments",
    "payment_events",
    "ledger_entries",
    "cash_remittances",
    "merchant_settlements",
    "courier_settlements",
    "courier_payout_accounts",
    "audit_logs",
    "cities",
    "auth_attempts",
}


def _safe_target(url: str) -> str:
    parsed = urlsplit(normalize_database_url(url))
    host = parsed.hostname or "unknown-host"
    database = (parsed.path or "").lstrip("/") or "unknown-database"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}/{database}"


def verify_database() -> None:
    print(f"[DB] verificando PostgreSQL: {_safe_target(settings.database_url)}")
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        if connection.dialect.name == "postgresql":
            database_name, schema_name = connection.execute(
                text("SELECT current_database(), current_schema()")
            ).one()
            print(f"[DB] database={database_name} schema={schema_name}")

        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError(
                "[MIGRATIONS] faltan tablas después de alembic upgrade head: "
                + ", ".join(missing)
            )

        alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        script = ScriptDirectory.from_config(alembic_config)
        expected_heads = set(script.get_heads())
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
        if current_heads != expected_heads:
            raise RuntimeError(
                f"[MIGRATIONS] revision incorrecta: actual={sorted(current_heads)} "
                f"esperada={sorted(expected_heads)}"
            )

        print(
            f"[MIGRATIONS] upgrade head verificado; "
            f"revision={sorted(current_heads)}; tablas={len(tables)}"
        )
        print("[MIGRATIONS] users existe y PostgreSQL está listo para el seed")


if __name__ == "__main__":
    verify_database()
    print("[DB] verificación completada")
