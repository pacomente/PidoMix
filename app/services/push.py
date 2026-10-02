"""Notificaciones push a la app movil via Firebase Cloud Messaging (API HTTP v1).

Se activa con FIREBASE_SERVICE_ACCOUNT (el JSON de la cuenta de servicio). Sin esa variable
no se manda nada y el resto funciona igual. El envio corre en un hilo aparte para que el
cambio de estado en el panel o en comandas no espere a Firebase.
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request

import jwt
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Order, OrderStatus, PushToken

logger = logging.getLogger(__name__)

SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
MAX_TOKENS_PER_ORDER = 5

# (titulo, texto) para cada estado que le interesa al cliente
MESSAGES = {
    'CONFIRMADO': ('¡Pedido confirmado! ✅', '{store} confirmó tu pedido #{id}.'),
    'PREPARANDO': ('Preparando tu pedido 🍳', '{store} ya está preparando tu pedido #{id}.'),
    'LISTO': ('¡Tu pedido está listo! 🛍', 'Ya podés pasar a retirar tu pedido #{id} por {store}.'),
    'LISTO_DELIVERY': ('Tu pedido está listo 📦', 'Tu pedido #{id} de {store} sale en breve.'),
    'EN_CAMINO': ('Tu pedido va en camino 🛵', 'El pedido #{id} de {store} ya salió para tu casa.'),
    'ENTREGADO': ('¡Pedido entregado! ⭐', '¿Qué tal estuvo? Calificá tu pedido #{id} de {store}.'),
    'CANCELADO': ('Pedido cancelado', '{store} canceló tu pedido #{id}. Escribile si tenés dudas.'),
}

_token_cache: dict = {}
_lock = threading.Lock()


def _service_account() -> dict | None:
    raw = settings.firebase_service_account.strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
        return info if info.get('private_key') and info.get('client_email') and info.get('project_id') else None
    except ValueError:
        logger.error('FIREBASE_SERVICE_ACCOUNT no es un JSON valido')
        return None


def enabled() -> bool:
    return _service_account() is not None


def _access_token(info: dict) -> str:
    """Token OAuth de Google para FCM, firmado con la cuenta de servicio (dura 1 hora)."""
    with _lock:
        if _token_cache.get('exp', 0) > time.time() + 60:
            return _token_cache['token']
        now = int(time.time())
        assertion = jwt.encode({'iss': info['client_email'], 'scope': SCOPE, 'aud': info.get('token_uri', 'https://oauth2.googleapis.com/token'),
                                'iat': now, 'exp': now + 3600}, info['private_key'], algorithm='RS256')
        body = f'grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion={assertion}'.encode()
        req = urllib.request.Request(info.get('token_uri', 'https://oauth2.googleapis.com/token'), data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        _token_cache.update(token=data['access_token'], exp=now + int(data.get('expires_in', 3600)))
        return data['access_token']


def message_for(order: Order) -> tuple[str, str] | None:
    key = order.status.value
    if key == 'LISTO' and order.delivery_method == 'delivery':
        key = 'LISTO_DELIVERY'
    if key not in MESSAGES:
        return None
    title, text = MESSAGES[key]
    return title, text.format(store=order.store.name, id=order.id)


def build_payload(token: str, order: Order, title: str, text: str) -> dict:
    # mensaje solo de datos: la app (expo-notifications) lo muestra y al tocarlo abre el seguimiento
    return {'message': {'token': token, 'android': {'priority': 'high'}, 'data': {
        'title': title, 'message': text, 'channelId': 'pedidos', 'tag': f'pedido-{order.id}', 'color': '#6C2BD9',
        'body': json.dumps({'order_id': order.id, 'status': order.status.value}),
    }}}


def _send(info: dict, payloads: list[tuple[str, dict]]) -> list[str]:
    """Manda cada mensaje y devuelve los tokens que Firebase ya no reconoce (app desinstalada)."""
    dead = []
    url = f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send"
    try:
        access = _access_token(info)
    except Exception:
        logger.exception('No se pudo obtener el token de Firebase')
        return dead
    for token, payload in payloads:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Authorization': f'Bearer {access}', 'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='ignore')
            if exc.code == 404 or 'UNREGISTERED' in detail or ('INVALID_ARGUMENT' in detail and 'registration token' in detail):
                dead.append(token)
            else:
                logger.warning('FCM respondio %s: %s', exc.code, detail[:300])
        except Exception:
            logger.exception('Fallo el envio de una notificacion push')
    return dead


def _deliver(info: dict, order_id: int, payloads: list[tuple[str, dict]]) -> None:
    dead = _send(info, payloads)
    if dead:
        with SessionLocal() as db:
            db.execute(delete(PushToken).where(PushToken.order_id == order_id, PushToken.token.in_(dead)))
            db.commit()


def notify_status(db: Session, order: Order) -> bool:
    """Avisa al cliente el nuevo estado del pedido. Devuelve True si hubo algo para mandar."""
    info = _service_account()
    msg = message_for(order)
    if not info or not msg:
        return False
    tokens = db.scalars(select(PushToken.token).where(PushToken.order_id == order.id)).all()
    if not tokens:
        return False
    payloads = [(t, build_payload(t, order, *msg)) for t in tokens]
    threading.Thread(target=_deliver, args=(info, order.id, payloads), daemon=True).start()
    return True


def register(db: Session, order: Order, token: str, platform: str = 'android') -> bool:
    """Guarda el telefono para avisarle de este pedido. No hace commit."""
    token = (token or '').strip()
    if not token or len(token) > 512 or order.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
        return False
    if order.id is None:  # pedido recien creado, todavia sin id
        db.flush()
    existing = db.scalars(select(PushToken).where(PushToken.order_id == order.id)).all()
    if any(p.token == token for p in existing):
        return True
    if len(existing) >= MAX_TOKENS_PER_ORDER:
        db.delete(min(existing, key=lambda p: p.created_at))
    db.add(PushToken(order_id=order.id, token=token, platform=platform if platform in ('android', 'ios') else 'android'))
    return True
