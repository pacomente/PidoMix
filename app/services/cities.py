"""Multi-ciudad: en que ciudad esta el cliente y que ve.

Cada comercio, repartidor de la flota, zona de cobertura y pedido es de una ciudad. Lo que no tiene
ciudad (lo anterior a multi-ciudad) se comparte entre todas, asi nada se rompe al sumar ciudades.

Como se decide la ciudad del cliente (resolve):
  1. la que eligio (web: la sesion; app: el parametro city)
  2. la que contiene su ubicacion (la mas cercana dentro de su radio)
  3. la ciudad principal (la primera activa)
Con una sola ciudad activa no se muestra ningun selector.
"""
import re
import threading
import time
import unicodedata

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from ..models import City, Product, Store
from .geo import distance_km

_cache: dict = {'at': 0.0, 'rows': None}
_lock = threading.Lock()


def slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-') or 'ciudad'


def all_cities(db: Session, include_inactive: bool = False) -> list[City]:
    """Ciudades (con cache corta: se consultan en cada pagina). Los objetos quedan fuera de la sesion."""
    with _lock:
        rows = _cache['rows'] if _cache['rows'] is not None and time.monotonic() - _cache['at'] < 30 else None
    if rows is None:
        rows = list(db.scalars(select(City).order_by(City.display_order, City.name)))
        for c in rows:
            db.expunge(c)
        with _lock:
            _cache.update(at=time.monotonic(), rows=rows)
    return rows if include_inactive else [c for c in rows if c.active]


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, rows=None)


def get(db: Session, city_id: int | None) -> City | None:
    return next((c for c in all_cities(db, include_inactive=True) if c.id == city_id), None) if city_id else None


def by_ref(db: Session, ref) -> City | None:
    """Ciudad activa por id o por slug."""
    ref = str(ref or '').strip().lower()
    if not ref:
        return None
    return next((c for c in all_cities(db) if str(c.id) == ref or c.slug == ref), None)


def default(db: Session) -> City | None:
    active = all_cities(db)
    return active[0] if active else None


def detect(db: Session, lat: float | None, lng: float | None) -> City | None:
    """La ciudad activa que contiene el punto (la mas cercana, dentro de su radio)."""
    if lat is None or lng is None:
        return None
    best, best_km = None, None
    for c in all_cities(db):
        km = distance_km(c.center_lat, c.center_lng, lat, lng)
        if km <= float(c.radius_km or 0) and (best_km is None or km < best_km):
            best, best_km = c, km
    return best


def resolve(db: Session, requested=None, loc: dict | None = None) -> City | None:
    return by_ref(db, requested) or (detect(db, loc.get('lat'), loc.get('lng')) if loc else None) or default(db)


def multi(db: Session) -> bool:
    """Hay mas de una ciudad activa (recien ahi se muestra el selector)."""
    return len(all_cities(db)) > 1


# ---------- filtros ----------

def store_clause(city_id: int | None):
    """Comercios de la ciudad (y los que todavia no tienen ciudad). Sin ciudad: todos."""
    if not city_id:
        return true()
    return or_(Store.city_id == city_id, Store.city_id.is_(None))


def product_clause(city_id: int | None):
    if not city_id:
        return true()
    return Product.store_id.in_(select(Store.id).where(store_clause(city_id)))


def same_city(a: int | None, b: int | None) -> bool:
    """Dos cosas pueden trabajar juntas: misma ciudad, o alguna sin ciudad (compartida)."""
    return a is None or b is None or a == b


def label(city: City | None) -> str:
    return f'{city.name}' + (f', {city.province}' if city and city.province else '') if city else 'Todas las ciudades'


def of_order(order) -> int | None:
    """Ciudad de un pedido: la guardada al crearlo (o la del comercio en pedidos viejos)."""
    if getattr(order, 'city_id', None):
        return order.city_id
    store = getattr(order, 'store', None)
    return store.city_id if store is not None else None


def for_request(request, db: Session | None = None) -> City | None:
    """Ciudad del visitante de la web: la que eligio (sesion), la de su ubicacion o la principal."""
    from .geo import parse_location

    def run(session):
        return resolve(session, request.session.get('city'), parse_location(request.session.get('loc') or {}))
    if db is not None:
        return run(db)
    from ..db import SessionLocal
    with SessionLocal() as session:
        return run(session)


def multi_for_templates() -> bool:
    from ..db import SessionLocal
    with SessionLocal() as session:
        return multi(session)
