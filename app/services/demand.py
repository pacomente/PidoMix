"""Demanda de repartidores en cada ciudad: zonas calientes y multiplicador (estilo Uber).

Demanda = pedidos que esperan repartidor de la flota / repartidores de la flota libres.
- La app de repartidores muestra en rojo las zonas donde hay pedidos esperando y, si estás libre,
  te sugiere a cuál ir.
- Si el multiplicador está prendido (Logística → Configuración → Demanda), los viajes de la flota de Trappi
  pagan más: lo que gana el repartidor x el multiplicador, con tope. El extra lo pone Trappi.
  Los cadetes propios de un local no tienen multiplicador (los paga el local).
Todo se calcula acá: la app solo muestra lo que le manda el backend. Solo lee: no cambia nada.
"""
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models import Courier, Order
from . import cities, payments, platform
from .geo import distance_km

ONE = Decimal('1.00')
CACHE_SECONDS = 15
CLUSTER_KM = 0.9  # locales a menos de esto forman una misma zona

_cache: dict = {}
_lock = threading.Lock()


@dataclass
class Hotspot:
    lat: float
    lng: float
    orders: int
    name: str  # el local con mas pedidos esperando de la zona
    radius_m: int

    def json(self) -> dict:
        return {'lat': self.lat, 'lng': self.lng, 'orders': self.orders, 'name': self.name, 'radius_m': self.radius_m}


@dataclass
class Demand:
    city_id: int | None
    waiting: int = 0       # pedidos esperando repartidor de la flota
    free: int = 0          # repartidores de la flota conectados y sin viaje
    level: str = 'normal'  # normal | alta | muy_alta
    multiplier: Decimal = ONE
    hotspots: list = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.waiting / self.free if self.free else float(self.waiting)


def clear() -> None:
    with _lock:
        _cache.clear()


