"""Trappi Viajes: empresas de viajes con su flota, tarifas por vehiculo, viajes y ofertas a conductores.

Revision ID: 0035_rides
Revises: 0034_own_batch
"""
import sqlalchemy as sa
from alembic import op

revision = '0035_rides'
down_revision = '0034_own_batch'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'RIDE_ADMIN'")
    have = _tables()
    if 'ride_companies' not in have:
        op.create_table(
            'ride_companies',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(160), nullable=False),
            sa.Column('slug', sa.String(180), nullable=False),
            sa.Column('city_id', sa.Integer(), sa.ForeignKey('cities.id'), nullable=True),
            sa.Column('phone', sa.String(40)), sa.Column('address', sa.String(255)), sa.Column('logo_url', sa.String(1000)),
            sa.Column('status', sa.String(16), nullable=False, server_default='pendiente'),
            sa.Column('legal_name', sa.String(200)), sa.Column('cuit', sa.String(20)), sa.Column('municipal_license', sa.String(80)),
            sa.Column('insurance_company', sa.String(120)), sa.Column('insurance_policy', sa.String(80)), sa.Column('insurance_expires', sa.Date()),
            sa.Column('approved_at', sa.DateTime()), sa.Column('approved_by', sa.Integer()), sa.Column('review_note', sa.String(500)),
            sa.Column('plan', sa.String(16), nullable=False, server_default='inicial'),
            sa.Column('monthly_fee', sa.Numeric(12, 2)), sa.Column('driver_cap', sa.Integer()), sa.Column('extra_driver_fee', sa.Numeric(12, 2)),
            sa.Column('rating_avg', sa.Numeric(3, 2)), sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_ride_companies_slug', 'ride_companies', ['slug'], unique=True)
        op.create_index('ix_ride_companies_city_id', 'ride_companies', ['city_id'])
    if 'ride_tariffs' not in have:
        op.create_table(
            'ride_tariffs',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('ride_companies.id', ondelete='CASCADE'), nullable=False),
            sa.Column('vehicle', sa.String(10), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('base', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('per_km', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('per_wait_min', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('minimum', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('night_percent', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_ride_tariffs_company_id', 'ride_tariffs', ['company_id'])
        op.create_index('ux_ride_tariffs_company_vehicle', 'ride_tariffs', ['company_id', 'vehicle'], unique=True)
    ucols = _cols('users')
    if 'ride_company_id' not in ucols:
        with op.batch_alter_table('users') as b:
            b.add_column(sa.Column('ride_company_id', sa.Integer(), nullable=True))
            b.create_foreign_key('fk_users_ride_company', 'ride_companies', ['ride_company_id'], ['id'])
            b.create_index('ix_users_ride_company_id', ['ride_company_id'])
    ccols = _cols('couriers')
    with op.batch_alter_table('couriers') as b:
        if 'ride_company_id' not in ccols:
            b.add_column(sa.Column('ride_company_id', sa.Integer(), nullable=True))
            b.create_foreign_key('fk_couriers_ride_company', 'ride_companies', ['ride_company_id'], ['id'])
            b.create_index('ix_couriers_ride_company_id', ['ride_company_id'])
        if 'plate' not in ccols:
            b.add_column(sa.Column('plate', sa.String(12)))
        if 'car_model' not in ccols:
            b.add_column(sa.Column('car_model', sa.String(80)))
        if 'rating_avg' not in ccols:
            b.add_column(sa.Column('rating_avg', sa.Numeric(3, 2)))
        if 'rating_count' not in ccols:
            b.add_column(sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'))
    if 'rides' not in have:
        op.create_table(
            'rides',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('ride_companies.id'), nullable=False),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', ondelete='SET NULL'), nullable=True),
            sa.Column('courier_id', sa.Integer(), sa.ForeignKey('couriers.id'), nullable=True),
            sa.Column('vehicle', sa.String(10), nullable=False),
            sa.Column('status', sa.String(16), nullable=False, server_default='buscando'),
            sa.Column('passenger_name', sa.String(160)), sa.Column('passenger_phone', sa.String(40)),
            sa.Column('origin_address', sa.String(255)), sa.Column('origin_lat', sa.Float(), nullable=False), sa.Column('origin_lng', sa.Float(), nullable=False),
            sa.Column('origin_note', sa.String(160)),
            sa.Column('dest_address', sa.String(255)), sa.Column('dest_lat', sa.Float(), nullable=False), sa.Column('dest_lng', sa.Float(), nullable=False),
            sa.Column('km', sa.Float(), nullable=False), sa.Column('minutes', sa.Float()),
            sa.Column('route_estimated', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('tariff_snapshot', sa.Text()), sa.Column('night', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('price', sa.Numeric(12, 2), nullable=False), sa.Column('wait_charge', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('final_price', sa.Numeric(12, 2)),
            sa.Column('payment_method', sa.String(20), nullable=False, server_default='efectivo'),
            sa.Column('pin', sa.String(6), nullable=False), sa.Column('search_from', sa.DateTime(), nullable=False),
            sa.Column('assigned_at', sa.DateTime()), sa.Column('arrived_at', sa.DateTime()), sa.Column('started_at', sa.DateTime()),
            sa.Column('finished_at', sa.DateTime()), sa.Column('cancelled_at', sa.DateTime()),
            sa.Column('cancelled_by', sa.String(12)), sa.Column('cancel_reason', sa.String(200)),
            sa.Column('rating', sa.Integer()), sa.Column('rating_tags', sa.String(200)), sa.Column('rating_comment', sa.String(500)),
            sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_rides_company_id', 'rides', ['company_id'])
        op.create_index('ix_rides_account_id', 'rides', ['account_id'])
        op.create_index('ix_rides_company_status', 'rides', ['company_id', 'status'])
        op.create_index('ix_rides_courier_status', 'rides', ['courier_id', 'status'])
    if 'ride_offers' not in have:
        op.create_table(
            'ride_offers',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('ride_id', sa.Integer(), sa.ForeignKey('rides.id', ondelete='CASCADE'), nullable=False),
            sa.Column('courier_id', sa.Integer(), sa.ForeignKey('couriers.id'), nullable=False),
            sa.Column('status', sa.String(12), nullable=False, server_default='pending'),
            sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('expires_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_ride_offers_ride_id', 'ride_offers', ['ride_id'])
        op.create_index('ix_ride_offers_courier_status', 'ride_offers', ['courier_id', 'status'])


def downgrade() -> None:
    have = _tables()
    for t in ('ride_offers', 'rides'):
        if t in have:
            op.drop_table(t)
    ccols = _cols('couriers')
    with op.batch_alter_table('couriers') as b:
        if 'ride_company_id' in ccols:
            b.drop_index('ix_couriers_ride_company_id')
            b.drop_constraint('fk_couriers_ride_company', type_='foreignkey')
        for col in ('rating_count', 'rating_avg', 'car_model', 'plate', 'ride_company_id'):
            if col in ccols:
                b.drop_column(col)
    if 'ride_company_id' in _cols('users'):
        with op.batch_alter_table('users') as b:
            b.drop_index('ix_users_ride_company_id')
            b.drop_constraint('fk_users_ride_company', type_='foreignkey')
            b.drop_column('ride_company_id')
    for t in ('ride_tariffs', 'ride_companies'):
        if t in have:
            op.drop_table(t)
    # el valor RIDE_ADMIN de role_enum queda (PostgreSQL no permite borrar valores de un enum); no se usa
