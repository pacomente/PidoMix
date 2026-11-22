"""Cuenta del cliente en la app (/api/v1/me...): entrar, datos, puntos, sellos, invitar, direcciones y sus pedidos.

Se separó de mobile_api.py (mismas rutas, mismo prefijo /api/v1): los helpers y servicios compartidos vienen de ahí."""
from fastapi import APIRouter

from .mobile_api import *  # noqa: F401,F403  (helpers, modelos de datos y servicios compartidos)

router = APIRouter()


exchange_limiter = PersistentRateLimiter('app-exchange', limit=20, window_seconds=600)


class ExchangeIn(BaseModel):
    code: str = Field(..., max_length=2000)
    verifier: str = Field(..., min_length=43, max_length=128)


@router.post('/auth/exchange')
def auth_exchange(body: ExchangeIn, request: Request, db: Session = Depends(get_db)):
    """La app cambia el codigo que le devolvio el ingreso (codigo por email, por deep link) por su token, mostrando el verifier de PKCE."""
    if not exchange_limiter.check(client_ip(request)):
        return JSONResponse({'ok': False, 'error': 'Demasiados intentos. Esperá unos minutos.'}, status_code=429)
    try:
        acct = accounts.redeem_app_code(db, body.code, body.verifier)
    except accounts.AccountError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    return {'ok': True, 'token': accounts.app_token(acct), 'account': account_json(acct)}


@router.get('/me')
def me(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    return {'ok': True, 'account': account_json(acct)} if acct else no_session()


class MeIn(BaseModel):
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=255)
    reference: str | None = Field(None, max_length=255)
    personalize: bool | None = None  # "Recomendado para vos" con sus pedidos
    marketing_opt_in: bool | None = None  # acepta novedades y promociones por email o notificacion


