"""Puntos Trappi: el cliente con cuenta suma puntos con cada pedido entregado y los canjea como descuento.

Reglas (las define el superadmin en Configuración → Puntos Trappi; arranca apagado):
  - gana 1 punto cada `loyalty_pesos_per_point` de productos (sin envío ni lo pagado con puntos) al ENTREGARSE el pedido,
  - cada punto vale `loyalty_point_value` al canjearlo; mínimo `loyalty_min_redeem` puntos,
  - con puntos se paga hasta `loyalty_max_percent` % de los productos; el descuento lo reparten Trappi (`loyalty_trappi_percent`)
    y el comercio, y la parte de Trappi nunca supera lo que gana en ese pedido (ver plans.breakdown),
  - los puntos ganados vencen a los `loyalty_expiry_months` meses (los más viejos se usan primero),
  - si el pedido se cancela o se devuelve, los puntos usados vuelven y los ganados se descuentan.
Todo se calcula en el backend: el cliente solo elige "usar mis puntos".
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import LoyaltyEntry, Order
from . import platform

ZERO = Decimal('0.00')


def config(db: Session) -> dict:
    cfg = platform.get_all(db)
    return {'enabled': bool(cfg['loyalty_enabled']), 'per_point': Decimal(str(cfg['loyalty_pesos_per_point'])),
            'value': Decimal(str(cfg['loyalty_point_value'])), 'min': int(cfg['loyalty_min_redeem']),
            'max_pct': int(cfg['loyalty_max_percent']), 'months': int(cfg['loyalty_expiry_months']),
            'trappi_pct': max(0, min(100, int(cfg['loyalty_trappi_percent'])))}


@dataclass
class Balance:
    points: int = 0
    expiring: int = 0               # vencen en los próximos 30 días
    expiring_at: datetime | None = None
    expired: int = 0

    def value(self, point_value: Decimal) -> Decimal:
        return (Decimal(self.points) * point_value).quantize(Decimal('0.01'))


def entries(db: Session, account_id: int) -> list[LoyaltyEntry]:
    return db.scalars(select(LoyaltyEntry).where(LoyaltyEntry.account_id == account_id).order_by(LoyaltyEntry.created_at, LoyaltyEntry.id)).all()


def balance(db: Session, account_id: int | None, now: datetime | None = None) -> Balance:
    """Saldo: lo ganado que no venció menos lo usado (lo usado consume primero lo más viejo)."""
    b = Balance()
    if not account_id:
        return b
    now = now or datetime.utcnow()
    lots = []  # [puntos que quedan, vence]
    for e in entries(db, account_id):
        if e.points > 0:
            lots.append([e.points, e.expires_at])
            continue
        need = -e.points
        for lot in lots:  # FIFO: se descuenta de lo ganado más viejo que no había vencido cuando se usó
            if need <= 0:
                break
            if lot[1] and lot[1] <= e.created_at:
                continue
            take = min(lot[0], need)
            lot[0] -= take
            need -= take
    soon = now + timedelta(days=30)
    for left, expires in lots:
        if left <= 0:
            continue
        if expires and expires <= now:
            b.expired += left
            continue
        b.points += left
        if expires and expires <= soon:
            b.expiring += left
            b.expiring_at = min(b.expiring_at or expires, expires)
    return b


def _add(db: Session, account_id: int, kind: str, points: int, *, order_id=None, amount=None, expires_at=None, note=None, dedupe=None, user=None) -> bool:
    if not points:
        return False
    if dedupe and db.scalar(select(LoyaltyEntry.id).where(LoyaltyEntry.dedupe_key == dedupe)):
        return False  # ya estaba (idempotente)
    db.add(LoyaltyEntry(account_id=account_id, order_id=order_id, kind=kind, points=points, amount=amount, expires_at=expires_at,
                        note=(note or '')[:255] or None, dedupe_key=dedupe, user_id=getattr(user, 'id', None)))
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        return False
    return True


# ---------- canje en el checkout ----------

def redeemable(db: Session, account, products: Decimal, trappi_amount: Decimal) -> dict:
    """Cuánto puede usar en este pedido. products = productos con el cupón ya descontado; trappi_amount = parte de Trappi sin puntos."""
    cfg = config(db)
    out = {'enabled': cfg['enabled'], 'balance': 0, 'points': 0, 'discount': ZERO, 'value': cfg['value'], 'min': cfg['min'], 'reason': None}
    if not cfg['enabled'] or account is None:
        return out
    bal = balance(db, account.id)
    out['balance'] = bal.points
    if bal.points < cfg['min']:
        out['reason'] = f'Necesitás al menos {cfg["min"]} puntos para usarlos.'
        return out
    caps = [Decimal(products) * cfg['max_pct'] / 100, Decimal(bal.points) * cfg['value']]
    if cfg['trappi_pct'] > 0:  # la parte de Trappi no puede superar lo que Trappi gana en el pedido
        caps.append(max(Decimal(trappi_amount), ZERO) * 100 / cfg['trappi_pct'])
    cap = min(caps)
    points = int((cap / cfg['value']).to_integral_value(rounding=ROUND_DOWN)) if cfg['value'] > 0 else 0
    if points < 1:
        out['reason'] = 'En este pedido no se pueden usar puntos.'
        return out
    out['points'] = points
    out['discount'] = (Decimal(points) * cfg['value']).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return out


def apply_to_order(db: Session, order: Order, account) -> None:
    """Descuenta los puntos que se pueden usar (después de plans.snapshot, para saber la parte de Trappi). No hace commit."""
    from . import plans
    order.points_used = order.points_discount = None
    b = plans.breakdown(order)
    r = redeemable(db, account, b['products'], b['trappi_amount'])
    if not r['points']:
        return
    order.points_used, order.points_discount = r['points'], r['discount']
    # el reparto queda fijo en el pedido: si despues se cambia la configuracion, este pedido no cambia
    import json
    snap = plans.read_snapshot(order)
    snap['points'] = {'trappi_percent': config(db)['trappi_pct']}
    order.pricing_snapshot = json.dumps(snap, ensure_ascii=False, default=str)
    order.total = plans.money(order.total) - r['discount']


def record_redeem(db: Session, order: Order) -> None:
    """Se descuentan los puntos al confirmar el pedido (después del flush, con el id)."""
    if order.points_used and order.account_id:
        _add(db, order.account_id, 'redeem', -order.points_used, order_id=order.id, amount=order.points_discount,
             note=f'Usados en el pedido #{order.id}', dedupe=f'redeem:{order.id}')


# ---------- al entregar, cancelar o devolver ----------

def earned_for(db: Session, order: Order) -> int:
    cfg = config(db)
    if not cfg['enabled'] or not order.account_id or cfg['per_point'] <= 0:
        return 0
    base = Decimal(order.subtotal or 0) - Decimal(order.discount or 0) - Decimal(order.points_discount or 0)
    return max(0, math.floor(base / cfg['per_point']))


def on_delivered(db: Session, order: Order) -> None:
    points = earned_for(db, order)
    if not points:
        return
    months = config(db)['months']
    expires = datetime.utcnow() + timedelta(days=30 * months) if months else None
    _add(db, order.account_id, 'earn', points, order_id=order.id, expires_at=expires, note=f'Pedido #{order.id} entregado', dedupe=f'earn:{order.id}')


def on_cancelled(db: Session, order: Order) -> None:
    """Pedido cancelado: vuelven los puntos que se habían usado."""
    if order.points_used and order.account_id:
        _add(db, order.account_id, 'restore', order.points_used, order_id=order.id, note=f'Pedido #{order.id} cancelado: te devolvimos los puntos',
             dedupe=f'restore:{order.id}')


def on_refunded(db: Session, order: Order) -> None:
    """Devolución del pago: vuelven los usados y se descuentan los ganados por ese pedido."""
    on_cancelled(db, order)
    earned = db.scalar(select(LoyaltyEntry.points).where(LoyaltyEntry.dedupe_key == f'earn:{order.id}'))
    if earned and order.account_id:
        _add(db, order.account_id, 'reverse', -earned, order_id=order.id, note=f'Pedido #{order.id} devuelto', dedupe=f'reverse:{order.id}')


def adjust(db: Session, account_id: int, points: int, reason: str, user) -> bool:
    """Ajuste manual del superadmin (queda con motivo y usuario)."""
    return _add(db, account_id, 'adjust', points, note=reason, user=user)


def summary(db: Session, account) -> dict | None:
    """Para la cuenta del cliente (web y app). None si los puntos están apagados."""
    cfg = config(db)
    if not cfg['enabled'] or account is None:
        return None
    bal = balance(db, account.id)
    history = list(reversed(entries(db, account.id)))[:20]
    return {'points': bal.points, 'value': bal.value(cfg['value']), 'expiring': bal.expiring, 'expiring_at': bal.expiring_at,
            'per_point': cfg['per_point'], 'point_value': cfg['value'], 'min': cfg['min'], 'max_pct': cfg['max_pct'], 'months': cfg['months'],
            'history': [{'kind': e.kind, 'points': e.points, 'note': e.note, 'created_at': e.created_at, 'order_id': e.order_id} for e in history]}
