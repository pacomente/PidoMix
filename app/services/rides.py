"""Trappi Viajes: el cliente pide un auto o una moto a una empresa habilitada y la empresa lo hace con su flota.

- Las empresas ponen sus tarifas (por vehiculo). El precio lo calcula siempre el servidor: el cliente ve el estimado
  antes de pedir, queda fijo al pedir y al terminar solo se suma la espera en la puerta (pasados los minutos gratis).
- El viaje se le ofrece a UN conductor de esa empresa por vez (del mas cercano al mas lejano, del mismo tipo de
  vehiculo). Si nadie acepta en unos minutos, queda "sin conductor".
- Los conductores de una empresa solo hacen viajes de esa empresa: nunca reciben pedidos de comida.
- El pasajero le dice un PIN al conductor al subir: sin el PIN el viaje no arranca (asi nadie se sube al auto equivocado).
- Trappi no cobra comision por viaje: la empresa paga un abono por plan. Por ahora se paga en efectivo al conductor.

Como en los pedidos, no hay un proceso aparte: tick() lo llaman el pulso de la app del conductor, el estado del
viaje que consulta el pasajero y el panel de la empresa.
"""
import json
import math
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import ClientAccount, Courier, Ride, RideCompany, RideOffer, RideTariff
from . import platform, push, routing
from .geo import distance_km
from .ratelimit import PersistentRateLimiter
from .store_hours import LOCAL_TZ

VEHICLES = {'auto': 'Auto', 'moto': 'Moto'}
PLANS = {'inicial': 'Flota Inicial', 'pro': 'Flota Pro', 'plus': 'Flota Plus'}
STATUS_LABEL = {'buscando': 'Buscando conductor', 'asignado': 'Conductor en camino', 'en_puerta': 'Tu conductor llegó',
                'en_viaje': 'En viaje', 'finalizado': 'Llegaste', 'cancelado': 'Cancelado', 'sin_conductor': 'Sin conductores disponibles'}
# lo mismo, como lo ve la empresa en su panel
COMPANY_LABEL = {'buscando': 'Buscando conductor', 'asignado': 'Yendo a buscarlo', 'en_puerta': 'En la puerta', 'en_viaje': 'En viaje',
                 'finalizado': 'Finalizado', 'cancelado': 'Cancelado', 'sin_conductor': 'Sin conductor'}
ACTIVE = ('buscando', 'asignado', 'en_puerta', 'en_viaje')
DRIVER_ACTIVE = ('asignado', 'en_puerta', 'en_viaje')
FINAL = ('finalizado', 'cancelado', 'sin_conductor')
PASSENGER_CANCEL = ('buscando', 'asignado', 'en_puerta')
DRIVER_CANCEL_REASONS = {'no_aparece': 'El pasajero no aparece', 'direccion': 'No encuentro la dirección', 'vehiculo': 'Problema con el vehículo',
                         'seguridad': 'No me siento seguro', 'otro': 'Otro motivo'}
RATING_TAGS = ('Manejo seguro', 'Puntual', 'Auto limpio', 'Buena onda', 'Buen recorrido')
PIN_ATTEMPTS = 5
ARRIVE_KM = 0.4  # el conductor tiene que estar cerca del pasajero para avisar que llego
AUTO_ARRIVE_KM = 0.25  # el GPS marca la llegada solo a esta distancia (margen para el GPS y la direccion geocodificada)
TICK_EVERY = 2.0  # segundos: lo llaman muchos (pulsos, pasajeros, panel); con uno cada tanto alcanza
SPEED_KMH = {'auto': 28, 'moto': 30}  # sin ruta por calle (para el tiempo de llegada)
FRESH = timedelta(minutes=2)
NIGHT_FROM, NIGHT_TO = 22, 6

_lock = threading.Lock()
_last_tick = 0.0
# intentos fallidos del PIN por viaje: en la base (sobrevive reinicios) y se libera solo a los 10 minutos
pin_limiter = PersistentRateLimiter('ride-pin', limit=PIN_ATTEMPTS, window_seconds=600)


class RideError(Exception):
    pass


def money(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal('0.01'))


def round_price(v: Decimal) -> Decimal:
    """Precios redondos para el pasajero: de a $10."""
    return (Decimal(v) / 10).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * 10


def enabled(db: Session) -> bool:
    return bool(platform.get(db, 'rides_enabled'))


