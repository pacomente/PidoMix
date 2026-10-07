"""Analítica de clientes y comercios (solo superadmin). Solo lee y cuenta: no cambia nada.

Un "cliente" es su cuenta; los pedidos sin cuenta (de antes) se agrupan por teléfono.
En las listas los datos de contacto van enmascarados: la ficha completa está en Clientes.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import ClientAccount, Order, OrderStatus, Review, SearchLog, Store
from .profit import Period, change
from .store_hours import to_local

ZERO = Decimal('0')
DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
AT_RISK_FROM, AT_RISK_TO = 30, 120  # dias sin pedir para "en riesgo"


def customer_key(o: Order) -> str | None:
    if o.account_id:
        return f'a{o.account_id}'
    phone = re.sub(r'\D', '', (o.customer.phone if o.customer else '') or '')[-10:]
    return f'p{phone}' if len(phone) >= 6 else None


def mask_email(email: str | None) -> str:
    if not email or '@' not in email:
        return ''
    user, domain = email.split('@', 1)
    return (user[:2] + '•••') + '@' + domain


def short_name(o: Order) -> str:
    c = o.customer
    if c and c.first_name:
        return f'{c.first_name} {(c.last_name or "")[:1]}.'.strip().rstrip('.') + ('.' if c.last_name else '')
    return 'Cliente'


@dataclass
class CustomerRow:
    key: str
    name: str
    account_id: int | None
    email: str = ''
    orders: int = 0
    spent: Decimal = ZERO
    first: datetime | None = None
    last: datetime | None = None
    period_orders: int = 0
    period_spent: Decimal = ZERO

    @property
    def gap_days(self) -> float | None:
        if self.orders < 2 or not self.first or not self.last:
            return None
        return (self.last - self.first).total_seconds() / 86400 / (self.orders - 1)


@dataclass
class StoreRow:
    store: Store
    orders: int = 0
    gmv: Decimal = ZERO
    prev_orders: int = 0
    prev_gmv: Decimal = ZERO
    cancelled: int = 0
    new_customers: int = 0
    prep_minutes: list = field(default_factory=list)
    total_minutes: list = field(default_factory=list)
    ratings: list = field(default_factory=list)

    @property
    def growth(self) -> Decimal | None:
        return change(self.gmv, self.prev_gmv)

    @property
    def trend(self) -> str:
        g = self.growth
        if g is None:
            return 'new' if self.orders and not self.prev_orders else 'flat'
        if max(self.orders, self.prev_orders) < 3:
            return 'flat'  # con muy pocos pedidos no se saca conclusion
        return 'up' if g >= 20 else ('down' if g <= -20 else 'flat')

    @property
    def cancel_rate(self) -> Decimal | None:
        n = self.orders + self.cancelled
        return (Decimal(self.cancelled) / n * 100).quantize(Decimal('0.1')) if n else None

    @staticmethod
    def _avg(values):
        return round(sum(values) / len(values)) if values else None

    @property
    def prep(self):
        return self._avg(self.prep_minutes)

    @property
    def total_time(self):
        return self._avg(self.total_minutes)

    @property
    def rating(self):
        return round(sum(self.ratings) / len(self.ratings), 1) if self.ratings else None


@dataclass
class Report:
    period: Period
    customers_active: int = 0
    customers_new: int = 0
    customers_returning: int = 0
    customers_repeat: int = 0          # pidieron 2 o más veces en el período
    retention: Decimal | None = None   # de los que pidieron en el período anterior, cuántos volvieron
    prev_active: int = 0
    prev_new: int = 0
    orders_per_customer: Decimal | None = None
    spend_per_customer: Decimal | None = None
    top_customers: list = field(default_factory=list)
    at_risk: list = field(default_factory=list)
    stores: list = field(default_factory=list)
    heat: dict = field(default_factory=dict)  # (weekday, hour) -> pedidos
    heat_max: int = 0
    peak: tuple | None = None
    searches: list = field(default_factory=list)
    searches_empty: list = field(default_factory=list)
    searches_total: int = 0
    searches_empty_total: int = 0


def build(db: Session, p: Period, city_id: int | None = None, now: datetime | None = None) -> Report:
    now = now or datetime.utcnow()
    r = Report(period=p)
    prev = p.previous()
    scope = [Order.store_id.in_(select(Store.id).where(Store.city_id == city_id))] if city_id else []
    # todos los pedidos entregados hasta el fin del periodo (para saber quien es nuevo y quien esta en riesgo)
    delivered = db.scalars(select(Order).options(joinedload(Order.customer), joinedload(Order.store), selectinload(Order.events)).where(
        Order.status == OrderStatus.ENTREGADO, Order.created_at < p.end, *scope).order_by(Order.created_at)).unique().all()
    accounts = {a.id: a for a in db.scalars(select(ClientAccount).where(ClientAccount.id.in_({o.account_id for o in delivered if o.account_id}))).all()}
    people: dict[str, CustomerRow] = {}
    in_period, in_prev = defaultdict(int), set()
    stores: dict[int, StoreRow] = {}
    for o in delivered:
        k = customer_key(o)
        if k:
            row = people.get(k)
            if not row:
                a = accounts.get(o.account_id)
                row = people[k] = CustomerRow(k, (a.name or short_name(o)) if a else short_name(o), o.account_id, mask_email(a.email) if a else '')
            row.orders += 1
            row.spent += Decimal(o.total)
            row.first = row.first or o.created_at
            row.last = o.created_at
        if p.start <= o.created_at < p.end:
            if k:
                in_period[k] += 1
                people[k].period_orders += 1
                people[k].period_spent += Decimal(o.total)
            sr = stores.setdefault(o.store_id, StoreRow(o.store))
            sr.orders += 1
            sr.gmv += Decimal(o.total)
            confirmed, ready, done = o.status_time(OrderStatus.CONFIRMADO), o.status_time(OrderStatus.LISTO), o.status_time(OrderStatus.ENTREGADO)
            if confirmed and ready and ready > confirmed:
                sr.prep_minutes.append((ready - confirmed).total_seconds() / 60)
            if done and done > o.created_at:
                sr.total_minutes.append((done - o.created_at).total_seconds() / 60)
            local = to_local(o.created_at)
            r.heat[(local.weekday(), local.hour)] = r.heat.get((local.weekday(), local.hour), 0) + 1
        elif prev.start <= o.created_at < prev.end:
            if k:
                in_prev.add(k)
            sr = stores.setdefault(o.store_id, StoreRow(o.store))
            sr.prev_orders += 1
            sr.prev_gmv += Decimal(o.total)

    # clientes
    r.customers_active = len(in_period)
    r.customers_new = sum(1 for k in in_period if p.start <= people[k].first < p.end)
    r.customers_returning = r.customers_active - r.customers_new
    r.customers_repeat = sum(1 for n in in_period.values() if n >= 2)
    r.prev_active = len(in_prev)
    r.prev_new = sum(1 for k in in_prev if prev.start <= people[k].first < prev.end)
    if in_prev:
        r.retention = (Decimal(len(in_prev & set(in_period))) / len(in_prev) * 100).quantize(Decimal('0.1'))
    if in_period:
        r.orders_per_customer = (Decimal(sum(in_period.values())) / len(in_period)).quantize(Decimal('0.01'))
        r.spend_per_customer = (sum((people[k].period_spent for k in in_period), ZERO) / len(in_period)).quantize(Decimal('1'))
    r.top_customers = sorted((people[k] for k in in_period), key=lambda c: -c.period_spent)[:10]
    ref = min(now, p.end)
    risk = [c for c in people.values() if c.orders >= 2 and AT_RISK_FROM <= (ref - c.last).days <= AT_RISK_TO]
    r.at_risk = sorted(risk, key=lambda c: -c.spent)[:15]

    # nuevos clientes por comercio (su primer pedido fue ahi)
    first_store = {}
    for o in delivered:
        k = customer_key(o)
        if k and k not in first_store:
            first_store[k] = (o.store_id, o.created_at)
    for k, (sid, when) in first_store.items():
        if p.start <= when < p.end and sid in stores:
            stores[sid].new_customers += 1
    for sid, n in db.execute(select(Order.store_id, func.count(Order.id)).where(Order.status == OrderStatus.CANCELADO, Order.created_at >= p.start,
                                                                                Order.created_at < p.end, *scope).group_by(Order.store_id)).all():
        if sid in stores:
            stores[sid].cancelled = n
        else:
            st = db.get(Store, sid)
            if st:
                stores[sid] = StoreRow(st, cancelled=n)
    for sid, rating in db.execute(select(Review.store_id, Review.rating).where(Review.hidden.is_(False), Review.created_at >= p.start, Review.created_at < p.end)).all():
        if sid in stores:
            stores[sid].ratings.append(rating)
    order = {'down': 0, 'up': 1, 'new': 2, 'flat': 3}
    r.stores = sorted(stores.values(), key=lambda s: (order[s.trend], -s.gmv))

    if r.heat:
        r.heat_max = max(r.heat.values())
        (d, h), _ = max(r.heat.items(), key=lambda kv: kv[1])
        r.peak = (DAYS[d], h)

    # busquedas
    sq = [SearchLog.created_at >= p.start, SearchLog.created_at < p.end] + ([SearchLog.city_id == city_id] if city_id else [])
    r.searches_total = db.scalar(select(func.count(SearchLog.id)).where(*sq)) or 0
    r.searches_empty_total = db.scalar(select(func.count(SearchLog.id)).where(SearchLog.results == 0, *sq)) or 0
    r.searches = db.execute(select(SearchLog.term, func.count(SearchLog.id).label('n')).where(*sq).group_by(SearchLog.term)
                            .order_by(func.count(SearchLog.id).desc()).limit(12)).all()
    r.searches_empty = db.execute(select(SearchLog.term, func.count(SearchLog.id).label('n')).where(SearchLog.results == 0, *sq).group_by(SearchLog.term)
                                  .order_by(func.count(SearchLog.id).desc()).limit(12)).all()
    return r


def heat_level(n: int, top: int) -> int:
    """0 a 4, para el color de la celda (un solo tono, de claro a oscuro)."""
    if not n or not top:
        return 0
    return min(4, 1 + int(3 * n / top))
