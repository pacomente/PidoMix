"""Caja: mesas del salón, comandas por tanda, promos del mostrador, propina, cliente frecuente y llamador.

Revision ID: 0039_pos_salon
Revises: 0038_pos_gastronomia
"""
import sqlalchemy as sa
from alembic import op

revision = '0039_pos_salon'
down_revision = '0038_pos_gastronomia'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


SALE_COLS = [
    ('promo_discount', lambda: sa.Column('promo_discount', sa.Numeric(12, 2), nullable=False, server_default='0')),
    ('promos', lambda: sa.Column('promos', sa.Text())),
    ('tip', lambda: sa.Column('tip', sa.Numeric(12, 2), nullable=False, server_default='0')),
    ('account_id', lambda: sa.Column('account_id', sa.Integer(), sa.ForeignKey('client_accounts.id', name='fk_pos_sales_account_id'))),
    ('table_name', lambda: sa.Column('table_name', sa.String(40))),
]


def upgrade() -> None:
    have = _cols('pos_sales')
    with op.batch_alter_table('pos_sales') as b:
        for name, col in SALE_COLS:
            if name not in have:
                b.add_column(col())
        if 'account_id' not in have:
            b.create_index('ix_pos_sales_account_id', ['account_id'])
    if 'pos_screen_code' not in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.add_column(sa.Column('pos_screen_code', sa.String(16)))
            b.create_unique_constraint('uq_stores_pos_screen_code', ['pos_screen_code'])
    tables = _tables()
    if 'pos_tables' not in tables:
        op.create_table(
            'pos_tables',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('name', sa.String(20), nullable=False),
            sa.Column('area', sa.String(30), nullable=False, server_default='Salón'),
            sa.Column('seats', sa.Integer(), nullable=False, server_default='4'),
            sa.Column('shape', sa.String(10), nullable=False, server_default='square'),
            sa.Column('col', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('row', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index('ix_pos_tables_store_id', 'pos_tables', ['store_id'])
    if 'pos_kitchen_tickets' not in tables:
        op.create_table(
            'pos_kitchen_tickets',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('cashier_id', sa.Integer(), sa.ForeignKey('pos_cashiers.id')),
            sa.Column('client_uuid', sa.String(40), nullable=False),
            sa.Column('label', sa.String(60), nullable=False),
            sa.Column('items', sa.Text(), nullable=False),
            sa.Column('kitchen', sa.String(10), nullable=False, server_default='cocina'),
            sa.Column('kitchen_at', sa.DateTime()),
            sa.Column('sent_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ux_pos_kitchen_client', 'pos_kitchen_tickets', ['store_id', 'client_uuid'], unique=True)
        op.create_index('ix_pos_kitchen_status', 'pos_kitchen_tickets', ['store_id', 'kitchen'])
    if 'pos_promos' not in tables:
        op.create_table(
            'pos_promos',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id'), nullable=False),
            sa.Column('name', sa.String(80), nullable=False),
            sa.Column('kind', sa.String(10), nullable=False),
            sa.Column('buy', sa.Integer(), nullable=False, server_default='2'),
            sa.Column('pay', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('value', sa.Numeric(12, 2), nullable=False, server_default='0'),
            sa.Column('product_ids', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('section_ids', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('days', sa.String(7), nullable=False, server_default='0123456'),
            sa.Column('start', sa.String(5)),
            sa.Column('end', sa.String(5)),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_pos_promos_store_id', 'pos_promos', ['store_id'])


def downgrade() -> None:
    tables = _tables()
    for t in ('pos_promos', 'pos_kitchen_tickets', 'pos_tables'):
        if t in tables:
            op.drop_table(t)
    if 'pos_screen_code' in _cols('stores'):
        with op.batch_alter_table('stores') as b:
            b.drop_constraint('uq_stores_pos_screen_code', type_='unique')
            b.drop_column('pos_screen_code')
    have = _cols('pos_sales')
    with op.batch_alter_table('pos_sales') as b:
        if 'account_id' in have:
            b.drop_index('ix_pos_sales_account_id')
        for name, _ in reversed(SALE_COLS):
            if name in have:
                b.drop_column(name)
