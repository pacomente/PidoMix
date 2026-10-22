""""Para hacer hoy" en el inicio del panel del local: lo pendiente, cada cosa con el link para resolverla."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Order, OrderStatus, Product, ProductStatus, Review, Store, StoreHour, StorePushSubscription


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
    order = {'bad': 0, 'warn': 1, 'info': 2}
    return sorted(out, key=lambda t: order[t['tone']])