# ---------------------------------------------------------------- empresas y planes
def company_ok(c: RideCompany, today=None) -> tuple[bool, str]:
    """Si la empresa puede recibir viajes: aprobada por Trappi, activa y con el seguro vigente."""
    today = today or datetime.utcnow().date()
    if c.status != 'activa' or c.approved_at is None:
        return False, 'La empresa todavía no está habilitada por Trappi.'
    if c.insurance_expires is not None and c.insurance_expires < today:
        return False, 'El seguro de pasajeros de la empresa está vencido.'
    return True, ''


def visible_companies(db: Session, city_id: int | None) -> list[RideCompany]:
    rows = db.scalars(select(RideCompany).options(joinedload(RideCompany.tariffs)).where(RideCompany.status == 'activa')
                      .order_by(RideCompany.name)).unique().all()
    return [c for c in rows if company_ok(c)[0] and (city_id is None or c.city_id is None or c.city_id == city_id)]


def driver_cap(db: Session, c: RideCompany) -> int | None:
    """Conductores que permite el plan (None: sin tope, plan Plus)."""
    if c.driver_cap:
        return c.driver_cap
    if c.plan == 'plus':
        return None
    return platform.get(db, 'rides_cap_pro' if c.plan == 'pro' else 'rides_cap_inicial')


def drivers_count(db: Session, c: RideCompany) -> int:
    return db.scalar(select(func.count(Courier.id)).where(Courier.ride_company_id == c.id, Courier.active.is_(True))) or 0


def monthly_fee(db: Session, c: RideCompany) -> Decimal:
    """Abono del mes: el acordado con la empresa o el del plan (+ conductores extra en el plan Plus)."""
    if c.monthly_fee is not None:
        base = Decimal(c.monthly_fee)
    else:
        base = Decimal(str(platform.get(db, f'rides_fee_{c.plan}' if c.plan in PLANS else 'rides_fee_inicial')))
    if c.plan == 'plus':
        extra_fee = Decimal(c.extra_driver_fee) if c.extra_driver_fee is not None else Decimal(str(platform.get(db, 'rides_fee_extra_driver')))
        extra = max(0, drivers_count(db, c) - platform.get(db, 'rides_cap_pro'))
        base += extra_fee * extra
    return money(base)


def tariff(c: RideCompany, vehicle: str) -> RideTariff | None:
    return next((t for t in c.tariffs if t.vehicle == vehicle), None)


def tariff_json(t: RideTariff) -> dict:
    return {'vehicle': t.vehicle, 'base': float(t.base), 'per_km': float(t.per_km), 'per_wait_min': float(t.per_wait_min),
            'minimum': float(t.minimum), 'night_percent': t.night_percent}


def vehicles_of(c: RideCompany) -> list[str]:
    return [v for v in VEHICLES if (t := tariff(c, v)) and t.enabled]


# ---------------------------------------------------------------- precio
def is_night(now: datetime | None = None) -> bool:
    h = (now or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).hour
    return h >= NIGHT_FROM or h < NIGHT_TO


def price_for(t: RideTariff, km: float, night: bool) -> Decimal:
    p = Decimal(t.base) + Decimal(t.per_km) * Decimal(str(round(km, 2)))
    if night and t.night_percent:
        p = p * (100 + t.night_percent) / 100
    return round_price(max(p, Decimal(t.minimum)))


def wait_charge(db: Session, ride: Ride) -> Decimal:
    """Espera en la puerta pasados los minutos gratis, con el minuto de espera de la tarifa usada al pedir."""
    if not ride.arrived_at or not ride.started_at:
        return Decimal('0')
    snap = json.loads(ride.tariff_snapshot or '{}')
    per_min = Decimal(str(snap.get('per_wait_min') or 0))
    free = platform.get(db, 'rides_wait_free_minutes')
    minutes = (ride.started_at - ride.arrived_at).total_seconds() / 60 - free
    if minutes < 1 or per_min <= 0:
        return Decimal('0')
    return round_price(per_min * Decimal(math.floor(minutes)))  # solo minutos completos


def route(origin: tuple[float, float], dest: tuple[float, float]):
    r = routing.service.route(origin, dest, fallback='estimate')
    minutes = r.minutes if r.minutes is not None else r.km * 60 / SPEED_KMH['auto']
    return round(r.km, 2), round(minutes, 1), r.source == 'estimate'


