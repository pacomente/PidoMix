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
# quien entrega lo define el plan: Trappi Delivery es la flota (por eso cobra comision);
# Trappi Comercio usa sus cadetes y, si Trappi se lo habilita, la flota de respaldo
PLAN_LOGISTICS = {COMERCIO: ('propia', 'mixta'), DELIVERY: ('trappi',)}
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


def defaults(db: Session, plan: str, city_id: int | None = None) -> dict:
    """Condiciones que se proponen para un plan (las de la configuracion comercial, o las de la ciudad)."""
    if plan not in PLANS:
        raise PlanError('Elegí un plan válido.')
    cfg = platform.for_city(db, city_id)
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
    if logistics not in PLAN_LOGISTICS[plan]:
        raise PlanError('Con Trappi Delivery entrega siempre la flota de Trappi.' if plan == DELIVERY else
                        'Con Trappi Comercio entregan los cadetes del comercio (o "propios y flota" como respaldo).')
    return fee, rate, logistics


def logistics_options(plan: str | None) -> tuple[str, ...]:
    """Logisticas posibles para un plan (los comercios sin plan: cualquiera)."""
    return PLAN_LOGISTICS.get(plan, tuple(LOGISTICS))


def fleet_allowed(store: Store) -> bool:
    """Puede usar la flota de Trappi: incluida en Trappi Delivery, o habilitada por Trappi como respaldo."""
    return store.plan == DELIVERY or bool(store.fleet_enabled)


FLEET_LABELS = {
    'trappi': ('Envío Trappi', 'Lo lleva un repartidor de Trappi.'),
    'store': ('Envío del local', 'Lo lleva un repartidor del comercio.'),
    'mixed': ('Envío del local o Trappi', 'Lo lleva un repartidor del comercio o, si no hay, uno de Trappi.'),
}


def fleet_kind(store) -> str | None:
    """Quien reparte, para mostrarle al cliente: trappi (flota de Trappi), store (cadetes propios) o mixed.
    Sin envio a domicilio: None. Los comercios sin logistica definida reparten con sus cadetes."""
    if not store.delivery_enabled:
        return None
    return {'trappi': 'trappi', 'mixta': 'mixed'}.get(store.logistics, 'store')


def accepts_transfer(store) -> bool:
    """Transferencia al alias del local: solo si cobra el comercio (Trappi Comercio, o los sin plan de antes).
    En Trappi Delivery la plata la maneja Trappi: efectivo con la flota o Mercado Pago."""
    return getattr(store, 'plan', None) != DELIVERY


def fleet_security(order) -> bool:
    """Codigo de retiro, pago del cadete al local y "no se pudo entregar": solo pedidos de Trappi Delivery
    (el plan guardado en el pedido al crearlo)."""
    return order.plan == DELIVERY and order.delivery_method == 'delivery'


def delivery_choices(store: Store) -> tuple[str, ...]:
    """Lo que el comercio puede elegir solo en "Pagos y liquidaciones". Vacio: lo fija el plan."""
    if store.plan == DELIVERY:
        return ()
    return ('propia', 'mixta') if store.fleet_enabled else ()


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
    if store.plan != plan or logistics in ('mixta', 'trappi'):
        # la flota viene con Trappi Delivery o con "propios y flota"; al pasar a cadetes propios se apaga
        store.fleet_enabled = logistics in ('mixta', 'trappi')
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

def commission_terms(db: Session | None, store: Store) -> dict:
    """Como se calcula la comision de este comercio hoy: % + fijo, con minimo y maximo (0 = sin tope).
    Lo del comercio (si se cargo) gana sobre lo del plan. Sin plan: sin comision (como siempre)."""
    if not store.plan:
        return {'rate': '0.00', 'fixed': '0.00', 'min': '0.00', 'max': '0.00', 'source': 'sin plan'}
    cfg = platform.for_city(db, store.city_id) if db is not None else platform.current()
    key = 'comercio' if store.plan == COMERCIO else 'delivery'
    plan_rate = cfg['plan_comercio_commission'] if store.plan == COMERCIO else cfg['plan_delivery_commission']
    pick = lambda own, default: money(own) if own is not None else money(default)  # noqa: E731
    return {'rate': str(pick(store.commission_rate, plan_rate)), 'fixed': str(pick(store.commission_fixed, cfg[f'commission_{key}_fixed'])),
            'min': str(pick(store.commission_min, cfg[f'commission_{key}_min'])), 'max': str(pick(store.commission_max, cfg[f'commission_{key}_max'])),
            'source': 'comercio' if any(v is not None for v in (store.commission_fixed, store.commission_min, store.commission_max)) else 'plan'}


def commission_amount(products: Decimal, terms: dict) -> Decimal:
    if products <= 0:
        return Decimal('0.00')
    value = (products * money(terms['rate']) / 100 + money(terms['fixed'])).quantize(CENT, rounding=ROUND_HALF_UP)
    if money(terms['min']) > 0:
        value = max(value, money(terms['min']))
    if money(terms['max']) > 0:
        value = min(value, money(terms['max']))
    return min(value, products)


def read_snapshot(order: Order) -> dict:
    import json
    try:
        return json.loads(order.pricing_snapshot or '{}') or {}
    except ValueError:
        return {}


