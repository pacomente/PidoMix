"""Cifrado de datos sensibles guardados en la base (tokens de Mercado Pago, CBU/CVU).

Usa Fernet (AES + HMAC). La clave sale de FIELD_ENCRYPTION_KEY o, si no esta, se deriva de SECRET_KEY:
cambiar cualquiera de las dos deja ilegibles los datos ya cifrados (habria que volver a conectarlos).
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


def _fernet() -> Fernet:
    key = settings.field_encryption_key.strip()
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(('trappi-fields:' + settings.secret_key).encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def mask(value: str | None, visible: int = 4) -> str:
    """'0000003100012345678901' -> '•••• 8901'."""
    digits = ''.join(ch for ch in (value or '') if ch.isalnum())
    return f'•••• {digits[-visible:]}' if digits else ''
