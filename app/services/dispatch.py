"""Asignacion de pedidos a repartidores, estilo Uber.

Cuando un pedido de delivery esta confirmado (o en preparacion, o listo) y no tiene repartidor,
se le ofrece a UN repartidor por vez durante unos segundos (configurables): primero los propios del local y
despues los de la flota de Trappi, del mas cercano al mas lejano. Si rechaza o se le vence,
pasa al siguiente. Si ninguno acepta, el pedido queda "sin repartidor" y el local lo puede
asignar a mano desde comandas o el panel (y la oferta sigue para quien se conecte despues).

No hay un proceso aparte: tick() avanza las ofertas y lo llaman el pulso de la app del
repartidor (cada pocos segundos), la pantalla de comandas y cada cambio de estado.
"""
import threading
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import Courier, DeliveryOffer, Order, OrderEvent, OrderStatus
from . import platform, push
from .geo import distance_km
from .orders import record

# Los tiempos y distancias se configuran desde el panel (services/platform.py, seccion Repartidores)


def offer_seconds(db: Session) -> int:
    return platform.get(db, 'dispatch_offer_seconds')


def location_fresh(db: Session) -> timedelta:
    return timedelta(minutes=platform.get(db, 'dispatch_location_minutes'))
DISPATCH_STATUSES = (OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO)
ACTIVE_TRIP_STATUSES = (OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO)

_lock = threading.Lock()  # un solo proceso: evita dos ofertas simultaneas para el mismo pedido


class DispatchError(Exception):
    pass


def needs_courier(order: Order) -> bool:
    return order.delivery_method == 'delivery' and order.status in DISPATCH_STATUSES and order.courier_id is None


def busy_courier_ids(db: Session) -> set[int]:
    rows = db.scalars(select(Order.courier_id).where(Order.courier_id.is_not(None), Order.status.in_(ACTIVE_TRIP_STATUSES)))
    return set(rows)


def available(db: Session, now: datetime | None = None) -> list[Courier]:
    """Repartidores conectados, con ubicacion reciente y sin un viaje en curso."""
    now = now or datetime.utcnow()
    busy = busy_courier_ids(db)
    rows = db.scalars(select(Courier).where(Courier.active.is_(True), Courier.online.is_(True), Courier.location_at >= now - location_fresh(db)))
    return [c for c in rows if c.id not in busy]


def courier_distance(courier: Courier, order: Order) -> float | None:
    store = order.store
    if store.lat is None or courier.lat is None:
        return None
    return distance_km(courier.lat, courier.lng, store.lat, store.lng)


def candidates(db: Session, order: Order, pool: list[Courier], now: datetime | None = None) -> list[Courier]:
    # no se le vuelve a ofrecer a quien lo rechazo o lo libero; a quien se le vencio, recien despues de un rato
    now = now or datetime.utcnow()
    cfg = platform.get_all(db)
    reoffer, radius = timedelta(minutes=cfg['dispatch_reoffer_minutes']), cfg['dispatch_radius_km']
    tried = set(db.scalars(select(DeliveryOffer.courier_id).where(DeliveryOffer.order_id == order.id, (DeliveryOffer.status == 'rejected') | (
        DeliveryOffer.status.in_(('expired', 'pending')) & (DeliveryOffer.created_at > now - reoffer)))))
    out = []
    for c in pool:
        if c.id in tried or (c.store_id is not None and c.store_id != order.store_id):
            continue
        d = courier_distance(c, order)
        if d is not None and d > radius:
            continue
        out.append((0 if c.store_id == order.store_id else 1, d if d is not None else 999, c))
    return [c for *_, c in sorted(out, key=lambda x: (x[0], x[1]))]


def pending_offer(db: Session, order_id: int) -> DeliveryOffer | None:
    return db.scalar(select(DeliveryOffer).where(DeliveryOffer.order_id == order_id, DeliveryOffer.status == 'pending'))


def tick(db: Session, now: datetime | None = None) -> int:
    """Vence ofertas viejas y crea las siguientes. Devuelve cuantas ofertas nuevas creo. Hace commit."""
    now = now or datetime.utcnow()
    with _lock:
        for offer in db.scalars(select(DeliveryOffer).options(joinedload(DeliveryOffer.order)).where(DeliveryOffer.status == 'pending')):
            if offer.expires_at <= now:
                offer.status = 'expired'
            elif not needs_courier(offer.order):  # lo cancelaron o lo asignaron a mano
                offer.status = 'cancelled'
        db.flush()
        cfg = platform.get_all(db)
        seconds = cfg['dispatch_offer_seconds']
        auto = cfg['dispatch_auto'] and cfg['app_repartidor_enabled']  # sin ofertas automaticas los locales asignan a mano
        orders = [] if not auto else db.scalars(select(Order).options(joinedload(Order.store)).where(
            Order.delivery_method == 'delivery', Order.status.in_(DISPATCH_STATUSES), Order.courier_id.is_(None)).order_by(Order.created_at)).all()
        created = 0
        notify = []
        if orders:
            pool = available(db, now)
            offered_now = {o.courier_id for o in db.scalars(select(DeliveryOffer).where(DeliveryOffer.status == 'pending'))}
            for order in orders:
                if pending_offer(db, order.id):
                    continue
                for courier in candidates(db, order, [c for c in pool if c.id not in offered_now], now):
                    db.add(DeliveryOffer(order_id=order.id, courier_id=courier.id, created_at=now, expires_at=now + timedelta(seconds=seconds)))
                    offered_now.add(courier.id)
                    notify.append((courier, order))
                    created += 1
                    break
        db.commit()
    for courier, order in notify:
        push.notify_offer(courier, order, seconds, platform.courier_pay(cfg, order.shipping))
    return created


