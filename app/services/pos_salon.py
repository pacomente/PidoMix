"""Caja para el salón y el mostrador: promos (2x1, % y combos con horario), comandas por tanda de las mesas,
llamador para la tele, cliente frecuente, agotar productos desde la caja y el resumen del día.

Las promos se calculan igual en la caja (para mostrarlas) y acá (para cobrarlas): primero los combos, después los
NxM y al final los %; cada unidad entra en una sola promo. El servidor usa la hora de la venta, no la de la subida.
"""
import json
import secrets
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ClientAccount, Order, OrderItem, OrderStatus, PosKitchenTicket, PosPromo, PosSale, PosTable, Product, Store
from . import pos
from .store_hours import to_local

ZERO = Decimal('0')
KINDS = {'nxm': 'Lleva N paga M (2x1, 3x2)', 'percent': '% de descuento', 'combo': 'Combo a precio fijo'}
SCREEN_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ---------- promos ----------

def _ids(raw) -> list[int]:
    try:
        return [int(x) for x in json.loads(raw or '[]')]
    except (ValueError, TypeError):
        return []


def promo_json(p: PosPromo) -> dict:
    return {'id': p.id, 'name': p.name, 'kind': p.kind, 'buy': p.buy, 'pay': p.pay, 'value': float(p.value),
            'product_ids': _ids(p.product_ids), 'section_ids': _ids(p.section_ids), 'days': p.days, 'start': p.start, 'end': p.end}


def store_promos(db: Session, store_id: int) -> list[PosPromo]:
    return db.scalars(select(PosPromo).where(PosPromo.store_id == store_id, PosPromo.active.is_(True)).order_by(PosPromo.id)).all()


def is_on(p: dict, local: datetime) -> bool:
    """Si la promo vale en ese momento (hora local): día de la semana y franja (puede pasar la medianoche)."""
    if str(local.weekday()) not in (p.get('days') or ''):
        return False
    start, end = p.get('start'), p.get('end')
    if not start or not end:
        return True
    hm = local.strftime('%H:%M')
    return start <= hm < end if start <= end else (hm >= start or hm < end)


def apply_promos(promos: list[dict], lines: list[dict], local: datetime) -> tuple[Decimal, list[dict]]:
    """lines: [{product_id, section_id, quantity, unit (con opciones), base (precio del producto)}].
    Devuelve (descuento total, [{id, name, amount}]). Misma cuenta que pos/lib/promos.dart."""
    units = []  # [line_index, product_id, section_id, unit, base]
    for i, l in enumerate(lines):
        if not l.get('product_id'):
            continue
        for _ in range(int(l.get('quantity') or 0)):
            units.append([i, int(l['product_id']), l.get('section_id'), money(l['unit']), money(l['base'])])
    used = [False] * len(units)
    order = sorted(range(len(units)), key=lambda k: (-units[k][3], units[k][0]))  # de la más cara a la más barata
    on = [p for p in promos if is_on(p, local)]
    applied = []

    def eligible(p, k):
        return units[k][1] in p['product_ids'] or (units[k][2] is not None and units[k][2] in p['section_ids'])

    for p in [x for x in on if x['kind'] == 'combo']:
        need = Counter(p['product_ids'])
        if not need or p['value'] <= 0:
            continue
        total = ZERO
        while True:
            pick = []
            for pid, n in need.items():
                got = [k for k in order if not used[k] and units[k][1] == pid and k not in pick][:n]
                if len(got) < n:
                    pick = None
                    break
                pick += got
            if not pick:
                break
            saving = sum((units[k][4] for k in pick), ZERO) - money(p['value'])
            if saving <= 0:
                break
            for k in pick:
                used[k] = True
            total += saving
        if total > 0:
            applied.append({'id': p['id'], 'name': p['name'], 'amount': float(money(total))})
    for p in [x for x in on if x['kind'] == 'nxm']:
        buy, pay = int(p['buy']), int(p['pay'])
        if buy < 2 or not 0 <= pay < buy:
            continue
        pool = [k for k in order if not used[k] and eligible(p, k)]
        total = ZERO
        for g in range(0, len(pool) - len(pool) % buy, buy):
            group = pool[g:g + buy]
            total += sum((units[k][3] for k in group[pay:]), ZERO)  # las más baratas del grupo van gratis
            for k in group:
                used[k] = True
        if total > 0:
            applied.append({'id': p['id'], 'name': p['name'], 'amount': float(money(total))})
    for p in [x for x in on if x['kind'] == 'percent']:
        pct = money(p['value'])
        if pct <= 0 or pct > 100:
            continue
        total = ZERO
        for k in order:
            if not used[k] and eligible(p, k):
                total += units[k][3] * pct / 100
                used[k] = True
        if total > 0:
            applied.append({'id': p['id'], 'name': p['name'], 'amount': float(money(total))})
    return money(sum((Decimal(str(a['amount'])) for a in applied), ZERO)), applied


