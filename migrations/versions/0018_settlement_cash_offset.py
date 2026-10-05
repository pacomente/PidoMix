"""Compensar el efectivo sin rendir del cadete con su liquidacion.

- courier_settlements.cash_offset: efectivo que se le desconto de lo que cobra.
- courier_settlements.remittance_id: la rendicion "compensada" que se registro por ese monto.

Revision ID: 0018_settlement_cash_offset
Revises: 0017_cities
"""
import sqlalchemy as sa
from alembic import op

revision = '0018_settlement_cash_offset'
down_revision = '0017_cities'
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('courier_settlements')}
    with op.batch_alter_table('courier_settlements') as batch:
        if 'cash_offset' not in have:
            batch.add_column(sa.Column('cash_offset', sa.Numeric(12, 2), nullable=False, server_default='0'))
        if 'remittance_id' not in have:
            batch.add_column(sa.Column('remittance_id', sa.Integer(), sa.ForeignKey('cash_remittances.id', name='fk_courier_settlements_remittance_id'), nullable=True))


def downgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('courier_settlements')}
    with op.batch_alter_table('courier_settlements') as batch:
        if 'remittance_id' in have:
            batch.drop_constraint('fk_courier_settlements_remittance_id', type_='foreignkey')
            batch.drop_column('remittance_id')
        if 'cash_offset' in have:
            batch.drop_column('cash_offset')
