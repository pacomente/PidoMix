"""API de Trappi Viajes para la app de clientes (/api/v1/rides).

El cliente cotiza (ve las empresas de su ciudad con el precio estimado y cuanto tarda el conductor mas cercano),
pide con su cuenta y sigue el viaje. El precio siempre lo calcula el servidor con la tarifa de la empresa.
"""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Ride
from ..services import accounts, cities, platform, rides
from ..services.ratelimit import PersistentRateLimiter, client_ip

router = APIRouter()
quote_limiter = PersistentRateLimiter('ride-quote', limit=60, window_seconds=600)  # cada cotizacion consulta el servidor de rutas
request_limiter = PersistentRateLimiter('ride-request', limit=10, window_seconds=600)


def num(v) -> float:
    return float(v or 0)


def iso(dt) -> str | None:
    return dt.isoformat() + 'Z' if dt else None


def error(message: str, status: int = 400):
    return JSONResponse({'ok': False, 'error': message}, status_code=status)


def no_session():
    return JSONResponse({'ok': False, 'error': 'Entrá con tu cuenta para pedir un viaje.', 'login_required': True}, status_code=401)


class Place(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    address: str = Field('', max_length=255)
    note: str = Field('', max_length=160)


class QuoteIn(BaseModel):
    origin: Place
    dest: Place
    city: str | None = Field(None, max_length=140)


class RideIn(QuoteIn):
    company_id: int
    vehicle: str = Field(max_length=10)


class RateIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=8)
    comment: str = Field('', max_length=500)


def _city_id(db: Session, slug: str | None, origin: Place) -> int | None:
    c = cities.resolve(db, slug, {'lat': origin.lat, 'lng': origin.lng})
    return c.id if c else None


def ride_json(db: Session, r: Ride) -> dict:
    """Lo que ve el pasajero. Del conductor: nombre, vehiculo, patente y calificacion; su telefono solo mientras el viaje esta activo."""
    c = r.courier
    active = r.status in rides.DRIVER_ACTIVE
    return {
        'id': r.id, 'status': r.status, 'label': rides.STATUS_LABEL[r.status], 'vehicle': r.vehicle,
        'company': {'id': r.company.id, 'name': r.company.name, 'phone': r.company.phone if r.status in rides.ACTIVE else None},
        'origin': {'address': r.origin_address, 'lat': r.origin_lat, 'lng': r.origin_lng, 'note': r.origin_note},
        'dest': {'address': r.dest_address, 'lat': r.dest_lat, 'lng': r.dest_lng},
        'km': r.km, 'minutes': r.minutes, 'night': r.night,
        'price': num(r.price), 'wait_charge': num(r.wait_charge), 'total': num(r.final_price if r.final_price is not None else r.price),
        'payment': r.payment_method,
        # el PIN se lo dice al conductor al subir; deja de mostrarse cuando el viaje arranco
        'pin': r.pin if r.status in ('buscando', 'asignado', 'en_puerta') else None,
        'driver': {'name': c.name.split()[0], 'vehicle': c.vehicle, 'car_model': c.car_model, 'plate': c.plate,
                   'rating': num(c.rating_avg) if c.rating_avg else None, 'phone': c.phone if active else None} if c else None,
        'tracking': rides.tracking(db, r),
        'can_cancel': r.status in rides.PASSENGER_CANCEL,
        'can_rate': r.status == 'finalizado' and r.rating is None, 'rating': r.rating,
        'rating_tags': list(rides.RATING_TAGS),
        'cancel_reason': r.cancel_reason if r.status in ('cancelado', 'sin_conductor', 'buscando') else None,
        'created_at': iso(r.created_at), 'started_at': iso(r.started_at), 'finished_at': iso(r.finished_at),
    }


