"""Quien entrega lo define el plan.

Trappi Delivery entrega siempre con la flota; Trappi Comercio con sus cadetes (o con la flota de
respaldo, "mixta"). Se corrigen los comercios que quedaron con una combinacion que no corresponde
(por ejemplo, Trappi Delivery con cadetes propios) y se marca fleet_enabled donde la flota ya se usaba.

Revision ID: 0014_plan_logistics
Revises: 0013_logistics_payments
"""
from alembic import op

revision = '0014_plan_logistics'
down_revision = '0013_logistics_payments'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE stores SET logistics = 'trappi', fleet_enabled = true WHERE plan = 'TRAPPI_DELIVERY'")
    # Trappi Comercio que habia elegido la flota: la sigue teniendo, como respaldo de sus cadetes
    op.execute("UPDATE stores SET logistics = 'mixta' WHERE plan = 'TRAPPI_COMERCIO' AND logistics = 'trappi'")
    op.execute("UPDATE stores SET fleet_enabled = true WHERE logistics IN ('mixta', 'trappi') AND fleet_enabled = false")


def downgrade() -> None:
    # solo corrige datos: no hay nada que deshacer en el esquema
    pass