def promos_for_sale(db: Session, store: Store, items: list[dict], sold_at: datetime) -> tuple[Decimal, list[dict]]:
    promos = [promo_json(p) for p in store_promos(db, store.id)]
    if not promos:
        return ZERO, []
    ids = {i['product_id'] for i in items if i.get('product_id')}
    prods = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids or [0])))}
    lines = []
    for i in items:
        p = prods.get(i.get('product_id'))
        lines.append({'product_id': i.get('product_id'), 'section_id': p.section_id if p else None, 'quantity': i['quantity'],
                      'unit': i['unit_price'], 'base': float(p.price) if p else i['unit_price']})
    return apply_promos(promos, lines, to_local(sold_at))


# ---------- mesas ----------

def tables(db: Session, store_id: int) -> list[PosTable]:
    return db.scalars(select(PosTable).where(PosTable.store_id == store_id, PosTable.active.is_(True))
                      .order_by(PosTable.area, PosTable.row, PosTable.col, PosTable.id)).all()


def table_json(t: PosTable) -> dict:
    return {'id': t.id, 'name': t.name, 'area': t.area, 'seats': t.seats, 'shape': t.shape, 'col': t.col, 'row': t.row}


def _clean_items(raw) -> list[dict]:
    if not isinstance(raw, list) or not raw or len(raw) > pos.MAX_LINES:
        raise pos.PosError('La comanda no tiene productos.')
    out = []
    for i in raw:
        if not isinstance(i, dict):
            raise pos.PosError('La comanda no es válida.')
        try:
            qty = int(i.get('quantity') or 0)
        except (TypeError, ValueError):
            qty = 0
        name = ' '.join(str(i.get('name') or '').split())[:80]
        if not name or not 1 <= qty <= 999:
            raise pos.PosError('La comanda no es válida.')
        row = {'name': name, 'quantity': qty}
        for k, n in (('modifiers_text', 255), ('note', pos.MAX_NOTE)):
            v = ' '.join(str(i.get(k) or '').split())[:n]
            if v:
                row[k] = v
        out.append(row)
    return out


