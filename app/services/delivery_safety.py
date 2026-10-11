"""Seguridad de la entrega: el cadete avisa que llegó (con GPS), espera en la puerta, saca fotos de prueba
y chatea con el cliente y con el local sin pasarse los teléfonos.

- "Llegué": solo si el GPS lo ubica cerca de la entrega (arrive_radius_m). Se le avisa al cliente.
- Si el cliente no aparece en noshow_wait_minutes, el cadete cancela con una foto (obligatoria):
  el pedido se cancela solo, se le avisa al local y al cliente, y el cadete cobra el viaje (si así está configurado).
  Si el cadete de la flota ya le había pagado al local en efectivo, el pedido queda marcado "no se pudo entregar"
  y el local lo cancela cuando le devuelven el pedido (así la plata vuelve a su lugar).
- Fotos: se guardan en la base (no en un CDN público), re-codificadas sin los datos de ubicación de la cámara,
  y se borran a los photo_retention_days. Solo las ven el cadete, el cliente, el local del pedido y Trappi.
- Chat: hilo "cliente" (cadete <-> cliente) e hilo "local" (cadete <-> local). Se puede escribir mientras el
  pedido está en curso y leer hasta un rato después.
"""
import io
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Order, OrderMessage, OrderPhoto, OrderStatus
from . import cities, platform
from .geo import distance_km

THREADS = ('cliente', 'local')
MAX_UPLOAD = 6 * 1024 * 1024  # lo que manda la app (ya achicada) entra holgado
MAX_SIDE = 1600
MAX_TEXT = 600
READ_AFTER_FINAL = timedelta(hours=6)  # despues de entregado o cancelado se puede leer un rato, no escribir


class SafetyError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def cfg_for(db: Session, order: Order) -> dict:
    return platform.for_city(db, cities.of_order(order))


# ---------- fotos ----------

def save_photo(db: Session, order: Order, raw: bytes, kind: str, sender: str) -> OrderPhoto:
    """Valida que sea una imagen, la achica y la re-codifica en JPEG (sin EXIF: sin la ubicación de la cámara). No hace commit."""
    if not raw:
        raise SafetyError('La foto llegó vacía.', 400)
    if len(raw) > MAX_UPLOAD:
        raise SafetyError('La foto es muy pesada (máximo 6 MB).', 413)
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw))
        img.verify()  # que sea una imagen de verdad
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)  # respeta la orientación del celular
        img = img.convert('RGB')
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, 'JPEG', quality=72, optimize=True)  # sin exif=: no se copian los metadatos
    except SafetyError:
        raise
    except Exception as exc:
        raise SafetyError('No es una foto válida.', 400) from exc
    photo = OrderPhoto(order_id=order.id, kind=kind, sender=sender, mime='image/jpeg', content=out.getvalue(), width=img.width, height=img.height,
                       created_at=datetime.utcnow())
    db.add(photo)
    db.flush()
    return photo


def photo_of(db: Session, order: Order, photo_id: int) -> OrderPhoto | None:
    p = db.get(OrderPhoto, photo_id)
    return p if p is not None and p.order_id == order.id else None


def purge_old(db: Session, now: datetime | None = None) -> int:
    """Borra las fotos (y los mensajes que las mostraban quedan sin foto) pasados los días configurados. Hace commit."""
    now = now or datetime.utcnow()
    days = platform.get_all(db)['photo_retention_days']
    limit = now - timedelta(days=days)
    n = db.execute(delete(OrderPhoto).where(OrderPhoto.created_at < limit)).rowcount or 0
    db.commit()
    return n


_last_purge = {'at': None}


def purge_throttled(db: Session) -> None:
    """Una vez por hora como mucho (lo llama la comandera, que consulta seguido). Nunca rompe la pantalla."""
    now = datetime.utcnow()
    if _last_purge['at'] and now - _last_purge['at'] < timedelta(hours=1):
        return
    _last_purge['at'] = now
    try:
        purge_old(db, now)
    except Exception:
        db.rollback()


# ---------- llegada y "el cliente no aparece" ----------

def arrival(db: Session, courier, order: Order, lat: float | None, lng: float | None, now: datetime | None = None) -> None:
    """El cadete marca que llegó a la entrega. Valida el GPS. No hace commit."""
    if order.courier_id != courier.id or order.status != OrderStatus.EN_CAMINO:
        raise SafetyError('Solo podés avisar que llegaste con un pedido que llevás en camino.')
    if order.courier_arrived_at:
        return
    radius = cfg_for(db, order)['arrive_radius_m']
    if order.lat is not None and order.lng is not None:
        if lat is None or lng is None:
            raise SafetyError('Necesitamos tu ubicación para confirmar que llegaste. Prendé el GPS.')
        meters = distance_km(lat, lng, order.lat, order.lng) * 1000
        if meters > radius:
            raise SafetyError(f'Todavía estás a {int(round(meters, -1))} m de la entrega. Marcá "Llegué" cuando estés en la puerta.')
    order.courier_arrived_at = now or datetime.utcnow()
    system_message(db, order, 'cliente', 'Tu repartidor llegó y te está esperando en la puerta.')


def wait_left(db: Session, order: Order, now: datetime | None = None) -> int | None:
    """Segundos que faltan para poder cancelar por "no aparece" (0 = ya puede). None si no marcó "Llegué"."""
    if not order.courier_arrived_at:
        return None
    now = now or datetime.utcnow()
    end = order.courier_arrived_at + timedelta(minutes=cfg_for(db, order)['noshow_wait_minutes'])
    return max(0, int((end - now).total_seconds()))


