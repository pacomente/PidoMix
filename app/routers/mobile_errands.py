"""Trappi Mandados en la app (/api/v1/errands...). La lógica está en services/errands.py.

Se separó de mobile_api.py (mismas rutas, mismo prefijo /api/v1): los helpers y servicios compartidos vienen de ahí."""
from fastapi import APIRouter

from .mobile_api import *  # noqa: F401,F403  (helpers, modelos de datos y servicios compartidos)

router = APIRouter()


# ---------- Trappi Mandados ----------

class ErrandPlace(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    address: str = Field('', max_length=255)
    note: str = Field('', max_length=160)


class ErrandPerson(BaseModel):
    name: str = Field('', max_length=80)
    phone: str = Field('', max_length=40)


class ErrandQuoteIn(BaseModel):
    pickup: ErrandPlace
    dropoff: ErrandPlace
    city: str | None = Field(None, max_length=140)


class ErrandIn(ErrandQuoteIn):
    kind: str = Field(max_length=20)
    size: str = Field(max_length=20)
    what: str = Field('', max_length=200)
    sender: ErrandPerson
    recipient: ErrandPerson
    push_token: str | None = Field(None, max_length=512)
    platform: str = Field('android', max_length=10)
    payment_method: str = Field('efectivo', max_length=20)


def _errand_city(db: Session, body: ErrandQuoteIn) -> int | None:
    c = cities.resolve(db, body.city, {'lat': body.pickup.lat, 'lng': body.pickup.lng})
    return c.id if c else None


@router.get('/errands/config')
def errands_config(city: str | None = None, lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
    """Si hay mandados en la ciudad, y las opciones (qué se manda y los tamaños)."""
    c = cities.resolve(db, city, {'lat': lat, 'lng': lng} if lat is not None and lng is not None else None)
    on = errands.enabled(db, c.id if c else None)
    return {'enabled': on, 'kinds': [{'code': k, 'label': v} for k, v in errands.KINDS.items()],
            'sizes': [{'code': k, 'label': v} for k, v in errands.SIZES.items()], 'forbidden': errands.FORBIDDEN,
            'payment': 'efectivo', 'payments': errands.payment_methods(db, c.id if c else None)}


@router.post('/errands/quote')
def errands_quote(body: ErrandQuoteIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if errand_quote_limiter.blocked(ip):
        return JSONResponse({'ok': False, 'error': 'Esperá un momento y probá de nuevo.'}, status_code=429)
    errand_quote_limiter.hit(ip)
    try:
        q = errands.quote(db, body.pickup.model_dump(), body.dropoff.model_dump(), _errand_city(db, body))
    except errands.ErrandError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    return {'ok': True, 'price': num(q.price), 'km': q.km, 'eta_min': q.eta_min, 'eta_max': q.eta_max}


@router.post('/errands')
def errands_create(body: ErrandIn, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if acct is None:
        return JSONResponse({'ok': False, 'error': 'Entrá con tu cuenta para mandar algo.', 'login_required': True}, status_code=401)
    ip = client_ip(request)
    if order_limiter.blocked(ip):
        return JSONResponse({'ok': False, 'error': 'Hiciste muchos pedidos seguidos. Esperá unos minutos.'}, status_code=429)
    try:
        order = errands.create(db, account=acct, pickup=body.pickup.model_dump(), dropoff=body.dropoff.model_dump(), kind=body.kind, size=body.size,
                               what=body.what, sender=body.sender.model_dump(), recipient=body.recipient.model_dump(), city_id=_errand_city(db, body), ip=ip,
                               payment_method=body.payment_method)
        db.flush()
    except errands.ErrandError as exc:
        db.rollback()
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    if body.push_token:
        push.register(db, order, body.push_token, body.platform)
    db.commit()
    order_limiter.hit(ip)
    token = order_token(order.id)
    return {'ok': True, 'id': order.id, 'token': token, 'total': num(order.total),
            'pay_path': f'/pedido/{order.id}/pagar?t={token}' if payments.awaiting_online(order) else None}
