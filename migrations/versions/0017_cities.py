"""Multi-ciudad.

- cities: ciudades donde opera Trappi (centro, radio para reconocerla por la ubicacion, contacto).
- city_id en stores, couriers, logistics_zones y orders.
- Se crea la ciudad principal (la de MAP_DEFAULT_CENTER; por defecto Bahia Blanca) y se le asigna
  todo lo que ya existe, asi nada cambia para los clientes ni para los comercios actuales.

Revision ID: 0017_cities
Revises: 0016_failed_delivery
"""
import os
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = '0017_cities'
down_revision = '0016_failed_delivery'
branch_labels = None
depends_on = None

TABLES = ('stores', 'couriers', 'logistics_zones', 'orders')


def _default_center() -> tuple[float, float]:
    try:
        lat, lng = (float(x) for x in os.environ.get('MAP_DEFAULT_CENTER', '-38.7183,-62.2663').split(','))
        return lat, lng
    except ValueError:
        return -38.7183, -62.2663


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'cities' not in inspector.get_table_names():
        op.create_table(
            'cities',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('slug', sa.String(140), nullable=False),
            sa.Column('province', sa.String(120)),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('center_lat', sa.Float(), nullable=False),
            sa.Column('center_lng', sa.Float(), nullable=False),
            sa.Column('radius_km', sa.Float(), nullable=False, server_default='25'),
            sa.Column('whatsapp', sa.String(40)),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_cities_slug', 'cities', ['slug'], unique=True)
    for table in TABLES:
        existing = {c['name'] for c in sa.inspect(bind).get_columns(table)}
        if 'city_id' not in existing:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column('city_id', sa.Integer(), sa.ForeignKey('cities.id', name=f'fk_{table}_city_id'), nullable=True))
                batch.create_index(f'ix_{table}_city_id', ['city_id'])
    # ciudad principal para todo lo que ya existe
    cities = sa.table('cities', sa.column('id', sa.Integer), sa.column('name', sa.String), sa.column('slug', sa.String),
                      sa.column('province', sa.String), sa.column('active', sa.Boolean), sa.column('center_lat', sa.Float),
                      sa.column('center_lng', sa.Float), sa.column('radius_km', sa.Float), sa.column('display_order', sa.Integer),
                      sa.column('created_at', sa.DateTime), sa.column('updated_at', sa.DateTime))
    has_data = bind.execute(sa.text('SELECT COUNT(*) FROM stores')).scalar() or bind.execute(sa.text('SELECT COUNT(*) FROM couriers')).scalar()
    if has_data and not bind.execute(sa.text('SELECT COUNT(*) FROM cities')).scalar():
        lat, lng = _default_center()
        bahia = abs(lat + 38.72) < 0.3 and abs(lng + 62.27) < 0.3
        now = datetime.utcnow()
        op.bulk_insert(cities, [{'name': 'Bahía Blanca' if bahia else 'Ciudad principal', 'slug': 'bahia-blanca' if bahia else 'principal',
                                 'province': 'Buenos Aires' if bahia else None, 'active': True, 'center_lat': lat, 'center_lng': lng,
                                 'radius_km': 25.0, 'display_order': 0, 'created_at': now, 'updated_at': now}])
        city_id = bind.execute(sa.text('SELECT MIN(id) FROM cities')).scalar()
        for table in ('stores', 'couriers', 'logistics_zones'):
            bind.execute(sa.text(f'UPDATE {table} SET city_id = :c WHERE city_id IS NULL'), {'c': city_id})
        bind.execute(sa.text('UPDATE orders SET city_id = (SELECT stores.city_id FROM stores WHERE stores.id = orders.store_id) WHERE city_id IS NULL'))


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        existing = {c['name'] for c in sa.inspect(bind).get_columns(table)}
        if 'city_id' in existing:
            with op.batch_alter_table(table) as batch:
                batch.drop_index(f'ix_{table}_city_id')
                batch.drop_constraint(f'fk_{table}_city_id', type_='foreignkey')
                batch.drop_column('city_id')
    if 'cities' in sa.inspect(bind).get_table_names():
        op.drop_index('ix_cities_slug', table_name='cities')
        op.drop_table('cities')
