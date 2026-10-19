"""Solicitudes de comercios que se quieren sumar (formulario público /sumate).

Revision ID: 0036_merchant_applications
Revises: 0035_rides
"""
import sqlalchemy as sa
from alembic import op

revision = '0036_merchant_applications'
down_revision = '0035_rides'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'merchant_applications' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        'merchant_applications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(16), nullable=False),
        sa.Column('status', sa.String(12), nullable=False, server_default='nueva'),
        sa.Column('store_name', sa.String(160), nullable=False),
        sa.Column('store_category_id', sa.Integer(), sa.ForeignKey('store_categories.id', ondelete='SET NULL')),
        sa.Column('category_other', sa.String(100)), sa.Column('food_types', sa.String(400)),
        sa.Column('province', sa.String(60), nullable=False), sa.Column('city_name', sa.String(120), nullable=False),
        sa.Column('city_id', sa.Integer(), sa.ForeignKey('cities.id', ondelete='SET NULL')),
        sa.Column('postal_code', sa.String(10), nullable=False), sa.Column('address', sa.String(255), nullable=False),
        sa.Column('address_extra', sa.String(120)),
        sa.Column('owner_name', sa.String(160), nullable=False), sa.Column('owner_whatsapp', sa.String(40), nullable=False),
        sa.Column('email', sa.String(255), nullable=False), sa.Column('store_phone', sa.String(40)), sa.Column('instagram', sa.String(120)),
        sa.Column('cuit', sa.String(20)), sa.Column('delivery', sa.String(12)), sa.Column('hours', sa.String(200)),
        sa.Column('comments', sa.Text()), sa.Column('admin_note', sa.Text()),
        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id', ondelete='SET NULL')),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('reviewed_at', sa.DateTime()), sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_merchant_applications_code', 'merchant_applications', ['code'], unique=True)
    op.create_index('ix_merchant_applications_status', 'merchant_applications', ['status'])


def downgrade() -> None:
    if 'merchant_applications' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('merchant_applications')