def offer_for(db: Session, courier: Courier, now: datetime | None = None) -> DeliveryOffer | None:
    now = now or datetime.utcnow()
    return db.scalar(select(DeliveryOffer).options(joinedload(DeliveryOffer.order).joinedload(Order.store)).where(
        DeliveryOffer.courier_id == courier.id, DeliveryOffer.status == 'pending', DeliveryOffer.expires_at > now))


def current_trip(db: Session, courier: Courier) -> Order | None:
    return db.scalar(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(
        Order.courier_id == courier.id, Order.status.in_(ACTIVE_TRIP_STATUSES)).order_by(Order.courier_assigned_at.desc()))


def pay_for(db: Session, order: Order):
    """Lo que gana el repartidor por este pedido con la regla actual (se fija al asignarlo)."""
    return platform.courier_pay(platform.get_all(db), order.shipping)


def _assign(db: Session, order: Order, courier: Courier, now: datetime) -> None:
    order.courier_id, order.courier_assigned_at, order.courier_pay = courier.id, now, pay_for(db, order)
    for other in db.scalars(select(DeliveryOffer).where(DeliveryOffer.order_id == order.id, DeliveryOffer.status == 'pending')):
        other.status = 'cancelled'


def accept(db: Session, courier: Courier, offer_id: int, now: datetime | None = None) -> Order:
    now = now or datetime.utcnow()
    with _lock:
        offer = db.get(DeliveryOffer, offer_id)
        if not offer or offer.courier_id != courier.id or offer.status != 'pending' or offer.expires_at <= now:
            raise DispatchError('Esta oferta ya no está disponible.')
        if current_trip(db, courier):
            raise DispatchError('Primero terminá el viaje que tenés en curso.')
        order = db.get(Order, offer.order_id)
        if not needs_courier(order):
            offer.status = 'cancelled'; db.commit()
            raise DispatchError('Este pedido ya no necesita repartidor.')
        offer.status = 'accepted'
        _assign(db, order, courier, now)
        db.commit()
        return order


def reject(db: Session, courier: Courier, offer_id: int) -> None:
    offer = db.get(DeliveryOffer, offer_id)
    if offer and offer.courier_id == courier.id and offer.status == 'pending':
        offer.status = 'rejected'
        db.commit()


def assign_manual(db: Session, order: Order, courier: Courier, now: datetime | None = None) -> None:
    """El local elige el repartidor. No hace commit."""
    if order.delivery_method != 'delivery' or order.status not in ACTIVE_TRIP_STATUSES:
        raise DispatchError('Este pedido no se puede asignar.')
    if not courier.active or (courier.store_id is not None and courier.store_id != order.store_id):
        raise DispatchError('Ese repartidor no puede llevar pedidos de este local.')
    if courier.id in busy_courier_ids(db) and order.courier_id != courier.id:
        raise DispatchError(f'{courier.name} ya está haciendo otro viaje.')
    _assign(db, order, courier, now or datetime.utcnow())


def unassign(db: Session, order: Order, by_courier: bool = False, now: datetime | None = None) -> None:
    """Saca al repartidor (lo libera el local o el repartidor no puede). Vuelve a ofrecerse. No hace commit."""
    if order.status == OrderStatus.EN_CAMINO:
        raise DispatchError('El pedido ya salió con el repartidor.')
    now = now or datetime.utcnow()
    if by_courier and order.courier_id:  # a el no se le vuelve a ofrecer este pedido
        db.add(DeliveryOffer(order_id=order.id, courier_id=order.courier_id, status='rejected', created_at=now, expires_at=now))
    order.courier_id = order.courier_assigned_at = order.courier_pay = None


def pickup(db: Session, courier: Courier, order: Order) -> None:
    """El repartidor retiró el pedido del local: pasa a "En camino". No hace commit."""
    if order.courier_id != courier.id or order.status not in DISPATCH_STATUSES:
        raise DispatchError('Este pedido no está para retirar.')
    order.status = OrderStatus.EN_CAMINO
    record(order, OrderStatus.EN_CAMINO)


def deliver(db: Session, courier: Courier, order: Order) -> None:
    if order.courier_id != courier.id or order.status != OrderStatus.EN_CAMINO:
        raise DispatchError('Primero marcá que retiraste el pedido.')
    order.status = OrderStatus.ENTREGADO
    record(order, OrderStatus.ENTREGADO)


def earnings(db: Session, courier: Courier, since: datetime) -> tuple[Decimal, int]:
    """Lo que gano el repartidor (lo fijado al asignarle cada pedido entregado) desde una fecha."""
    total, count = db.execute(select(func.coalesce(func.sum(func.coalesce(Order.courier_pay, Order.shipping)), 0), func.count(Order.id))
                              .join(OrderEvent, (OrderEvent.order_id == Order.id) & (OrderEvent.status == OrderStatus.ENTREGADO.value))
                              .where(Order.courier_id == courier.id, Order.status == OrderStatus.ENTREGADO, OrderEvent.created_at >= since)).one()
    return Decimal(total or 0), int(count or 0)