def record_kitchen(db: Session, store: Store, data: dict, now: datetime | None = None) -> PosKitchenTicket:
    """Tanda de una mesa para la cocina (subida en el momento o después de un corte). Idempotente. No hace commit."""
    now = now or datetime.utcnow()
    uuid = str(data.get('client_uuid') or '').strip()[:40]
    if len(uuid) < 8:
        raise pos.PosError('Falta el identificador de la comanda.')
    existing = db.scalar(select(PosKitchenTicket).where(PosKitchenTicket.store_id == store.id, PosKitchenTicket.client_uuid == uuid))
    if existing:
        return existing
    label = ' '.join(str(data.get('label') or '').split())[:60] or 'Mesa'
    items = _clean_items(data.get('items'))
    try:
        sent = datetime.fromisoformat(str(data.get('sent_at', '')).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        sent = now
    sent = min(max(sent, now - timedelta(days=1)), now + timedelta(minutes=5))
    cashier = data.get('cashier_id')
    t = PosKitchenTicket(store_id=store.id, cashier_id=int(cashier) if str(cashier or '').isdigit() else None, client_uuid=uuid, label=label,
                         items=json.dumps(items, ensure_ascii=False), sent_at=sent, created_at=now, kitchen_at=now,
                         kitchen='cocina' if sent > now - timedelta(hours=pos.KITCHEN_HOURS) else 'entregado')
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(PosKitchenTicket).where(PosKitchenTicket.store_id == store.id, PosKitchenTicket.client_uuid == uuid))
    return t


def kitchen_tickets(db: Session, store_id: int, now: datetime | None = None) -> list[PosKitchenTicket]:
    since = (now or datetime.utcnow()) - timedelta(hours=pos.KITCHEN_HOURS)
    return db.scalars(select(PosKitchenTicket).where(PosKitchenTicket.store_id == store_id, PosKitchenTicket.kitchen.in_(('cocina', 'listo')),
                                                     PosKitchenTicket.sent_at >= since).order_by(PosKitchenTicket.sent_at)).all()


def set_ticket(db: Session, store_id: int, ticket_id: int, status: str) -> PosKitchenTicket:
    t = db.get(PosKitchenTicket, ticket_id)
    if not t or t.store_id != store_id:
        raise pos.PosError('Esa comanda no existe.', 404)
    if status not in pos.KITCHEN:
        raise pos.PosError('Estado no válido.')
    t.kitchen, t.kitchen_at = status, datetime.utcnow()
    return t


# ---------- llamador (pantalla "pedido listo" para la tele) ----------

def screen_code(db: Session, store: Store, new: bool = False) -> str:
    """Código del link del llamador (se crea la primera vez; new=True lo cambia y el link viejo deja de andar). No hace commit."""
    if new or not store.pos_screen_code:
        for _ in range(10):
            code = ''.join(secrets.choice(SCREEN_ALPHABET) for _ in range(12))
            if not db.scalar(select(Store.id).where(Store.pos_screen_code == code)):
                store.pos_screen_code = code
                db.flush()
                break
    return store.pos_screen_code


def _short(name: str | None) -> str:
    """Solo el nombre de pila (en la tele lo ve todo el local)."""
    return (name or '').split()[0][:16] if (name or '').split() else ''


def screen_data(db: Session, store: Store, now: datetime | None = None) -> dict:
    """Preparando y listos para retirar: ventas del mostrador con número o nombre y pedidos online para retirar.
    Las mesas no salen (se las lleva el mozo). Los listos se van solos a los 15 minutos."""
    now = now or datetime.utcnow()
    since = now - timedelta(hours=pos.KITCHEN_HOURS)
    preparing, ready = [], []
    for s in db.scalars(select(PosSale).where(PosSale.store_id == store.id, PosSale.kitchen.in_(('cocina', 'listo')), PosSale.voided.is_(False),
                                              PosSale.sold_at >= since, PosSale.table_name.is_(None)).order_by(PosSale.sold_at)):
        if not (s.call_number or s.customer_name) or s.service == 'aca':
            continue
        item = {'key': f's{s.id}', 'number': str(s.call_number) if s.call_number else '', 'name': _short(s.customer_name)}
        if s.kitchen == 'cocina':
            preparing.append(item)
        elif s.kitchen_at and s.kitchen_at > now - timedelta(minutes=15):
            ready.append({**item, 'at': s.kitchen_at.isoformat() + 'Z'})
    for o in db.scalars(select(Order).where(Order.store_id == store.id, Order.delivery_method == 'retiro', Order.created_at >= now - timedelta(hours=12),
                                            Order.status.in_((OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO))).order_by(Order.created_at)):
        item = {'key': f'o{o.id}', 'number': f'#{o.id}', 'name': _short(o.customer.first_name if o.customer else '')}
        if o.status == OrderStatus.LISTO:
            at = o.status_time(OrderStatus.LISTO) or o.updated_at
            if at and at > now - timedelta(minutes=15):
                ready.append({**item, 'at': at.isoformat() + 'Z'})
        else:
            preparing.append(item)
    ready.sort(key=lambda x: x['at'], reverse=True)  # el último que salió, arriba y grande
    return {'store': store.name, 'preparing': preparing[:12], 'ready': ready[:8], 'now': now.isoformat() + 'Z'}


