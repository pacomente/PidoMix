"""Caja (punto de venta) para el mostrador: el programa Trappi Caja para Windows.

Reglas:
  - La compu se vincula una vez con el usuario del local (token de la caja). Cada cajero entra con su PIN.
  - Las ventas se pueden hacer sin internet: la caja les pone un client_uuid y las sube despues; acá no se duplican.
  - Los precios de los productos los pone el servidor (los del menú); solo el "monto libre" lo escribe el cajero.
  - Puntos Trappi: cada venta trae un QR de un solo uso que vence; los puntos quedan fijos al crearlo y hay tope por día.
  - Comisión de Trappi por usar la caja (hoy 0): % por venta y/o abono mensual, en la liquidación del local.
  - Gastronomía: cada línea puede traer opciones del menú (las cobra el servidor) y una aclaración; la venta puede ir al
    tablero de Comandas (cocina -> listo -> entregado), pagarse con varios medios y llevar número o nombre para llamarlo.
  - Retiros e ingresos de efectivo cuentan en el cierre. Un retiro y un descuento grande de un cajero los autoriza el dueño.
"""
import json
import math
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ModifierGroup, ModifierOption, PointsClaim, PosCashier, PosCashMovement, PosSale, PosShift, Product, Store
from . import audit, finance, loyalty, platform

METHODS = ('efectivo', 'mercadopago', 'transferencia')
METHOD_LABELS = {'efectivo': 'Efectivo', 'mercadopago': 'Mercado Pago', 'transferencia': 'Transferencia', 'mixto': 'Mixto'}
SERVICES = {'aca': 'Para comer acá', 'llevar': 'Para llevar'}
KITCHEN = ('cocina', 'listo', 'entregado')
KITCHEN_HOURS = 8  # lo que quedo sin marcar en el tablero se va solo despues de este rato
FREE_DISCOUNT_PCT = Decimal('10')  # hasta este % un cajero descuenta solo; mas, lo autoriza el dueño
MOVEMENTS = {'retiro': 'Retiro', 'ingreso': 'Ingreso'}
BILLS = (20000, 10000, 2000, 1000, 500, 200, 100, 50, 20, 10)  # billetes para el arqueo (y "monedas" aparte)
MAX_NOTE = 120
MAX_LINES = 80
MAX_AMOUNT = Decimal('50000000')
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sin 0/O ni 1/I
DEVICE_DAYS = 400
CASHIER_HOURS = 16
_device = URLSafeTimedSerializer(settings.secret_key, salt='trappi-pos-device')
_cashier = URLSafeTimedSerializer(settings.secret_key, salt='trappi-pos-cashier')
_approval = URLSafeTimedSerializer(settings.secret_key, salt='trappi-pos-approval')
APPROVAL_HOURS = 2
ZERO = Decimal('0')


class PosError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ---------- quién puede usarla y cuánto cuesta ----------

def available(db: Session, store: Store) -> bool:
    if store.pos_enabled is not None:  # lo de la ficha del comercio manda
        return bool(store.pos_enabled)
    cfg = platform.get_all(db)
    if not cfg['pos_enabled']:
        return False
    plans = cfg['pos_plans']
    if plans == 'comercio':
        return store.plan == 'TRAPPI_COMERCIO'
    if plans == 'delivery':
        return store.plan == 'TRAPPI_DELIVERY'
    return True


def commission(db: Session, store: Store) -> tuple[Decimal, Decimal]:
    """(% por venta, abono mensual) que rige para este comercio."""
    cfg = platform.get_all(db)
    pct = store.pos_commission_percent if store.pos_commission_percent is not None else cfg['pos_commission_percent']
    fee = store.pos_monthly_fee if store.pos_monthly_fee is not None else cfg['pos_monthly_fee']
    return money(pct), money(fee)


def points_config(db: Session) -> dict:
    cfg = platform.get_all(db)
    lc = loyalty.config(db)
    on = bool(cfg['pos_points']) and lc['enabled'] and lc['per_point'] > 0
    return {'enabled': on, 'per_point': lc['per_point'], 'value': lc['value'], 'days': int(cfg['pos_qr_days']),
            'cap': int(cfg['pos_daily_points_cap'])}


# ---------- vincular la compu y los cajeros ----------

def device_token(store: Store) -> str:
    return _device.dumps({'s': store.id, 'v': store.pos_device_version})


