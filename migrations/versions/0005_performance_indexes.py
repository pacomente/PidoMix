"""indices para las consultas frecuentes (FKs y filtros por fecha)

PostgreSQL no indexa automaticamente las foreign keys: sin estos indices, cargar el
menu de una tienda, el tablero de pedidos o el dashboard recorre tablas completas.

Revision ID: 0005_performance_indexes
Revises: 0004_sections_modifiers
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_performance_indexes"
down_revision = "0004_sections_modifiers"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_products_store_id", "products", ["store_id"]),
    ("ix_products_category_id", "products", ["category_id"]),
    ("ix_products_section_id", "products", ["section_id"]),
    ("ix_orders_store_created", "orders", ["store_id", "created_at"]),
    ("ix_orders_created_at", "orders", ["created_at"]),
    ("ix_orders_customer_id", "orders", ["customer_id"]),
    ("ix_order_items_order_id", "order_items", ["order_id"]),
    ("ix_store_hours_store_id", "store_hours", ["store_id"]),
    ("ix_store_sections_store_id", "store_sections", ["store_id"]),
    ("ix_modifier_groups_product_id", "modifier_groups", ["product_id"]),
    ("ix_modifier_options_group_id", "modifier_options", ["group_id"]),
    ("ix_reviews_store_id", "reviews", ["store_id"]),
    ("ix_users_store_id", "users", ["store_id"]),
]


def _existing(bind, table):
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    for name, table, columns in INDEXES:
        if name not in _existing(bind, table):
            op.create_index(name, table, columns)


def downgrade():
    bind = op.get_bind()
    for name, table, _ in reversed(INDEXES):
        if name in _existing(bind, table):
            op.drop_index(name, table_name=table)