# ---------- cliente frecuente ----------

def _digits(phone) -> str:
    return ''.join(ch for ch in str(phone or '') if ch.isdigit())


def find_customer(db: Session, store: Store, phone: str) -> dict | None:
    """Cliente con cuenta Trappi por su teléfono (últimos 10 números). Solo se muestra lo que compró en este local."""
    d = _digits(phone)
    if len(d) < 8:
        raise pos.PosError('Poné el teléfono completo, con la característica.')
    key = d[-10:]
    candidates = db.scalars(select(ClientAccount).where(ClientAccount.active.is_(True), ClientAccount.phone.is_not(None),
                                                        func.replace(func.replace(func.replace(ClientAccount.phone, ' ', ''), '-', ''), '+', '').like(f'%{key[-8:]}'))).all()
    acct = next((a for a in candidates if _digits(a.phone).endswith(key) or key.endswith(_digits(a.phone)[-8:])), None)
    if not acct:
        return None
    from . import loyalty
    sales = db.scalars(select(PosSale).where(PosSale.store_id == store.id, PosSale.account_id == acct.id, PosSale.voided.is_(False))
                       .order_by(PosSale.sold_at.desc()).limit(30)).all()
    orders = db.scalars(select(Order).where(Order.store_id == store.id, Order.account_id == acct.id, Order.status != OrderStatus.CANCELADO)
                        .order_by(Order.created_at.desc()).limit(30)).all()
    purchases = []  # (fecha, total, [{product_id, name, quantity, modifiers_text}])
    for s in sales:
        purchases.append((s.sold_at, money(s.total), [{'product_id': i.get('product_id'), 'name': i['name'], 'quantity': i['quantity'],
                                                       'modifiers': [m['id'] for m in i.get('modifiers', [])], 'note': i.get('note'),
                                                       'modifiers_text': i.get('modifiers_text')} for i in json.loads(s.items or '[]')]))
    for o in orders:
        purchases.append((o.created_at, money(o.total), [{'product_id': it.product_id, 'name': it.product_name, 'quantity': it.quantity,
                                                          'modifiers': [], 'modifiers_text': it.modifiers_text} for it in o.items]))
    purchases.sort(key=lambda x: x[0], reverse=True)
    fav = Counter()
    for _, _, items in purchases:
        for i in items:
            if i['product_id']:
                fav[(i['product_id'], i['name'])] += i['quantity']
    last = purchases[0] if purchases else None
    lc = loyalty.config(db)
    return {'id': acct.id, 'name': ' '.join(x for x in [acct.first_name, (acct.last_name or '')[:1] + '.' if acct.last_name else ''] if x) or 'Cliente',
            'points': loyalty.balance(db, acct.id).points if lc['enabled'] else None,
            'purchases': len(purchases), 'average': float(money(sum((p[1] for p in purchases), ZERO) / len(purchases))) if purchases else 0,
            'last_at': last[0].isoformat() + 'Z' if last else None, 'last_total': float(last[1]) if last else None,
            'last_items': last[2] if last else [], 'favorites': [{'product_id': k[0], 'name': k[1], 'quantity': n} for k, n in fav.most_common(3)]}


# ---------- agotar desde la caja ----------

