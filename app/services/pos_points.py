"""Pagar con Puntos Trappi en el mostrador.

  1. El local imprime su QR fijo del mostrador (panel → Caja) y lo deja en la caja.
  2. El cajero arma el ticket y toca "Puntos Trappi": la caja pide un pago con el total y recibe un código de 4 números.
  3. El cliente escanea el QR del mostrador (web o app), entra con su cuenta, pone el código y confirma.
     Ve cuánto se descuenta antes de confirmar. Los puntos se descuentan en ese momento.
  4. La caja ve la confirmación, resta el descuento y el cliente paga el resto como siempre.

Reglas (las mismas que en los pedidos): mínimo de puntos para usarlos y hasta `loyalty_max_percent` % del ticket.
Lo que pone Trappi (`pos_points_trappi_percent`, arranca en 0) se le acredita al local en la liquidación.
Los puntos vuelven si la caja cancela, si la venta no llega en 24 h o si se anula. El código vale 3 minutos.
"""
import secrets
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ClientAccount, PointsPayment, PosSale, Store
from . import finance, loyalty, platform

CODE_MINUTES = 3
CONFIRMED_HOURS = 24  # una confirmación que la caja nunca usó: se devuelven los puntos
COUNTER_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'
CENT = Decimal('0.01')


class PointsPayError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def enabled(db: Session, store: Store | None) -> bool:
    from . import pos
    cfg = platform.get_all(db)
    return bool(store and cfg['pos_points_pay'] and loyalty.config(db)['enabled'] and pos.available(db, store))


def trappi_percent(db: Session) -> int:
    cfg = platform.get_all(db)
    if cfg['loyalty_trappi_funded']:  # Trappi paga los puntos: también en el mostrador
        return 100
    return max(0, min(100, int(cfg['pos_points_trappi_percent'])))


# ---------- QR fijo del mostrador ----------

def counter_code(db: Session, store: Store) -> str:
    """Código del QR del mostrador (se crea la primera vez). No hace commit."""
    if not store.pos_counter_code:
        for _ in range(10):
            code = ''.join(secrets.choice(COUNTER_ALPHABET) for _ in range(10))
            if not db.scalar(select(Store.id).where(Store.pos_counter_code == code)):
                store.pos_counter_code = code
                db.flush()
                break
    return store.pos_counter_code


def counter_url(code: str) -> str:
    base = (settings.public_base_url or 'https://trappi.com.ar').rstrip('/')
    return f'{base}/puntos/local/{code}'


def store_by_counter(db: Session, code: str) -> Store | None:
    code = (code or '').strip().lower()
    if not code or len(code) > 16:
        return None
    return db.scalar(select(Store).where(Store.pos_counter_code == code))


# ---------- vencimientos ----------

def _restore(db: Session, p: PointsPayment, note: str) -> None:
    if p.account_id and p.points:
        loyalty._add(db, p.account_id, 'restore', p.points, note=note, dedupe=f'pospay:{p.id}:restore')


def cleanup(db: Session, store_id: int, now: datetime | None = None) -> None:
    """Códigos vencidos y confirmaciones que la caja nunca usó. No hace commit."""
    now = now or datetime.utcnow()
    rows = db.scalars(select(PointsPayment).where(PointsPayment.store_id == store_id, PointsPayment.status.in_(('pending', 'confirmed')))).all()
    for p in rows:
        if p.status == 'pending' and p.expires_at < now:
            p.status = 'expired'
        elif p.status == 'confirmed' and p.confirmed_at and p.confirmed_at < now - timedelta(hours=CONFIRMED_HOURS):
            _restore(db, p, 'La compra con puntos en el local no se completó: te devolvimos los puntos')
            p.status = 'restored'


# ---------- la caja ----------

