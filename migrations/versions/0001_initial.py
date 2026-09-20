"""initial pidomix schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    role = sa.Enum('SUPERADMIN','STORE_ADMIN','REPARTIDOR','CLIENTE', name='role_enum'); role.create(op.get_bind(), checkfirst=True)
    store_status = sa.Enum('ACTIVA','INACTIVA','CERRADA', name='store_status_enum'); store_status.create(op.get_bind(), checkfirst=True)
    product_status = sa.Enum('ACTIVO','INACTIVO','SIN_STOCK', name='product_status_enum'); product_status.create(op.get_bind(), checkfirst=True)
    order_status = sa.Enum('PENDIENTE','CONFIRMADO','PREPARANDO','LISTO','EN_CAMINO','ENTREGADO','CANCELADO', name='order_status_enum'); order_status.create(op.get_bind(), checkfirst=True)
    op.create_table('store_categories', sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(100),unique=True),sa.Column('slug',sa.String(120),unique=True),sa.Column('active',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('stores', sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(160),nullable=False),sa.Column('slug',sa.String(180),unique=True),sa.Column('description',sa.Text()),sa.Column('phone',sa.String(40)),sa.Column('whatsapp',sa.String(40)),sa.Column('address',sa.String(255)),sa.Column('logo_url',sa.String(1000)),sa.Column('logo_public_id',sa.String(255)),sa.Column('cover_url',sa.String(1000)),sa.Column('cover_public_id',sa.String(255)),sa.Column('delivery_enabled',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('delivery_cost',sa.Numeric(12,2),nullable=False,server_default='0'),sa.Column('minimum_order',sa.Numeric(12,2),nullable=False,server_default='0'),sa.Column('estimated_minutes',sa.Integer(),nullable=False,server_default='30'),sa.Column('status',store_status,nullable=False,server_default='ACTIVA'),sa.Column('featured',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('store_category_id',sa.Integer(),sa.ForeignKey('store_categories.id')),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('users',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('email',sa.String(255),unique=True),sa.Column('password_hash',sa.String(255),nullable=False),sa.Column('role',role,nullable=False,server_default='STORE_ADMIN'),sa.Column('active',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('store_id',sa.Integer(),sa.ForeignKey('stores.id')),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('categories',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(120),unique=True),sa.Column('slug',sa.String(140),unique=True),sa.Column('image_url',sa.String(1000)),sa.Column('image_public_id',sa.String(255)),sa.Column('description',sa.Text()),sa.Column('active',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('display_order',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('products',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(180),nullable=False),sa.Column('description',sa.Text()),sa.Column('price',sa.Numeric(12,2),nullable=False),sa.Column('previous_price',sa.Numeric(12,2)),sa.Column('image_url',sa.String(1000)),sa.Column('image_public_id',sa.String(255)),sa.Column('status',product_status,nullable=False,server_default='ACTIVO'),sa.Column('stock',sa.Integer()),sa.Column('featured',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('display_order',sa.Integer(),nullable=False,server_default='0'),sa.Column('store_id',sa.Integer(),sa.ForeignKey('stores.id'),nullable=False),sa.Column('category_id',sa.Integer(),sa.ForeignKey('categories.id')),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('banners',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('image_url',sa.String(1000)),sa.Column('image_public_id',sa.String(255)),sa.Column('title',sa.String(180)),sa.Column('subtitle',sa.String(255)),sa.Column('button_text',sa.String(80)),sa.Column('link',sa.String(500)),sa.Column('display_order',sa.Integer(),nullable=False,server_default='0'),sa.Column('active',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('store_hours',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('store_id',sa.Integer(),sa.ForeignKey('stores.id'),nullable=False),sa.Column('weekday',sa.Integer(),nullable=False),sa.Column('open_time',sa.String(5),nullable=False),sa.Column('close_time',sa.String(5),nullable=False),sa.Column('closed',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_table('customers',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('first_name',sa.String(100),nullable=False),sa.Column('last_name',sa.String(100),nullable=False),sa.Column('phone',sa.String(40),nullable=False),sa.Column('email',sa.String(255)),sa.Column('address',sa.String(255)),sa.Column('reference',sa.String(255)),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('orders',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('store_id',sa.Integer(),sa.ForeignKey('stores.id'),nullable=False),sa.Column('customer_id',sa.Integer(),sa.ForeignKey('customers.id')),sa.Column('delivery_method',sa.String(30),nullable=False),sa.Column('payment_method',sa.String(30),nullable=False,server_default='whatsapp'),sa.Column('address',sa.String(255)),sa.Column('reference',sa.String(255)),sa.Column('notes',sa.Text()),sa.Column('subtotal',sa.Numeric(12,2),nullable=False),sa.Column('shipping',sa.Numeric(12,2),nullable=False),sa.Column('total',sa.Numeric(12,2),nullable=False),sa.Column('platform_commission',sa.Numeric(12,2),nullable=False,server_default='0'),sa.Column('store_commission',sa.Numeric(12,2),nullable=False,server_default='0'),sa.Column('status',order_status,nullable=False,server_default='PENDIENTE'),sa.Column('whatsapp_url',sa.String(2000)),sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False))
    op.create_table('order_items',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('order_id',sa.Integer(),sa.ForeignKey('orders.id'),nullable=False),sa.Column('product_id',sa.Integer(),sa.ForeignKey('products.id'),nullable=False),sa.Column('product_name',sa.String(180),nullable=False),sa.Column('unit_price',sa.Numeric(12,2),nullable=False),sa.Column('quantity',sa.Integer(),nullable=False))
    op.create_table('settings',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('key',sa.String(100),unique=True),sa.Column('value',sa.Text()))


def downgrade():
    for t in ['settings','order_items','orders','customers','store_hours','banners','products','categories','users','stores','store_categories']:
        op.drop_table(t)
    for name in ['order_status_enum','product_status_enum','store_status_enum','role_enum']:
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