def _money_mult(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def fleet_may_take(order: Order) -> bool:
    """El pedido lo puede llevar la flota de Trappi (no es solo para cadetes propios)."""
    effective = 'propia' if (order.delivery_mode == 'store' and order.logistics == 'trappi') else order.logistics
    return effective != 'propia'


def _waiting_orders(db: Session, city_id: int | None) -> list[Order]:
    from .dispatch import DISPATCH_STATUSES  # import tardio: dispatch usa este modulo
    rows = db.scalars(select(Order).options(joinedload(Order.store)).where(
        Order.delivery_method == 'delivery', Order.status.in_(DISPATCH_STATUSES), Order.courier_id.is_(None))).all()
    return [o for o in rows if not payments.awaiting_online(o) and fleet_may_take(o) and cities.same_city(city_id, cities.of_order(o))]


def _free_couriers(db: Session, city_id: int | None, now: datetime) -> list[Courier]:
    from .dispatch import available
    return [c for c in available(db, now) if c.store_id is None and cities.same_city(c.city_id, city_id)]


def _clusters(orders: list[Order]) -> list[Hotspot]:
    by_store: dict[int, list[Order]] = {}
    for o in orders:
        if o.store is not None and o.store.lat is not None and o.store.lng is not None:
            by_store.setdefault(o.store_id, []).append(o)
    groups: list[list] = []  # [lat, lng, cantidad, [(nombre, cantidad)]]
    for items in sorted(by_store.values(), key=len, reverse=True):
        s = items[0].store
        for g in groups:
            if distance_km(g[0], g[1], s.lat, s.lng) <= CLUSTER_KM:
                total = g[2] + len(items)
                g[0], g[1] = (g[0] * g[2] + s.lat * len(items)) / total, (g[1] * g[2] + s.lng * len(items)) / total
                g[2] = total
                g[3].append((s.name, len(items)))
                break
        else:
            groups.append([s.lat, s.lng, len(items), [(s.name, len(items))]])
    out = [Hotspot(lat=round(g[0], 5), lng=round(g[1], 5), orders=g[2], name=max(g[3], key=lambda x: x[1])[0],
                   radius_m=min(1500, 500 + 150 * g[2])) for g in groups]
    return sorted(out, key=lambda h: -h.orders)


def compute(db: Session, city_id: int | None, now: datetime | None = None) -> Demand:
    """Sin cache (para tests y el panel)."""
    now = now or datetime.utcnow()
    cfg = platform.for_city(db, city_id)
    orders = _waiting_orders(db, city_id)
    d = Demand(city_id=city_id, waiting=len(orders), free=len(_free_couriers(db, city_id, now)))
    d.hotspots = _clusters(orders)
    if d.waiting >= cfg['surge_min_orders']:
        if d.ratio >= cfg['surge_very_high_ratio']:
            d.level = 'muy_alta'
        elif d.ratio >= cfg['surge_high_ratio']:
            d.level = 'alta'
    d.multiplier = multiplier_for(cfg, d.level)
    return d


def multiplier_for(cfg: dict, level: str) -> Decimal:
    if not cfg['surge_enabled']:
        return ONE
    if cfg['surge_mode'] == 'manual':
        m = cfg['surge_manual_multiplier']
    else:
        m = {'alta': cfg['surge_high_multiplier'], 'muy_alta': cfg['surge_very_high_multiplier']}.get(level, 1)
    return max(ONE, min(_money_mult(m), _money_mult(cfg['surge_max_multiplier'])))


def current(db: Session, city_id: int | None, now: datetime | None = None) -> Demand:
    """La demanda de la ciudad, recalculada como mucho cada CACHE_SECONDS (lo piden todos los pulsos)."""
    t = time.monotonic()
    with _lock:
        hit = _cache.get(city_id)
        if hit and t - hit[0] < CACHE_SECONDS:
            return hit[1]
    d = compute(db, city_id, now)
    with _lock:
        _cache[city_id] = (t, d)
    return d


def courier_city(db: Session, c: Courier) -> int | None:
    if c.city_id:
        return c.city_id
    city = cities.detect(db, c.lat, c.lng)
    return city.id if city else None


def surge_for(db: Session, order: Order, courier: Courier, now: datetime | None = None) -> Decimal:
    """Multiplicador para este viaje: solo la flota de Trappi; con la demanda de la ciudad del pedido."""
    if courier.store_id is not None:
        return ONE
    return current(db, cities.of_order(order), now).multiplier


LEVEL_TEXT = {'normal': 'Demanda normal', 'alta': 'Alta demanda', 'muy_alta': 'Demanda muy alta'}


def mult_text(m: Decimal) -> str:
    return 'x' + f'{m.normalize():f}'.replace('.', ',')


def for_courier(db: Session, c: Courier, busy: bool, now: datetime | None = None) -> dict:
    """Lo que ve el repartidor: nivel, multiplicador, zonas calientes y a cual le conviene ir."""
    d = current(db, courier_city(db, c), now)
    own_store = c.store_id is not None
    m = ONE if own_store else d.multiplier
    out = {'level': d.level, 'label': LEVEL_TEXT[d.level], 'multiplier': float(m), 'multiplier_text': mult_text(m) if m > ONE else None,
           'waiting': d.waiting, 'hotspots': [] if own_store else [h.json() for h in d.hotspots[:8]], 'suggestion': None}
    if not own_store and not busy and d.hotspots and c.lat is not None and c.lng is not None:
        best = min(d.hotspots, key=lambda h: (distance_km(c.lat, c.lng, h.lat, h.lng) - 0.3 * h.orders))  # cerca y con mas pedidos
        km = distance_km(c.lat, c.lng, best.lat, best.lng)
        if km > 0.4:  # si ya esta en la zona no hace falta decirle nada
            out['suggestion'] = {'lat': best.lat, 'lng': best.lng, 'km': round(km, 1), 'orders': best.orders,
                                 'text': f"{best.orders} {'pedido esperando' if best.orders == 1 else 'pedidos esperando'} cerca de {best.name}, a {str(round(km, 1)).replace('.', ',')} km"}
    return out
