"""Busquedas (sin datos de quien busca) para la analitica: que piden los clientes y no encuentran.

Revision ID: 0026_search_logs
Revises: 0025_personalize
"""
import sqlalchemy as sa
from alembic import op

revision = '0026_search_logs'
down_revision = '0025_personalize'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'search_logs' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'search_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('term', sa.String(100), nullable=False),
        sa.Column('results', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('corrected', sa.String(100)),
        sa.Column('city_id', sa.Integer(), sa.ForeignKey('cities.id')),
        sa.Column('channel', sa.String(10)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_search_logs_created', 'search_logs', ['created_at'])
    op.create_index('ix_search_logs_city_id', 'search_logs', ['city_id'])


def downgrade() -> None:
    op.drop_index('ix_search_logs_city_id', 'search_logs')
    op.drop_index('ix_search_logs_created', 'search_logs')
    op.drop_table('search_logs')
