"""Verificacion en dos pasos con codigos de 6 digitos (TOTP, RFC 6238).

Sirve con Google Authenticator, Microsoft Authenticator, Authy, 1Password, etc. El secreto se guarda
cifrado; cada codigo se puede usar una sola vez. Los codigos de recuperacion (por si se pierde el
celular) se guardan como hash y se gastan al usarlos.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

import segno

from . import crypto

ISSUER = 'Trappi'
STEP = 30
DIGITS = 6
RECOVERY_CODES = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def _key(secret: str) -> bytes:
    secret = secret.strip().replace(' ', '').upper()
    return base64.b32decode(secret + '=' * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """El paso del codigo si es valido (tolera 30 s de diferencia de reloj) y no se uso antes; si no, None."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in (current, current - 1, current + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    return f'otpauth://totp/{quote(ISSUER)}:{quote(account)}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}'


def qr_svg(uri: str) -> str:
    """El QR como SVG para mostrar en la pagina (se genera en el servidor: el secreto no sale a ningun servicio)."""
    return segno.make(uri, error='m').svg_inline(scale=5, border=2, dark='#111', light='#fff')


def group(secret: str) -> str:
    return ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))


# ---------- secreto de un usuario ----------

def secret_of(user) -> str | None:
    return crypto.decrypt(user.totp_secret_enc) if user.totp_secret_enc else None


def enabled(user) -> bool:
    return bool(user.totp_enabled_at and user.totp_secret_enc)


def check_user(user, code: str) -> bool:
    """Valida el codigo de la app y lo marca usado (no hace commit)."""
    step = verify(secret_of(user) or '', code, user.totp_last_step)
    if step is None:
        return False
    user.totp_last_step = step
    return True


# ---------- codigos de recuperacion ----------

def _hash(code: str) -> str:
    return hashlib.sha256(''.join(ch for ch in code.lower() if ch.isalnum()).encode()).hexdigest()


def new_recovery_codes(user) -> list[str]:
    """Genera codigos nuevos (reemplazan a los anteriores) y devuelve el texto para mostrarlos una sola vez."""
    codes = [f'{secrets.token_hex(3)}-{secrets.token_hex(3)}' for _ in range(RECOVERY_CODES)]
    user.recovery_codes = json.dumps([_hash(c) for c in codes])
    return codes


def recovery_left(user) -> int:
    try:
        return len(json.loads(user.recovery_codes or '[]'))
    except ValueError:
        return 0


def use_recovery_code(user, code: str) -> bool:
    try:
        hashes = json.loads(user.recovery_codes or '[]')
    except ValueError:
        return False
    wanted = _hash(code or '')
    for h in hashes:
        if hmac.compare_digest(h, wanted):
            hashes.remove(h)
            user.recovery_codes = json.dumps(hashes)
            return True
    return False


def disable(user) -> None:
    user.totp_secret_enc = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.recovery_codes = None
