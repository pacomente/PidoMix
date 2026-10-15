"""Seguimiento en vivo para el cliente: dónde está su repartidor y cuánto falta.

Privacidad: la ubicación del repartidor se le muestra solo al cliente de un pedido en curso que lleva
ese repartidor, y solo mientras va al local o a su casa. Si el repartidor lleva varios pedidos y
primero entrega otro, este cliente no ve dónde está (sería ver la casa del otro cliente): solo que
es el siguiente. Una ubicación vieja (la app dejó de reportar) no se muestra.
"""
import math
import threading
import time
from datetime import datetime, timedelta

from ..models import Order, OrderStatus
from . import dispatch, routing

FRESH = timedelta(minutes=2)
ETA_SECONDS = 60          # el tiempo de llegada se recalcula como mucho una vez por minuto por pedido
SPEED_KMH = 22            # sin ruta por calle: moto en la ciudad
LIVE_STATUSES = (OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO)

_eta: dict[int, tuple[float, tuple, int]] = {}
_lock = threading.Lock()


def _pt(lat, lng):
    return {'lat': round(lat, 5), 'lng': round(lng, 5)} if lat is not None and lng is not None else None


def _minutes(a, b) -> float:
    r = routing.service.route(a, b, fallback='estimate')
    if r is None:
        return 0.0
    return r.minutes if r.minutes is not None else r.km * 60 / SPEED_KMH


def _eta_for(o: Order, stage: str, me: tuple[float, float]) -> int | None:
    home = (o.lat, o.lng) if o.lat is not None and o.lng is not None else None
    store = (o.store.lat, o.store.lng) if o.store.lat is not None and o.store.lng is not None else None
    key = (stage, round(me[0], 3), round(me[1], 3))
    now = time.monotonic()
    with _lock:
        hit = _eta.get(o.id)
        if hit and hit[1][0] == stage and (hit[1] == key or now - hit[0] < ETA_SECONDS):  # cambió la etapa: se recalcula
            return hit[2]
    if stage == 'to_you':
        if not home:
            return None
        total = _minutes(me, home)
    else:
        if not store:
            return None
        to_store = _minutes(me, store)
        rest = o.route_minutes if o.route_minutes is not None else (_minutes(store, home) if home else 0)
        total = to_store + rest
    eta = max(1, math.ceil(total))
    with _lock:
        if len(_eta) > 5000:
            _eta.clear()
        _eta[o.id] = (now, key, eta)
    return eta


def for_order(db, o: Order, now: datetime | None = None) -> dict | None:
    """Lo que ve el cliente en el mapa de su pedido; None si no hay nada para mostrar."""
    if o.delivery_method != 'delivery' or o.courier is None or o.status not in LIVE_STATUSES:
        return None
    now = now or datetime.utcnow()
    c = o.courier
    trips = dispatch.active_trips(db, c)
    if o.id not in [t.id for t in trips]:
        return None
    store, home = _pt(o.store.lat, o.store.lng), _pt(o.lat, o.lng)
    picked = o.status == OrderStatus.EN_CAMINO
    base = {'store': store, 'home': home, 'vehicle': c.vehicle, 'name': c.name.split()[0]}
    if picked and trips[0].id != o.id:
        ahead = sum(1 for t in trips[:[t.id for t in trips].index(o.id)] if t.status == OrderStatus.EN_CAMINO)
        return {**base, 'stage': 'other_delivery', 'ahead': ahead, 'courier': None, 'eta_min': None}
    stage = 'to_you' if picked else 'to_store'
    fresh = c.lat is not None and c.lng is not None and c.location_at is not None and now - c.location_at <= FRESH
    if not fresh:
        return {**base, 'stage': stage, 'courier': None, 'eta_min': None}
    me = (c.lat, c.lng)
    return {**base, 'stage': stage, 'courier': {**_pt(*me), 'at': c.location_at.isoformat() + 'Z'}, 'eta_min': _eta_for(o, stage, me)}
