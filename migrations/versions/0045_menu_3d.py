"""Menu en 3D ("Ver en tu mesa"): stores.ar_enabled y el modelo 3D de cada producto (products.model_*).

Revision ID: 0045_menu_3d
Revises: 0044_wa_billing
"""
import sqlalchemy as sa
from alembic import op

revision = '0045_menu_3d'
down_revision = '0044_wa_billing'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


PRODUCT_COLS = [
    ('model_url', lambda: sa.Column('model_url', sa.String(1000))),
    ('model_public_id', lambda: sa.Column('model_public_id', sa.String(255))),
    ('model_ios_url', lambda: sa.Column('model_ios_url', sa.String(1000))),
    ('model_ios_public_id', lambda: sa.Column('model_ios_public_id', sa.String(255))),
    ('model_visible', lambda: sa.Column('model_visible', sa.Boolean(), nullable=False, server_default=sa.true())),
]


def upgrade() -> None:
    if 'ar_enabled' not in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.add_column(sa.Column('ar_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    have = _cols('products')
    with op.batch_alter_table('products') as b:
        for name, col in PRODUCT_COLS:
            if name not in have:
                b.add_column(col())


def downgrade() -> None:
    have = _cols('products')
    with op.batch_alter_table('products') as b:
        for name, _ in reversed(PRODUCT_COLS):
            if name in have:
                b.drop_column(name)
    if 'ar_enabled' in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.drop_column('ar_enabled')