def set_stock(db: Session, store: Store, product_id: int, action: str) -> Product:
    """out: agotado (también en la app y la web) · tomorrow: agotado hasta que abra mañana · back: disponible otra vez."""
    from . import schedule
    from .stock import restock
    p = db.get(Product, product_id)
    if not p or p.store_id != store.id or p.deleted:
        raise pos.PosError('Ese producto no es de este local.', 404)
    if action == 'back':
        if p.stock is not None and p.stock <= 0:
            restock(p)
        p.out_until = None
    elif action in ('out', 'tomorrow'):
        if not (p.stock is not None and p.stock <= 0):
            p.stock_before_out, p.stock = p.stock, 0
        p.out_until = schedule.next_day_opening(store) if action == 'tomorrow' else None
    else:
        raise pos.PosError('Acción no válida.')
    return p


# ---------- resumen del día ----------

def day_report(db: Session, store: Store, now: datetime | None = None) -> dict:
    """Hoy (hora local) contra el mismo día de la semana pasada: mostrador + pedidos online no cancelados."""
    from .store_hours import local_now
    now_local = to_local(now) if now else local_now()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = now_local.utcoffset() or timedelta(0)
    start = (start_local - offset).replace(tzinfo=None)

    def window(a: datetime, b: datetime):
        sales = db.scalars(select(PosSale).where(PosSale.store_id == store.id, PosSale.voided.is_(False), PosSale.sold_at >= a, PosSale.sold_at < b)).all()
        orders = db.scalars(select(Order).where(Order.store_id == store.id, Order.status != OrderStatus.CANCELADO, Order.created_at >= a, Order.created_at < b)).all()
        return sales, orders

    end = (now_local - offset).replace(tzinfo=None) + timedelta(seconds=1)
    sales, orders = window(start, end)
    prev_sales, prev_orders = window(start - timedelta(days=7), end - timedelta(days=7))  # hasta la misma hora
    counter = sum((money(s.total) for s in sales), ZERO)
    online = sum((money(o.total) for o in orders), ZERO)
    prev = sum((money(s.total) for s in prev_sales), ZERO) + sum((money(o.total) for o in prev_orders), ZERO)
    total = counter + online
    count = len(sales) + len(orders)
    hours = Counter()
    for s in sales:
        hours[to_local(s.sold_at).hour] += float(money(s.total))
    for o in orders:
        hours[to_local(o.created_at).hour] += float(money(o.total))
    top = Counter()
    for s in sales:
        for i in json.loads(s.items or '[]'):
            if i.get('product_id'):
                top[i['product_id']] += int(i.get('quantity') or 0)
    for pid, qty in db.execute(select(OrderItem.product_id, func.sum(OrderItem.quantity)).where(OrderItem.order_id.in_([o.id for o in orders] or [0]),
                                                                                              OrderItem.product_id.is_not(None)).group_by(OrderItem.product_id)):
        top[pid] += int(qty or 0)
    prods = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(list(top) or [0])))}
    tips = sum((money(s.tip) for s in sales), ZERO)
    return {'date': start_local.strftime('%d/%m'), 'total': float(total), 'count': count, 'counter': float(counter), 'online': float(online),
            'average': float(money(total / count)) if count else 0, 'previous': float(prev),
            'change_pct': round(float((total - prev) / prev * 100), 1) if prev > 0 else None, 'tips': float(tips),
            'promos': float(sum((money(s.promo_discount) for s in sales), ZERO)),
            'by_hour': [{'hour': h, 'total': round(hours[h], 2)} for h in sorted(hours)],
            'top': [{'product_id': pid, 'name': prods[pid].name if pid in prods else 'Producto', 'quantity': n,
                     'stock': prods[pid].stock if pid in prods else None, 'out': bool(pid in prods and prods[pid].stock is not None and prods[pid].stock <= 0)}
                    for pid, n in top.most_common(8)]}