@router.get('/rides/available')
def available(city: str | None = None, lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
    """Si se muestra el modulo Viajes en el inicio: prendido y con alguna empresa aprobada en la ciudad."""
    if not rides.enabled(db):
        return {'enabled': False, 'companies': 0}
    c = cities.resolve(db, city, {'lat': lat, 'lng': lng} if lat is not None and lng is not None else None)
    companies = rides.visible_companies(db, c.id if c else None)
    vehicles = sorted({v for co in companies for v in rides.vehicles_of(co)})
    return {'enabled': bool(companies), 'companies': len(companies), 'vehicles': vehicles}


@router.post('/rides/quote')
def quote(body: QuoteIn, request: Request, db: Session = Depends(get_db)):
    if not rides.enabled(db):
        return error('Los viajes no están disponibles por ahora.', 409)
    key = client_ip(request)
    if quote_limiter.blocked(key):
        return error('Demasiadas consultas. Esperá un momento.', 429)
    quote_limiter.hit(key)
    try:
        return {'ok': True, **rides.quote(db, (body.origin.lat, body.origin.lng), (body.dest.lat, body.dest.lng), _city_id(db, body.city, body.origin))}
    except rides.RideError as exc:
        return error(str(exc))


@router.post('/rides')
def create(body: RideIn, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    if not rides.enabled(db):
        return error('Los viajes no están disponibles por ahora.', 409)
    acct = accounts.from_bearer(db, authorization)
    if acct is None:
        return no_session()
    if not acct.active:
        return error('Tu cuenta está bloqueada. Escribinos por WhatsApp.', 403)
    key = f'{client_ip(request)}|{acct.id}'
    if request_limiter.blocked(key):
        return error('Pediste demasiados viajes seguidos. Esperá unos minutos.', 429)
    request_limiter.hit(key)
    try:
        r = rides.request(db, acct, body.company_id, body.vehicle, body.origin.model_dump(), body.dest.model_dump(), _city_id(db, body.city, body.origin))
    except rides.RideError as exc:
        return error(str(exc), 409)
    return {'ok': True, 'ride': ride_json(db, r)}


def _mine(db: Session, authorization: str | None, ride_id: int):
    acct = accounts.from_bearer(db, authorization)
    if acct is None:
        return None, no_session()
    r = db.get(Ride, ride_id)
    if r is None or r.account_id != acct.id:
        return None, error('Viaje no encontrado.', 404)
    return (acct, r), None


@router.get('/rides/current')
def current(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = accounts.from_bearer(db, authorization)
    if acct is None:
        return no_session()
    rides.tick(db)
    r = rides.active_for_account(db, acct.id)
    return {'ride': ride_json(db, r) if r else None}


@router.get('/rides')
def history(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = accounts.from_bearer(db, authorization)
    if acct is None:
        return no_session()
    rows = db.scalars(select(Ride).where(Ride.account_id == acct.id).order_by(Ride.id.desc()).limit(30)).all()
    return {'rides': [ride_json(db, r) for r in rows]}


@router.get('/rides/{ride_id}')
def detail(ride_id: int, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    found, err = _mine(db, authorization, ride_id)
    if err:
        return err
    rides.tick(db)  # avanza la busqueda de conductor mientras el pasajero mira
    db.refresh(found[1])
    return {'ride': ride_json(db, found[1])}


@router.post('/rides/{ride_id}/cancel')
def cancel(ride_id: int, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    found, err = _mine(db, authorization, ride_id)
    if err:
        return err
    acct, r = found
    try:
        rides.cancel_by_passenger(db, acct.id, r)
    except rides.RideError as exc:
        return error(str(exc), 409)
    return {'ok': True, 'ride': ride_json(db, r)}


@router.post('/rides/{ride_id}/rate')
def rate(ride_id: int, body: RateIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    found, err = _mine(db, authorization, ride_id)
    if err:
        return err
    acct, r = found
    try:
        rides.rate(db, acct.id, r, body.stars, body.tags, body.comment)
    except rides.RideError as exc:
        return error(str(exc), 409)
    return {'ok': True, 'ride': ride_json(db, r)}
