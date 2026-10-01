"""reseñas: respuesta del local y moderacion

Revision ID: 0006_review_replies
Revises: 0005_performance_indexes
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_review_replies"
down_revision = "0005_performance_indexes"
branch_labels = None
depends_on = None


def _column_exists(bind, table, column) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if not _column_exists(bind, 'reviews', 'reply'):
        op.add_column('reviews', sa.Column('reply', sa.Text()))
    if not _column_exists(bind, 'reviews', 'replied_at'):
        op.add_column('reviews', sa.Column('replied_at', sa.DateTime()))
    if not _column_exists(bind, 'reviews', 'hidden'):
        op.add_column('reviews', sa.Column('hidden', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    bind = op.get_bind()
    for column in ('hidden', 'replied_at', 'reply'):
        if _column_exists(bind, 'reviews', column):
            with op.batch_alter_table('reviews') as batch_op:
                batch_op.drop_column(column)
