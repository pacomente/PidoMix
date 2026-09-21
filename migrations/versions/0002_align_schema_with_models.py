"""align initial schema with SQLAlchemy models

Revision ID: 0002_align_schema_with_models
Revises: 0001_initial
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_align_schema_with_models"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    # The original initial migration predated the final mapped_column definitions.
    # Keep the migration additive and non-destructive so existing installations can
    # be upgraded without dropping tables or data.
    with op.batch_alter_table("categories") as batch_op:
        batch_op.alter_column("name", existing_type=sa.String(length=120), nullable=False)
        batch_op.alter_column("slug", existing_type=sa.String(length=140), nullable=False)
        batch_op.create_index("ix_categories_slug", ["slug"], unique=True)

    with op.batch_alter_table("products") as batch_op:
        batch_op.create_index("ix_products_name", ["name"], unique=False)

    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("key", existing_type=sa.String(length=100), nullable=False)

    with op.batch_alter_table("store_categories") as batch_op:
        batch_op.alter_column("name", existing_type=sa.String(length=100), nullable=False)
        batch_op.alter_column("slug", existing_type=sa.String(length=120), nullable=False)
        batch_op.create_index("ix_store_categories_slug", ["slug"], unique=True)

    with op.batch_alter_table("stores") as batch_op:
        batch_op.alter_column("slug", existing_type=sa.String(length=180), nullable=False)
        batch_op.create_index("ix_stores_name", ["name"], unique=False)
        batch_op.create_index("ix_stores_slug", ["slug"], unique=True)

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", existing_type=sa.String(length=255), nullable=False)
        batch_op.create_index("ix_users_email", ["email"], unique=True)


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.alter_column("email", existing_type=sa.String(length=255), nullable=True)

    with op.batch_alter_table("stores") as batch_op:
        batch_op.drop_index("ix_stores_slug")
        batch_op.drop_index("ix_stores_name")
        batch_op.alter_column("slug", existing_type=sa.String(length=180), nullable=True)

    with op.batch_alter_table("store_categories") as batch_op:
        batch_op.drop_index("ix_store_categories_slug")
        batch_op.alter_column("slug", existing_type=sa.String(length=120), nullable=True)
        batch_op.alter_column("name", existing_type=sa.String(length=100), nullable=True)

    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column("key", existing_type=sa.String(length=100), nullable=True)

    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_index("ix_products_name")

    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_index("ix_categories_slug")
        batch_op.alter_column("slug", existing_type=sa.String(length=140), nullable=True)
        batch_op.alter_column("name", existing_type=sa.String(length=120), nullable=True)
