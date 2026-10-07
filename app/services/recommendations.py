"""Recomendado para vos: lo que a cada cliente le puede gustar, calculado con SUS propios datos.

Aprende de a poco con cada pedido: no guarda un perfil aparte, lo arma en el momento con
  - los productos que compró (y cada cuánto los repite),
  - los comercios donde pidió, sus favoritos y cómo los calificó,
  - los rubros y categorías que más pide,
  - el rango de precios en el que suele comprar,
  - a qué hora suele pedir (y qué pide a esa hora),
  - dónde está (si el comercio llega y a qué distancia).
Los pedidos recientes pesan más que los viejos. Solo recomienda productos reales, a la venta y de su ciudad;
nunca usa datos de otros clientes ni los muestra. Con `personalize` apagado en la cuenta no se calcula nada.
"""
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import ClientAccount, Order, OrderItem, OrderStatus, Product, ProductStatus, Review, Store
from . import cities, plans
from .geo import coverage
from .store_hours import is_open, to_local

HISTORY_DAYS = 365
HISTORY_ORDERS = 60
HALF_LIFE_DAYS = 60  # un pedido de hace 2 meses pesa la mitad que uno de hoy
MAX_PER_STORE = 3
BANDS = (('madrugada', 0, 6), ('mañana', 6, 11), ('mediodía', 11, 15), ('tarde', 15, 19), ('noche', 19, 24))


def band_of(hour: int) -> str:
    return next(name for name, a, b in BANDS if a <= hour < b)


