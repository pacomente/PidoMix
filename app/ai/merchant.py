"""IA para comercios: recomendaciones para cada local, calculadas con SUS datos, y textos escritos con IA.

Se prende en Configuración → IA para comercios (merchant_ai_enabled). Reglas:
  - Solo usa datos del propio local (nunca de otros comercios ni de clientes puntuales).
  - Sugiere; no cambia nada solo. Lo único que guarda es una descripción cuando el local lo pide.
  - Los textos con IA no inventan precios, promociones ni ingredientes que no estén en el nombre o la descripción.
"""
import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Coupon, Order, OrderEvent, OrderItem, OrderStatus, Product, ProductStatus, Review, Store
from ..services import platform
from ..services.formatting import money
from ..services.store_hours import to_local

log = logging.getLogger('pidomix.ai.merchant')
DAYS = 30
WEEKDAYS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábados', 'domingos')


def enabled(db: Session) -> bool:
    return bool(platform.get_all(db).get('merchant_ai_enabled'))


def _tip(kind: str, icon: str, title: str, text: str, url: str | None = None, label: str | None = None, items=None) -> dict:
    return {'kind': kind, 'icon': icon, 'title': title, 'text': text, 'url': url, 'label': label, 'items': items or []}


def insights(db: Session, store: Store, now: datetime | None = None) -> dict:
    """Números del local y la lista de recomendaciones, de la más útil a la menos."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=DAYS)
    products = db.scalars(select(Product).where(Product.store_id == store.id, Product.deleted.is_(False))).all()
    active = [p for p in products if p.status == ProductStatus.ACTIVO]
    orders = db.scalars(select(Order).options(selectinload(Order.items), selectinload(Order.events))
                        .where(Order.store_id == store.id, Order.created_at >= since, Order.status != OrderStatus.CANCELADO)).all()
    delivered = [o for o in orders if o.status == OrderStatus.ENTREGADO]
    tips: list[dict] = []

    # ventas: lo que más sale y lo que no sale
    sold = Counter()
    pairs = Counter()
    names = {p.id: p.name for p in products}
    for o in delivered:
        ids = sorted({i.product_id for i in o.items})
        for i in o.items:
            sold[i.product_id] += i.quantity
        for a_i, a in enumerate(ids):
            for b in ids[a_i + 1:]:
                pairs[(a, b)] += 1
    top = [(names.get(pid, '—'), q) for pid, q in sold.most_common(5) if pid in names]
    ticket = sum(float(o.total) for o in delivered) / len(delivered) if delivered else 0

    no_photo = [p for p in active if not p.image_url]
    if no_photo:
        tips.append(_tip('foto', '📷', f'{len(no_photo)} producto{"s" if len(no_photo) != 1 else ""} sin foto',
                         'Los productos con foto se ven mucho mejor en el menú. Sacales una foto con el celular: '
                         'Trappi la mejora sola' + (' y le pone fondo blanco.' if platform.get_all(db).get('photo_white_bg') else '.'),
                         '/admin/products', 'Cargar fotos', [p.name for p in no_photo[:6]]))
    no_desc = [p for p in active if not (p.description or '').strip()]
    if no_desc:
        tips.append(_tip('descripcion', '✍️', f'{len(no_desc)} producto{"s" if len(no_desc) != 1 else ""} sin descripción',
                         'Una descripción corta ayuda a decidir. La IA te la escribe con el nombre del producto y vos la revisás.',
                         None, None, [{'id': p.id, 'name': p.name} for p in no_desc[:8]]))
    if pairs:
        (a, b), n = pairs.most_common(1)[0]
        if n >= 2 and a in names and b in names:
            tips.append(_tip('combo', '🍟', 'Armá un combo',
                             f'"{names[a]}" y "{names[b]}" se pidieron juntos en {n} pedidos este mes. '
                             'Un combo con un precio un poco mejor puede subir tu ticket.', '/admin/products', 'Crear el combo'))
    if len(delivered) >= 10:
        idle = [p.name for p in active if sold.get(p.id, 0) == 0]
        if idle:
            tips.append(_tip('sin_ventas', '💤', f'{len(idle)} producto{"s" if len(idle) != 1 else ""} sin ventas en {DAYS} días',
                             'Revisá el precio, la foto o el nombre. Si no se venden, ocultalos para que el menú se vea más corto.',
                             '/admin/products', 'Ver productos', idle[:6]))

    # horarios: cuándo te piden y qué día flojea
    if len(orders) >= 8:
        hours = Counter(to_local(o.created_at).hour for o in orders)
        best = max(range(24), key=lambda h: hours[h] + hours[(h + 1) % 24])
        share = (hours[best] + hours[(best + 1) % 24]) * 100 // len(orders)
        tips.append(_tip('horas', '⏰', f'Tus horas fuertes: {best:02d} a {(best + 2) % 24:02d} h',
                         f'Ahí entra el {share}% de tus pedidos. Tené repartidores conectados y la cocina lista un rato antes.'))
    if len(orders) >= 14:
        days = Counter(to_local(o.created_at).weekday() for o in orders)
        weak = min(range(7), key=lambda d: days[d])
        has_auto = db.scalar(select(func.count(Coupon.id)).where(Coupon.store_id == store.id, Coupon.active.is_(True), Coupon.auto_apply.is_(True)))
        tips.append(_tip('dia_flojo', '📉', f'Los {WEEKDAYS[weak]} te piden menos',
                         'Probá un cupón automático para ese día: se muestra en tu tienda y se aplica solo.' if not has_auto else
                         'Probá una promo o un producto destacado para ese día.', '/admin/coupons', 'Crear cupón'))

    # atención: cuánto tardás en aceptar y reseñas sin responder
    waits = []
    for o in orders:
        ev = next((e for e in o.events if e.status in ('CONFIRMADO', 'PREPARANDO')), None)
        if ev:
            waits.append((ev.created_at - o.created_at).total_seconds() / 60)
    if len(waits) >= 5:
        avg = sum(waits) / len(waits)
        if avg > 4:
            tips.append(_tip('aceptar', '🔔', f'Tardás {avg:.0f} min en aceptar los pedidos',
                             'Aceptar rápido da confianza y el pedido llega antes. Dejá la comanda abierta con el sonido prendido.',
                             '/admin/comandas', 'Abrir comandas'))
    unanswered = db.scalar(select(func.count(Review.id)).where(Review.store_id == store.id, Review.hidden.is_(False),
                                                                Review.reply.is_(None), Review.comment.is_not(None), Review.comment != '')) or 0
    if unanswered:
        tips.append(_tip('resenas', '💬', f'{unanswered} reseña{"s" if unanswered != 1 else ""} sin responder',
                         'Responder (sobre todo las malas) muestra que te importa. Los clientes lo leen.', '/admin/reviews?filter=sin_respuesta', 'Responder'))
    if store.rating_count and float(store.rating_avg or 0) < 4:
        tips.append(_tip('calificacion', '⭐', f'Tu calificación es {float(store.rating_avg):.1f}'.replace('.', ','),
                         'Mirá qué dicen las reseñas: casi siempre es la demora o algo que llegó frío. Mejorarlo sube tus ventas.',
                         '/admin/reviews', 'Ver reseñas'))
    if not orders:
        tips.append(_tip('inicio', '🚀', 'Todavía no tenés pedidos este mes',
                         'Compartí el link de tu tienda en tus redes y en WhatsApp, y activá un cupón automático de bienvenida.',
                         '/admin/coupons', 'Crear cupón'))
    return {'orders': len(orders), 'delivered': len(delivered), 'ticket': money(round(ticket)), 'top': top, 'tips': tips, 'days': DAYS}


# ---------- textos con IA ----------

def _clean(text: str, limit: int = 180) -> str:
    text = re.sub(r'\s+', ' ', (text or '').replace('"', '').replace('*', '')).strip()
    text = re.sub(r'\$\s?\d[\d.,]*', '', text)  # nunca precios inventados
    return text[:limit].rstrip(' ,;') + ('' if len(text) <= limit else '…')


def template_description(name: str, category: str | None = None) -> str:
    """Sin modelo de IA: una frase prolija con lo que ya sabemos (el nombre y el rubro)."""
    base = name.strip().rstrip('.')
    cat = (category or '').lower()
    if any(w in cat for w in ('bebida', 'gaseosa', 'cerveza')):
        return f'{base}, bien fría para acompañar tu pedido.'
    if any(w in cat for w in ('postre', 'helado', 'dulce')):
        return f'{base}, ideal para cerrar con algo rico.'
    return f'{base}, preparado en el momento con ingredientes frescos.'


def write_description(product: Product, store: Store) -> str:
    """Descripción corta para el menú. Con modelo configurado la escribe la IA; si no, una plantilla."""
    from . import providers
    category = product.category.name if product.category else (store.store_category.name if store.store_category else '')
    p = providers.get_provider()
    if p is not None:
        prompt = ('Escribí la descripción de un producto para el menú de un local de comida en Argentina. '
                  'Una sola frase de hasta 140 caracteres, en español rioplatense, cálida y concreta. '
                  'No inventes precios, promociones, tamaños ni ingredientes que no se deduzcan del nombre. Sin comillas ni emojis.')
        try:
            reply = p.chat([{'role': 'system', 'content': prompt},
                            {'role': 'user', 'content': f'Producto: {product.name}\nRubro: {category or "comida"}\nLocal: {store.name}'}], [])
            text = _clean(reply.text or '')
            if len(text) >= 15:
                return text
        except Exception as exc:  # modelo apagado o lento: plantilla
            log.info('IA de comercios no disponible: %s', exc)
    return template_description(product.name, category)


def template_reply(rating: int, name: str | None, store_name: str, comment: str | None) -> str:
    """Respuesta a una reseña sin IA: agradece y, si fue mala, pide disculpas e invita a escribir."""
    hi = f'¡Hola{" " + name if name else ""}!'
    if rating >= 4:
        return f'{hi} Muchas gracias por elegir {store_name} y por tomarte el tiempo de calificarnos. ¡Te esperamos pronto!'
    if rating == 3:
        return (f'{hi} Gracias por tu opinión. Nos sirve mucho para mejorar: la próxima queremos que sea de 5 estrellas. '
                f'Si querés contarnos más, escribinos por WhatsApp.')
    return (f'{hi} Lamentamos mucho que tu pedido no haya sido como esperabas. Ya lo estamos revisando con el equipo. '
            f'Escribinos por WhatsApp así lo resolvemos.')


def suggest_reply(db: Session, review, store: Store, name: str | None) -> str:
    """Respuesta sugerida para una reseña (no se publica sola: el dueño la revisa). Con IA del local, la escribe el modelo."""
    from . import providers
    p = providers.get_provider() if enabled(db) else None
    if p is not None:
        prompt = ('Sos el dueño de un local de comida en Argentina y respondés públicamente una reseña de un cliente. '
                  'Respondé en español rioplatense, en 2 o 3 oraciones, cálido y profesional. Si la reseña es mala, pedí disculpas sin excusas '
                  'e invitá a escribir por WhatsApp. No prometas descuentos ni montos, no inventes hechos y no repitas datos personales.')
        try:
            reply = p.chat([{'role': 'system', 'content': prompt},
                            {'role': 'user', 'content': f'Local: {store.name}\nEstrellas: {review.rating} de 5\nCliente: {name or "sin nombre"}\n'
                                                        f'Comentario: {(review.comment or "sin comentario")[:600]}'}], [])
            text = re.sub(r'\s+', ' ', (reply.text or '').replace('*', '')).strip().strip('"')[:480]
            if len(text) >= 20:
                return text
        except Exception as exc:
            log.info('IA de comercios no disponible: %s', exc)
    return template_reply(review.rating, name, store.name, review.comment)
