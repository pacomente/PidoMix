"""API de la app del repartidor (/api/courier/v1).

El repartidor entra con su telefono y un PIN. La app, mientras esta conectado, manda cada pocos
segundos un "pulso" con su ubicacion y recibe la oferta que tenga para aceptar o el viaje en curso.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..db import get_db
from ..models import Courier, Order, OrderStatus
from ..services import cities, dispatch, finance, payments, plans, platform, push
from ..services.auth import verify_password
from ..services.geo import distance_km
from ..services.ratelimit import RateLimiter, client_ip
from ..services.store_hours import local_day_start_utc

router = APIRouter()
_signer = URLSafeTimedSerializer(settings.secret_key, salt='trappi-courier')
TOKEN_DAYS = 60
login_limiter = RateLimiter(limit=8, window_seconds=600)
pin_limiter = RateLimiter(limit=payments.PIN_ATTEMPTS, window_seconds=600)  # por pedido: que no se pueda adivinar el PIN


def digits(phone: str) -> str:
    return ''.join(ch for ch in (phone or '') if ch.isdigit())


def wa_link(phone: str | None) -> str | None:
    d = digits(phone or '')
    return f'https://wa.me/{d}' if d else None


def courier_token(c: Courier) -> str:
    return _signer.dumps({'id': c.id, 'v': c.token_version})


class AuthError(Exception):
    pass


class AppDisabled(Exception):
    def __init__(self, message: str):
        self.message = message


def current_courier(authorization: str = Header(''), db: Session = Depends(get_db)) -> Courier:
    cfg = platform.get_all(db)
    if not cfg['app_repartidor_enabled']:
        raise AppDisabled(platform.app_status(cfg, 'repartidor')['message'])
    token = authorization.removeprefix('Bearer ').strip()
    try:
        data = _signer.loads(token, max_age=TOKEN_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        raise AuthError()
    c = db.get(Courier, int(data.get('id', 0)))
    if not c or not c.active or c.token_version != data.get('v'):
        raise AuthError()
    return c


def num(v) -> float:
    return float(v or 0)


def courier_json(c: Courier, db: Session | None = None) -> dict:
    data = {'id': c.id, 'name': c.name, 'phone': c.phone, 'vehicle': c.vehicle, 'online': c.online,
            'fleet': 'local' if c.store_id else 'trappi', 'store': c.store.name if c.store else None}
    if db is not None and c.store_id is None:
        box = finance.courier_box(db, c)
        data['cash'] = {'pending': num(box['pending']), 'limit': num(box['limit']), 'available': num(box['available']), 'blocked': box['blocked'],
                        'online_enabled': c.online_orders_enabled}
    return data


def payout_json(detail, total) -> dict:
    """Detalle de lo que gana el repartidor (base, km, bonos...). detail: dict o el JSON guardado en el pedido."""
    import json
    if isinstance(detail, dict):
        d = detail
    else:
        try:
            d = json.loads(detail or '{}')
        except ValueError:
            d = {}
    lines = []
    if d.get('mode') == 'formula':
        for key, label in (('base', 'Base'), ('per_km', 'Por km'), ('delivery', 'Por entrega')):
            if float(d.get(key) or 0):
                lines.append({'label': label, 'amount': float(d[key])})
        for key, value in (d.get('bonuses') or {}).items():
            lines.append({'label': {'nocturno': 'Bono nocturno', 'alta_demanda': 'Bono alta demanda'}.get(key, key), 'amount': float(value)})
        for key, value in (d.get('extras') or {}).items():
            lines.append({'label': {'viaje_largo': 'Adicional viaje largo'}.get(key, key), 'amount': float(value)})
    return {'total': num(total), 'lines': lines, 'distance_km': d.get('distance_km')}


def point(lat, lng) -> dict | None:
    return {'lat': lat, 'lng': lng} if lat is not None and lng is not None else None


def km_between(a: dict | None, b: dict | None) -> float | None:
    return round(distance_km(a['lat'], a['lng'], b['lat'], b['lng']), 1) if a and b else None


def offer_json(db: Session, offer, courier: Courier) -> dict:
    o = offer.order
    store_at, drop_at, me = point(o.store.lat, o.store.lng), point(o.lat, o.lng), point(courier.lat, courier.lng)
    return {
        'id': offer.id, 'order_id': o.id,
        'expires_in': max(0, int((offer.expires_at - datetime.utcnow()).total_seconds())),
        'seconds': dispatch.offer_seconds(db),
        'earnings': num(dispatch.pay_for(db, o)),
        'store': {'name': o.store.name, 'address': o.store.address, **(store_at or {})},
        'dropoff': {'address': o.address, **(drop_at or {})},
        'to_store_km': km_between(me, store_at),
        'trip_km': o.distance_km if o.distance_km is not None else km_between(store_at, drop_at),
        'items': sum(it.quantity for it in o.items),
        'own_store': courier.store_id == o.store_id,
        'paid_online': o.payment_method in payments.ONLINE,
        'collect': 0 if (payments.is_paid(o) or o.payment_method in payments.ONLINE) else num(o.total),
        'pay_store': store_payment(db, o, courier),
        'payout': payout_json(*reversed(dispatch.payout_for(platform.for_city(db, cities.of_order(o)), o))),
    }


def store_payment(db: Session, o: Order, courier: Courier) -> float:
    """Efectivo que este cadete le paga al local al retirar (solo la flota, en pedidos que se cobran en efectivo)."""
    if courier.store_id is not None:
        return 0
    if o.pickup_paid is not None:
        return num(o.pickup_paid)
    return num(finance.store_cash_amount(db, o) or 0)


def payment_json(o: Order) -> dict:
    change = payments.change_for(o)
    return {'method': o.payment_method, 'label': payments.method_label(o), 'paid': payments.is_paid(o),
            'cash_with': num(o.cash_with) if o.cash_with else None, 'change': num(change) if change else None,
            # eligio transferencia pero el local todavia no la confirmo: hay que cobrarle o esperar la confirmacion
            'transfer_pending': o.payment_method == 'transferencia' and not payments.is_paid(o)}


def trip_json(db: Session, o: Order, courier: Courier) -> dict:
    s, cu = o.store, o.customer
    picked = o.status == OrderStatus.EN_CAMINO
    return {
        'order_id': o.id, 'status': o.status.value, 'stage': 'dropoff' if picked else 'pickup',
        'ready': o.status == OrderStatus.LISTO, 'earnings': num(o.courier_pay if o.courier_pay is not None else o.shipping), 'total': num(o.total),
        'collect': num(payments.to_collect(o)),  # 0 si ya esta pagado
        'payment': payment_json(o),
        'pin_required': dispatch.pin_required(db, o),
        # codigo de retiro: el cadete se lo muestra al local, que lo tiene en la comanda y el ticket
        'pickup_code': o.pickup_code if (not picked and dispatch.pickup_code_on(db, o)) else None,
        # reporto que no pudo entregar: vuelve al local con el pedido (y el local le devuelve lo que pago)
        'failed': o.delivery_fail_reason if o.delivery_failed_at else None,
        'fail_reasons': [{'code': k, 'label': v} for k, v in dispatch.FAIL_REASONS.items()] if (picked and plans.fleet_security(o)) else [],
        'pay_store': store_payment(db, o, courier),
        'payout': payout_json(o.courier_pay_breakdown, o.courier_pay if o.courier_pay is not None else o.shipping),
        'route_km': o.route_km, 'zone': o.zone_name,
        'store': {'name': s.name, 'address': s.address, 'phone': s.phone, 'whatsapp': wa_link(s.whatsapp or s.phone or ''), **(point(s.lat, s.lng) or {})},
        'customer': {'name': ' '.join(x for x in [cu.first_name if cu else '', cu.last_name if cu else ''] if x).strip() or 'Cliente',
                     'phone': cu.phone if cu else None, 'whatsapp': wa_link(cu.phone) if cu and cu.phone else None,
                     'address': o.address, 'reference': o.reference, **(point(o.lat, o.lng) or {})},
        'items': [{'quantity': it.quantity, 'name': it.product_name, 'modifiers_text': it.modifiers_text} for it in o.items],
        'notes': o.notes,
        'trip_km': o.distance_km,
    }


def earnings_json(db: Session, c: Courier) -> dict:
    today, trips_today = dispatch.earnings(db, c, local_day_start_utc(0))
    week, trips_week = dispatch.earnings(db, c, local_day_start_utc(6))
    return {'today': num(today), 'trips_today': trips_today, 'week': num(week), 'trips_week': trips_week,
            'cash_today': num(dispatch.cash_collected(db, c, local_day_start_utc(0)))}


def state_json(db: Session, c: Courier) -> dict:
    trip = dispatch.current_trip(db, c)
    offer = None if trip else dispatch.offer_for(db, c)
    return {'courier': courier_json(c, db), 'trip': trip_json(db, trip, c) if trip else None,
            'offer': offer_json(db, offer, c) if offer else None, 'earnings': earnings_json(db, c)}


def error(message: str, status: int = 400):
    return JSONResponse({'ok': False, 'error': message}, status_code=status)


# ---------- configuracion (la app la consulta al abrir) ----------

@router.get('/config')
def config(db: Session = Depends(get_db)):
    cfg = platform.get_all(db)
    return {'app': platform.app_status(cfg, 'repartidor'), 'map_style': platform.map_style_url(cfg),
            'pulse_seconds': cfg['courier_pulse_seconds'], 'support_whatsapp': cfg['platform_whatsapp'] or None}


# ---------- sesion ----------

class LoginIn(BaseModel):
    phone: str = Field(max_length=40)
    pin: str = Field(max_length=12)


@router.post('/login')
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    cfg = platform.get_all(db)
    if not cfg['app_repartidor_enabled']:
        raise AppDisabled(platform.app_status(cfg, 'repartidor')['message'])
    key = f'{client_ip(request)}|{digits(body.phone)}'
    if login_limiter.blocked(key):
        return error('Demasiados intentos. Esperá unos minutos.', 429)
    c = db.scalar(select(Courier).where(Courier.phone == digits(body.phone)))
    if not c or not c.active or not verify_password(body.pin.strip(), c.pin_hash):
        login_limiter.hit(key)
        return error('Teléfono o PIN incorrectos.', 401)
    login_limiter.reset(key)
    return {'ok': True, 'token': courier_token(c), 'courier': courier_json(c)}


@router.get('/me')
def me(c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    return state_json(db, c)


class PushIn(BaseModel):
    token: str = Field('', max_length=512)


@router.post('/push')
def register_push(body: PushIn, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    c.push_token = body.token.strip() or None
    db.commit()
    return {'ok': True, 'enabled': push.enabled()}


# ---------- conexion y pulso ----------

class PulseIn(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    online: bool | None = None


@router.post('/pulse')
def pulse(body: PulseIn, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    """Ubicacion + conectado/desconectado. Devuelve la oferta o el viaje en curso."""
    if body.lat is not None and body.lng is not None:
        c.lat, c.lng, c.location_at = body.lat, body.lng, datetime.utcnow()
    if body.online is not None:
        if not body.online and dispatch.current_trip(db, c):
            db.commit()
            return error('Terminá el viaje en curso antes de desconectarte.', 409)
        c.online = body.online
    db.commit()
    if c.online:
        dispatch.tick(db)
    return state_json(db, c)


# ---------- ofertas ----------

@router.post('/offers/{offer_id}/accept')
def accept(offer_id: int, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    try:
        dispatch.accept(db, c, offer_id)
    except dispatch.DispatchError as exc:
        return error(str(exc), 409)
    return state_json(db, c)


@router.post('/offers/{offer_id}/reject')
def reject(offer_id: int, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    dispatch.reject(db, c, offer_id)
    dispatch.tick(db)
    return state_json(db, c)


# ---------- viaje en curso ----------

def _trip(db: Session, c: Courier, order_id: int) -> Order | None:
    o = db.scalar(select(Order).options(joinedload(Order.store), joinedload(Order.customer), selectinload(Order.items), selectinload(Order.events)).where(Order.id == order_id))
    return o if o and o.courier_id == c.id else None


@router.post('/trip/{order_id}/pickup')
def trip_pickup(order_id: int, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    o = _trip(db, c, order_id)
    if not o:
        return error('Ese viaje ya no es tuyo.', 404)
    try:
        dispatch.pickup(db, c, o)
    except dispatch.DispatchError as exc:
        return error(str(exc), 409)
    db.commit()
    push.notify_status(db, o)
    return state_json(db, c)


class DeliverIn(BaseModel):
    pin: str = Field('', max_length=12)


@router.post('/trip/{order_id}/deliver')
def trip_deliver(order_id: int, body: DeliverIn | None = None, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    o = _trip(db, c, order_id)
    if not o:
        return error('Ese viaje ya no es tuyo.', 404)
    pin = body.pin if body else ''
    key = f'order:{o.id}'
    if pin_limiter.blocked(key):
        return error('Demasiados PIN incorrectos. Esperá unos minutos o pedile al local que lo marque entregado.', 429)
    try:
        dispatch.deliver(db, c, o, pin)
    except dispatch.DispatchError as exc:
        if pin.strip():
            pin_limiter.hit(key)
        return error(str(exc), 409)
    pin_limiter.reset(key)
    db.commit()
    push.notify_status(db, o)
    dispatch.tick(db)
    collected = num(o.total) if o.paid_by == 'repartidor' else 0
    return {**state_json(db, c), 'delivered': {'order_id': o.id, 'earnings': num(o.courier_pay if o.courier_pay is not None else o.shipping), 'collected': collected}}


class FailIn(BaseModel):
    reason: str = Field(..., max_length=20)
    note: str = Field('', max_length=120)


@router.post('/trip/{order_id}/fail')
def trip_fail(order_id: int, body: FailIn, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    """No pudo entregar (cliente no atiende, direccion mal, rechazo): queda avisado en la comanda del local."""
    o = _trip(db, c, order_id)
    if not o:
        return error('Ese viaje ya no es tuyo.', 404)
    try:
        dispatch.report_failed(db, c, o, body.reason, body.note)
    except dispatch.DispatchError as exc:
        return error(str(exc), 409)
    db.commit()
    return state_json(db, c)


@router.post('/trip/{order_id}/release')
def trip_release(order_id: int, c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    """El repartidor no puede llevarlo (antes de retirarlo): se le ofrece a otro."""
    o = _trip(db, c, order_id)
    if not o:
        return error('Ese viaje ya no es tuyo.', 404)
    try:
        dispatch.unassign(db, o, by_courier=True)
    except dispatch.DispatchError as exc:
        return error(str(exc), 409)
    db.commit()
    dispatch.tick(db)
    return state_json(db, c)


# ---------- ganancias ----------

@router.get('/earnings')
def earnings(c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.scalars(select(Order).options(joinedload(Order.store), selectinload(Order.events)).where(
        Order.courier_id == c.id, Order.status == OrderStatus.ENTREGADO, Order.created_at >= since).order_by(Order.created_at.desc()).limit(60)).all()
    trips = [{'order_id': o.id, 'store': o.store.name, 'address': o.address, 'earnings': num(o.courier_pay if o.courier_pay is not None else o.shipping),
              'payout': payout_json(o.courier_pay_breakdown, o.courier_pay if o.courier_pay is not None else o.shipping),
              'delivered_at': (o.status_time(OrderStatus.ENTREGADO) or o.created_at).isoformat() + 'Z', 'km': o.distance_km} for o in rows]
    month, trips_month = dispatch.earnings(db, c, local_day_start_utc(29))
    return {**earnings_json(db, c), 'month': num(month), 'trips_month': trips_month, 'trips': trips}


# ---------- mi caja (solo lectura: los valores los calcula y cambia solo Trappi) ----------

@router.get('/caja')
def cash_box(c: Courier = Depends(current_courier), db: Session = Depends(get_db)):
    box = finance.courier_box(db, c)
    moves = finance.movements(db, 'courier_cash', courier_id=c.id, limit=40)
    return {'own_store': c.store_id is not None, **{k: (num(v) if not isinstance(v, bool) else v) for k, v in box.items()},
            'movements': [{'id': m.id, 'kind': m.kind, 'description': m.description, 'amount': num(m.amount), 'settled': m.settled,
                           'order_id': m.order_id, 'at': m.created_at.isoformat() + 'Z'} for m in moves]}
