"""Notificaciones web (Web Push) al celular o la PC del local. Gratis: las entrega el navegador (Chrome, Edge, Firefox, Safari).

Las claves VAPID se generan solas la primera vez y quedan en la base (la privada cifrada con services/crypto).
El contenido viaja cifrado de punta a punta (RFC 8291, aes128gcm): el servicio de push del navegador no lo puede leer.
Solo se manda a servicios de push conocidos, nunca a una URL cualquiera.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Setting
from . import crypto

logger = logging.getLogger(__name__)

PRIVATE_KEY, PUBLIC_KEY = 'webpush.vapid_private', 'webpush.vapid_public'
# servicios de push de los navegadores (Chrome/Edge/Android, Firefox, Windows, Safari/iPhone)
PUSH_HOSTS = ('fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com', 'push.services.mozilla.com',
              'notify.windows.com', 'push.apple.com')
_keys: dict = {}


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def allowed_endpoint(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
    except ValueError:
        return False
    host = (u.hostname or '').lower()
    return u.scheme == 'https' and any(host == h or host.endswith('.' + h) for h in PUSH_HOSTS)


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_keys(db: Session) -> tuple[ec.EllipticCurvePrivateKey, str]:
    """(clave privada, clave publica para el navegador). Las crea la primera vez."""
    if _keys:
        return _keys['private'], _keys['public']
    rows = dict(db.execute(select(Setting.key, Setting.value).where(Setting.key.in_((PRIVATE_KEY, PUBLIC_KEY)))).all())
    pem = crypto.decrypt(rows.get(PRIVATE_KEY))
    if not pem:
        private = ec.generate_private_key(ec.SECP256R1())
        pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        try:
            with db.begin_nested():
                for row in db.scalars(select(Setting).where(Setting.key.in_((PRIVATE_KEY, PUBLIC_KEY)))):
                    db.delete(row)  # una privada ilegible (cambio la clave de cifrado): se reemplaza
                db.flush()
                db.add_all([Setting(key=PRIVATE_KEY, value=crypto.encrypt(pem)), Setting(key=PUBLIC_KEY, value=b64u(_raw_public(private.public_key())))])
            db.commit()
        except IntegrityError:  # otro proceso las creo al mismo tiempo: se usan esas
            db.rollback()
            pem = crypto.decrypt(db.scalar(select(Setting.value).where(Setting.key == PRIVATE_KEY)))
    private = serialization.load_pem_private_key(pem.encode(), password=None)
    _keys.update(private=private, public=b64u(_raw_public(private.public_key())))
    return _keys['private'], _keys['public']


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """Cuerpo cifrado aes128gcm (RFC 8291 + RFC 8188), un solo registro."""
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(ephemeral.public_key())
    shared = ephemeral.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    hm = lambda key, data: hmac.new(key, data, hashlib.sha256).digest()
    ikm = hm(hm(auth_secret, shared), b'WebPush: info\x00' + ua_public + as_public + b'\x01')
    salt = os.urandom(16)
    prk = hm(salt, ikm)
    cek = hm(prk, b'Content-Encoding: aes128gcm\x00\x01')[:16]
    nonce = hm(prk, b'Content-Encoding: nonce\x00\x01')[:12]
    body = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    return salt + struct.pack('!L', 4096) + bytes([len(as_public)]) + as_public + body


def _vapid_header(private, public: str, endpoint: str) -> str:
    u = urlparse(endpoint)
    contact = (settings.admin_email or '').strip()
    claims = {'aud': f'{u.scheme}://{u.netloc}', 'exp': int(time.time()) + 12 * 3600,
              'sub': f'mailto:{contact}' if contact and not contact.endswith('.local') else 'https://trappi.com.ar'}
    return f'vapid t={jwt.encode(claims, private, algorithm="ES256")}, k={public}'


def send(db: Session, sub, data: dict, ttl: int = 600) -> str:
    """Manda una notificacion. 'ok', 'gone' (el navegador la dio de baja: hay que borrarla) o 'error'."""
    if not allowed_endpoint(sub.endpoint):
        return 'gone'
    private, public = vapid_keys(db)
    try:
        body = encrypt(json.dumps(data, ensure_ascii=False).encode(), sub.p256dh, sub.auth)
        r = httpx.post(sub.endpoint, content=body, timeout=10, headers={
            'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', 'TTL': str(ttl), 'Urgency': 'high',
            'Authorization': _vapid_header(private, public, sub.endpoint)})
    except Exception as exc:  # sin internet, clave del navegador invalida, etc.
        logger.warning('web push: %s', exc)
        return 'error'
    if r.status_code in (404, 410):
        return 'gone'
    if r.status_code >= 400:
        logger.warning('web push %s: %s', r.status_code, r.text[:200])
        return 'error'
    return 'ok'
