"""Pedí desde tu mesa: el cliente sentado en el local escanea el QR de su mesa, arma el pedido y le llega a la mesa.

- Lo habilita Trappi por comercio (funciones de la caja: Mesas + "Pedí desde tu mesa"). Cada mesa del salón tiene su QR.
- Al escanear queda anotada la mesa en el navegador (unas horas). El checkout ya no pregunta envío ni dirección:
  el pedido entra como retiro con "Mesa 3" (no se programa, el local tiene que estar abierto).
- Comisión propia, más baja que la de la app (al cliente lo trajo el local): la general de Configuración
  ("Comisión por pedido desde la mesa") o la que Trappi le ponga al local. Queda fija en el pedido al crearlo.
"""
import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Order, PosTable, Store
from . import plans, platform, pos_salon

SESSION_KEY = 'mesa'
TTL = timedelta(hours=4)  # lo que dura sentado: despues hay que volver a escanear
ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def enabled(store: Store | None) -> bool:
    return bool(store is not None and pos_salon.has(store, 'tables') and pos_salon.has(store, 'table_orders') and plans.is_visible(store))


def label(table: PosTable) -> str:
    """"Mesa 3" (si la mesa se llama "Barra 2" o "Vereda 1", queda asi)."""
    name = table.name.strip()
    return f'Mesa {name}' if name[:1].isdigit() else name


def qr_code(db: Session, table: PosTable) -> str:
    """El codigo del QR de la mesa (se crea la primera vez)."""
    if not table.qr_code:
        while True:
            code = ''.join(secrets.choice(ALPHABET) for _ in range(10))
            if db.scalar(select(PosTable.id).where(PosTable.qr_code == code)) is None:
                break
        table.qr_code = code
        db.flush()
    return table.qr_code


def url(code: str) -> str:
    return f"{(settings.public_base_url or 'https://trappi.com.ar').rstrip('/')}/mesa/{code}"


def by_code(db: Session, code: str) -> PosTable | None:
    code = (code or '').strip().lower()
    if not code or len(code) > 16:
        return None
    t = db.scalar(select(PosTable).where(PosTable.qr_code == code, PosTable.active.is_(True)))
    return t if t is not None and enabled(db.get(Store, t.store_id)) else None


def remember(request, table: PosTable) -> None:
    request.session[SESSION_KEY] = {'table': table.id, 'store': table.store_id, 'until': (datetime.utcnow() + TTL).isoformat()}


def forget(request) -> None:
    request.session.pop(SESSION_KEY, None)


def current(request, db: Session, store_id: int | None) -> PosTable | None:
    """La mesa en la que esta sentado el cliente (si escaneo el QR de ese local hace poco y sigue habilitado)."""
    data = request.session.get(SESSION_KEY)
    if not isinstance(data, dict) or store_id is None or data.get('store') != store_id:
        return None
    try:
        if datetime.fromisoformat(data['until']) < datetime.utcnow():
            forget(request)
            return None
    except (KeyError, TypeError, ValueError):
        forget(request)
        return None
    t = db.get(PosTable, data.get('table'))
    if t is None or not t.active or t.store_id != store_id or not enabled(db.get(Store, store_id)):
        return None
    return t


def commission(db: Session, store: Store) -> Decimal:
    if store.table_commission_percent is not None:
        return plans.money(store.table_commission_percent)
    return plans.money(platform.get_all(db)['table_commission_percent'])


def apply(db: Session, order: Order, store: Store, table: PosTable) -> None:
    """Marca el pedido como de la mesa y le pone la comision de la mesa (en vez de la de la app)."""
    order.table_name = label(table)
    order.origin = 'mesa'
    pct = commission(db, store)
    snap = plans.read_snapshot(order)
    snap['commission'] = {'rate': str(pct), 'fixed': '0.00', 'min': '0.00', 'max': '0.00', 'source': f'pedido desde la mesa (QR) · {order.table_name}'}
    order.commission_rate = pct
    order.pricing_snapshot = json.dumps(snap, ensure_ascii=False, default=str)
    plans.settle(order)