def store_from_token(db: Session, token: str) -> Store:
    try:
        data = _device.loads(token, max_age=DEVICE_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        raise PosError('La caja no está vinculada. Volvé a ingresar con el usuario del local.', 401)
    store = db.get(Store, int(data.get('s', 0)))
    if not store or store.pos_device_version != data.get('v'):
        raise PosError('La caja fue desvinculada desde el panel. Volvé a ingresar con el usuario del local.', 401)
    if not available(db, store):
        raise PosError('La caja no está habilitada para este comercio. Escribile a Trappi.', 403)
    return store


def cashier_token(c: PosCashier) -> str:
    return _cashier.dumps({'c': c.id, 's': c.store_id})


def cashier_from_token(db: Session, store: Store, token: str | None) -> PosCashier:
    try:
        data = _cashier.loads(token or '', max_age=CASHIER_HOURS * 3600)
    except (BadSignature, SignatureExpired):
        raise PosError('Volvé a poner tu PIN.', 401)
    c = db.get(PosCashier, int(data.get('c', 0)))
    if not c or not c.active or c.store_id != store.id:
        raise PosError('Ese cajero ya no está habilitado.', 401)
    return c


def cashiers(db: Session, store: Store) -> list[PosCashier]:
    return db.scalars(select(PosCashier).where(PosCashier.store_id == store.id, PosCashier.active.is_(True)).order_by(PosCashier.name)).all()


# ---------- turno (caja abierta) ----------

def open_shift(db: Session, store: Store) -> PosShift | None:
    return db.scalar(select(PosShift).where(PosShift.store_id == store.id, PosShift.closed_at.is_(None)).order_by(PosShift.id.desc()))


def start_shift(db: Session, store: Store, cashier: PosCashier, opening_cash) -> PosShift:
    current = open_shift(db, store)
    if current:
        return current
    amount = money(opening_cash)
    if amount < 0 or amount > MAX_AMOUNT:
        raise PosError('El fondo inicial no es válido.')
    s = PosShift(store_id=store.id, opened_by=cashier.id, opening_cash=amount, opened_at=datetime.utcnow())
    db.add(s)
    db.flush()
    return s


def sale_payments(sale: PosSale) -> list[dict]:
    """[{method, amount}] de la venta: los medios del pago mixto o el unico medio por el total."""
    if sale.payments:
        try:
            return [{'method': p['method'], 'amount': money(p['amount'])} for p in json.loads(sale.payments)]
        except (ValueError, KeyError, TypeError):
            pass
    return [{'method': sale.payment_method, 'amount': money(sale.total) + money(sale.tip)}]


def movements(db: Session, shift: PosShift) -> list[PosCashMovement]:
    return db.scalars(select(PosCashMovement).where(PosCashMovement.shift_id == shift.id).order_by(PosCashMovement.id)).all()


def shift_summary(db: Session, shift: PosShift) -> dict:
    sales = db.scalars(select(PosSale).where(PosSale.shift_id == shift.id, PosSale.voided.is_(False))).all()
    by = {m: {'count': 0, 'total': ZERO} for m in METHODS}
    tips = {m: ZERO for m in METHODS}
    for s in sales:
        pays = sale_payments(s)
        for p in pays:
            if p['method'] in by:
                by[p['method']]['count'] += 1
                by[p['method']]['total'] += p['amount']
        if s.tip and pays and pays[0]['method'] in tips:
            tips[pays[0]['method']] += money(s.tip)  # la propina va con el primer medio (la caja la cobra así)
    total = sum((money(s.total) for s in sales), ZERO)
    claims = db.scalars(select(PointsClaim).join(PosSale, PosSale.id == PointsClaim.sale_id).where(PosSale.shift_id == shift.id, PosSale.voided.is_(False))).all()
    moves = movements(db, shift)
    names = {c.id: c.name for c in db.scalars(select(PosCashier).where(PosCashier.store_id == shift.store_id))}
    cash_in = sum((money(m.amount) for m in moves if m.kind == 'ingreso'), ZERO)
    cash_out = sum((money(m.amount) for m in moves if m.kind == 'retiro'), ZERO)
    voided = db.scalars(select(PosSale).where(PosSale.shift_id == shift.id, PosSale.voided.is_(True))).all()
    expected = money(shift.opening_cash) + by['efectivo']['total'] + cash_in - cash_out
    return {'shift_id': shift.id, 'opened_at': shift.opened_at.isoformat() + 'Z', 'closed_at': shift.closed_at.isoformat() + 'Z' if shift.closed_at else None,
            'sales': len(sales), 'total': float(total), 'average': float(money(total / len(sales))) if sales else 0.0,
            'by_method': {m: {'label': METHOD_LABELS[m], 'count': v['count'], 'total': float(v['total'])} for m, v in by.items()},
            'opening_cash': float(money(shift.opening_cash)), 'expected_cash': float(expected),
            'counted_cash': float(shift.counted_cash) if shift.counted_cash is not None else None,
            'difference': float(money(shift.counted_cash) - expected) if shift.counted_cash is not None else None,
            'points': sum(c.points for c in claims), 'qr_total': len(claims), 'qr_claimed': sum(1 for c in claims if c.claimed_at),
            'cash_in': float(cash_in), 'cash_out': float(cash_out),
            'movements': [{'id': m.id, 'kind': m.kind, 'label': MOVEMENTS[m.kind], 'amount': float(m.amount), 'reason': m.reason,
                           'cashier': names.get(m.cashier_id), 'at': m.created_at.isoformat() + 'Z'} for m in moves],
            'voided': len(voided), 'voided_total': float(sum((money(v.total) for v in voided), ZERO)),
            'discounts': float(sum((money(s.discount) for s in sales), ZERO)),
            'promos': float(sum((money(s.promo_discount) for s in sales), ZERO)),
            'tips': float(sum(tips.values(), ZERO)), 'tips_cash': float(tips['efectivo'])}


def count_bills(bills) -> tuple[Decimal, dict]:
    """Arqueo: {"20000": 3, "1000": 7, "monedas": 350} -> (total, lo mismo limpio). Los billetes que no existen se ignoran."""
    if not isinstance(bills, dict):
        raise PosError('El arqueo no es válido.')
    clean, total = {}, ZERO
    for b in BILLS:
        n = bills.get(str(b), bills.get(b, 0))
        try:
            n = int(n or 0)
        except (TypeError, ValueError):
            raise PosError('El arqueo no es válido.')
        if n < 0 or n > 100000:
            raise PosError('Hay una cantidad de billetes que no es válida.')
        if n:
            clean[str(b)] = n
            total += Decimal(b) * n
    coins = money(bills.get('monedas') or 0)
    if coins < 0 or coins > MAX_AMOUNT:
        raise PosError('Las monedas no son válidas.')
    if coins:
        clean['monedas'] = float(coins)
        total += coins
    return money(total), clean


def close_shift(db: Session, store: Store, cashier: PosCashier, counted_cash, bills=None) -> dict:
    shift = open_shift(db, store)
    if not shift:
        raise PosError('No hay una caja abierta.', 409)
    counted, counted_bills = (count_bills(bills) if bills else (money(counted_cash), None))
    if counted < 0 or counted > MAX_AMOUNT:
        raise PosError('El efectivo contado no es válido.')
    shift.counted_cash = counted
    shift.closed_at, shift.closed_by = datetime.utcnow(), cashier.id
    summary = shift_summary(db, shift)
    summary['bills'] = counted_bills
    summary['closed_by'] = cashier.name
    shift.expected_cash = Decimal(str(summary['expected_cash']))
    shift.totals = json.dumps(summary, ensure_ascii=False)
    return summary


def add_movement(db: Session, store: Store, cashier: PosCashier, data: dict, owner: PosCashier | None = None) -> PosCashMovement:
    """Retiro o ingreso de efectivo en la caja abierta. El retiro lo autoriza un dueño. Idempotente por client_uuid. No hace commit."""
    uuid = str(data.get('client_uuid') or '').strip()[:40]
    if len(uuid) < 8:
        raise PosError('Falta el identificador del movimiento.')
    existing = db.scalar(select(PosCashMovement).where(PosCashMovement.store_id == store.id, PosCashMovement.client_uuid == uuid))
    if existing:
        return existing
    kind = data.get('kind')
    if kind not in MOVEMENTS:
        raise PosError('Tiene que ser un retiro o un ingreso.')
    if kind == 'retiro' and not (cashier.is_owner or (owner and owner.is_owner)):
        raise PosError('Un retiro de efectivo lo autoriza el dueño.', 403)
    amount = money(data.get('amount'))
    if amount <= 0 or amount > MAX_AMOUNT:
        raise PosError('El importe no es válido.')
    reason = ' '.join(str(data.get('reason') or '').split())[:120]
    if len(reason) < 3:
        raise PosError('Poné el motivo (por ejemplo: pago al proveedor de bebidas).')
    shift = open_shift(db, store)
    if not shift:
        raise PosError('No hay una caja abierta.', 409)
    m = PosCashMovement(store_id=store.id, shift_id=shift.id, cashier_id=cashier.id, client_uuid=uuid, kind=kind, amount=amount, reason=reason,
                        created_at=datetime.utcnow())
    db.add(m)
    db.flush()
    by = owner if owner and owner.id != cashier.id else None
    audit.log(db, f'pos.cash.{kind}', 'pos_shift', shift.id, new={'amount': str(amount), 'reason': reason},
              reason=f'{cashier.name}' + (f' (autorizó {by.name})' if by else ''))
    return m


# ---------- autorización del dueño (descuentos grandes) ----------

def approval_token(store: Store, owner: PosCashier, kind: str, amount) -> str:
    """El dueño pone su PIN y la caja recibe esto para un descuento de hasta [amount]. Vale un rato y sirve sin internet."""
    if not owner.is_owner or owner.store_id != store.id:
        raise PosError('Solo el dueño puede autorizar.', 403)
    if kind != 'discount':
        raise PosError('No se puede autorizar eso.')
    value = money(amount)
    if value <= 0 or value > MAX_AMOUNT:
        raise PosError('El importe no es válido.')
    return _approval.dumps({'s': store.id, 'o': owner.id, 'k': kind, 'a': str(value)})


def check_approval(db: Session, store: Store, token: str | None, kind: str, amount: Decimal) -> PosCashier | None:
    """El dueño que autorizó (o None si no hay autorización válida para ese importe)."""
    if not token:
        return None
    try:
        data = _approval.loads(str(token), max_age=APPROVAL_HOURS * 3600 + 7 * 86400)  # la venta puede subirse días despues
    except (BadSignature, SignatureExpired):
        return None
    if data.get('s') != store.id or data.get('k') != kind or money(data.get('a')) < amount:
        return None
    owner = db.get(PosCashier, int(data.get('o') or 0))
    return owner if owner and owner.store_id == store.id and owner.is_owner else None


# ---------- ventas ----------

def _lines(db: Session, store: Store, raw_items) -> tuple[list[dict], Decimal]:
    if not isinstance(raw_items, list) or not raw_items:
        raise PosError('La venta no tiene productos.')
    if len(raw_items) > MAX_LINES:
        raise PosError('La venta tiene demasiadas líneas.')
    try:
        ids = {int(i.get('product_id')) for i in raw_items if i.get('product_id')}
    except (TypeError, ValueError, AttributeError):
        raise PosError('Hay un producto que no es válido.')
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids or [0]), Product.store_id == store.id)).all()}
    # opciones de esos productos (gustos, extras, punto...): la caja manda los ids y el precio lo pone el menú
    options = {}
    for o, pid in db.execute(select(ModifierOption, ModifierGroup.product_id).join(ModifierGroup, ModifierGroup.id == ModifierOption.group_id)
                             .where(ModifierGroup.product_id.in_(ids or [0]))):
        options[o.id] = (pid, o)
    out, subtotal = [], ZERO
    for i in raw_items:
        try:
            qty = int(i.get('quantity') or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1 or qty > 999:
            raise PosError('Hay una cantidad que no es válida.')
        pid = i.get('product_id')
        mods = []
        if pid:
            p = products.get(int(pid))
            if not p:
                raise PosError('Hay un producto que no es de este local.')
            unit, name = money(p.price), p.name  # el precio lo pone el menú, no la caja
            raw_mods = i.get('modifiers') or []
            if not isinstance(raw_mods, list) or len(raw_mods) > 30:
                raise PosError('Las opciones de un producto no son válidas.')
            for mid in raw_mods:
                try:
                    hit = options.get(int(mid))
                except (TypeError, ValueError):
                    hit = None
                # una opcion de otro producto no se acepta; una que se agotó despues de venderla (sin internet) se cobra igual
                if not hit or hit[0] != p.id:
                    raise PosError(f'Hay una opción que no es de {p.name}.')
                if hit[1].id not in {m['id'] for m in mods}:
                    mods.append({'id': hit[1].id, 'name': hit[1].name, 'price': float(money(hit[1].price_extra))})
            unit += sum((money(m['price']) for m in mods), ZERO)
        else:
            unit, name = money(i.get('unit_price')), (str(i.get('name') or 'Monto libre').strip() or 'Monto libre')[:80]
            if unit <= 0 or unit > MAX_AMOUNT:
                raise PosError('El monto libre no es válido.')
        line = money(unit * qty)
        subtotal += line
        row = {'product_id': int(pid) if pid else None, 'name': name, 'quantity': qty, 'unit_price': float(unit), 'total': float(line)}
        if mods:
            row['modifiers'] = mods
            row['modifiers_text'] = ', '.join(m['name'] for m in mods)
        note = ' '.join(str(i.get('note') or '').split())[:MAX_NOTE]
        if note:
            row['note'] = note
        out.append(row)
    return out, subtotal


def _new_code(db: Session) -> str:
    for _ in range(8):
        raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        code = f'{raw[:4]}-{raw[4:]}'
        if not db.scalar(select(PointsClaim.id).where(PointsClaim.code == code)):
            return code
    raise PosError('No se pudo generar el QR. Probá de nuevo.', 500)


def _points_for(db: Session, store: Store, total: Decimal, now: datetime) -> int:
    pc = points_config(db)
    if not pc['enabled']:
        return 0
    points = max(0, math.floor(total / pc['per_point']))
    if pc['cap'] > 0:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        given = db.scalar(select(func.coalesce(func.sum(PosSale.points), 0)).where(PosSale.store_id == store.id, PosSale.created_at >= start,
                                                                                  PosSale.voided.is_(False))) or 0
        points = max(0, min(points, pc['cap'] - int(given)))
    return points


def claim_url(code: str) -> str:
    base = (settings.public_base_url or 'https://trappi.com.ar').rstrip('/')
    return f'{base}/puntos/q/{code}'


def sale_json(db: Session, sale: PosSale) -> dict:
    claim = db.scalar(select(PointsClaim).where(PointsClaim.sale_id == sale.id))
    return {'id': sale.id, 'client_uuid': sale.client_uuid, 'number': sale.number, 'total': float(sale.total),
            'subtotal': float(sale.subtotal), 'discount': float(sale.discount), 'points_discount': float(sale.points_discount or 0),
            'payment_method': sale.payment_method,
            'paid_with': float(sale.paid_with) if sale.paid_with is not None else None, 'items': json.loads(sale.items),
            'sold_at': sale.sold_at.isoformat() + 'Z', 'voided': sale.voided, 'points': sale.points, 'cashier_id': sale.cashier_id,
            'payments': [{'method': p['method'], 'label': METHOD_LABELS.get(p['method'], p['method']), 'amount': float(p['amount'])} for p in sale_payments(sale)],
            'call_number': sale.call_number, 'customer_name': sale.customer_name, 'service': sale.service, 'kitchen': sale.kitchen,
            'promo_discount': float(sale.promo_discount or 0), 'promos': json.loads(sale.promos) if sale.promos else [],
            'tip': float(sale.tip or 0), 'table_name': sale.table_name, 'account_id': sale.account_id,
            'claim': ({'code': claim.code, 'url': claim_url(claim.code), 'expires_at': claim.expires_at.isoformat() + 'Z',
                       'claimed': bool(claim.claimed_at)} if claim else None)}


def record_sale(db: Session, store: Store, data: dict, now: datetime | None = None) -> PosSale:
    """Guarda una venta (subida en el momento o despues de un corte de internet). Idempotente por client_uuid. No hace commit."""
    now = now or datetime.utcnow()
    uuid = str(data.get('client_uuid') or '').strip()[:40]
    if len(uuid) < 8:
        raise PosError('Falta el identificador de la venta.')
    existing = db.scalar(select(PosSale).where(PosSale.store_id == store.id, PosSale.client_uuid == uuid))
    if existing:
        return existing
    method = data.get('payment_method')
    if method not in METHODS and method != 'mixto':
        raise PosError('Medio de pago no válido.')
    try:
        cashier = db.get(PosCashier, int(data.get('cashier_id') or 0))
    except (TypeError, ValueError):
        cashier = None
    if not cashier or cashier.store_id != store.id:
        raise PosError('Cajero no válido.')
    items, subtotal = _lines(db, store, data.get('items'))
    try:
        sold_at = datetime.fromisoformat(str(data.get('sold_at', '')).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        sold_at = now
    sold_at = min(max(sold_at, now - timedelta(days=7)), now + timedelta(minutes=5))
    from . import pos_salon
    promo_off, promos = pos_salon.promos_for_sale(db, store, items, sold_at)  # 2x1, combos, happy hour: a la hora de la venta
    discount = money(data.get('discount'))
    if discount < 0 or discount > subtotal - promo_off:
        discount = max(ZERO, min(discount, subtotal - promo_off))  # la venta ya se hizo: no se rechaza por una promo que cambió
    total = subtotal - promo_off - discount
    pay = None
    if data.get('points_payment_id'):
        from . import pos_points
        try:
            pay = pos_points.use_in_sale(db, store, data['points_payment_id'], total)
        except pos_points.PointsPayError as e:
            raise PosError(str(e), e.status)
        total -= money(pay.discount)
    approver = None
    if discount > 0 and not cashier.is_owner and discount > money(subtotal * FREE_DISCOUNT_PCT / 100):
        approver = check_approval(db, store, data.get('approval'), 'discount', discount)
    tip = money(data.get('tip'))
    if tip < 0 or tip > MAX_AMOUNT:
        raise PosError('La propina no es válida.')
    split = _split(data.get('payments'), total + tip) if method == 'mixto' else None
    if split and len(split) == 1:
        method, split = split[0]['method'], None
    cash_part = total + tip if method == 'efectivo' else (sum((p['amount'] for p in split if p['method'] == 'efectivo'), ZERO) or None if split else None)
    paid_with = money(data['paid_with']) if cash_part is not None and data.get('paid_with') not in (None, '') else None
    if paid_with is not None and paid_with < cash_part:
        raise PosError('El efectivo recibido es menor que el total.')
    try:
        call_number = int(data['call_number']) if data.get('call_number') not in (None, '') else None
    except (TypeError, ValueError):
        call_number = None
    if call_number is not None and not 1 <= call_number <= 9999:
        call_number = None
    customer_name = ' '.join(str(data.get('customer_name') or '').split())[:60] or None
    service = data.get('service') if data.get('service') in SERVICES else None
    account = None
    if data.get('account_id'):
        from ..models import ClientAccount
        try:
            account = db.get(ClientAccount, int(data['account_id']))
        except (TypeError, ValueError):
            account = None
        from . import pos_salon
        account = account if account and account.active and pos_salon.has(store, 'customers') else None
    table_name = ' '.join(str(data.get('table_name') or '').split())[:40] or None
    shift = open_shift(db, store)
    number = (db.scalar(select(func.max(PosSale.number)).where(PosSale.store_id == store.id)) or 0) + 1
    pct, fee = commission(db, store)
    comm = money(total * pct / 100) if pct > 0 else ZERO
    from .stock import take_for_pos
    take_for_pos(db, store.id, items)  # el mismo stock que los pedidos online
    sale = PosSale(store_id=store.id, shift_id=shift.id if shift else None, cashier_id=cashier.id, client_uuid=uuid, number=number,
                   items=json.dumps(items, ensure_ascii=False), subtotal=subtotal, discount=discount, total=total, payment_method=method,
                   paid_with=paid_with, points=0, commission=comm, sold_at=sold_at, created_at=now,
                   points_discount=money(pay.discount) if pay else ZERO, points_payment_id=pay.id if pay else None,
                   payments=json.dumps([{'method': p['method'], 'amount': str(p['amount'])} for p in split]) if split else None,
                   call_number=call_number, customer_name=customer_name, service=service,
                   kitchen='cocina' if data.get('kitchen') and sold_at > now - timedelta(hours=KITCHEN_HOURS) else None,
                   kitchen_at=now if data.get('kitchen') else None, approved_by=approver.id if approver else None,
                   promo_discount=promo_off, promos=json.dumps(promos, ensure_ascii=False) if promos else None, tip=tip,
                   account_id=account.id if account else None, table_name=table_name)
    db.add(sale)
    try:
        db.flush()
    except IntegrityError:  # la misma venta llegó dos veces a la vez
        db.rollback()
        return db.scalar(select(PosSale).where(PosSale.store_id == store.id, PosSale.client_uuid == uuid))
    if pay:
        from . import pos_points
        pos_points.after_sale(db, store, pay, sale)
    if discount > 0 and not cashier.is_owner and discount > money(subtotal * FREE_DISCOUNT_PCT / 100):
        # descuento grande de un cajero: queda registrado quien lo autorizo (o que nadie lo hizo, para que el dueño lo vea)
        audit.log(db, 'pos.discount' if approver else 'pos.discount.unapproved', 'pos_sale', sale.id,
                  new={'discount': str(discount), 'subtotal': str(subtotal)},
                  reason=f'{cashier.name}' + (f' · autorizó {approver.name}' if approver else ' · sin autorización del dueño'))
    points = _points_for(db, store, total, now)
    if points:
        sale.points = points
        pc = PointsClaim(code=_new_code(db), store_id=store.id, sale_id=sale.id, points=points,
                         expires_at=now + timedelta(days=points_config(db)['days']), created_at=now)
        db.add(pc)
        if account:  # cliente frecuente: los puntos van directo a su cuenta, sin escanear el QR
            db.flush()
            try:
                claim(db, pc.code, account)
            except PosError:
                pass  # queda el QR para que lo escanee
    if comm > 0:
        finance.entry(db, 'merchant', 'pos_commission', -comm, store_id=store.id, description=f'Comisión caja · venta #{number}',
                      dedupe=f'pos:{sale.id}:commission')
    if fee > 0:
        month = now.strftime('%Y-%m')
        finance.entry(db, 'merchant', 'pos_fee', -fee, store_id=store.id, description=f'Abono caja Trappi {month}', dedupe=f'pos:{store.id}:fee:{month}')
    db.flush()
    return sale


def _split(raw, total: Decimal) -> list[dict]:
    """Pago mixto: [{method, amount}] con dos a ocho pagos (también la cuenta dividida en partes). Si no suma justo el total (la caja redondea, o el precio
    del menú cambió mientras estaba sin internet) la diferencia va al efectivo, o al primer medio: la venta ya se hizo."""
    if not isinstance(raw, list) or not 2 <= len(raw) <= 8:
        raise PosError('El pago mixto tiene que tener entre dos y ocho pagos.')
    out = []
    for p in raw:  # el mismo medio puede repetirse: una cuenta dividida en partes iguales
        m = (p or {}).get('method') if isinstance(p, dict) else None
        if m not in METHODS:
            raise PosError('El pago mixto tiene un medio de pago no válido.')
        a = money(p.get('amount'))
        if a <= 0 or a > MAX_AMOUNT:
            raise PosError('El pago mixto tiene un importe no válido.')
        out.append({'method': m, 'amount': a})
    diff = total - sum((p['amount'] for p in out), ZERO)
    if diff:
        target = next((p for p in out if p['method'] == 'efectivo'), out[0])
        target['amount'] = money(target['amount'] + diff)
        if target['amount'] <= 0:  # no alcanza para corregirlo: queda todo en el primer medio
            return [{'method': out[0]['method'], 'amount': total}]
    return out


def void_sale(db: Session, store: Store, sale_id: int, cashier: PosCashier) -> PosSale:
    """Anular una venta (solo el dueño). Se anula el QR si no se usó y se devuelve la comisión."""
    if not cashier.is_owner:
        raise PosError('Solo el dueño puede anular ventas.', 403)
    sale = db.get(PosSale, sale_id)
    if not sale or sale.store_id != store.id:
        raise PosError('Esa venta no existe.', 404)
    if sale.voided:
        return sale
    sale.voided = True
    if sale.kitchen in ('cocina', 'listo'):
        sale.kitchen = None  # ya no se prepara: sale del tablero
    from .stock import give_back_pos
    items = json.loads(sale.items or '[]')
    give_back_pos(db, items)
    sale.items = json.dumps(items, ensure_ascii=False)
    claim = db.scalar(select(PointsClaim).where(PointsClaim.sale_id == sale.id))
    if claim and not claim.claimed_at:
        claim.expires_at = datetime.utcnow()  # ya no se puede usar
    if sale.commission and sale.commission > 0:
        finance.entry(db, 'merchant', 'pos_commission', money(sale.commission), store_id=store.id,
                      description=f'Venta #{sale.number} anulada: se devuelve la comisión', dedupe=f'pos:{sale.id}:commission:void')
    if sale.points_payment_id:
        from . import pos_points
        pos_points.on_void(db, store, sale)
    audit.log(db, 'pos.void', 'pos_sale', sale.id, old={'total': str(sale.total)}, new={'voided': True}, reason=f'Anulada por {cashier.name}')
    return sale


# ---------- el cliente escanea el QR ----------

def claim_status(db: Session, code: str) -> tuple[PointsClaim | None, str | None]:
    c = db.scalar(select(PointsClaim).where(PointsClaim.code == (code or '').strip().upper()))
    if not c:
        return None, 'Ese código no existe.'
    sale = db.get(PosSale, c.sale_id)
    if sale and sale.voided:
        return c, 'Esa venta fue anulada.'
    if c.claimed_at:
        return c, 'Estos puntos ya se sumaron a una cuenta.'
    if c.expires_at < datetime.utcnow():
        return c, 'Este QR venció.'
    return c, None


def claim(db: Session, code: str, account) -> PointsClaim:
    """Suma los puntos del QR a la cuenta. Un solo uso. No hace commit."""
    c, problem = claim_status(db, code)
    if problem:
        raise PosError(problem, 409 if c else 404)
    store = db.get(Store, c.store_id)
    months = loyalty.config(db)['months']
    expires = datetime.utcnow() + timedelta(days=30 * months) if months else None
    added = loyalty._add(db, account.id, 'earn', c.points, expires_at=expires, note=f'Compra en el local {store.name if store else ""}'.strip(),
                         dedupe=f'pos:{c.code}')
    if not added:
        raise PosError('Estos puntos ya se sumaron a una cuenta.', 409)
    c.claimed_by, c.claimed_at = account.id, datetime.utcnow()
    return c


# ---------- tablero de cocina (Comandas) ----------

def kitchen_sales(db: Session, store_id: int, now: datetime | None = None) -> list[PosSale]:
    """Ventas del mostrador que la cocina tiene que preparar o entregar (las de mas de unas horas se dejan de mostrar)."""
    since = (now or datetime.utcnow()) - timedelta(hours=KITCHEN_HOURS)
    return db.scalars(select(PosSale).where(PosSale.store_id == store_id, PosSale.kitchen.in_(('cocina', 'listo')), PosSale.voided.is_(False),
                                            PosSale.sold_at >= since).order_by(PosSale.sold_at)).all()


def set_kitchen(db: Session, store_id: int, sale_id: int, status: str) -> PosSale:
    sale = db.get(PosSale, sale_id)
    if not sale or sale.store_id != store_id or sale.voided:
        raise PosError('Esa venta no existe.', 404)
    if status not in KITCHEN:
        raise PosError('Estado no válido.')
    sale.kitchen, sale.kitchen_at = status, datetime.utcnow()
    return sale


def call_label(sale: PosSale) -> str:
    """Como se lo llama al mostrador: "Pedido 23 · Juan", "Juan" o "Venta #812"."""
    parts = [f'Pedido {sale.call_number}' if sale.call_number else None, sale.customer_name]
    return ' · '.join(p for p in parts if p) or f'Venta #{sale.number}'


# ---------- los que más se venden (botones de favoritos) ----------

FAVORITES = 12


def favorites(db: Session, store: Store, days: int = 30) -> list[int]:
    """Ids de los productos mas vendidos en el mostrador (y si todavia hay pocas ventas, en los pedidos online)."""
    from collections import Counter
    from ..models import Order, OrderItem, OrderStatus
    since = datetime.utcnow() - timedelta(days=days)
    count = Counter()
    for raw in db.scalars(select(PosSale.items).where(PosSale.store_id == store.id, PosSale.voided.is_(False), PosSale.sold_at >= since)
                          .order_by(PosSale.id.desc()).limit(3000)):
        try:
            for it in json.loads(raw or '[]'):
                if it.get('product_id'):
                    count[int(it['product_id'])] += int(it.get('quantity') or 0)
        except (ValueError, TypeError):
            continue
    if len(count) < FAVORITES:
        for pid, qty in db.execute(select(OrderItem.product_id, func.sum(OrderItem.quantity)).join(Order, Order.id == OrderItem.order_id)
                                   .where(Order.store_id == store.id, Order.status != OrderStatus.CANCELADO, Order.created_at >= since,
                                          OrderItem.product_id.is_not(None))
                                   .group_by(OrderItem.product_id)):
            count[int(pid)] += int(qty or 0) // 4 + 1  # pesan menos que lo del mostrador
    return [pid for pid, _ in count.most_common(FAVORITES * 2)]