def no_show(db: Session, courier, order: Order, photo_raw: bytes, now: datetime | None = None) -> str:
    """El cliente no apareció después de la espera: con la foto de prueba se cancela el pedido (o queda para que el local
    confirme la devolución si el cadete ya le había pagado en efectivo). Devuelve 'cancelled' o 'returning'. No hace commit."""
    from . import dispatch
    from .orders import record
    now = now or datetime.utcnow()
    if order.courier_id != courier.id or order.status != OrderStatus.EN_CAMINO:
        raise SafetyError('Solo se puede cancelar un pedido que llevás en camino.')
    left = wait_left(db, order, now)
    if left is None:
        raise SafetyError('Primero marcá "Llegué" en la puerta.')
    if left > 0:
        raise SafetyError(f'Esperá {left // 60}:{left % 60:02d} más: el cliente tiene {cfg_for(db, order)["noshow_wait_minutes"]} minutos para salir.')
    photo = save_photo(db, order, photo_raw, 'no_aparecio', 'courier')
    order.proof_photo_id = photo.id
    waited = int((now - order.courier_arrived_at).total_seconds() // 60)
    order.delivery_failed_at, order.delivery_fail_reason = now, f'El cliente no apareció (esperó {waited} min en la puerta, con foto)'[:160]
    system_message(db, order, 'local', f'El cliente no apareció: el cadete esperó {waited} min en la puerta (foto adjunta).', photo.id)
    if order.pickup_paid is not None:
        # el cadete de la flota le pago al local: el local cancela cuando le devuelven el pedido (vuelve la plata)
        system_message(db, order, 'cliente', 'No pudimos entregarte el pedido: el repartidor te esperó en la puerta y no apareciste.')
        return 'returning'
    dispatch.cancel_after_pickup(db, order, None)
    order.status = OrderStatus.CANCELADO
    record(order, OrderStatus.CANCELADO)
    system_message(db, order, 'cliente', 'Cancelamos el pedido: el repartidor te esperó en la puerta y no apareciste.')
    return 'cancelled'


def attach_delivery_photo(db: Session, courier, order: Order, raw: bytes) -> OrderPhoto:
    if order.courier_id != courier.id or order.status != OrderStatus.EN_CAMINO:
        raise SafetyError('Solo podés sacar la foto de un pedido que llevás en camino.')
    photo = save_photo(db, order, raw, 'entrega', 'courier')
    order.proof_photo_id = photo.id
    return photo


def delivery_photo_missing(db: Session, order: Order) -> bool:
    """Falta la foto obligatoria de la entrega."""
    if not cfg_for(db, order)['delivery_photo_required']:
        return False
    p = db.get(OrderPhoto, order.proof_photo_id) if order.proof_photo_id else None
    return p is None or p.kind != 'entrega'


# ---------- chat ----------

def chat_open(db: Session, order: Order, now: datetime | None = None) -> tuple[bool, bool]:
    """(se puede leer, se puede escribir). Solo con un cadete asignado."""
    if not platform.get_all(db)['order_chat_enabled'] or order.courier_id is None and order.status not in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
        return False, False
    now = now or datetime.utcnow()
    if order.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
        done = order.updated_at or order.created_at
        return (now - done <= READ_AFTER_FINAL and db.scalar(select(OrderMessage.id).where(OrderMessage.order_id == order.id).limit(1)) is not None), False
    return True, True


def system_message(db: Session, order: Order, thread: str, text: str, photo_id: int | None = None) -> OrderMessage:
    m = OrderMessage(order_id=order.id, thread=thread, sender='system', text=text[:MAX_TEXT], photo_id=photo_id, created_at=datetime.utcnow())
    db.add(m)
    db.flush()
    return m


def post(db: Session, order: Order, thread: str, sender: str, text: str = '', photo_id: int | None = None, user_id: int | None = None) -> OrderMessage:
    """Mensaje nuevo (texto y/o foto). Valida que el chat esté abierto. No hace commit."""
    if thread not in THREADS:
        raise SafetyError('Chat inválido.', 400)
    _, can_write = chat_open(db, order)
    if not can_write:
        raise SafetyError('Este chat ya está cerrado.')
    text = (text or '').strip()[:MAX_TEXT]
    if not text and not photo_id:
        raise SafetyError('Escribí un mensaje.', 400)
    m = OrderMessage(order_id=order.id, thread=thread, sender=sender, text=text or None, photo_id=photo_id, user_id=user_id, created_at=datetime.utcnow())
    db.add(m)
    db.flush()
    return m


def messages(db: Session, order: Order, thread: str, after: int = 0, limit: int = 100) -> list[OrderMessage]:
    return db.scalars(select(OrderMessage).where(OrderMessage.order_id == order.id, OrderMessage.thread == thread, OrderMessage.id > after)
                      .order_by(OrderMessage.id).limit(limit)).all()


def message_json(m: OrderMessage, photo_url) -> dict:
    """photo_url: función photo_id -> URL para quien lo va a ver (cada uno tiene su ruta con su autenticación)."""
    return {'id': m.id, 'sender': m.sender, 'text': m.text, 'photo': photo_url(m.photo_id) if m.photo_id else None,
            'at': m.created_at.isoformat() + 'Z'}
