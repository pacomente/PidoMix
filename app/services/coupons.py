"""Cupones automáticos: el local marca un cupón como "automático", se muestra en su tienda y se aplica solo
en el checkout (el cliente no tiene que escribir el código). Si el cliente escribe un código válido, manda ese.

El descuento lo calcula siempre el backend con los datos del cupón (nunca llega un importe desde el cliente).
"""
import time
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Coupon
from .formatting import money

_cache: dict = {'at': 0.0, 'offers': {}}
CACHE_SECONDS = 30


def usable(c: Coupon, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(c.active and (not c.expires_at or c.expires_at >= now) and (not c.max_uses or c.uses_count < c.max_uses))


def discount_for(c: Coupon, subtotal: Decimal) -> Decimal:
    d = (subtotal * Decimal(c.discount_value) / 100) if c.discount_type == 'percent' else Decimal(c.discount_value)
    return min(max(d, Decimal('0')), subtotal).quantize(Decimal('0.01'))


def label(c: Coupon) -> str:
    """"10% OFF" o "$1.500 OFF", y el mínimo si tiene."""
    off = f'{Decimal(c.discount_value).normalize():f}% OFF' if c.discount_type == 'percent' else f'{money(c.discount_value)} OFF'
    return off + (f' en pedidos desde {money(c.min_order)}' if Decimal(c.min_order or 0) > 0 else '')


def _auto_coupons(db: Session, store_id: int) -> list[Coupon]:
    rows = db.scalars(select(Coupon).where(Coupon.store_id == store_id, Coupon.auto_apply.is_(True), Coupon.active.is_(True))).all()
    return [c for c in rows if usable(c)]


def best_auto(db: Session, store_id: int, subtotal: Decimal) -> tuple[Coupon | None, Decimal]:
    """El cupón automático que más descuenta para este subtotal (respeta mínimo, vencimiento y usos)."""
    best, best_d = None, Decimal('0')
    for c in _auto_coupons(db, store_id):
        if subtotal < Decimal(c.min_order or 0):
            continue
        d = discount_for(c, subtotal)
        if d > best_d:
            best, best_d = c, d
    return best, best_d


def offer_for(db: Session, store_id: int) -> dict | None:
    """Lo que se muestra en la tienda: el cupón automático vigente más generoso."""
    rows = _auto_coupons(db, store_id)
    if not rows:
        return None
    c = max(rows, key=lambda c: (c.discount_type == 'percent', Decimal(c.discount_value)))
    return {'code': c.code, 'label': label(c), 'min_order': Decimal(c.min_order or 0)}


def offers(db: Session) -> dict[int, str]:
    """{store_id: etiqueta} de todos los comercios con cupón automático (con cache corta: lo usan las tarjetas)."""
    now = time.monotonic()
    if now - _cache['at'] < CACHE_SECONDS:
        return _cache['offers']
    out: dict[int, str] = {}
    for c in db.scalars(select(Coupon).where(Coupon.auto_apply.is_(True), Coupon.active.is_(True))).all():
        if usable(c) and c.store_id not in out:
            out[c.store_id] = label(c).split(' en pedidos')[0]
    _cache.update(at=now, offers=out)
    return out


def invalidate() -> None:
    _cache['at'] = 0.0
