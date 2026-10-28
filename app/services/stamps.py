"""Tarjeta de sellos del local (la paga el local, no Trappi).

- El local la prende en Cupones: cuántos sellos hacen falta, el premio (% o $ de descuento) y el pedido mínimo que suma.
- Cada pedido ENTREGADO de un cliente con cuenta suma un sello (una sola vez por pedido).
- Al completar la tarjeta se crea un premio: un cupón personal (solo esa cuenta, un uso, vence a los 60 días)
  que se aplica solo en el checkout de ese local. Si el pedido que lo usó se cancela, el premio vuelve.
"""
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Coupon, Order, StampCard, Store
from .formatting import money

GOALS = (5, 6, 8, 10, 12, 15)
REWARD_DAYS = 60
PREFIX = 'SELLOS-'


def enabled(store: Store) -> bool:
    return bool(store.stamps_goal and store.stamps_goal > 0 and store.stamps_reward_value and store.stamps_reward_value > 0)


def reward_text(store: Store) -> str:
    v = Decimal(store.stamps_reward_value or 0)
    return f'{int(v) if v == int(v) else v} % de descuento' if store.stamps_reward_type == 'percent' else f'{money(v)} de descuento'


def info(store: Store) -> dict | None:
    """Lo que ve el cliente en la pagina del local."""
    if not enabled(store):
        return None
    return {'goal': store.stamps_goal, 'reward': reward_text(store),
            'min_order': Decimal(store.stamps_min_order or 0)}


def card(db: Session, store_id: int, account_id: int) -> StampCard | None:
    return db.scalar(select(StampCard).where(StampCard.store_id == store_id, StampCard.account_id == account_id))


def rewards(db: Session, store_id: int, account_id: int, now: datetime | None = None) -> list[Coupon]:
    now = now or datetime.utcnow()
    return db.scalars(select(Coupon).where(Coupon.store_id == store_id, Coupon.account_id == account_id, Coupon.active.is_(True),
                                           Coupon.uses_count < Coupon.max_uses, (Coupon.expires_at.is_(None)) | (Coupon.expires_at >= now))
                      .order_by(Coupon.expires_at)).all()


def progress(db: Session, store: Store, account) -> dict | None:
    """Tarjeta del cliente en este local: sellos, cuantos faltan y premios sin usar."""
    if account is None or not enabled(store):
        return None
    c = card(db, store.id, account.id)
    have = c.stamps if c else 0
    return {'stamps': have, 'goal': store.stamps_goal, 'missing': max(0, store.stamps_goal - have), 'rewards': rewards(db, store.id, account.id)}


def my_cards(db: Session, account) -> list[dict]:
    """Todas las tarjetas del cliente (para Mi cuenta)."""
    rows = db.execute(select(StampCard, Store).join(Store, Store.id == StampCard.store_id).where(StampCard.account_id == account.id)
                      .order_by(StampCard.updated_at.desc())).all()
    out = []
    for c, s in rows:
        prizes = rewards(db, s.id, account.id)
        if enabled(s) or prizes:
            out.append({'store': s, 'stamps': c.stamps, 'goal': s.stamps_goal or 0, 'reward': reward_text(s) if enabled(s) else None, 'rewards': prizes})
    return out


def on_delivered(db: Session, order: Order) -> Coupon | None:
    """Suma el sello del pedido entregado (si corresponde). Devuelve el premio si completo la tarjeta."""
    store = order.store
    if not order.account_id or not enabled(store) or order.stamp_at is not None:
        return None
    if Decimal(order.subtotal or 0) < Decimal(store.stamps_min_order or 0):
        return None
    if order.coupon is not None and order.coupon.account_id:  # el pedido que canjea el premio no suma sello
        return None
    claimed = db.execute(update(Order).where(Order.id == order.id, Order.stamp_at.is_(None)).values(stamp_at=datetime.utcnow()))
    if claimed.rowcount != 1:  # otro proceso ya lo sumo
        return None
    order.stamp_at = order.stamp_at or datetime.utcnow()
    c = card(db, store.id, order.account_id)
    if c is None:
        c = StampCard(store_id=store.id, account_id=order.account_id, stamps=0, rewards=0)
        db.add(c)
    c.stamps += 1
    c.updated_at = datetime.utcnow()
    prize = None
    if c.stamps >= store.stamps_goal:
        c.stamps -= store.stamps_goal
        c.rewards += 1
        prize = Coupon(store_id=store.id, account_id=order.account_id, code=f'{PREFIX}{secrets.token_hex(3).upper()}',
                       discount_type='fixed' if store.stamps_reward_type == 'fixed' else 'percent', discount_value=store.stamps_reward_value,
                       min_order=0, max_uses=1, uses_count=0, active=True, expires_at=datetime.utcnow() + timedelta(days=REWARD_DAYS))
        db.add(prize)
    db.flush()
    return prize


def on_cancelled(db: Session, order: Order) -> None:
    """Si se cancela el pedido que uso el premio, el premio vuelve a estar disponible."""
    if order.coupon is not None and order.coupon.account_id and order.coupon.uses_count > 0:
        order.coupon.uses_count -= 1


def best_reward(db: Session, store_id: int, account, subtotal: Decimal) -> tuple[Coupon | None, Decimal]:
    """El premio personal que mas descuenta para este pedido (se aplica solo en el checkout)."""
    if account is None:
        return None, Decimal('0')
    best, value = None, Decimal('0')
    for c in rewards(db, store_id, account.id):
        d = (subtotal * Decimal(c.discount_value) / 100) if c.discount_type == 'percent' else Decimal(c.discount_value)
        d = min(d, subtotal)
        if d > value:
            best, value = c, d
    return best, value


def stats(db: Session, store_id: int) -> dict:
    from sqlalchemy import func
    cards = db.scalar(select(func.count(StampCard.id)).where(StampCard.store_id == store_id, (StampCard.stamps > 0) | (StampCard.rewards > 0))) or 0
    issued = db.scalar(select(func.count(Coupon.id)).where(Coupon.store_id == store_id, Coupon.account_id.is_not(None))) or 0
    used = db.scalar(select(func.count(Coupon.id)).where(Coupon.store_id == store_id, Coupon.account_id.is_not(None), Coupon.uses_count > 0)) or 0
    return {'cards': cards, 'issued': issued, 'used': used}