# ---------------------------------------------------------------- conductores
def busy_ids(db: Session) -> set[int]:
    return set(db.scalars(select(Ride.courier_id).where(Ride.courier_id.is_not(None), Ride.status.in_(DRIVER_ACTIVE))))


def offered_ids(db: Session) -> set[int]:
    return set(db.scalars(select(RideOffer.courier_id).where(RideOffer.status == 'pending')))


def free_drivers(db: Session, company_id: int, vehicle: str, now: datetime | None = None, busy: set[int] | None = None) -> list[Courier]:
    """Conductores de la empresa conectados, con ubicacion reciente, del vehiculo pedido y sin un viaje en curso.
    busy: los ocupados, si ya se calcularon (al recorrer varios viajes o empresas se consulta una sola vez)."""
    now = now or datetime.utcnow()
    fresh = timedelta(minutes=platform.get(db, 'dispatch_location_minutes'))
    busy = busy_ids(db) if busy is None else busy
    rows = db.scalars(select(Courier).where(Courier.ride_company_id == company_id, Courier.active.is_(True), Courier.online.is_(True),
                                            Courier.vehicle == vehicle, Courier.location_at >= now - fresh)).all()
    return [c for c in rows if c.id not in busy and c.lat is not None]


def eta_minutes(c: Courier, lat: float, lng: float, vehicle: str) -> int:
    km = distance_km(c.lat, c.lng, lat, lng) * 1.35
    return max(1, math.ceil(km * 60 / SPEED_KMH.get(vehicle, 28)))


# ---------------------------------------------------------------- cotizar y pedir
def quote(db: Session, origin: tuple[float, float], dest: tuple[float, float], city_id: int | None, now: datetime | None = None) -> dict:
    """Las empresas de la ciudad con su precio estimado por vehiculo y cuanto tarda el conductor mas cercano."""
    now = now or datetime.utcnow()
    km, minutes, estimated = route(origin, dest)
    if km > platform.get(db, 'rides_max_km'):
        raise RideError(f'El viaje es muy largo (máximo {platform.get(db, "rides_max_km")} km).')
    if km < 0.2:
        raise RideError('El destino está demasiado cerca del origen.')
    night = is_night(now)
    options = []
    busy = busy_ids(db)
    for c in visible_companies(db, city_id):
        for v in vehicles_of(c):
            free = free_drivers(db, c.id, v, now, busy)
            eta = min((eta_minutes(d, origin[0], origin[1], v) for d in free), default=None)
            options.append({'company_id': c.id, 'company': c.name, 'logo_url': c.logo_url, 'vehicle': v,
                            'rating': float(c.rating_avg) if c.rating_avg else None, 'rating_count': c.rating_count,
                            'price': float(price_for(tariff(c, v), km, night)), 'eta_min': eta, 'available': eta is not None})
    for v in VEHICLES:
        group = [o for o in options if o['vehicle'] == v and o['available']]
        if group:
            min(group, key=lambda o: o['price'])['badge'] = 'Mejor precio'
            fastest = min(group, key=lambda o: o['eta_min'])
            fastest.setdefault('badge', 'Más rápido')
    options.sort(key=lambda o: (not o['available'], o['eta_min'] or 999, o['price']))
    return {'km': km, 'minutes': minutes, 'estimated': estimated, 'night': night, 'options': options}


def active_for_account(db: Session, account_id: int) -> Ride | None:
    return db.scalar(select(Ride).where(Ride.account_id == account_id, Ride.status.in_(ACTIVE)).order_by(Ride.id.desc()))