def create(db: Session, store: Store, cashier, amount) -> PointsPayment:
    """La caja pide un pago con puntos por el total del ticket. Cancela el anterior del mismo cajero si quedó esperando."""
    if not enabled(db, store):
        raise PointsPayError('Pagar con Puntos Trappi no está habilitado para este local.', 403)
    amount = money(amount)
    if amount <= 0 or amount > Decimal('50000000'):
        raise PointsPayError('El total del ticket no es válido.')
    now = datetime.utcnow()
    cleanup(db, store.id, now)
    for old in db.scalars(select(PointsPayment).where(PointsPayment.store_id == store.id, PointsPayment.cashier_id == cashier.id,
                                                      PointsPayment.status == 'pending')).all():
        old.status = 'cancelled'
    db.flush()
    used = set(db.scalars(select(PointsPayment.code).where(PointsPayment.store_id == store.id, PointsPayment.status == 'pending')).all())
    code = next((c for c in (f'{secrets.randbelow(10000):04d}' for _ in range(30)) if c not in used), None)
    if not code:
        raise PointsPayError('Hay demasiados pagos esperando. Probá en un minuto.', 429)
    counter_code(db, store)
    p = PointsPayment(store_id=store.id, cashier_id=cashier.id, code=code, amount=amount, status='pending',
                      expires_at=now + timedelta(minutes=CODE_MINUTES), created_at=now)
    db.add(p)
    db.flush()
    return p


def get(db: Session, store: Store, payment_id: int) -> PointsPayment:
    p = db.get(PointsPayment, payment_id)
    if not p or p.store_id != store.id:
        raise PointsPayError('Ese pago con puntos no existe.', 404)
    if p.status == 'pending' and p.expires_at < datetime.utcnow():
        p.status = 'expired'
    return p


def cancel(db: Session, store: Store, payment_id: int) -> PointsPayment:
    """La caja lo cancela (el cliente se arrepintió o cambió el ticket): si ya había confirmado, vuelven los puntos."""
    p = get(db, store, payment_id)
    if p.status == 'used':
        raise PointsPayError('Ese pago ya está en una venta: para devolver los puntos, anulá la venta.', 409)
    if p.status == 'confirmed':
        _restore(db, p, f'Cancelaste el pago con puntos en {store.name}: te devolvimos los puntos')
    if p.status in ('pending', 'confirmed'):
        p.status = 'cancelled'
    return p


def _first_name(db: Session, account_id: int | None) -> str | None:
    a = db.get(ClientAccount, account_id) if account_id else None
    if not a:
        return None
    name = (a.first_name or a.name or '').strip().split(' ')[0]
    return name or (a.email.split('@')[0][:2] + '…')


def status_json(db: Session, p: PointsPayment) -> dict:
    return {'id': p.id, 'code': p.code, 'status': p.status, 'amount': float(p.amount), 'points': p.points, 'discount': float(p.discount),
            'expires_at': p.expires_at.isoformat() + 'Z', 'customer': _first_name(db, p.account_id) if p.status in ('confirmed', 'used') else None}


# ---------- el cliente ----------

def find(db: Session, store: Store, code: str) -> PointsPayment | None:
    code = ''.join(ch for ch in (code or '') if ch.isdigit())
    if len(code) != 4:
        return None
    p = db.scalar(select(PointsPayment).where(PointsPayment.store_id == store.id, PointsPayment.code == code,
                                              PointsPayment.status == 'pending').order_by(PointsPayment.id.desc()))
    if p and p.expires_at < datetime.utcnow():
        return None
    return p


def quote(db: Session, p: PointsPayment, account) -> dict:
    """Cuánto puede usar el cliente en este ticket (lo ve antes de confirmar)."""
    cfg = loyalty.config(db)
    bal = loyalty.balance(db, account.id) if account else loyalty.Balance()
    out = {'balance': bal.points, 'points': 0, 'discount': Decimal('0.00'), 'rest': money(p.amount), 'max_pct': cfg['max_pct'], 'reason': None}
    if bal.points < max(cfg['min'], 1):
        out['reason'] = f'Necesitás al menos {max(cfg["min"], 1)} puntos para usarlos. Tenés {bal.points}.'
        return out
    if cfg['value'] <= 0:
        out['reason'] = 'Los puntos no se pueden usar en este momento.'
        return out
    cap = min(Decimal(p.amount) * cfg['max_pct'] / 100, Decimal(bal.points) * cfg['value'])
    points = int((cap / cfg['value']).to_integral_value(rounding=ROUND_DOWN))
    if points < 1:
        out['reason'] = 'En esta compra no se pueden usar puntos.'
        return out
    discount = (Decimal(points) * cfg['value']).quantize(CENT, rounding=ROUND_DOWN)
    out.update(points=points, discount=discount, rest=money(p.amount) - discount)
    return out


