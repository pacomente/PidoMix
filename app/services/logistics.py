"""Logistica de la flota Trappi: zonas de cobertura, tarifa por km, quien paga el envio,
costo operativo y pago al repartidor.

Como se calcula el envio de un pedido con la flota (todo en el backend):
  1. ubicacion del local y del cliente
  2. la flota esta activa y en horario
  3. la zona: el cliente tiene que caer dentro de una zona activa y disponible (radio o poligono);
     si hay varias superpuestas, gana la de mayor prioridad (y a igual prioridad, la mas chica)
  4. distancia real por calle local -> cliente (services/routing.py)
  5. tope de km de la zona
  6. tarifa: base + max(0, km - km incluidos) x precio por km, con minimo, maximo y redondeo
  7. quien lo paga: cliente, comercio, Trappi o compartido
Los comercios que no usan la flota (o si todavia no hay ninguna zona cargada) siguen con su envio
de siempre (fijo o por anillos de distancia, services/geo.py).
"""
import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LogisticsZone, LogisticsZoneVersion
from . import cities, platform, routing
from .geo import Coverage, coverage as store_coverage, distance_km
from .store_hours import local_now

CENT = Decimal('0.01')
PAYERS = {'CUSTOMER': 'El cliente', 'MERCHANT': 'El comercio', 'TRAPPI': 'Trappi', 'SHARED': 'Compartido'}
ZONE_KINDS = {'radius': 'Radio', 'polygon': 'Polígono'}


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- zonas ----------

_cache: dict = {'at': 0.0, 'zones': None}
_lock = threading.Lock()


def zones(db: Session, include_inactive: bool = False) -> list[LogisticsZone]:
    """Zonas no borradas (con cache corta para no consultar en cada carrito)."""
    if include_inactive:
        return list(db.scalars(select(LogisticsZone).where(LogisticsZone.deleted.is_(False)).order_by(LogisticsZone.priority.desc(), LogisticsZone.name)))
    with _lock:
        if _cache['zones'] is not None and time.monotonic() - _cache['at'] < 5:
            return _cache['zones']
    rows = list(db.scalars(select(LogisticsZone).where(LogisticsZone.deleted.is_(False), LogisticsZone.active.is_(True))))
    for z in rows:  # se usan fuera de la sesion: los atributos ya cargados alcanzan
        db.expunge(z)
    with _lock:
        _cache.update(at=time.monotonic(), zones=rows)
    return rows


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, zones=None)


def polygon_points(zone) -> list[tuple[float, float]]:
    try:
        pts = json.loads(zone.polygon or '[]')
        return [(float(p[0]), float(p[1])) for p in pts]
    except (ValueError, TypeError, IndexError):
        return []


def contains(zone, lat: float, lng: float) -> bool:
    if zone.kind == 'polygon':
        pts = polygon_points(zone)
        if len(pts) < 3:
            return False
        inside = False
        j = len(pts) - 1
        for i in range(len(pts)):  # ray casting sobre lat/lng (alcanza para zonas de una ciudad)
            yi, xi = pts[i]
            yj, xj = pts[j]
            if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
                inside = not inside
            j = i
        return inside
    if zone.center_lat is None or zone.center_lng is None or not zone.radius_km:
        return False
    return distance_km(zone.center_lat, zone.center_lng, lat, lng) <= float(zone.radius_km)


def area_km2(zone) -> float:
    if zone.kind == 'polygon':
        pts = polygon_points(zone)
        if len(pts) < 3:
            return 0.0
        lat0 = sum(p[0] for p in pts) / len(pts)
        kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57
        xy = [(p[1] * kx, p[0] * ky) for p in pts]
        return abs(sum(xy[i][0] * xy[i - 1][1] - xy[i - 1][0] * xy[i][1] for i in range(len(xy)))) / 2
    return math.pi * float(zone.radius_km or 0) ** 2


