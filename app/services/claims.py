"""Reclamos de los clientes por un pedido ("tuve un problema con mi pedido").

- Lo hace quien hizo el pedido (desde el mismo navegador o con su cuenta), hasta 48 h después de entregado,
  o si el pedido sigue "en camino" hace mucho ("no llegó"). Uno por pedido, con foto opcional (sin datos de ubicación).
- Al local le llega el aviso y lo ve en el panel: puede contestar o darle un cupón suyo (lo paga el local).
- Trappi lo resuelve: Puntos Trappi, cupón del local o reintegro por Mercado Pago. El reintegro NO sale de acá:
  se hace con el botón de reintegro del pedido (el flujo de Mercado Pago que ya existe); acá solo queda anotado.
"""
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Coupon, Order, OrderClaim, OrderStatus

REASONS = {'falta': 'Faltó algo', 'mal': 'Vino algo mal o distinto', 'frio': 'Llegó frío o en mal estado', 'demora': 'Tardó demasiado',
           'no_llego': 'No llegó', 'otro': 'Otro problema'}
RESOLUTIONS = {'puntos': 'Te dimos Puntos Trappi', 'cupon': 'Te dimos un descuento para tu próximo pedido',
               'reintegro': 'Te devolvimos la plata por Mercado Pago', 'nada': 'Revisamos el pedido'}
WINDOW = timedelta(hours=48)
LATE = timedelta(minutes=90)  # "no llegó": el pedido sigue en camino hace mas de esto
MAX_TEXT = 1000
COUPON_DAYS = 60


class ClaimError(Exception):
    pass


def can_claim(order: Order, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if order.status == OrderStatus.ENTREGADO:
        done = order.status_time(OrderStatus.ENTREGADO) or order.updated_at or order.created_at
        return now - done <= WINDOW
    if order.status == OrderStatus.EN_CAMINO:
        return now - (order.status_time(OrderStatus.EN_CAMINO) or order.created_at) >= LATE
    return False


def of_order(db: Session, order_id: int) -> OrderClaim | None:
    return db.scalar(select(OrderClaim).where(OrderClaim.order_id == order_id))


def create(db: Session, order: Order, reason: str, text: str, photo_raw: bytes | None = None) -> OrderClaim:
    from . import delivery_safety, owner_alerts
    if reason not in REASONS:
        raise ClaimError('Elegí qué pasó con el pedido.')
    if of_order(db, order.id) is not None:
        raise ClaimError('Ya nos contaste el problema de este pedido. Te respondemos por acá.')
    if not can_claim(order):
        raise ClaimError('Este pedido ya no se puede reclamar desde acá (pasaron más de 48 h). Escribinos por WhatsApp.')
    text = ' '.join((text or '').split())[:MAX_TEXT]
    if reason == 'otro' and len(text) < 5:
        raise ClaimError('Contanos en pocas palabras qué pasó.')
    photo = None
    if photo_raw:
        try:
            photo = delivery_safety.save_photo(db, order, photo_raw, 'reclamo', 'customer')
        except delivery_safety.SafetyError as exc:
            raise ClaimError(str(exc)) from exc
    claim = OrderClaim(order_id=order.id, store_id=order.store_id, account_id=order.account_id, reason=reason, text=text or None,
                       photo_id=photo.id if photo else None, status='abierto', created_at=datetime.utcnow())
    db.add(claim)
    db.flush()
    owner_alerts.push_store_later(order.store_id, {'title': f'⚠️ Reclamo en el pedido #{order.id}', 'body': f'{REASONS[reason]}' + (f': {text[:120]}' if text else ''),
                                                   'tag': f'claim-{claim.id}', 'url': '/admin/reclamos', 'urgent': True})
    return claim


def store_reply(db: Session, claim: OrderClaim, note: str) -> None:
    note = ' '.join((note or '').split())[:MAX_TEXT]
    if not note:
        raise ClaimError('Escribí la respuesta.')
    claim.store_note = note


def _coupon(db: Session, claim: OrderClaim, amount: Decimal) -> Coupon:
    if not claim.account_id:
        raise ClaimError('El cliente pidió sin cuenta: no se le puede dar un descuento personal. Contestale o hacé el reintegro.')
    if amount <= 0 or amount > Decimal(claim.order.total or 0):
        raise ClaimError('El descuento tiene que ser mayor a 0 y no más que el total del pedido.')
    c = Coupon(store_id=claim.store_id, account_id=claim.account_id, code=f'RECLAMO-{secrets.token_hex(3).upper()}', discount_type='fixed',
               discount_value=amount, min_order=0, max_uses=1, uses_count=0, active=True, expires_at=datetime.utcnow() + timedelta(days=COUPON_DAYS))
    db.add(c)
    db.flush()
    return c


def resolve(db: Session, claim: OrderClaim, user, resolution: str, answer: str, points: int = 0, amount: Decimal = Decimal('0'),
            superadmin: bool = False) -> None:
    """Cierra el reclamo. El local solo puede dar un cupón suyo o contestar; puntos y reintegro, solo Trappi."""
    from . import email, loyalty
    if claim.status != 'abierto':
        raise ClaimError('Este reclamo ya está cerrado.')
    if resolution not in RESOLUTIONS or (not superadmin and resolution in ('puntos', 'reintegro')):
        raise ClaimError('Elegí cómo lo resolvés.')
    answer = ' '.join((answer or '').split())[:MAX_TEXT]
    if not answer:
        raise ClaimError('Escribí la respuesta para el cliente.')
    if resolution == 'puntos':
        if not claim.account_id or not loyalty.config(db)['enabled']:
            raise ClaimError('Para dar puntos el cliente tiene que tener cuenta y los Puntos Trappi tienen que estar prendidos.')
        if not 1 <= points <= 100000:
            raise ClaimError('Poné cuántos puntos le das.')
        loyalty.adjust(db, claim.account_id, points, f'Reclamo del pedido #{claim.order_id}', user)
        claim.points = points
    elif resolution == 'cupon':
        claim.coupon_id = _coupon(db, claim, amount).id
    claim.status = 'rechazado' if resolution == 'nada' else 'resuelto'
    claim.resolution, claim.answer, claim.resolved_by, claim.resolved_at = resolution, answer, getattr(user, 'id', None), datetime.utcnow()
    from ..models import ClientAccount
    acct = db.get(ClientAccount, claim.account_id) if claim.account_id else None
    to = acct.email if acct is not None and acct.active else None
    if to and email.configured():
        try:
            email.send(to, f'Respondimos tu reclamo del pedido #{claim.order_id}',
                       f'Hola, revisamos el problema con tu pedido #{claim.order_id} en {claim.order.store.name}.\n\n{answer}\n\n{RESOLUTIONS[resolution]}.\n\nGracias por avisarnos.')
        except Exception:
            pass