def confirm(db: Session, store: Store, p: PointsPayment, account) -> PointsPayment:
    """El cliente confirma: se descuentan sus puntos. No hace commit."""
    if p.store_id != store.id or p.status != 'pending' or p.expires_at < datetime.utcnow():
        raise PointsPayError('Ese código ya no vale. Pedile a la caja uno nuevo.', 409)
    q = quote(db, p, account)
    if not q['points']:
        raise PointsPayError(q['reason'] or 'No se pueden usar puntos en esta compra.', 409)
    added = loyalty._add(db, account.id, 'redeem', -q['points'], amount=q['discount'], note=f'Pagaste con puntos en {store.name}',
                         dedupe=f'pospay:{p.id}')
    if not added:
        raise PointsPayError('Ese pago ya se confirmó.', 409)
    p.account_id, p.points, p.discount = account.id, q['points'], q['discount']
    p.trappi_part = (q['discount'] * trappi_percent(db) / 100).quantize(CENT, rounding=ROUND_DOWN)
    p.status, p.confirmed_at = 'confirmed', datetime.utcnow()
    return p


# ---------- la venta ----------

def use_in_sale(db: Session, store: Store, payment_id, base: Decimal) -> PointsPayment:
    """record_sale: el pago tiene que estar confirmado, ser de este local y por el mismo total que la venta."""
    try:
        p = db.get(PointsPayment, int(payment_id))
    except (TypeError, ValueError):
        p = None
    if not p or p.store_id != store.id:
        raise PointsPayError('El pago con puntos no es de este local.')
    if p.status != 'confirmed':
        raise PointsPayError('El pago con puntos no está confirmado (o ya se usó o se canceló).', 409)
    if abs(money(p.amount) - money(base)) > CENT:
        raise PointsPayError('El ticket cambió después de pagar con puntos. Cancelá el pago con puntos y hacelo de nuevo.', 409)
    return p


def after_sale(db: Session, store: Store, p: PointsPayment, sale: PosSale) -> None:
    p.status, p.sale_id = 'used', sale.id
    if p.trappi_part and p.trappi_part > 0:
        finance.entry(db, 'merchant', 'pos_points', money(p.trappi_part), store_id=store.id,
                      description=f'Puntos Trappi en el mostrador · venta #{sale.number} (parte de Trappi)', dedupe=f'pos:{sale.id}:points')


def on_void(db: Session, store: Store, sale: PosSale) -> None:
    """Venta anulada: vuelven los puntos al cliente y se saca lo que Trappi le iba a pagar al local."""
    p = db.get(PointsPayment, sale.points_payment_id) if sale.points_payment_id else None
    if not p or p.status != 'used':
        return
    _restore(db, p, f'Se anuló tu compra en {store.name}: te devolvimos los puntos')
    p.status = 'restored'
    if p.trappi_part and p.trappi_part > 0:
        finance.entry(db, 'merchant', 'pos_points', -money(p.trappi_part), store_id=store.id,
                      description=f'Venta #{sale.number} anulada: se descuenta la parte de Trappi de los puntos', dedupe=f'pos:{sale.id}:points:void')


# ---------- web y app del cliente (con límite de intentos de código) ----------

from .ratelimit import PersistentRateLimiter  # noqa: E402

code_limiter = PersistentRateLimiter('pos-points-code', limit=10, window_seconds=600)


def lookup(db: Session, counter: str, code: str, account) -> tuple[Store, PointsPayment, dict]:
    """El cliente escaneó el QR del mostrador y puso el código de la caja: qué pago es y cuánto puede usar."""
    store = store_by_counter(db, counter)
    if not store:
        raise PointsPayError('Este QR no es de ningún local de Trappi.', 404)
    if not enabled(db, store):
        raise PointsPayError('Este local no acepta Puntos Trappi en el mostrador por ahora.', 403)
    key = f'{account.id}'
    if code_limiter.blocked(key):
        raise PointsPayError('Probaste demasiados códigos. Esperá unos minutos.', 429)
    p = find(db, store, code)
    if not p:
        code_limiter.hit(key)
        raise PointsPayError('Ese código no está esperando un pago. Fijate el número en la pantalla de la caja.', 404)
    return store, p, quote(db, p, account)
