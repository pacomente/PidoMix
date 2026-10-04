"""Modelo comercial de Trappi: planes de cada comercio y reparto de la plata de cada pedido.

Planes
  TRAPPI_COMERCIO  abono mensual fijo, 0 % de comision, reparte con sus propios cadetes.
  TRAPPI_DELIVERY  sin abono, comision por venta, reparte la flota de Trappi.
Los valores que se proponen al dar de alta salen de la configuracion (services/platform.py,
seccion comercial); lo acordado con cada comercio queda en su ficha y solo lo cambia el superadmin.
Los comercios anteriores a los planes quedan sin plan: sin comision y con la logistica de siempre.

Cada pedido guarda las condiciones vigentes al crearse (plan, % de comision, logistica) y con eso
se calculan la comision, el neto del comercio y el ingreso de Trappi. Cambiar despues el plan del
comercio no toca los pedidos ya hechos.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import Order, OrderStatus, Store, StorePlanChange, StoreStatus, SubscriptionPayment
from . import platform

COMERCIO, DELIVERY = 'TRAPPI_COMERCIO', 'TRAPPI_DELIVERY'
PLANS = {
    COMERCIO: {'name': 'Trappi Comercio', 'logistics': 'propia', 'short': 'Abono mensual · 0 % de comisión · cadetes propios'},
    DELIVERY: {'name': 'Trappi Delivery', 'logistics': 'trappi', 'short': 'Sin abono · comisión por venta · flota Trappi'},
}
LOGISTICS = {
    'propia': 'Cadetes propios del comercio',
    'mixta': 'Cadetes propios y, si no hay, la flota Trappi',
    'trappi': 'Flota de cadetes de Trappi',
}
LOGISTICS_SHORT = {'propia': 'Propia', 'mixta': 'Propia + flota', 'trappi': 'Flota Trappi'}
ACCOUNT_STATUSES = {
    'pendiente': 'Pendiente de configuración',
    'activo': 'Activo',
    'suspendido': 'Suspendido',
    'desactivado': 'Desactivado',
}
CENT = Decimal('0.01')


class PlanError(Exception):
    pass


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def plan_name(plan: str | None) -> str:
    return PLANS[plan]['name'] if plan in PLANS else 'Sin plan asignado'


def defaults(db: Session, plan: str) -> dict:
    """Condiciones que se proponen para un plan (las de la configuracion comercial)."""
    if plan not in PLANS:
        raise PlanError('Elegí un plan válido.')
    cfg = platform.get_all(db)
    if plan == COMERCIO:
        return {'monthly_fee': money(cfg['plan_comercio_price']), 'commission_rate': money(0), 'logistics': 'propia'}
    return {'monthly_fee': money(0), 'commission_rate': money(cfg['plan_delivery_commission']), 'logistics': 'trappi'}


def terms(store: Store) -> dict:
    """Lo que rige hoy para el comercio (los sin plan: sin abono ni comision, logistica de siempre)."""
    return {'plan': store.plan, 'name': plan_name(store.plan), 'monthly_fee': money(store.monthly_fee),
            'commission_rate': money(store.commission_rate), 'logistics': store.logistics or 'mixta',
            'logistics_label': LOGISTICS.get(store.logistics or 'mixta'), 'status': store.account_status,
            'status_label': ACCOUNT_STATUSES.get(store.account_status, store.account_status)}


def validate(plan: str, monthly_fee, commission_rate, logistics: str) -> tuple[Decimal, Decimal, str]:
    if plan not in PLANS:
        raise PlanError('Elegí un plan válido.')
    fee, rate = money(monthly_fee), money(commission_rate)
    if fee < 0:
        raise PlanError('El abono no puede ser negativo.')
    if not Decimal('0') <= rate <= Decimal('100'):
        raise PlanError('La comisión tiene que estar entre 0 y 100 %.')
    if logistics not in LOGISTICS:
        raise PlanError('Elegí una modalidad de logística válida.')
    return fee, rate, logistics


def set_plan(db: Session, store: Store, plan: str, monthly_fee, commission_rate, logistics: str, user=None, note: str = '',
             now: datetime | None = None) -> bool:
    """Asigna o cambia el plan y las condiciones; deja el registro en el historial. No hace commit.
    Devuelve False si no cambio nada. Los pedidos ya hechos conservan sus condiciones."""
    fee, rate, logistics = validate(plan, monthly_fee, commission_rate, logistics)
    if (store.plan, money(store.monthly_fee) if store.monthly_fee is not None else None,
            money(store.commission_rate) if store.commission_rate is not None else None, store.logistics) == (plan, fee, rate, logistics):
        return False
    now = now or datetime.utcnow()
    db.add(StorePlanChange(store_id=store.id, from_plan=store.plan, to_plan=plan, monthly_fee=fee, commission_rate=rate,
                           logistics=logistics, note=(note or '').strip()[:255] or None, user_id=user.id if user else None, created_at=now))
    if store.plan != plan or store.plan_started_at is None:
        store.plan_started_at = now
    store.plan, store.monthly_fee, store.commission_rate, store.logistics = plan, fee, rate, logistics
    return True


def set_status(store: Store, status: str) -> None:
    if status not in ACCOUNT_STATUSES:
        raise PlanError('Estado no válido.')
    store.account_status = status


# ---------- quien ve la tienda ----------

def visible_clause():
    """Tiendas que se muestran y reciben pedidos: activas (cuenta) y no ocultadas por el local."""
    return and_(Store.status != StoreStatus.INACTIVA, Store.account_status == 'activo')


def visible_product_clause():
    """Productos de tiendas visibles (para promos, categorias y busquedas)."""
    from ..models import Product
    return Product.store_id.in_(select(Store.id).where(visible_clause()))


def is_visible(store: Store | None) -> bool:
    return bool(store) and store.status != StoreStatus.INACTIVA and store.account_status == 'activo'


# ---------- la plata de cada pedido ----------

def snapshot(order: Order, store: Store) -> None:
    """Copia al pedido las condiciones vigentes del comercio (al crearlo). No se vuelve a llamar despues."""
    order.plan = store.plan
    order.commission_rate = money(store.commission_rate) if store.plan else money(0)
    order.logistics = store.logistics
    settle(order)


def fleet_delivers(order: Order) -> bool:
    """El envio lo hace (o lo hara) la flota de Trappi: entonces el envio lo cobra Trappi y le paga al cadete."""
    if order.delivery_method != 'delivery':
        return False
    if order.courier is not None:
        return order.courier.store_id is None
    return order.logistics == 'trappi'


def breakdown(order: Order) -> dict:
    """Separa los importes del pedido segun sus condiciones guardadas."""
    products = money(order.subtotal) - money(order.discount)
    shipping = money(order.shipping)
    rate = money(order.commission_rate)
    commission = (products * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    fleet = fleet_delivers(order)
    courier_pay = money(order.courier_pay) if order.courier_pay is not None else None
    if fleet:
        logistics_margin = shipping - (courier_pay if courier_pay is not None else shipping)
        store_net = products - commission
    else:
        logistics_margin = Decimal('0')
        store_net = products - commission + shipping  # reparte el comercio: el envio es suyo (y paga a su cadete)
    return {'products': products, 'shipping': shipping, 'total': money(order.total), 'commission_rate': rate, 'commission': commission,
            'courier_pay': courier_pay, 'fleet': fleet, 'store_net': store_net, 'trappi_income': commission + logistics_margin}


def settle(order: Order) -> None:
    """Recalcula comision, neto y el ingreso de Trappi (al crear y cuando cambia el cadete). No hace commit."""
    b = breakdown(order)
    order.platform_commission, order.store_net, order.trappi_income = b['commission'], b['store_net'], b['trappi_income']


# ---------- resumen para los paneles ----------

def sales_summary(db: Session, store_ids: list[int] | None = None, since: datetime | None = None) -> dict[int, dict]:
    """Ventas entregadas, comisiones y neto por comercio."""
    q = select(Order.store_id, func.count(Order.id), func.coalesce(func.sum(Order.total), 0), func.coalesce(func.sum(Order.platform_commission), 0),
               func.coalesce(func.sum(Order.trappi_income), 0), func.coalesce(func.sum(Order.store_net), 0)).where(Order.status == OrderStatus.ENTREGADO)
    if store_ids is not None:
        q = q.where(Order.store_id.in_(store_ids))
    if since is not None:
        q = q.where(Order.created_at >= since)
    out = {}
    for sid, count, total, commission, income, net in db.execute(q.group_by(Order.store_id)).all():
        out[sid] = {'orders': int(count), 'sales': money(total), 'commission': money(commission), 'trappi_income': money(income), 'store_net': money(net)}
    return out


def subscription_summary(db: Session, store_ids: list[int] | None = None) -> dict[int, dict]:
    q = select(SubscriptionPayment.store_id, SubscriptionPayment.status, func.coalesce(func.sum(SubscriptionPayment.amount), 0), func.count(SubscriptionPayment.id))
    if store_ids is not None:
        q = q.where(SubscriptionPayment.store_id.in_(store_ids))
    out: dict[int, dict] = {}
    for sid, status, amount, count in db.execute(q.group_by(SubscriptionPayment.store_id, SubscriptionPayment.status)).all():
        row = out.setdefault(sid, {'paid': money(0), 'pending': money(0), 'pending_count': 0})
        if status == 'pagado':
            row['paid'] = money(amount)
        else:
            row['pending'], row['pending_count'] = money(amount), int(count)
    return out


def valid_period(period: str) -> str:
    period = (period or '').strip()
    try:
        datetime.strptime(period, '%Y-%m')
    except ValueError:
        raise PlanError('El período tiene que ser AAAA-MM (por ejemplo 2026-10).')
    return period