def _in_window(now_hm: str, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return True
    return start <= now_hm < end if start <= end else (now_hm >= start or now_hm < end)  # cruza la medianoche


def available(zone, now: datetime | None = None) -> bool:
    now = now or local_now()
    return str(now.weekday()) in (zone.days or '0123456') and _in_window(now.strftime('%H:%M'), zone.start_time, zone.end_time)


def fleet_open(cfg: dict, now: datetime | None = None) -> bool:
    now = now or local_now()
    return bool(cfg['fleet_active']) and _in_window(now.strftime('%H:%M'), cfg['fleet_start_time'] or None, cfg['fleet_end_time'] or None)


def matching(all_zones, lat: float, lng: float, now: datetime | None = None) -> list:
    """Zonas activas y en horario que contienen el punto, de la que manda a la que menos."""
    hits = [z for z in all_zones if z.active and not z.deleted and available(z, now) and contains(z, lat, lng)]
    return sorted(hits, key=lambda z: (-z.priority, area_km2(z), z.id or 0))


def overlaps(all_zones) -> list[tuple]:
    """Pares de zonas que se superponen (aproximado: se prueban puntos de cada una dentro de la otra)."""
    def sample(z):
        if z.kind == 'polygon':
            pts = polygon_points(z)
            if not pts:
                return []
            c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            return pts + [c]
        if z.center_lat is None or not z.radius_km:
            return []
        r = float(z.radius_km) / 111.0
        k = math.cos(math.radians(z.center_lat)) or 1
        return [(z.center_lat, z.center_lng)] + [(z.center_lat + r * 0.95 * math.sin(a), z.center_lng + r * 0.95 * math.cos(a) / k) for a in [i * math.pi / 4 for i in range(8)]]
    out = []
    zs = [z for z in all_zones if not z.deleted]
    for i, a in enumerate(zs):
        for b in zs[i + 1:]:
            if any(contains(b, *p) for p in sample(a)) or any(contains(a, *p) for p in sample(b)):
                out.append((a, b))
    return out


def zone_data(zone) -> dict:
    keys = ['name', 'description', 'active', 'color', 'priority', 'kind', 'center_lat', 'center_lng', 'radius_km', 'polygon', 'max_km',
            'base_fee', 'included_km', 'per_km', 'min_fee', 'max_fee', 'rounding', 'days', 'start_time', 'end_time', 'deleted', 'city_id']
    return {k: (str(getattr(zone, k)) if isinstance(getattr(zone, k), Decimal) else getattr(zone, k)) for k in keys}


def record_version(db: Session, zone, user=None) -> None:
    """Guarda una copia de la zona (historial de tarifas). No hace commit."""
    db.add(LogisticsZoneVersion(zone_id=zone.id, data=json.dumps(zone_data(zone), ensure_ascii=False), user_id=getattr(user, 'id', None)))


# ---------- tarifa ----------

def tariff(zone, km: float) -> dict:
    """Envio de la zona para una distancia por ruta (km)."""
    base, per_km = money(zone.base_fee), money(zone.per_km)
    included = float(zone.included_km or 0)
    billable = max(0.0, round(km - included, 3))
    raw = base + (Decimal(str(billable)) * per_km)
    fee = max(raw, money(zone.min_fee))
    if zone.max_fee is not None and money(zone.max_fee) > 0:
        fee = min(fee, money(zone.max_fee))
    step = money(zone.rounding)
    if step > 0:
        fee = (fee / step).to_integral_value(rounding=ROUND_CEILING) * step
    return {'base_fee': str(base), 'per_km': str(per_km), 'included_km': included, 'billable_km': billable, 'min_fee': str(money(zone.min_fee)),
            'max_fee': str(money(zone.max_fee)) if zone.max_fee is not None else None, 'rounding': str(step), 'raw': str(money(raw)), 'fee': money(fee)}


def payer_rule(store, cfg: dict) -> dict:
    payer = store.delivery_fee_payer or cfg['delivery_fee_payer']
    mode = store.fee_share_mode or cfg['fee_share_mode']
    value = store.fee_share_value if store.fee_share_value is not None else cfg['fee_share_value']
    return {'payer': payer if payer in PAYERS else 'CUSTOMER', 'share_mode': mode, 'share_value': str(money(value))}


def split_fee(fee: Decimal, rule: dict) -> tuple[Decimal, Decimal, Decimal]:
    """(cliente, comercio, Trappi) del costo real del envio."""
    fee = money(fee)
    payer = rule['payer']
    if payer == 'MERCHANT':
        return Decimal('0.00'), fee, Decimal('0.00')
    if payer == 'TRAPPI':
        return Decimal('0.00'), Decimal('0.00'), fee
    if payer == 'SHARED':
        value = money(rule['share_value'])
        customer = (fee * value / 100).quantize(CENT, rounding=ROUND_HALF_UP) if rule['share_mode'] == 'percent' else value
        customer = min(max(customer, Decimal('0.00')), fee)
        return customer, fee - customer, Decimal('0.00')
    return fee, Decimal('0.00'), Decimal('0.00')


# ---------- cotizacion del envio de un pedido ----------

@dataclass
class DeliveryQuote(Coverage):
    """Coverage de siempre + lo de la flota. mode: store (envio del comercio) | trappi (flota)."""
    mode: str = 'store'
    zone_id: int | None = None
    zone_name: str | None = None
    route_km: float | None = None
    minutes: float | None = None
    route_source: str | None = None
    fee_real: Decimal | None = None
    fee_customer: Decimal | None = None
    fee_merchant: Decimal | None = None
    fee_trappi: Decimal | None = None
    reason: str | None = None  # por que no hay cobertura (para mostrarle al cliente)
    pickup_allowed: bool = True
    eta_min: int | None = None
    eta_max: int | None = None
    snapshot: dict = field(default_factory=dict)


OUT_OF_COVERAGE = 'Esta dirección está fuera de la zona de entrega de este comercio.'


def _store_quote(store, loc, note: str | None = None, mode: str = 'store') -> DeliveryQuote:
    """Envio con la tarifa del comercio (lo de siempre). El comercio puede bonificarlo (paga el comercio).
    mode dice quien reparte: store (el comercio) o trappi (la flota, si todavia no hay zonas cargadas)."""
    cov = store_coverage(store, loc)
    q = DeliveryQuote(**cov.__dict__, mode=mode)
    fee = cov.cost if cov.cost is not None else (cov.from_cost if cov.zoned else None)
    if fee is not None:
        fee = money(fee)
        merchant_pays = (store.delivery_fee_payer == 'MERCHANT')
        q.fee_real = fee
        q.fee_customer, q.fee_merchant, q.fee_trappi = (Decimal('0.00'), fee, Decimal('0.00')) if merchant_pays else (fee, Decimal('0.00'), Decimal('0.00'))
        if merchant_pays and cov.cost is not None:
            q.cost = Decimal('0.00')
    q.eta_min, q.eta_max = store.estimated_minutes, store.estimated_minutes + 10
    q.snapshot = {'mode': mode, 'pricing': 'store', 'note': note, 'fee': str(fee) if fee is not None else None, 'payer': 'MERCHANT' if store.delivery_fee_payer == 'MERCHANT' else 'CUSTOMER'}
    return q


def cities_zone_clause(city_id):
    from sqlalchemy import or_, true
    return or_(LogisticsZone.city_id == city_id, LogisticsZone.city_id.is_(None)) if city_id else true()


def uses_fleet(store) -> bool:
    return store.logistics == 'trappi'


def delivery_quote(db: Session, store, loc: dict | None, precise: bool = True, now: datetime | None = None) -> DeliveryQuote:
    """Cotiza el envio de un pedido. precise=False (listados) estima sin llamar al servicio de rutas."""
    if not store.delivery_enabled:
        return DeliveryQuote(zoned=False, covered=False, mode='store', reason='Este comercio no hace envíos.')
    if not uses_fleet(store):
        return _store_quote(store, loc)
    all_zones = [z for z in zones(db) if cities.same_city(z.city_id, store.city_id)]  # las zonas de la ciudad del comercio
    if not all_zones and not db.scalar(select(LogisticsZone.id).where(LogisticsZone.deleted.is_(False), cities_zone_clause(store.city_id)).limit(1)):
        # todavia no se cargo ninguna zona de la flota en esta ciudad: se sigue cobrando el envio del comercio
        return _store_quote(store, loc, note='sin zonas de la flota: tarifa del comercio', mode='trappi')
    cfg = platform.for_city(db, store.city_id)
    policy = cfg['out_of_coverage_policy']

    def out(reason: str) -> DeliveryQuote:
        if policy == 'merchant':
            q = _store_quote(store, loc, note='fuera de cobertura: entrega el comercio')
            q.reason = reason
            return q
        return DeliveryQuote(zoned=True, covered=False, mode='trappi', reason=reason, pickup_allowed=policy != 'reject',
                             snapshot={'mode': 'trappi', 'out': reason, 'policy': policy})

    if not fleet_open(cfg, now):
        return out('La flota de Trappi no está trabajando en este horario.')
    if store.lat is None or store.lng is None:
        return out('El comercio todavía no marcó su ubicación.')
    if not loc:
        # sin la ubicacion del cliente no sabemos: se muestra "desde" con la tarifa mas barata
        cheapest = min((tariff(z, 0)['fee'] for z in all_zones), default=None)
        return DeliveryQuote(zoned=True, covered=None, mode='trappi', from_cost=cheapest, max_km=max((z.max_km or 0) for z in all_zones) or None)
    hits = matching(all_zones, loc['lat'], loc['lng'], now)
    if not hits:
        return out(OUT_OF_COVERAGE)
    zone = hits[0]
    straight = distance_km(store.lat, store.lng, loc['lat'], loc['lng'])
    if precise:
        route = routing.service.route((store.lat, store.lng), (loc['lat'], loc['lng']), fallback=cfg['routing_fallback'], detour=cfg['routing_detour_factor'])
        if route is None:
            return out('No pudimos calcular la ruta de entrega. Probá de nuevo en un rato o elegí retiro.')
    else:
        route = routing.Route(km=round(straight * cfg['routing_detour_factor'], 3), minutes=None, source='estimate')
    if zone.max_km and route.km > float(zone.max_km):
        return out(OUT_OF_COVERAGE)
    t = tariff(zone, route.km)
    rule = payer_rule(store, cfg)
    customer, merchant, trappi = split_fee(t['fee'], rule)
    travel = route.minutes if route.minutes is not None else route.km * 3  # ~20 km/h si no hay estimacion del proveedor
    eta = store.estimated_minutes + int(math.ceil(travel)) + int(cfg['fleet_extra_minutes'])
    q = DeliveryQuote(zoned=True, distance=straight, covered=True, cost=customer, max_km=zone.max_km, mode='trappi', zone_id=zone.id, zone_name=zone.name,
                      route_km=route.km, minutes=route.minutes, route_source=route.source, fee_real=t['fee'], fee_customer=customer, fee_merchant=merchant,
                      fee_trappi=trappi, eta_min=eta, eta_max=eta + 15)
    q.snapshot = {'mode': 'trappi', 'pricing': 'zone', 'zone': {'id': zone.id, 'name': zone.name, 'priority': zone.priority}, 'route': {'km': route.km, 'minutes': route.minutes, 'source': route.source},
                  'tariff': {k: v for k, v in t.items() if k != 'fee'} | {'fee': str(t['fee'])}, 'payer': rule,
                  'split': {'customer': str(customer), 'merchant': str(merchant), 'trappi': str(trappi)}}
    return q


# ---------- flota: costo operativo y pago al repartidor ----------

def operating_cost(cfg: dict, operational_km: float | None) -> Decimal:
    km = Decimal(str(operational_km or 0))
    return max(money(km * Decimal(str(cfg['operating_cost_per_km']))), money(cfg['operating_cost_min']))


def courier_payout(cfg: dict, shipping, km: float | None = None, now: datetime | None = None, multiplier=None) -> tuple[Decimal, dict]:
    """Lo que gana el repartidor por un viaje y el detalle (se guarda en el pedido al asignarlo).
    multiplier: por demanda (services/demand.py); suma un extra sobre lo calculado, con el tope en $ de la configuracion."""
    mode = cfg['courier_pay_mode']
    if mode != 'formula':
        pay = platform.courier_pay(cfg, shipping)
        detail = {'mode': mode, 'total': str(pay)}
        return _with_surge(cfg, pay, detail, multiplier)
    now = now or local_now()
    km = float(km or 0)
    parts = {'base': money(cfg['payout_base']), 'per_km': money(Decimal(str(km)) * Decimal(str(cfg['payout_per_km']))), 'delivery': money(cfg['payout_per_delivery'])}
    bonuses = {}
    if cfg['payout_night_start'] and cfg['payout_night_end'] and _in_window(now.strftime('%H:%M'), cfg['payout_night_start'], cfg['payout_night_end']):
        bonuses['nocturno'] = money(cfg['payout_night_bonus'])
    if cfg['payout_high_demand']:
        bonuses['alta_demanda'] = money(cfg['payout_high_demand_bonus'])
    extras = {}
    if cfg['payout_long_km'] and km >= float(cfg['payout_long_km']):
        extras['viaje_largo'] = money(cfg['payout_long_amount'])
    total = sum(parts.values(), Decimal('0')) + sum(bonuses.values(), Decimal('0')) + sum(extras.values(), Decimal('0'))
    detail = {'mode': 'formula', 'distance_km': km, **{k: str(v) for k, v in parts.items()}, 'bonuses': {k: str(v) for k, v in bonuses.items()},
              'extras': {k: str(v) for k, v in extras.items()}, 'total': str(money(total))}
    return _with_surge(cfg, money(total), detail, multiplier)


def _with_surge(cfg: dict, pay: Decimal, detail: dict, multiplier) -> tuple[Decimal, dict]:
    m = Decimal(str(multiplier or 1))
    if m <= 1 or pay <= 0:
        return pay, detail
    extra = money(pay * (m - 1))
    cap = Decimal(str(cfg.get('surge_max_extra') or 0))
    if cap > 0:
        extra = min(extra, money(cap))
    total = money(pay + extra)
    detail = {**detail, 'before_surge': str(pay), 'multiplier': str(m), 'surge': str(extra), 'total': str(total)}
    return total, detail