@router.put('/me')
def me_update(body: MeIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    data = body.model_dump()
    personalize, marketing = data.pop('personalize'), data.pop('marketing_opt_in')
    accounts.save_contact(acct, **data)
    if personalize is not None:
        acct.personalize = personalize
    if marketing is not None:
        acct.marketing_opt_in = marketing
    db.commit()
    return {'ok': True, 'account': account_json(acct)}


@router.get('/me/offer')
def my_offer(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Para el inicio: "Hace 7 dias pediste ... ¿Queres pedir de nuevo?" y su descuento de Trappi, si tiene. Sin cuenta: nada."""
    acct = current_account(db, authorization)
    if not acct:
        return {'reminder': None, 'voucher': None}
    return retention.offer(db, acct)


@router.get('/me/points')
def my_points(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Puntos Trappi del cliente: saldo, cuánto valen, cuándo vencen y los últimos movimientos."""
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    s = loyalty.summary(db, acct)
    if s is None:
        return {'enabled': False}
    t = s['tier']
    return {'enabled': True, 'points': s['points'], 'value': num(s['value']),
            # niveles Bronce/Plata/Oro (None si están apagados) y el cumpleaños para el regalo
            'tier': {k: t[k] for k in ('key', 'label', 'emoji', 'bonus', 'orders', 'silver', 'gold', 'bonuses', 'birthday_points', 'next')} if t else None,
            'birthday': s['birthday'], 'birthday_gift': s['birthday_gift'], 'expiring': s['expiring'], 'expiring_at': iso(s['expiring_at']) if s['expiring_at'] else None,
            'rules': {'pesos_per_point': num(s['per_point']), 'point_value': num(s['point_value']), 'min': s['min'], 'max_percent': s['max_pct'], 'months': s['months']},
            'history': [{**h, 'created_at': iso(h['created_at'])} for h in s['history']]}


class BirthdayIn(BaseModel):
    day: int = Field(..., ge=1, le=31)
    month: int = Field(..., ge=1, le=12)


@router.post('/me/birthday')
def my_birthday(body: BirthdayIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Cumpleaños para el regalo de Puntos Trappi (una sola vez)."""
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    err = loyalty.set_birthday(acct, body.day, body.month)
    if err:
        return JSONResponse({'ok': False, 'error': err}, status_code=400)
    db.commit()
    return {'ok': True, 'birthday': {'day': acct.birth_day, 'month': acct.birth_month}}


@router.get('/me/stamps')
def my_stamps(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Mis tarjetas de sellos (una por local) y los premios sin usar."""
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    return {'cards': [{'store': {'slug': c['store'].slug, 'name': c['store'].name, 'logo_url': cdn(c['store'].logo_url, 'logo')},
                       'stamps': c['stamps'], 'goal': c['goal'], 'reward': c['reward'],
                       'rewards': [{'code': r.code, 'expires_at': iso(r.expires_at)} for r in c['rewards']]} for c in stamps.my_cards(db, acct)]}


@router.get('/me/invite')
def my_invite(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Invitá a un amigo: el link propio del cliente para compartir y cuántos amigos ya sumó."""
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    inv = referrals.summary(db, acct)
    if inv is None:
        return {'enabled': False}
    db.commit()  # el codigo se crea la primera vez
    base = (settings.public_base_url or 'https://trappi.com.ar').rstrip('/')
    link = f'{base}/invitar/{inv["code"]}'
    minimum = f' de ${num(inv["min_order"]):,.0f}'.replace(',', '.') + ' o más' if inv['min_order'] else ''
    return {'enabled': True, 'code': inv['code'], 'link': link, 'friends': inv['friends'], 'waiting': inv['waiting'],
            'inviter_points': inv['inviter'], 'friend_points': inv['friend'],
            'share_text': f'Te regalo {inv["friend"]} Puntos Trappi para tu primer pedido{minimum} 🎁 Creá tu cuenta desde este link: {link}'}


@router.get('/recommendations')
def recommendations_for_me(lat: float | None = None, lng: float | None = None, city: str | None = None,
                           authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Recomendado para vos: solo con la cuenta del cliente y sus propios pedidos. Sin cuenta o apagado: vacío."""
    acct = current_account(db, authorization)
    loc = loc_from(lat, lng)
    here = city_for(db, city, loc)
    picks = recommendations.recommend(db, acct, here.id if here else None, loc)
    return {'enabled': recommendations.enabled(acct), 'title': 'Recomendado para vos',
            'items': [{**product_json(x.product, with_store=True), 'reason': x.reason} for x in picks]}


class LogoutIn(BaseModel):
    everywhere: bool = False


@router.post('/me/logout')
def me_logout(body: LogoutIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if acct and body.everywhere:
        accounts.sign_out_everywhere(acct)
        db.commit()
    return {'ok': True}


@router.delete('/me')
def me_delete(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    audit.log(db, 'client.delete', 'client_account', acct.id, new={'via': 'app'}, ip=client_ip(request))
    accounts.delete(db, acct)
    db.commit()
    return {'ok': True}


class AddressIn(BaseModel):
    label: str = Field(max_length=40)
    address: str = Field(max_length=255)
    reference: str | None = Field(None, max_length=255)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    icon: str | None = Field(None, max_length=12)


@router.get('/me/addresses')
def me_addresses(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    return {'ok': True, 'addresses': [addresses.as_json(a) for a in addresses.for_account(db, acct.id)], 'max': addresses.MAX}


@router.post('/me/addresses')
def me_address_create(body: AddressIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    try:
        row = addresses.save(db, acct.id, body.model_dump())
    except addresses.AddressError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    db.commit()
    return {'ok': True, 'address': addresses.as_json(row)}


@router.put('/me/addresses/{address_id}')
def me_address_update(address_id: int, body: AddressIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    row = addresses.get(db, acct.id, address_id)
    if not row:
        return JSONResponse({'ok': False, 'error': 'No encontramos esa dirección.'}, status_code=404)
    try:
        addresses.save(db, acct.id, body.model_dump(), row)
    except addresses.AddressError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    db.commit()
    return {'ok': True, 'address': addresses.as_json(row)}


@router.delete('/me/addresses/{address_id}')
def me_address_delete(address_id: int, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    row = addresses.get(db, acct.id, address_id)
    if row:
        db.delete(row)
        db.commit()
    return {'ok': True}


@router.get('/me/orders')
def me_orders(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    rows = db.scalars(select(Order).options(*ORDER_OPTS).where(Order.account_id == acct.id).order_by(Order.created_at.desc()).limit(30)).all()
    return {'orders': [{**order_json(o), 'token': order_token(o.id)} for o in rows]}