def request(db: Session, account: ClientAccount, company_id: int, vehicle: str, origin: dict, dest: dict, city_id: int | None,
            now: datetime | None = None) -> Ride:
    """Crea el viaje con el precio calculado aca (lo que mande la app como precio no se usa). Hace commit."""
    now = now or datetime.utcnow()
    if vehicle not in VEHICLES:
        raise RideError('Elegí auto o moto.')
    if active_for_account(db, account.id):
        raise RideError('Ya tenés un viaje en curso.')
    c = db.get(RideCompany, company_id)
    if c is None or c not in visible_companies(db, city_id):
        raise RideError('Esa empresa no está disponible.')
    t = tariff(c, vehicle)
    if not t or not t.enabled:
        raise RideError(f'{c.name} no ofrece viajes en {VEHICLES[vehicle].lower()}.')
    if not free_drivers(db, c.id, vehicle, now):
        raise RideError(f'{c.name} no tiene conductores libres ahora. Probá con otra empresa.')
    o, d = (origin['lat'], origin['lng']), (dest['lat'], dest['lng'])
    km, minutes, estimated = route(o, d)
    if km > platform.get(db, 'rides_max_km') or km < 0.2:
        raise RideError('Revisá el origen y el destino.')
    night = is_night(now)
    ride = Ride(company_id=c.id, account_id=account.id, vehicle=vehicle, status='buscando',
                passenger_name=(account.first_name or (account.name or '').split(' ')[0] or 'Pasajero')[:160], passenger_phone=account.phone or None,
                origin_address=(origin.get('address') or '')[:255] or None, origin_lat=o[0], origin_lng=o[1],
                origin_note=(origin.get('note') or '')[:160] or None,
                dest_address=(dest.get('address') or '')[:255] or None, dest_lat=d[0], dest_lng=d[1],
                km=km, minutes=minutes, route_estimated=estimated, night=night,
                tariff_snapshot=json.dumps(tariff_json(t)), price=price_for(t, km, night),
                pin=f'{secrets.randbelow(10_000):04d}', created_at=now, search_from=now)
    db.add(ride)
    db.commit()
    tick(db, force=True)
    return ride


# ---------------------------------------------------------------- ofertas
def pending_offer(db: Session, ride_id: int) -> RideOffer | None:
    return db.scalar(select(RideOffer).where(RideOffer.ride_id == ride_id, RideOffer.status == 'pending'))


def tick(db: Session, now: datetime | None = None, force: bool = False) -> int:
    """Vence ofertas, ofrece cada viaje buscando al conductor libre mas cercano y corta la busqueda que tardo demasiado. Hace commit.
    Sin force corre como mucho una vez cada TICK_EVERY segundos (lo llaman todos los pulsos y las pantallas que se actualizan)."""
    global _last_tick
    mono = time.monotonic()
    if not force and now is None and mono - _last_tick < TICK_EVERY:
        return 0
    _last_tick = mono
    now = now or datetime.utcnow()
    notify = []
    with _lock:
        for offer in db.scalars(select(RideOffer).options(joinedload(RideOffer.ride)).where(RideOffer.status == 'pending')):
            if offer.expires_at <= now:
                offer.status = 'expired'
            elif offer.ride.status != 'buscando':
                offer.status = 'cancelled'
        db.flush()
        rides = db.scalars(select(Ride).where(Ride.status == 'buscando').order_by(Ride.created_at)).all()
        if not rides:
            db.commit()
            return 0
        seconds = platform.get(db, 'rides_offer_seconds')
        limit = timedelta(minutes=platform.get(db, 'rides_search_minutes'))
        taken = offered_ids(db)
        busy = busy_ids(db)
        companies: dict[int, bool] = {}
        for ride in rides:
            if ride.company_id not in companies:
                companies[ride.company_id] = company_ok(db.get(RideCompany, ride.company_id))[0]
            if not companies[ride.company_id]:  # la suspendieron mientras buscaba
                ride.status, ride.cancelled_at, ride.cancelled_by = 'cancelado', now, 'sistema'
                ride.cancel_reason = 'La empresa no está disponible.'
                continue
            if now - ride.search_from >= limit:
                ride.status, ride.cancelled_at, ride.cancelled_by = 'sin_conductor', now, 'sistema'
                ride.cancel_reason = 'Ningún conductor aceptó a tiempo.'
                continue
            if pending_offer(db, ride.id):
                continue
            past = db.execute(select(RideOffer.courier_id, RideOffer.status, RideOffer.created_at).where(RideOffer.ride_id == ride.id)).all()
            rejected = {cid for cid, st, _ in past if st == 'rejected'}  # el que rechazo o cancelo este viaje no lo vuelve a ver
            asked = {cid for cid, _, when in past if when >= ride.search_from}
            free = [c for c in free_drivers(db, ride.company_id, ride.vehicle, now, busy) if c.id not in taken and c.id not in rejected]
            # primero los que todavia no la vieron; si ya la vieron todos, se le vuelve a ofrecer a los que la dejaron vencer
            free.sort(key=lambda c: (c.id in asked, distance_km(c.lat, c.lng, ride.origin_lat, ride.origin_lng)))
            if free:
                c = free[0]
                db.add(RideOffer(ride_id=ride.id, courier_id=c.id, created_at=now, expires_at=now + timedelta(seconds=seconds)))
                taken.add(c.id)
                notify.append((c, ride))
        db.commit()
    for c, ride in notify:
        push.notify_ride_offer(c, ride, seconds)
    return len(notify)


