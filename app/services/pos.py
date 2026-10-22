"""Caja (punto de venta) para el mostrador: el programa Trappi Caja para Windows.

Reglas:
  - La compu se vincula una vez con el usuario del local (token de la caja). Cada cajero entra con su PIN.
  - Las ventas se pueden hacer sin internet: la caja les pone un client_uuid y las sube despues; acá no se duplican.
  - Los precios de los productos los pone el servidor (los del menú); solo el "monto libre" lo escribe el cajero.
  - Puntos Trappi: cada venta trae un QR de un solo uso que vence; los puntos quedan fijos al crearlo y hay tope por día.
  - Comisión de Trappi por usar la caja (hoy 0): % por venta y/o abono mensual, en la liquidación del local.
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
from ..models import PointsClaim, PosCashier, PosSale, PosShift, Product, Store
from . import audit, finance, loyalty, platform

METHODS = ('efectivo', 'mercadopago', 'transferencia')
METHOD_LABELS = {'efectivo': 'Efectivo', 'mercadopago': 'Mercado Pago', 'transferencia': 'Transferencia'}
MAX_LINES = 80
MAX_AMOUNT = Decimal('50000000')
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sin 0/O ni 1/I
DEVICE_DAYS = 400
CASHIER_HOURS = 16
_device = URLSafeTimedSerializer(settings.secret_key, salt='trappi-pos-device')
_cashier = URLSafeTimedSerializer(settings.secret_key, salt='trappi-pos-cashier')
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


def shift_summary(db: Session, shift: PosShift) -> dict:
    sales = db.scalars(select(PosSale).where(PosSale.shift_id == shift.id, PosSale.voided.is_(False))).all()
    by = {m: {'count': 0, 'total': ZERO} for m in METHODS}
    for s in sales:
        by[s.payment_method]['count'] += 1
        by[s.payment_method]['total'] += money(s.total)
    total = sum((v['total'] for v in by.values()), ZERO)
    claims = db.scalars(select(PointsClaim).join(PosSale, PosSale.id == PointsClaim.sale_id).where(PosSale.shift_id == shift.id, PosSale.voided.is_(False))).all()
    expected = money(shift.opening_cash) + by['efectivo']['total']
    return {'shift_id': shift.id, 'opened_at': shift.opened_at.isoformat() + 'Z', 'closed_at': shift.closed_at.isoformat() + 'Z' if shift.closed_at else None,
            'sales': len(sales), 'total': float(total), 'average': float(money(total / len(sales))) if sales else 0.0,
            'by_method': {m: {'label': METHOD_LABELS[m], 'count': v['count'], 'total': float(v['total'])} for m, v in by.items()},
            'opening_cash': float(money(shift.opening_cash)), 'expected_cash': float(expected),
            'counted_cash': float(shift.counted_cash) if shift.counted_cash is not None else None,
            'difference': float(money(shift.counted_cash) - expected) if shift.counted_cash is not None else None,
            'points': sum(c.points for c in claims), 'qr_total': len(claims), 'qr_claimed': sum(1 for c in claims if c.claimed_at)}


def close_shift(db: Session, store: Store, cashier: PosCashier, counted_cash) -> dict:
    shift = open_shift(db, store)
    if not shift:
        raise PosError('No hay una caja abierta.', 409)
    counted = money(counted_cash)
    if counted < 0 or counted > MAX_AMOUNT:
        raise PosError('El efectivo contado no es válido.')
    shift.counted_cash = counted
    shift.closed_at, shift.closed_by = datetime.utcnow(), cashier.id
    summary = shift_summary(db, shift)
    shift.expected_cash = Decimal(str(summary['expected_cash']))
    shift.totals = json.dumps(summary, ensure_ascii=False)
    return summary


# ---------- ventas ----------

def _lines(db: Session, store: Store, raw_items) -> tuple[list[dict], Decimal]:
    if not isinstance(raw_items, list) or not raw_items:
        raise PosError('La venta no tiene productos.')
    if len(raw_items) > MAX_LINES:
        raise PosError('La venta tiene demasiadas líneas.')
    ids = {int(i.get('product_id')) for i in raw_items if i.get('product_id')}
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids or [0]), Product.store_id == store.id)).all()}
    out, subtotal = [], ZERO
    for i in raw_items:
        qty = int(i.get('quantity') or 0)
        if qty < 1 or qty > 999:
            raise PosError('Hay una cantidad que no es válida.')
        pid = i.get('product_id')
        if pid:
            p = products.get(int(pid))
            if not p:
                raise PosError('Hay un producto que no es de este local.')
            unit, name = money(p.price), p.name  # el precio lo pone el menú, no la caja
        else:
            unit, name = money(i.get('unit_price')), (str(i.get('name') or 'Monto libre').strip() or 'Monto libre')[:80]
            if unit <= 0 or unit > MAX_AMOUNT:
                raise PosError('El monto libre no es válido.')
        line = money(unit * qty)
        subtotal += line
        out.append({'product_id': int(pid) if pid else None, 'name': name, 'quantity': qty, 'unit_price': float(unit), 'total': float(line)})
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
    if method not in METHODS:
        raise PosError('Medio de pago no válido.')
    cashier = db.get(PosCashier, int(data.get('cashier_id') or 0))
    if not cashier or cashier.store_id != store.id:
        raise PosError('Cajero no válido.')
    items, subtotal = _lines(db, store, data.get('items'))
    discount = money(data.get('discount'))
    if discount < 0 or discount > subtotal:
        raise PosError('El descuento no es válido.')
    total = subtotal - discount
    pay = None
    if data.get('points_payment_id'):
        from . import pos_points
        try:
            pay = pos_points.use_in_sale(db, store, data['points_payment_id'], total)
        except pos_points.PointsPayError as e:
            raise PosError(str(e), e.status)
        total -= money(pay.discount)
    paid_with = money(data['paid_with']) if method == 'efectivo' and data.get('paid_with') not in (None, '') else None
    if paid_with is not None and paid_with < total:
        raise PosError('El efectivo recibido es menor que el total.')
    try:
        sold_at = datetime.fromisoformat(str(data.get('sold_at', '')).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        sold_at = now
    sold_at = min(max(sold_at, now - timedelta(days=7)), now + timedelta(minutes=5))
    shift = open_shift(db, store)
    number = (db.scalar(select(func.max(PosSale.number)).where(PosSale.store_id == store.id)) or 0) + 1
    pct, fee = commission(db, store)
    comm = money(total * pct / 100) if pct > 0 else ZERO
    from .stock import take_for_pos
    take_for_pos(db, store.id, items)  # el mismo stock que los pedidos online
    sale = PosSale(store_id=store.id, shift_id=shift.id if shift else None, cashier_id=cashier.id, client_uuid=uuid, number=number,
                   items=json.dumps(items, ensure_ascii=False), subtotal=subtotal, discount=discount, total=total, payment_method=method,
                   paid_with=paid_with, points=0, commission=comm, sold_at=sold_at, created_at=now,
                   points_discount=money(pay.discount) if pay else ZERO, points_payment_id=pay.id if pay else None)
    db.add(sale)
    try:
        db.flush()
    except IntegrityError:  # la misma venta llegó dos veces a la vez
        db.rollback()
        return db.scalar(select(PosSale).where(PosSale.store_id == store.id, PosSale.client_uuid == uuid))
    if pay:
        from . import pos_points
        pos_points.after_sale(db, store, pay, sale)
    points = _points_for(db, store, total, now)
    if points:
        sale.points = points
        db.add(PointsClaim(code=_new_code(db), store_id=store.id, sale_id=sale.id, points=points,
                           expires_at=now + timedelta(days=points_config(db)['days']), created_at=now))
    if comm > 0:
        finance.entry(db, 'merchant', 'pos_commission', -comm, store_id=store.id, description=f'Comisión caja · venta #{number}',
                      dedupe=f'pos:{sale.id}:commission')
    if fee > 0:
        month = now.strftime('%Y-%m')
        finance.entry(db, 'merchant', 'pos_fee', -fee, store_id=store.id, description=f'Abono caja Trappi {month}', dedupe=f'pos:{store.id}:fee:{month}')
    db.flush()
    return sale


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
