"""Avisos del pedido al navegador del cliente (web instalada o no): "confirmado", "listo", "en camino", "entregado".

Gratis (notificaciones web con las mismas claves VAPID de Comandas). Se guardan por pedido, asi sirve sin cuenta,
y se borran cuando el pedido termina. Salen despues de guardar el cambio de estado (si no se guarda, no salen).
"""
import logging
import threading

from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Order, OrderPushSubscription, OrderStatus
from . import webpush

log = logging.getLogger(__name__)
MAX_PER_ORDER = 3
SYNC = False  # las pruebas lo prenden: todo en el mismo hilo
TEXT = {
    'CONFIRMADO': ('✅ {store} confirmó tu pedido', 'Pedido #{id}. Ya lo empiezan a preparar.'),
    'LISTO': ('🛍 Tu pedido está listo', 'Pedido #{id}: ya lo podés retirar en {store}.'),
    'LISTO_DELIVERY': ('🛍 Tu pedido está listo', 'Pedido #{id}: sale en breve.'),
    'EN_CAMINO': ('🛵 Tu pedido está en camino', 'Pedido #{id} de {store}.'),
    'ENTREGADO': ('🙌 ¡Pedido entregado!', 'Gracias por pedir en {store}. Contanos cómo estuvo.'),
    'CANCELADO': ('Tu pedido se canceló', 'Pedido #{id} de {store}. Tocá para ver el detalle.'),
}
FINAL = ('ENTREGADO', 'CANCELADO')


def subscribe(db: Session, order: Order, endpoint: str, p256dh: str, auth: str) -> None:
    row = db.scalar(select(OrderPushSubscription).where(OrderPushSubscription.order_id == order.id, OrderPushSubscription.endpoint == endpoint))
    if row is None:
        count = len(db.scalars(select(OrderPushSubscription.id).where(OrderPushSubscription.order_id == order.id)).all())
        if count >= MAX_PER_ORDER:
            raise ValueError('Ya hay avisos activados en otros dispositivos para este pedido.')
        row = OrderPushSubscription(order_id=order.id, endpoint=endpoint)
        db.add(row)
    row.p256dh, row.auth = p256dh, auth
    db.flush()


def queue(session: Session, order: Order, status: OrderStatus) -> None:
    if status.value not in TEXT or order.id is None:  # un pedido recien creado todavia no tiene avisos
        return
    pending = session.info.setdefault('client_push', [])
    if not pending:
        event.listen(session, 'after_commit', _flush, once=True)
        event.listen(session, 'after_rollback', lambda s: s.info.pop('client_push', None), once=True)
    pending.append((order.id, status.value))


def _flush(session: Session) -> None:
    items = session.info.pop('client_push', [])

    def run():
        for oid, status in items:
            try:
                with SessionLocal() as db:
                    send(db, oid, status)
            except Exception:
                log.exception('aviso al cliente')
    if items:
        if SYNC:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()


def send(db: Session, order_id: int, status: str) -> int:
    from ..routers.public import order_token
    o = db.get(Order, order_id)
    subs = db.scalars(select(OrderPushSubscription).where(OrderPushSubscription.order_id == order_id)).all() if o else []
    if not subs or o.status.value != status:
        return 0  # sin avisos activados, o ya cambio otra vez
    key = 'LISTO_DELIVERY' if status == 'LISTO' and o.delivery_method == 'delivery' else status
    title, body = TEXT[key]
    data = {'title': title.format(store=o.store.name, id=o.id), 'body': body.format(store=o.store.name, id=o.id), 'tag': f'pedido-{o.id}',
            'url': f'/pedido/{o.id}?t={order_token(o.id)}'}
    sent, gone = 0, []
    for sub in subs:
        result = webpush.send(db, sub, data)
        sent += result == 'ok'
        if result == 'gone':
            gone.append(sub.id)
    if status in FINAL:
        db.execute(delete(OrderPushSubscription).where(OrderPushSubscription.order_id == order_id))
    elif gone:
        db.execute(delete(OrderPushSubscription).where(OrderPushSubscription.id.in_(gone)))
    db.commit()
    return sent