@dataclass
class Taste:
    """El gusto del cliente, armado con sus pedidos (solo para calcular; no se guarda)."""
    orders: int = 0
    products: Counter = field(default_factory=Counter)       # product_id -> peso
    times: Counter = field(default_factory=Counter)          # product_id -> veces que lo pidió
    last_bought: dict = field(default_factory=dict)          # product_id -> fecha
    stores: Counter = field(default_factory=Counter)
    categories: Counter = field(default_factory=Counter)     # categoria del producto
    store_categories: Counter = field(default_factory=Counter)
    band_categories: dict = field(default_factory=lambda: defaultdict(Counter))  # franja -> categoria -> peso
    prices: list = field(default_factory=list)
    ratings: dict = field(default_factory=dict)              # store_id -> promedio de sus calificaciones
    favorites: set = field(default_factory=set)
    gap_days: float | None = None                            # cada cuantos dias pide (mediana)

    @property
    def median_price(self) -> float | None:
        if not self.prices:
            return None
        p = sorted(self.prices)
        return p[len(p) // 2]


def enabled(acct: ClientAccount | None) -> bool:
    return bool(acct and acct.active and getattr(acct, 'personalize', True) is not False)


def build_taste(db: Session, account_id: int, favorites=(), now: datetime | None = None) -> Taste:
    now = now or datetime.utcnow()
    orders = db.scalars(select(Order).options(selectinload(Order.items).joinedload(OrderItem.product), joinedload(Order.store)).where(
        Order.account_id == account_id, Order.status != OrderStatus.CANCELADO, Order.created_at >= now - timedelta(days=HISTORY_DAYS))
        .order_by(Order.created_at.desc()).limit(HISTORY_ORDERS)).unique().all()
    t = Taste(orders=len(orders), favorites=set(favorites))
    for o in orders:
        w = 0.5 ** ((now - o.created_at).total_seconds() / 86400 / HALF_LIFE_DAYS)
        band = band_of(to_local(o.created_at).hour)
        t.stores[o.store_id] += w
        if o.store and o.store.store_category_id:
            t.store_categories[o.store.store_category_id] += w
        for it in o.items:
            t.products[it.product_id] += w * it.quantity
            t.times[it.product_id] += 1
            t.last_bought.setdefault(it.product_id, o.created_at)
            t.prices.append(float(it.unit_price))
            cat = it.product.category_id if it.product else None
            if cat:
                t.categories[cat] += w
                t.band_categories[band][cat] += w
    dates = sorted(o.created_at for o in orders)
    if len(dates) >= 3:
        gaps = sorted((b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:]))
        t.gap_days = gaps[len(gaps) // 2]
    rows = db.execute(select(Review.store_id, Review.rating).join(Order, Order.id == Review.order_id).where(Order.account_id == account_id)).all()
    by_store = defaultdict(list)
    for sid, rating in rows:
        by_store[sid].append(rating)
    t.ratings = {sid: sum(r) / len(r) for sid, r in by_store.items()}
    return t


def _share(counter: Counter, key) -> float:
    total = sum(counter.values())
    return counter.get(key, 0) / total if total and key is not None else 0.0


@dataclass
class Pick:
    product: Product
    score: float
    reason: str


def recommend(db: Session, acct: ClientAccount | None, city_id=None, loc: dict | None = None, favorites=(), limit: int = 12,
              now: datetime | None = None) -> list[Pick]:
    """Productos recomendados para este cliente, con el motivo. Sin cuenta, apagado o sin pedidos: lista vacía."""
    if not enabled(acct):
        return []
    now = now or datetime.utcnow()
    t = build_taste(db, acct.id, favorites, now)
    if not t.orders and not t.favorites:
        return []
    band = band_of(to_local(now).hour)
    band_cats = t.band_categories.get(band, Counter())
    median = t.median_price
    candidates = db.scalars(select(Product).options(joinedload(Product.store).selectinload(Store.hours), joinedload(Product.store).selectinload(Store.zones),
                                                    joinedload(Product.store).joinedload(Store.store_category),
                                                    joinedload(Product.category), selectinload(Product.modifier_groups)).where(
        Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False), plans.visible_product_clause(), cities.product_clause(city_id))
        .order_by(Product.featured.desc(), Product.id).limit(600)).unique().all()

    picks: list[Pick] = []
    for p in candidates:
        s = p.store
        if p.stock is not None and p.stock <= 0:
            continue
        if t.ratings.get(s.id, 5) <= 2:
            continue  # lo calificó mal: no se lo volvemos a ofrecer
        parts: list[tuple[float, str]] = []
        times = t.times.get(p.id, 0)
        if times:
            due = t.gap_days is None or (now - t.last_bought[p.id]).days >= t.gap_days * 0.8
            parts.append((1.4 * math.log1p(t.products[p.id]) + (0.6 if due else 0), f'Lo pediste {times} veces' if times > 1 else 'Lo pediste antes'))
        if s.id in t.favorites:
            parts.append((1.2, f'{s.name} está en tus favoritos'))
        st = _share(t.stores, s.id)
        if st:
            parts.append((1.6 * st + (0.4 if t.ratings.get(s.id, 0) >= 4 else 0), f'Porque pediste en {s.name}'))
        cat = p.category_id
        cs = _share(t.categories, cat)
        if cs:
            parts.append((1.8 * cs, f'Te gusta {p.category.name.lower()}' if p.category else 'Parecido a lo que pedís'))
        bs = _share(band_cats, cat)
        if bs:
            parts.append((0.9 * bs, f'Lo que solés pedir a la {band}' if band != 'mediodía' else 'Lo que solés pedir al mediodía'))
        scs = _share(t.store_categories, s.store_category_id)
        if scs and not st:
            parts.append((0.7 * scs, f'Parecido a lo que pedís en {s.store_category.name.lower()}' if s.store_category else 'Parecido a lo que pedís'))
        if not parts:
            continue  # nada que ver con sus gustos: no es "para vos"
        score = sum(x for x, _ in parts)
        if median:
            score += 0.5 * math.exp(-abs(math.log(max(float(p.price), 1) / median)))
        if p.previous_price and p.previous_price > p.price:
            score += 0.3
        if not is_open(s):
            score -= 1.5
        if loc and s.delivery_enabled:
            cov = coverage(s, loc)
            if cov.covered is False:
                score -= 1.0
            elif cov.distance is not None:
                score -= min(cov.distance, 10) * 0.04
        reason = parts[0][1] if times else max(parts, key=lambda x: x[0])[1]  # lo que ya pidió: el motivo más concreto
        picks.append(Pick(p, score, reason))

    picks.sort(key=lambda x: -x.score)
    out, per_store = [], Counter()
    for pick in picks:  # variedad: como mucho 3 productos del mismo comercio
        if per_store[pick.product.store_id] >= MAX_PER_STORE:
            continue
        per_store[pick.product.store_id] += 1
        out.append(pick)
        if len(out) >= limit:
            break
    return out
