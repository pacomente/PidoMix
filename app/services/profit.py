"""Rentabilidad: cuánto gana (o pierde) Trappi en cada pedido y el tablero financiero por período.

Todo sale de los números que ya guarda cada pedido (plans.breakdown) y del libro de movimientos:
nada se edita desde acá, solo se calcula y se muestra.

Ganancia de Trappi en un pedido entregado =
    comisión  (+ lo que cobró de envío − pago al cadete − costo operativo, si repartió la flota)
La comisión de Mercado Pago la paga el comercio y los cupones los pone cada comercio: no restan a Trappi.
Los pedidos cancelados también pueden costar: el viaje que se le paga igual al cadete y los reintegros.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import City, LedgerEntry, Order, OrderStatus, Store, SubscriptionPayment
from . import plans
from .formatting import money as fmt
from .store_hours import LOCAL_TZ, local_now, to_local

ZERO = Decimal('0.00')
BREAK_EVEN = Decimal('1.00')  # menos de $1 de diferencia: "sin ganancia"


def order_profit(order: Order) -> dict:
    """Ganancia de Trappi en un pedido, con el detalle y las causas si dio pérdida o casi nada."""
    b = plans.breakdown(order)
    profit = b['trappi_income']
    total = b['total']
    collected = b['fee_customer'] + b['fee_merchant'] if b['fleet'] else ZERO
    courier = (b['expected_courier_pay'] or ZERO) if b['fleet'] else ZERO
    causes = []
    if b['fleet']:
        if b['fee_trappi'] > 0:
            causes.append(f'Trappi puso {fmt(b["fee_trappi"])} del envío')
        if courier > collected:
            causes.append(f'Al cadete se le paga {fmt(courier - collected)} más de lo que se cobró de envío')
        if b['operating_cost'] > 0 and profit < BREAK_EVEN:
            causes.append(f'Costo operativo: {fmt(b["operating_cost"])}')
    if b['commission'] <= 0:
        causes.append('Sin comisión en este pedido')
    status = 'loss' if profit <= -BREAK_EVEN else ('even' if profit < BREAK_EVEN else 'gain')
    return {
        'breakdown': b, 'profit': profit, 'status': status, 'causes': causes if status != 'gain' else [],
        'margin_pct': (profit / total * 100).quantize(Decimal('0.1')) if total > 0 else None,
        'commission': b['commission'], 'shipping_collected': collected, 'courier_pay': courier, 'operating_cost': b['operating_cost'] if b['fleet'] else ZERO,
        'logistics_margin': b['logistics_margin'], 'fleet': b['fleet'],
    }


# ---------- períodos ----------

PERIODS = {'hoy': 'Hoy', '7d': 'Últimos 7 días', '30d': 'Últimos 30 días', '90d': 'Últimos 90 días', 'mes': 'Este mes', 'mes-anterior': 'Mes anterior'}


@dataclass
class Period:
    key: str
    label: str
    start: datetime  # UTC naive, como created_at
    end: datetime
    days: int

    def previous(self) -> 'Period':
        length = self.end - self.start
        return Period(self.key, 'período anterior', self.start - length, self.start, self.days)


def _utc(d: datetime) -> datetime:
    """Hora local (Argentina) -> UTC sin zona, como se guarda created_at."""
    return d.astimezone(timezone.utc).replace(tzinfo=None)


def period(key: str = '30d', now: datetime | None = None) -> Period:
    """Período en días locales. `now` (UTC sin zona) solo para los tests."""
    now_l = now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ) if now else local_now()
    today = now_l.replace(hour=0, minute=0, second=0, microsecond=0)
    if key not in PERIODS:
        key = '30d'
    if key == 'hoy':
        start, end = today, today + timedelta(days=1)
    elif key in ('7d', '30d', '90d'):
        n = int(key[:-1])
        start, end = today - timedelta(days=n - 1), today + timedelta(days=1)
    elif key == 'mes':
        start = today.replace(day=1)
        end = today + timedelta(days=1)
    else:  # mes anterior
        first = today.replace(day=1)
        start = (first - timedelta(days=1)).replace(day=1)
        end = first
    return Period(key, PERIODS[key], _utc(start), _utc(end), max(1, round((end - start).total_seconds() / 86400)))


# ---------- resumen ----------

@dataclass
class Bucket:
    orders: int = 0
    gmv: Decimal = ZERO          # lo que pagaron los clientes
    products: Decimal = ZERO
    commission: Decimal = ZERO
    shipping_collected: Decimal = ZERO
    courier_pay: Decimal = ZERO
    operating_cost: Decimal = ZERO
    logistics_margin: Decimal = ZERO
    profit: Decimal = ZERO       # ganancia de Trappi en pedidos entregados
    loss_orders: int = 0
    loss_amount: Decimal = ZERO

    def add(self, p: dict) -> None:
        b = p['breakdown']
        self.orders += 1
        self.gmv += b['total']
        self.products += b['products']
        self.commission += p['commission']
        self.shipping_collected += p['shipping_collected']
        self.courier_pay += p['courier_pay']
        self.operating_cost += p['operating_cost']
        self.logistics_margin += p['logistics_margin']
        self.profit += p['profit']
        if p['status'] == 'loss':
            self.loss_orders += 1
            self.loss_amount += p['profit']

    @property
    def avg_ticket(self) -> Decimal:
        return (self.gmv / self.orders).quantize(Decimal('0.01')) if self.orders else ZERO

    @property
    def take_rate(self) -> Decimal | None:
        return (self.profit / self.gmv * 100).quantize(Decimal('0.1')) if self.gmv else None


@dataclass
class Summary:
    period: Period
    total: Bucket = field(default_factory=Bucket)
    by_day: dict = field(default_factory=dict)       # date -> Bucket
    by_store: dict = field(default_factory=dict)     # store_id -> Bucket
    by_city: dict = field(default_factory=dict)      # city_id -> Bucket
    store_names: dict = field(default_factory=dict)
    city_names: dict = field(default_factory=dict)
    cancelled: int = 0
    cancelled_cost: Decimal = ZERO   # viajes pagados y reintegros de pedidos cancelados
    subscriptions: Decimal = ZERO    # abonos mensuales cobrados en el período
    lines: list = field(default_factory=list)  # (order, profit) de cada pedido entregado

    @property
    def net(self) -> Decimal:
        """Resultado de Trappi en el período: pedidos + abonos − lo que costaron los cancelados."""
        return self.total.profit + self.subscriptions - self.cancelled_cost

    @property
    def cancel_rate(self) -> Decimal | None:
        n = self.total.orders + self.cancelled
        return (Decimal(self.cancelled) / n * 100).quantize(Decimal('0.1')) if n else None


def summarize(db: Session, p: Period, city_id: int | None = None, store_id: int | None = None, keep_lines: bool = False) -> Summary:
    scope = []
    if city_id:
        scope.append(Order.store_id.in_(select(Store.id).where(Store.city_id == city_id)))
    if store_id:
        scope.append(Order.store_id == store_id)
    s = Summary(period=p)
    day = p.start
    while day < p.end:  # todos los días, aunque no haya pedidos (para el gráfico)
        s.by_day[to_local(day).date()] = Bucket()
        day += timedelta(days=1)
    rows = db.scalars(select(Order).options(joinedload(Order.store)).where(
        Order.status == OrderStatus.ENTREGADO, Order.created_at >= p.start, Order.created_at < p.end, *scope).order_by(Order.created_at)).all()
    for o in rows:
        pr = order_profit(o)
        s.total.add(pr)
        s.by_day.setdefault(to_local(o.created_at).date(), Bucket()).add(pr)
        s.by_store.setdefault(o.store_id, Bucket()).add(pr)
        s.store_names[o.store_id] = o.store.name
        cid = o.store.city_id
        s.by_city.setdefault(cid, Bucket()).add(pr)
        if keep_lines:
            s.lines.append((o, pr))
    if s.by_city:
        s.city_names = {c.id: c.name for c in db.scalars(select(City).where(City.id.in_([c for c in s.by_city if c]))).all()}
    s.cancelled = db.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.CANCELADO, Order.created_at >= p.start,
                                                               Order.created_at < p.end, *scope)) or 0
    s.cancelled_cost = Decimal(db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).join(Order, Order.id == LedgerEntry.order_id).where(
        LedgerEntry.account == 'courier_earnings', LedgerEntry.kind.in_(('trip', 'reimbursement')), Order.status == OrderStatus.CANCELADO,
        Order.created_at >= p.start, Order.created_at < p.end, *scope)) or 0).quantize(Decimal('0.01'))
    subs = select(func.coalesce(func.sum(SubscriptionPayment.amount), 0)).where(
        SubscriptionPayment.status == 'pagado', SubscriptionPayment.paid_at >= p.start, SubscriptionPayment.paid_at < p.end)
    if city_id:
        subs = subs.where(SubscriptionPayment.store_id.in_(select(Store.id).where(Store.city_id == city_id)))
    if store_id:
        subs = subs.where(SubscriptionPayment.store_id == store_id)
    s.subscriptions = Decimal(db.scalar(subs) or 0).quantize(Decimal('0.01'))
    return s


def change(now: Decimal | int | None, before: Decimal | int | None) -> Decimal | None:
    """Variación % contra el período anterior (None si antes era 0)."""
    if now is None or before in (None, 0):
        return None
    return ((Decimal(now) - Decimal(before)) / abs(Decimal(before)) * 100).quantize(Decimal('0.1'))


def day_label(d: date) -> str:
    return f'{d.day:02d}/{d.month:02d}'
