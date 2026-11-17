"""Promos de la caja (2x1, combos, happy hour) que el local marcó "también en la app".

El cálculo es el mismo de la caja (pos_salon.apply_promos): el servidor lo hace siempre, nunca el teléfono.
En el pedido el descuento va dentro de `discount` (junto con el cupón) y queda anotado en promo_discount / promo_text.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from . import pos_salon
from .store_hours import LOCAL_TZ, to_local

ZERO = Decimal('0')


def store_online(db: Session, store) -> list[dict]:
    """Las promos activas del local que valen online (si tiene la función de promos de la caja)."""
    if store is None or not pos_salon.has(store, 'promos'):
        return []
    return [pos_salon.promo_json(p) for p in pos_salon.store_promos(db, store.id) if p.online]


def for_cart(db: Session, store, items: list[dict], now: datetime | None = None) -> tuple[Decimal, list[dict]]:
    """Descuento de las promos para los ítems del carrito (los de price_lines). Los productos por peso no entran."""
    promos = store_online(db, store)
    if not promos or not items:
        return ZERO, []
    lines = [{'product_id': it['product'].id, 'section_id': it['product'].section_id, 'quantity': it['quantity'],
              'unit': it['unit_price'], 'base': it['product'].price}
             for it in items if not it.get('grams')]
    return pos_salon.apply_promos(promos, lines, to_local(now or datetime.utcnow()))


def label(p: dict) -> str:
    """Lo que se ve en el cartelito: "2×1", "3×2", "-20 %", "Combo $9.900"."""
    if p['kind'] == 'nxm':
        return f"{p['buy']}×{p['pay']}" if p['pay'] else f"{p['buy']}×0"
    if p['kind'] == 'percent':
        v = Decimal(str(p['value']))
        return f"-{int(v) if v == int(v) else v} %"
    return f"Combo ${int(Decimal(str(p['value']))):,}".replace(',', '.')


def _ends_at(p: dict, local: datetime) -> datetime | None:
    """Cuándo termina hoy la franja (en UTC, para la cuenta regresiva). None si es todo el día."""
    if not p.get('start') or not p.get('end'):
        return None
    h, m = (int(x) for x in p['end'].split(':'))
    end = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if end <= local:  # la franja pasa la medianoche ("22:00" a "02:00")
        end += timedelta(days=1)
    return end.astimezone(timezone.utc).replace(tzinfo=None)


def badges(db: Session, store, now: datetime | None = None) -> list[dict]:
    """Para la app y la web: las promos online de hoy, si valen ahora y hasta cuándo (o desde qué hora)."""
    local = (now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ) if now else datetime.now(LOCAL_TZ))
    out = []
    for p in store_online(db, store):
        if str(local.weekday()) not in (p.get('days') or ''):
            continue
        on = pos_salon.is_on(p, local)
        if not on and not (p.get('start') and p['start'] > local.strftime('%H:%M')):
            continue  # ya terminó por hoy
        out.append({'id': p['id'], 'name': p['name'], 'kind': p['kind'], 'label': label(p), 'on': on,
                    'start': p.get('start'), 'end': p.get('end'), 'ends_at': _ends_at(p, local) if on else None,
                    'product_ids': p['product_ids'], 'section_ids': p['section_ids']})
    return out


def summary(applied: list[dict]) -> str | None:
    """"2x1 en pintas · Happy hour" (lo que se anota en el pedido)."""
    return ' · '.join(a['name'] for a in applied)[:200] or None