def snapshot(order: Order, store: Store, db: Session | None = None, quote=None) -> None:
    """Copia al pedido las condiciones vigentes (al crearlo): plan, comision, logistica y el calculo del envio.
    No se vuelve a llamar despues: cambiar tarifas o comisiones no toca pedidos ya hechos."""
    import json
    order.plan = store.plan
    order.city_id = store.city_id
    terms = commission_terms(db, store)
    order.commission_rate = money(terms['rate'])
    order.logistics = store.logistics
    data = {'commission': terms, 'taken_at': datetime.utcnow().isoformat() + 'Z'}
    if order.delivery_method == 'delivery' and quote is not None:
        order.delivery_mode = quote.mode
        order.zone_id, order.zone_name = quote.zone_id, quote.zone_name
        order.route_km, order.route_minutes, order.route_source = quote.route_km, quote.minutes, quote.route_source
        order.delivery_fee = quote.fee_real if quote.fee_real is not None else money(order.shipping)
        order.delivery_fee_customer = money(order.shipping)
        order.delivery_fee_merchant = quote.fee_merchant if quote.fee_merchant is not None else Decimal('0.00')
        order.delivery_fee_trappi = quote.fee_trappi if quote.fee_trappi is not None else Decimal('0.00')
        data['delivery'] = quote.snapshot
        if quote.mode == 'trappi':
            from . import logistics
            cfg = platform.for_city(db, store.city_id) if db is not None else platform.current()
            payout, detail = logistics.courier_payout(cfg, order.delivery_fee, order.route_km)
            data['payout_estimate'] = detail
            data['operating'] = {'per_km': str(cfg['operating_cost_per_km']), 'min': str(cfg['operating_cost_min'])}
            order.operating_cost = logistics.operating_cost(cfg, order.route_km)
    elif order.delivery_method != 'delivery':
        order.delivery_mode = 'pickup'
    order.pricing_snapshot = json.dumps(data, ensure_ascii=False, default=str)
    settle(order)


def fleet_delivers(order: Order) -> bool:
    """El envio lo hace (o lo hara) la flota de Trappi: entonces el envio lo cobra Trappi y le paga al cadete."""
    if order.delivery_method != 'delivery':
        return False
    if order.courier is not None:
        return order.courier.store_id is None
    if order.delivery_mode:
        return order.delivery_mode == 'trappi'
    return order.logistics == 'trappi'


def breakdown(order: Order) -> dict:
    """Separa los importes del pedido segun sus condiciones guardadas (nunca con las tarifas de hoy).

    products        lo vendido (sin envio, con el descuento)
    shipping        lo que pago el cliente por el envio
    delivery_fee    costo real del envio (cliente + comercio + Trappi)
    commission      comision de Trappi (con la regla guardada en el pedido)
    merchant_amount lo que le corresponde al comercio
    trappi_amount   lo que le corresponde a Trappi (comision + envio si reparte la flota) = fee del Split
    logistics_margin envio cobrado - pago al cadete - costo operativo (si reparte la flota)
    trappi_income   ganancia de Trappi: comision + margen logistico - su mitad de los puntos
    points          descuento por puntos Trappi: lo reparten Trappi (points_trappi) y el comercio (points_store), con el % guardado en el pedido
    """
    snap = read_snapshot(order)
    products = money(order.subtotal) - money(order.discount)
    shipping = money(order.shipping)
    terms = snap.get('commission') or {'rate': str(money(order.commission_rate)), 'fixed': '0', 'min': '0', 'max': '0'}
    commission = commission_amount(products, terms)
    fleet = fleet_delivers(order)
    merchant_fee = money(order.delivery_fee_merchant)
    trappi_fee = money(order.delivery_fee_trappi)
    delivery_fee = money(order.delivery_fee) if order.delivery_fee is not None else shipping
    courier_pay = money(order.courier_pay) if order.courier_pay is not None else None
    operating = money(order.operating_cost)
    points = money(order.points_discount)
    share = Decimal(str((snap.get('points') or {}).get('trappi_percent', 50)))  # lo que pone Trappi (guardado al hacer el pedido)
    points_trappi = (points * share / 100).quantize(Decimal('0.01'))
    points_store = points - points_trappi
    if fleet:
        # hasta que se asigne el cadete, lo que se estimo al crear el pedido (o el envio entero, en pedidos viejos)
        expected_pay = courier_pay if courier_pay is not None else money((snap.get('payout_estimate') or {}).get('total', delivery_fee))
        collected = shipping + merchant_fee
        logistics_margin = collected - expected_pay - operating
        merchant_amount = products - commission - merchant_fee - points_store
        trappi_amount = commission + collected - points_trappi
    else:
        expected_pay = courier_pay
        logistics_margin = Decimal('0.00')
        merchant_amount = products - commission + shipping - points_store  # reparte el comercio: el envio es suyo (y paga a su cadete)
        trappi_amount = commission - points_trappi
    return {'products': products, 'shipping': shipping, 'total': money(order.total), 'commission_rate': money(terms['rate']), 'commission_terms': terms,
            'commission': commission, 'delivery_fee': delivery_fee, 'fee_customer': shipping, 'fee_merchant': merchant_fee, 'fee_trappi': trappi_fee,
            'courier_pay': courier_pay, 'expected_courier_pay': expected_pay, 'operating_cost': operating, 'fleet': fleet,
            'logistics_margin': logistics_margin, 'merchant_amount': merchant_amount, 'store_net': merchant_amount, 'trappi_amount': trappi_amount,
            'trappi_income': commission + logistics_margin - points_trappi, 'processing_fee': money(order.payment_processing_fee),
            'points': points, 'points_trappi': points_trappi, 'points_store': points_store, 'points_trappi_percent': share}


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
