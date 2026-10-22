""""Para hacer hoy" en el inicio del panel del local: lo pendiente, cada cosa con el link para resolverla."""
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Order, OrderStatus, Product, ProductStatus, Review, Store, StoreHour, StorePushSubscription


MIN_SAMPLES = 8  # pedidos para que la medicion valga
GAP = 10  # minutos de diferencia a partir de los cuales se sugiere ajustar


def real_prep(db: Session, store: Store, days: int = 30, now: datetime | None = None) -> dict | None:
    """Cuanto tarda de verdad el local en preparar (de aceptado a listo), con los pedidos entregados de los ultimos dias.
    {'real': 42, 'shown': 30, 'suggested': 45, 'samples': 20} o None si no hay pedidos suficientes."""
    now = now or datetime.utcnow()
    rows = db.scalars(select(Order).options(selectinload(Order.events)).where(
        Order.store_id == store.id, Order.status == OrderStatus.ENTREGADO, Order.created_at >= now - timedelta(days=days),
        Order.scheduled_for.is_(None)).order_by(Order.created_at.desc()).limit(300)).all()
    mins = []
    for o in rows:
        a, b = o.status_time(OrderStatus.CONFIRMADO), o.status_time(OrderStatus.LISTO)
        if a and b and b > a:
            m = (b - a).total_seconds() / 60
            if m <= 240:  # descarta los que quedaron olvidados en el tablero
                mins.append(m)
    if len(mins) < MIN_SAMPLES:
        return None
    real = round(median(mins))
    return {'real': real, 'shown': store.estimated_minutes, 'suggested': max(5, int(round(real / 5.0)) * 5), 'samples': len(mins)}


def for_store(db: Session, store: Store) -> list[dict]:
    """[{'tone': 'bad'|'warn'|'info', 'text': ..., 'href': ..., 'cta': ...}] de lo mas urgente a lo menos."""
    out = []
    sid = store.id
    waiting_pay = db.scalar(select(func.count(Order.id)).where(Order.store_id == sid, Order.status == OrderStatus.PENDIENTE,
                                                               Order.payment_status == 'pending')) or 0
    if waiting_pay:
        out.append({'tone': 'info', 'text': f'{waiting_pay} {"pedido espera" if waiting_pay == 1 else "pedidos esperan"} que Mercado Pago apruebe el pago',
                    'href': '/admin/orders', 'cta': 'Ver pedidos'})
    bad = db.scalar(select(func.count(Review.id)).where(Review.store_id == sid, Review.reply.is_(None), Review.hidden.is_(False), Review.rating <= 2)) or 0
    unanswered = db.scalar(select(func.count(Review.id)).where(Review.store_id == sid, Review.reply.is_(None), Review.hidden.is_(False))) or 0
    if unanswered:
        out.append({'tone': 'bad' if bad else 'warn', 'href': '/admin/reviews?filter=sin_respuesta', 'cta': 'Responder',
                    'text': f'{unanswered} {"reseña sin responder" if unanswered == 1 else "reseñas sin responder"}' + (f' ({bad} con 1 o 2 estrellas)' if bad else '')})
    active = (Product.store_id == sid, Product.deleted.is_(False), Product.status == ProductStatus.ACTIVO)
    out_of_stock = db.scalar(select(func.count(Product.id)).where(*active, Product.stock.is_not(None), Product.stock <= 0)) or 0
    if out_of_stock:
        out.append({'tone': 'warn', 'text': f'{out_of_stock} {"producto agotado" if out_of_stock == 1 else "productos agotados"}: los clientes no los pueden pedir',
                    'href': '/admin/products', 'cta': 'Revisar'})
    no_photo = db.scalar(select(func.count(Product.id)).where(*active, Product.image_url.is_(None))) or 0
    if no_photo:
        out.append({'tone': 'info', 'text': f'{no_photo} {"producto sin foto" if no_photo == 1 else "productos sin foto"}: con foto se venden más',
                    'href': '/admin/products', 'cta': 'Agregar fotos'})
    if not db.scalar(select(func.count(StoreHour.id)).where(StoreHour.store_id == sid)):
        out.append({'tone': 'warn', 'text': 'Cargá tus horarios: así el cliente sabe cuándo abrís y puede programar pedidos',
                    'href': '/admin/stores#horarios', 'cta': 'Cargar horarios'})
    if store.delivery_enabled and (store.lat is None or store.lng is None):
        out.append({'tone': 'warn', 'text': 'Marcá la ubicación del local en el mapa para calcular bien el envío', 'href': '/admin/stores', 'cta': 'Marcar'})
    if not db.scalar(select(func.count(StorePushSubscription.id)).where(StorePushSubscription.store_id == sid)):
        out.append({'tone': 'info', 'text': 'Activá los avisos al celular: te llega cada pedido nuevo aunque comandas esté cerrada',
                    'href': '/admin/comandas', 'cta': 'Activar'})
    prep = real_prep(db, store)
    if prep and abs(prep['real'] - prep['shown']) >= GAP:
        slower = prep['real'] > prep['shown']
        out.append({'tone': 'warn' if slower else 'info', 'post': f'/admin/stores/{sid}/demora-real', 'cta': f'Mostrar {prep["suggested"]} min',
                    'text': (f'Tardás en promedio {prep["real"]} min en preparar y los clientes ven {prep["shown"]}: ' +
                             ('ajustalo para que no se quejen por la demora' if slower else 'sos más rápido de lo que mostrás, aprovechalo')
                             + f' (medido en {prep["samples"]} pedidos)')})
    order = {'bad': 0, 'warn': 1, 'info': 2}
    return sorted(out, key=lambda t: order[t['tone']])