def offer_for(db: Session, courier: Courier, now: datetime | None = None) -> RideOffer | None:
    now = now or datetime.utcnow()
    return db.scalar(select(RideOffer).options(joinedload(RideOffer.ride)).where(
        RideOffer.courier_id == courier.id, RideOffer.status == 'pending', RideOffer.expires_at > now))


def current_for(db: Session, courier: Courier) -> Ride | None:
    return db.scalar(select(Ride).options(joinedload(Ride.company)).where(Ride.courier_id == courier.id, Ride.status.in_(DRIVER_ACTIVE)))


def accept(db: Session, courier: Courier, offer_id: int, now: datetime | None = None) -> Ride:
    now = now or datetime.utcnow()
    with _lock:
        offer = db.get(RideOffer, offer_id)
        if not offer or offer.courier_id != courier.id or offer.status != 'pending' or offer.expires_at <= now:
            raise RideError('Este viaje ya no está disponible.')
        ride = db.get(Ride, offer.ride_id)
        if ride.status != 'buscando' or courier.ride_company_id != ride.company_id or not company_ok(ride.company)[0]:
            offer.status = 'cancelled'
            db.commit()
            raise RideError('Este viaje ya no está disponible.')
        if current_for(db, courier):
            raise RideError('Primero terminá el viaje que tenés en curso.')
        if not courier.active or not courier.online:
            raise RideError('Conectate para aceptar viajes.')
        offer.status = 'accepted'
        ride.courier_id, ride.status, ride.assigned_at = courier.id, 'asignado', now
        db.commit()
        return ride


def reject(db: Session, courier: Courier, offer_id: int) -> None:
    offer = db.get(RideOffer, offer_id)
    if offer and offer.courier_id == courier.id and offer.status == 'pending':
        offer.status = 'rejected'
        db.commit()


def _mine(courier: Courier, ride: Ride | None, *statuses: str) -> Ride:
    if ride is None or ride.courier_id != courier.id:
        raise RideError('Este viaje no es tuyo.')
    if statuses and ride.status not in statuses:
        raise RideError('El viaje ya cambió de estado.')
    return ride


def arrive(db: Session, courier: Courier, ride: Ride, now: datetime | None = None) -> None:
    _mine(courier, ride, 'asignado')
    if courier.lat is not None and distance_km(courier.lat, courier.lng, ride.origin_lat, ride.origin_lng) > ARRIVE_KM:
        raise RideError('Todavía estás lejos del pasajero.')
    ride.status, ride.arrived_at = 'en_puerta', now or datetime.utcnow()
    db.commit()


def auto_arrive(db: Session, courier: Courier, now: datetime | None = None) -> bool:
    """Con el pulso del GPS: si el conductor ya esta en la puerta del pasajero, el viaje pasa a "llego" solo."""
    ride = current_for(db, courier)
    if ride is None or ride.status != 'asignado' or courier.lat is None:
        return False
    if distance_km(courier.lat, courier.lng, ride.origin_lat, ride.origin_lng) > AUTO_ARRIVE_KM:
        return False
    ride.status, ride.arrived_at = 'en_puerta', now or datetime.utcnow()
    db.commit()
    return True


def start(db: Session, courier: Courier, ride: Ride, pin: str, now: datetime | None = None) -> None:
    _mine(courier, ride, 'asignado', 'en_puerta')
    key = f'ride{ride.id}'
    if pin_limiter.blocked(key):
        raise RideError('Demasiados intentos con el PIN. El pasajero lo ve en su app; probá de nuevo en unos minutos.')
    if not secrets.compare_digest((pin or '').strip(), ride.pin):
        pin_limiter.hit(key)
        raise RideError('El PIN no coincide. Pedíselo de nuevo al pasajero.')
    pin_limiter.reset(key)
    now = now or datetime.utcnow()
    ride.arrived_at = ride.arrived_at or now
    ride.status, ride.started_at = 'en_viaje', now
    db.commit()


def finish(db: Session, courier: Courier, ride: Ride, now: datetime | None = None) -> None:
    _mine(courier, ride, 'en_viaje')
    ride.wait_charge = wait_charge(db, ride)
    ride.final_price = money(Decimal(ride.price) + ride.wait_charge)
    ride.status, ride.finished_at = 'finalizado', now or datetime.utcnow()
    db.commit()


