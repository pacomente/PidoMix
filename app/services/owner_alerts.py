"""Avisos al dueño del local: pedido nuevo, pedido sin aceptar a los 3 minutos y resumen del dia.

Van como notificacion web al celular o la PC donde el dueño toco "Avisarme" en comandas (gratis) y, si Trappi
conecta la API de WhatsApp Cloud (WHATSAPP_CLOUD_TOKEN y las plantillas), tambien por WhatsApp al numero del local.
Corre en un hilo de fondo cada 20 s; cada aviso se "reserva" con un UPDATE condicional, asi no sale dos veces
aunque haya varios procesos.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..db import SessionLocal
from ..models import Order, OrderItem, OrderStatus, Store, StorePushSubscription, StoreStatus
from . import webpush
from .formatting import money
from .store_hours import to_local

logger = logging.getLogger(__name__)

LATE_AFTER = timedelta(minutes=3)
LOOK_BACK = timedelta(minutes=45)  # pedidos mas viejos no se avisan (por ejemplo al prender esto por primera vez)
SUMMARY_HOUR = 23  # a partir de las 23 (hora local) sale el resumen del dia
EVERY = 20
MAX_SUBSCRIPTIONS = 10
_last = {'at': 0.0}
_lock = threading.Lock()


def whatsapp_enabled() -> bool:
    return bool(settings.whatsapp_cloud_token and settings.whatsapp_cloud_phone_id)


def _visible():
    """Pedidos que el local ya ve en comandas: los de Mercado Pago recien cuando el pago esta aprobado."""
    return or_(Order.payment_status.is_(None), Order.payment_status != 'pending')


def _claim(db: Session, order_id: int, column) -> bool:
    res = db.execute(update(Order).where(Order.id == order_id, column.is_(None)).values({column.key: datetime.utcnow()}))
    db.commit()
    return res.rowcount == 1


def push_store(db: Session, store_id: int, data: dict) -> int:
    """Manda la notificacion a todos los dispositivos del local. Borra los que el navegador dio de baja."""
    sent, gone = 0, []
    for sub in db.scalars(select(StorePushSubscription).where(StorePushSubscription.store_id == store_id)).all():
        result = webpush.send(db, sub, data)
        if result == 'ok':
            sub.last_ok_at, sent = datetime.utcnow(), sent + 1
        elif result == 'gone':
            gone.append(sub.id)
    if gone:
        db.execute(delete(StorePushSubscription).where(StorePushSubscription.id.in_(gone)))
    db.commit()
    return sent


def push_store_later(store_id: int, data: dict) -> None:
    """Igual que push_store pero en un hilo aparte (para no hacer esperar al que toco el boton)."""
    def run():
        try:
            with SessionLocal() as db:
                push_store(db, store_id, data)
        except Exception:
            logger.exception('aviso al local')
    threading.Thread(target=run, daemon=True).start()


def bad_review(store_id: int, order_id: int, rating: int) -> None:
    """Reseña de 1 o 2 estrellas: aviso al celular del dueño para que la responda rápido."""
    if rating <= 2:
        push_store_later(store_id, {'title': f'⚠️ Reseña de {rating} estrella{"s" if rating > 1 else ""}', 'tag': f'review-{order_id}',
                                    'body': f'El pedido #{order_id} recibió una calificación baja. Respondé rápido: los clientes lo ven.',
                                    'url': '/admin/reviews?filter=negativas'})


def whatsapp_template(to: str | None, template: str, params: list[str]) -> bool:
    """Plantilla aprobada de WhatsApp Cloud API al numero del local. Sin configuracion no hace nada."""
    number = ''.join(ch for ch in to or '' if ch.isdigit())
    if not whatsapp_enabled() or not template or len(number) < 10:
        return False
    if not number.startswith('54'):
        number = '549' + number.lstrip('0')
    try:
        r = httpx.post(f'https://graph.facebook.com/v21.0/{settings.whatsapp_cloud_phone_id}/messages', timeout=10,
                       headers={'Authorization': f'Bearer {settings.whatsapp_cloud_token}'},
                       json={'messaging_product': 'whatsapp', 'to': number, 'type': 'template',
                             'template': {'name': template, 'language': {'code': settings.whatsapp_cloud_lang or 'es_AR'},
                                          'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': p[:200]} for p in params]}]}})
    except httpx.HTTPError as exc:
        logger.warning('whatsapp cloud: %s', exc)
        return False
    if r.status_code >= 400:
        logger.warning('whatsapp cloud %s: %s', r.status_code, r.text[:300])
        return False
    return True


def _when(o: Order) -> str:
    return f' · programado para las {to_local(o.scheduled_for).strftime("%H:%M")}' if o.scheduled_for else ''


def new_order(db: Session, o: Order) -> None:
    store = o.store
    if not store.alert_new_order:
        return
    by_wa = o.origin == 'whatsapp'
    if by_wa:
        from . import wa_agent
        if not wa_agent.alerts(store)['order']:
            return
    text = f'#{o.id} · {money(o.total)} · {"Delivery" if o.delivery_method == "delivery" else "Retira en el local"}{_when(o)}'
    title = (f'📅 Pedido programado por WhatsApp en {store.name}' if o.scheduled_for else f'💬 Pedido nuevo por WhatsApp en {store.name}') if by_wa \
        else f'🛎 Pedido nuevo en {store.name}'
    push_store(db, store.id, {'title': title, 'body': text + '. Tocá para aceptarlo.', 'tag': f'order-{o.id}',
                              'url': '/admin/comandas', 'urgent': True})
    whatsapp_template(store.whatsapp, settings.whatsapp_template_new_order, [store.name, f'#{o.id}', money(o.total)])


def late_order(db: Session, o: Order, minutes: int) -> None:
    store = o.store
    if not store.alert_late:
        return
    push_store(db, store.id, {'title': f'⏰ Pedido #{o.id} sin aceptar', 'body': f'Hace {minutes} min que espera. El cliente está esperando tu respuesta.',
                              'tag': f'order-{o.id}', 'url': '/admin/comandas', 'urgent': True})
    whatsapp_template(store.whatsapp, settings.whatsapp_template_late_order, [store.name, f'#{o.id}', str(minutes)])


def day_summary(db: Session, store: Store, start_utc: datetime, end_utc: datetime) -> dict:
    """Pedidos, entregados, ventas y cancelados del dia; el mas vendido y la comparacion con el mismo dia de la semana pasada."""
    def totals(a, b):
        rows = db.execute(select(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(
            Order.store_id == store.id, Order.created_at >= a, Order.created_at < b).group_by(Order.status)).all()
        by = {status: (count, total) for status, count, total in rows}
        delivered = by.get(OrderStatus.ENTREGADO, (0, 0))
        return {'orders': sum(c for c, _ in by.values()), 'delivered': delivered[0], 'sales': delivered[1],
                'cancelled': by.get(OrderStatus.CANCELADO, (0, 0))[0]}
    out = totals(start_utc, end_utc)
    week = totals(start_utc - timedelta(days=7), end_utc - timedelta(days=7))
    out['last_week_sales'] = week['sales']
    out['vs_last_week'] = round((float(out['sales']) - float(week['sales'])) / float(week['sales']) * 100) if week['sales'] else None
    top = db.execute(select(OrderItem.product_name, func.sum(OrderItem.quantity).label('q')).join(Order, Order.id == OrderItem.order_id).where(
        Order.store_id == store.id, Order.status == OrderStatus.ENTREGADO, Order.created_at >= start_utc, Order.created_at < end_utc)
        .group_by(OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(1)).first()
    out['top'] = (top[0], int(top[1])) if top else None
    return out


def summary_text(s: dict) -> str:
    parts = [f'{s["delivered"]} entregados · ventas {money(s["sales"])}']
    if s['vs_last_week'] is not None:
        parts.append(f'{"▲" if s["vs_last_week"] >= 0 else "▼"} {abs(s["vs_last_week"])}% vs. el mismo día de la semana pasada')
    if s['top']:
        parts.append(f'Lo más pedido: {s["top"][0]} ({s["top"][1]})')
    if s['cancelled']:
        parts.append(f'{s["cancelled"]} cancelado{"s" if s["cancelled"] > 1 else ""}')
    return ' · '.join(parts)


def _summaries(db: Session, now_local: datetime) -> None:
    if now_local.hour < SUMMARY_HOUR:
        return
    today = now_local.date()
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = start_utc + timedelta(days=1)
    where = [Store.alert_summary.is_(True), or_(Store.summary_sent_on.is_(None), Store.summary_sent_on < today)]
    if not whatsapp_enabled():  # sin WhatsApp: solo los locales que activaron la notificacion en algun dispositivo
        where.append(Store.id.in_(select(StorePushSubscription.store_id)))
    ids = db.scalars(select(Store.id).where(*where)).all()
    for sid in ids:
        res = db.execute(update(Store).where(Store.id == sid, or_(Store.summary_sent_on.is_(None), Store.summary_sent_on < today)).values(summary_sent_on=today))
        db.commit()
        if res.rowcount != 1:
            continue
        store = db.get(Store, sid)
        s = day_summary(db, store, start_utc, end_utc)
        if not s['orders']:
            continue
        body = summary_text(s)
        if store.wa_enabled:
            from . import wa_agent
            if wa_agent.alerts(store)['summary']:
                w = wa_agent.day_counts(db, sid, start_utc, end_utc)
                if w['chats']:
                    body += f' · WhatsApp: {w["chats"]} chats, {w["orders"]} pedidos ({money(w["sales"])})'
        push_store(db, sid, {'title': f'📊 Tu día en Trappi: {s["orders"]} pedidos', 'body': body, 'tag': f'summary-{today}', 'url': '/admin'})
        whatsapp_template(store.whatsapp, settings.whatsapp_template_summary, [store.name, today.strftime('%d/%m'), str(s['orders']), money(s['sales'])])


UNATTENDED_AFTER = timedelta(minutes=20)


def _unattended(db: Session, now: datetime) -> None:
    """El local figura abierto pero hace rato nadie mira los pedidos (comandas o el panel): un aviso por dia."""
    from .store_hours import is_open
    today = to_local(now).date()
    rows = db.scalars(select(Store).where(Store.status == StoreStatus.ACTIVA, Store.panel_seen_at.is_not(None), Store.panel_seen_at < now - UNATTENDED_AFTER,
                                          or_(Store.unattended_warned_on.is_(None), Store.unattended_warned_on < today),
                                          Store.id.in_(select(StorePushSubscription.store_id)))).all()
    for store in rows:
        if not is_open(store):
            continue
        res = db.execute(update(Store).where(Store.id == store.id, or_(Store.unattended_warned_on.is_(None), Store.unattended_warned_on < today))
                         .values(unattended_warned_on=today))
        db.commit()
        if res.rowcount == 1:
            push_store(db, store.id, {'title': f'👀 {store.name} figura abierto', 'tag': 'unattended', 'url': '/admin/comandas', 'urgent': True,
                                      'body': 'Hace un rato que nadie mira los pedidos. Abrí comandas para no perder ventas, o pausá el local si no estás atendiendo.'})


def tick(db: Session, now: datetime | None = None, force: bool = False) -> None:
    """Revisa que avisos corresponden. Liviano: se puede llamar seguido (se limita a uno cada EVERY segundos)."""
    with _lock:
        if not force and time.monotonic() - _last['at'] < EVERY:
            return
        _last['at'] = time.monotonic()
    now = now or datetime.utcnow()
    base = (Order.status == OrderStatus.PENDIENTE, Order.created_at >= now - LOOK_BACK, _visible())
    for o in db.scalars(select(Order).options(joinedload(Order.store)).where(*base, Order.store_notified_at.is_(None))).all():
        if _claim(db, o.id, Order.store_notified_at):
            new_order(db, o)
    for o in db.scalars(select(Order).options(joinedload(Order.store)).where(
            *base, Order.store_alerted_at.is_(None), Order.created_at <= now - LATE_AFTER)).all():
        if _claim(db, o.id, Order.store_alerted_at):
            late_order(db, o, max(3, int((now - o.created_at).total_seconds() // 60)))
    _summaries(db, to_local(now))
    from . import weekly_report
    weekly_report.run(db, to_local(now))  # los lunes: resumen de la semana por mail al dueño
    from . import wa_agent
    wa_agent.bill(db, now)  # mensajes de WhatsApp de los dias que terminaron: a la liquidacion de cada local
    _unattended(db, now)
    from .stock import restock_due
    restock_due(db, now)  # "agotado hasta mañana" que ya tiene que volver


def background_dispatch() -> None:
    """Hace avanzar las ofertas a repartidores y conductores aunque nadie tenga abierta una app o comandas."""
    from . import dispatch, rides
    for run in (dispatch.tick, rides.tick):
        try:
            with SessionLocal() as db:
                run(db)
        except Exception:
            logger.exception('despacho en segundo plano')


def _loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                tick(db, force=True)
            background_dispatch()
        except Exception:  # un error no frena los avisos siguientes
            logger.exception('avisos al dueño')
        time.sleep(EVERY)


_started = {'on': False}


def start() -> None:
    if settings.owner_alerts_enabled and not _started['on']:
        _started['on'] = True
        threading.Thread(target=_loop, name='owner-alerts', daemon=True).start()
