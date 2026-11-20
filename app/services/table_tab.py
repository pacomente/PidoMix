"""La cuenta de la mesa para el cliente (desde el QR de la mesa o desde su pedido en la app).

- La cuenta la arma la caja (Trappi Caja, en la compu del local) y la sube cada vez que cambia: acá solo se guarda
  una copia para mostrar. Lo que se cobra lo decide la caja; el cliente nunca cambia importes.
- "Llamar al mozo" y "Pedir la cuenta": quedan anotados, la caja los ve en el salón y le avisamos al local.
- Dividir la cuenta en partes iguales es solo una cuenta para mostrar (cada uno paga su parte en el local).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Order, PosTable, PosTableTab, Store, TableCall
from . import table_orders

KINDS = {'mozo': 'llama al mozo', 'cuenta': 'pide la cuenta'}
CALL_WINDOW = timedelta(minutes=3)  # no repetir el mismo llamado mientras la caja no lo vio
CALLS_SHOWN = timedelta(hours=2)
MAX_ITEMS = 200


def _money(v) -> Decimal:
    try:
        d = Decimal(str(v or 0))
    except Exception:
        d = Decimal('0')
    return max(Decimal('0'), min(d, Decimal('100000000'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _clean(items) -> list[dict]:
    out = []
    for i in (items or [])[:MAX_ITEMS]:
        if not isinstance(i, dict):
            continue
        name = ' '.join(str(i.get('name') or '').split())[:80]
        try:
            qty = max(0, min(999, int(float(i.get('quantity') or 0))))
        except (TypeError, ValueError):
            qty = 0
        if not name or not qty:
            continue
        row = {'name': name, 'quantity': qty, 'unit_price': float(_money(i.get('unit_price'))), 'total': float(_money(i.get('total')))}
        mods = ' '.join(str(i.get('modifiers_text') or '').split())[:120]
        if mods:
            row['modifiers_text'] = mods
        out.append(row)
    return out


def save_tabs(db: Session, store: Store, tabs: list[dict], now: datetime | None = None) -> int:
    """Lo que manda la caja: [{table_id, items, subtotal, promo_discount, total, opened_at}]. Sin ítems = la mesa se cerró."""
    now = now or datetime.utcnow()
    own = {t.id for t in db.scalars(select(PosTable).where(PosTable.store_id == store.id))}
    saved = 0
    for t in tabs[:100]:
        try:
            tid = int(t.get('table_id'))
        except (TypeError, ValueError, AttributeError):
            continue
        if tid not in own:
            continue
        row = db.scalar(select(PosTableTab).where(PosTableTab.table_id == tid))
        items = _clean(t.get('items'))
        if not items:
            if row is not None:
                db.delete(row)
            saved += 1
            continue
        if row is None:
            row = PosTableTab(store_id=store.id, table_id=tid)
            db.add(row)
        row.items = json.dumps(items, ensure_ascii=False)
        row.subtotal, row.promo_discount, row.total = _money(t.get('subtotal')), _money(t.get('promo_discount')), _money(t.get('total'))
        try:
            row.opened_at = datetime.fromisoformat(str(t.get('opened_at'))[:19]) if t.get('opened_at') else row.opened_at or now
        except ValueError:
            row.opened_at = row.opened_at or now
        row.updated_at = now
        saved += 1
    db.flush()
    return saved


def tab_json(db: Session, table: PosTable, people: int = 0) -> dict:
    """La cuenta para el cliente; people > 1: cuánto pone cada uno si se divide en partes iguales."""
    row = db.scalar(select(PosTableTab).where(PosTableTab.table_id == table.id))
    items = json.loads(row.items) if row else []
    total = Decimal(row.total) if row else Decimal('0')
    out = {'table': table_orders.label(table), 'items': items, 'subtotal': float(row.subtotal) if row else 0.0,
           'promo_discount': float(row.promo_discount) if row else 0.0, 'total': float(total),
           'updated_at': row.updated_at.isoformat() + 'Z' if row else None,
           'calls': [c.kind for c in pending_for_table(db, table)]}
    if people and people > 1 and total:
        out['split'] = {'people': people, 'each': float((total / people).quantize(Decimal('1'), rounding=ROUND_HALF_UP))}
    return out


def table_of_order(db: Session, order: Order) -> PosTable | None:
    """La mesa de un pedido hecho desde el QR (el pedido guarda "Mesa 3")."""
    if not order.table_name:
        return None
    for t in db.scalars(select(PosTable).where(PosTable.store_id == order.store_id, PosTable.active.is_(True))):
        if table_orders.label(t) == order.table_name:
            return t
    return None


def pending_for_table(db: Session, table: PosTable, now: datetime | None = None) -> list[TableCall]:
    now = now or datetime.utcnow()
    return db.scalars(select(TableCall).where(TableCall.table_id == table.id, TableCall.seen_at.is_(None), TableCall.created_at >= now - CALLS_SHOWN)
                      .order_by(TableCall.id)).all()


def call(db: Session, table: PosTable, kind: str, now: datetime | None = None) -> tuple[TableCall, bool]:
    """Anota el llamado (si ya hay uno igual sin ver hace menos de 3 min, devuelve ese). (llamado, es_nuevo)."""
    if kind not in KINDS:
        raise ValueError('kind')
    now = now or datetime.utcnow()
    same = db.scalar(select(TableCall).where(TableCall.table_id == table.id, TableCall.kind == kind, TableCall.seen_at.is_(None),
                                             TableCall.created_at >= now - CALL_WINDOW))
    if same is not None:
        return same, False
    c = TableCall(store_id=table.store_id, table_id=table.id, kind=kind, created_at=now)
    db.add(c)
    db.flush()
    return c, True


def notify(db: Session, table: PosTable, kind: str) -> None:
    """Aviso al local (además de verse en la caja). Si falla el aviso, el llamado igual queda anotado."""
    try:
        from . import owner_alerts
        owner_alerts.push_store_later(table.store_id, {'title': f'🔔 {table_orders.label(table)} {KINDS[kind]}', 'body': 'Lo ves en la caja, en el salón.',
                                                       'tag': f'mesa-{table.id}-{kind}'})
    except Exception:
        pass


def pending_calls(db: Session, store: Store, now: datetime | None = None) -> list[dict]:
    """Para la caja: los llamados sin atender de las últimas 2 horas."""
    now = now or datetime.utcnow()
    rows = db.scalars(select(TableCall).where(TableCall.store_id == store.id, TableCall.seen_at.is_(None), TableCall.created_at >= now - CALLS_SHOWN)
                      .order_by(TableCall.id)).all()
    return [{'id': c.id, 'table_id': c.table_id, 'kind': c.kind, 'created_at': c.created_at.isoformat() + 'Z'} for c in rows]


def mark_seen(db: Session, store: Store, call_id: int, now: datetime | None = None) -> bool:
    c = db.get(TableCall, call_id)
    if c is None or c.store_id != store.id:
        return False
    c.seen_at = c.seen_at or now or datetime.utcnow()
    return True