def cancel_by_passenger(db: Session, account_id: int, ride: Ride, now: datetime | None = None) -> None:
    if ride.account_id != account_id:
        raise RideError('Viaje no encontrado.')
    if ride.status not in PASSENGER_CANCEL:
        raise RideError('El viaje ya empezó: no se puede cancelar desde la app.')
    ride.status, ride.cancelled_at, ride.cancelled_by = 'cancelado', now or datetime.utcnow(), 'pasajero'
    db.commit()
    tick(db, force=True)


def cancel_by_driver(db: Session, courier: Courier, ride: Ride, reason: str, now: datetime | None = None) -> None:
    """El conductor suelta el viaje antes de que suba el pasajero: se busca otro conductor de la empresa."""
    _mine(courier, ride, 'asignado', 'en_puerta')
    if reason not in DRIVER_CANCEL_REASONS:
        raise RideError('Elegí un motivo.')
    now = now or datetime.utcnow()
    for offer in db.scalars(select(RideOffer).where(RideOffer.ride_id == ride.id, RideOffer.courier_id == courier.id)):
        offer.status = 'rejected'  # no se le vuelve a ofrecer
    if reason == 'no_aparece' and ride.status == 'en_puerta':
        ride.status, ride.cancelled_at, ride.cancelled_by, ride.cancel_reason = 'cancelado', now, 'conductor', DRIVER_CANCEL_REASONS[reason]
    else:
        ride.status, ride.courier_id, ride.assigned_at, ride.arrived_at, ride.search_from = 'buscando', None, None, None, now
        ride.cancel_reason = f'El conductor anterior canceló: {DRIVER_CANCEL_REASONS[reason]}'
    db.commit()
    tick(db, force=True)


def cancel_by_company(db: Session, ride: Ride, reason: str = '', now: datetime | None = None) -> None:
    if ride.status not in ACTIVE:
        raise RideError('El viaje ya terminó.')
    ride.status, ride.cancelled_at, ride.cancelled_by = 'cancelado', now or datetime.utcnow(), 'empresa'
    ride.cancel_reason = (reason or 'Cancelado por la empresa')[:200]
    db.commit()


# ---------------------------------------------------------------- calificacion
def _avg(old, count: int, stars: int) -> Decimal:
    total = Decimal(old or 0) * count + stars
    return (total / (count + 1)).quantize(Decimal('0.01'))


def rate(db: Session, account_id: int, ride: Ride, stars: int, tags: list[str], comment: str = '') -> None:
    if ride.account_id != account_id or ride.status != 'finalizado':
        raise RideError('Solo se califican los viajes terminados.')
    if ride.rating is not None:
        raise RideError('Ya calificaste este viaje.')
    if not 1 <= stars <= 5:
        raise RideError('Elegí de 1 a 5 estrellas.')
    ride.rating = stars
    ride.rating_tags = ', '.join(t for t in tags if t in RATING_TAGS)[:200] or None
    ride.rating_comment = (comment or '').strip()[:500] or None
    if ride.courier:
        ride.courier.rating_avg = _avg(ride.courier.rating_avg, ride.courier.rating_count, stars)
        ride.courier.rating_count += 1
    c = ride.company
    c.rating_avg, c.rating_count = _avg(c.rating_avg, c.rating_count, stars), c.rating_count + 1
    db.commit()


# ---------------------------------------------------------------- seguimiento para el pasajero
def tracking(db: Session, ride: Ride, now: datetime | None = None) -> dict | None:
    """Donde esta el conductor (solo mientras viene, espera o lleva al pasajero, y con una ubicacion reciente)."""
    c = ride.courier
    if ride.status not in DRIVER_ACTIVE or c is None:
        return None
    now = now or datetime.utcnow()
    if c.lat is None or c.location_at is None or now - c.location_at > FRESH:
        return {'driver': None, 'eta_min': None}
    if ride.status == 'asignado':
        eta = eta_minutes(c, ride.origin_lat, ride.origin_lng, ride.vehicle)
    elif ride.status == 'en_viaje':
        eta = eta_minutes(c, ride.dest_lat, ride.dest_lng, ride.vehicle)
    else:
        eta = None
    return {'driver': {'lat': round(c.lat, 5), 'lng': round(c.lng, 5), 'at': c.location_at.isoformat() + 'Z'}, 'eta_min': eta}
