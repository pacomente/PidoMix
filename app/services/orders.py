"""Flujo de estados de los pedidos: que cambios se permiten y su historial."""
from datetime import datetime

from ..models import Order, OrderEvent, OrderStatus

FLOW = [OrderStatus.PENDIENTE, OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO, OrderStatus.ENTREGADO]
FINAL = (OrderStatus.ENTREGADO, OrderStatus.CANCELADO)
ADVANCE_LABEL = {'CONFIRMADO': 'Confirmar pedido', 'PREPARANDO': 'Empezar a preparar', 'LISTO': 'Marcar listo', 'EN_CAMINO': 'Enviar con repartidor', 'ENTREGADO': 'Marcar entregado'}

# Mensaje sugerido para avisarle al cliente por WhatsApp en cada etapa
CUSTOMER_MESSAGE = {
    'CONFIRMADO': 'Hola {name}, confirmamos tu pedido #{id} en {store}. ¡Ya lo empezamos a preparar!',
    'PREPARANDO': 'Hola {name}, tu pedido #{id} en {store} se está preparando.',
    'LISTO': 'Hola {name}, tu pedido #{id} está listo. ¡Te esperamos en {store}!',
    'LISTO_DELIVERY': 'Hola {name}, tu pedido #{id} de {store} está listo y sale en breve.',
    'EN_CAMINO': 'Hola {name}, tu pedido #{id} de {store} ya está en camino.',
    'ENTREGADO': '¡Gracias por pedir en {store}, {name}! Si querés, calificá tu pedido #{id} desde el seguimiento.',
    'CANCELADO': 'Hola {name}, lamentablemente tuvimos que cancelar tu pedido #{id} en {store}. Escribinos si tenés dudas.',
}


def sequence(order: Order) -> list[OrderStatus]:
    """Etapas del pedido: el retiro en el local no pasa por 'En camino'."""
    return [s for s in FLOW if not (s == OrderStatus.EN_CAMINO and order.delivery_method == 'retiro')]


def advance(order: Order):
    """(estado siguiente, texto del boton) o None si ya no avanza."""
    seq = sequence(order)
    if order.status not in seq or seq.index(order.status) + 1 >= len(seq):
        return None
    nxt = seq[seq.index(order.status) + 1]
    return nxt.value, ADVANCE_LABEL[nxt.value]


def previous(order: Order):
    """Estado anterior, para deshacer un clic equivocado (solo en pedidos activos)."""
    seq = sequence(order)
    if order.status in FINAL or order.status not in seq or seq.index(order.status) == 0:
        return None
    return seq[seq.index(order.status) - 1]


def allowed_statuses(order: Order) -> set[OrderStatus]:
    if order.status in FINAL:
        return set()
    allowed = {OrderStatus.CANCELADO}
    if nxt := advance(order):
        allowed.add(OrderStatus(nxt[0]))
    if prev := previous(order):
        allowed.add(prev)
    return allowed


def record(order: Order, status: OrderStatus, user=None) -> None:
    order.events.append(OrderEvent(status=status.value, user_id=user.id if user else None, created_at=datetime.utcnow()))


def set_status(order: Order, status: OrderStatus, user=None) -> bool:
    """Aplica el cambio si es valido desde el estado actual. Devuelve False si no se permite."""
    if status not in allowed_statuses(order):
        return False
    from . import payments
    if status in (OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO, OrderStatus.ENTREGADO) and payments.awaiting_online(order):
        return False  # pago online sin aprobar: solo se puede cancelar
    order.status = status
    record(order, status, user)
    return True


def minutes_since(dt: datetime | None, now: datetime | None = None) -> int:
    return max(0, int(((now or datetime.utcnow()) - dt).total_seconds() // 60)) if dt else 0


def customer_message(order: Order) -> str | None:
    key = order.status.value
    if key == 'LISTO' and order.delivery_method == 'delivery':
        key = 'LISTO_DELIVERY'
    template = CUSTOMER_MESSAGE.get(key)
    if not template:
        return None
    name = order.customer.first_name.strip().split()[0].capitalize() if order.customer and order.customer.first_name.strip() else ''
    return template.format(name=name, id=order.id, store=order.store.name).replace('Hola ,', 'Hola,').replace(', !', '!')
