"""Multiplicador por demanda: queda fijo en cada oferta de viaje (lo que se le mostro al repartidor es lo que cobra).
Y el canal de notificaciones de la app del repartidor (las versiones nuevas tienen otro sonido).

Revision ID: 0029_surge
Revises: 0028_retention
"""
import sqlalchemy as sa
from alembic import op

revision = '0029_surge'
down_revision = '0028_retention'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    columns = {c['name'] for c in insp.get_columns('delivery_offers')}
    if 'surge' not in columns:
        with op.batch_alter_table('delivery_offers') as batch:
            batch.add_column(sa.Column('surge', sa.Numeric(4, 2)))
    ccols = {c['name'] for c in insp.get_columns('couriers')}
    if 'push_channel' not in ccols:
        with op.batch_alter_table('couriers') as batch:
            batch.add_column(sa.Column('push_channel', sa.String(30)))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'push_channel' in {c['name'] for c in insp.get_columns('couriers')}:
        with op.batch_alter_table('couriers') as batch:
            batch.drop_column('push_channel')
    if 'surge' in {c['name'] for c in insp.get_columns('delivery_offers')}:
        with op.batch_alter_table('delivery_offers') as batch:
            batch.drop_column('surge')
