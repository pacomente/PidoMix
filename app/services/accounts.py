"""Cuentas de clientes: alta/ingreso con un codigo por email, sesion web, token de la app, bloqueo y baja.

- Codigo por email: 6 numeros, 10 minutos, de un solo uso. En la sesion solo queda su HMAC (la cookie
  se puede leer, pero sin la clave del servidor no se saca el codigo). Limites por email y por IP.

- Web: la sesion guarda {'id', 'v'}; si Trappi bloquea la cuenta o el cliente sale de todos lados,
  sube session_version y la sesion deja de valer.
- App: token firmado (90 dias) con el mismo id y version, en el encabezado Authorization: Bearer.
- Obligatoria para pedir cuando la opcion "Pedir cuenta para hacer pedidos" esta prendida y el envio de
  emails esta configurado; sin eso se sigue pidiendo como invitado, para no frenar las ventas.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ClientAccount, Customer, Order
from . import email as email_service
from . import platform
from .ratelimit import PersistentRateLimiter

# version de los terminos y la politica de privacidad: al cambiarla, los clientes la vuelven a aceptar al entrar
TERMS_VERSION = '2026-10-06'
SESSION_KEY = 'client'
TOKEN_DAYS = 90
_signer = URLSafeTimedSerializer(settings.secret_key, salt='trappi-client')
_code_signer = URLSafeTimedSerializer(settings.secret_key, salt='trappi-client-app-code')
APP_CODE_SECONDS = 180
EMAIL_FLOW_KEY = 'email_login'
EMAIL_CODE_MINUTES = 10
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$')
code_requests_by_email = PersistentRateLimiter('email-code-send', limit=3, window_seconds=600)
code_requests_by_ip = PersistentRateLimiter('email-code-send-ip', limit=10, window_seconds=3600)
code_failures = PersistentRateLimiter('email-code-fail', limit=5, window_seconds=600)


class AccountError(Exception):
    pass


def required(db: Session) -> bool:
    return bool(platform.get_all(db).get('customer_login_required')) and available()


def available() -> bool:
    return email_service.configured()


def methods() -> list[str]:
    return ['email'] if available() else []


def new_pkce() -> tuple[str, str]:
    """(verifier, challenge) para PKCE S256 (lo usa la app: aca solo para los tests)."""
    verifier = secrets.token_urlsafe(48)
    return verifier, challenge_of(verifier)


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


def _touch(acct: ClientAccount) -> None:
    acct.last_login_at = datetime.utcnow()
    if acct.terms_version != TERMS_VERSION:  # entrar con el aviso a la vista = aceptar los terminos vigentes
        acct.terms_version, acct.terms_accepted_at = TERMS_VERSION, datetime.utcnow()


def _by_email(db: Session, email: str) -> ClientAccount | None:
    return db.scalar(select(ClientAccount).where(func.lower(ClientAccount.email) == email).order_by(ClientAccount.id).limit(1))


# ---------- codigo por email ----------

def normalize_email(value: str) -> str:
    email = (value or '').strip().lower()
    if len(email) > 255 or not EMAIL_RE.match(email):
        raise AccountError('Revisá el email: tiene que ser como nombre@gmail.com.')
    return email


def _code_hash(email: str, code: str, nonce: str) -> str:
    return hmac.new(settings.secret_key.encode(), f'{email}|{code}|{nonce}'.encode(), hashlib.sha256).hexdigest()


def send_email_code(request, email: str, ip: str, **flow) -> None:
    """Manda un codigo nuevo y deja en la sesion su HMAC (el anterior deja de valer). flow: next, app_redirect, app_challenge."""
    email = normalize_email(email)
    if not code_requests_by_ip.check(ip):
        raise AccountError('Pediste muchos códigos. Esperá un rato y probá de nuevo.')
    if not code_requests_by_email.check(email):
        raise AccountError('Ya te mandamos varios códigos a ese email. Revisá tu bandeja (y la de spam) o esperá unos minutos.')
    code, nonce = f'{secrets.randbelow(10 ** 6):06d}', secrets.token_urlsafe(16)
    try:
        email_service.send(email, f'{code} es tu código para entrar a Trappi',
                           f'Tu código para entrar a Trappi es: {code}\n\n'
                           f'Vence en {EMAIL_CODE_MINUTES} minutos y sirve una sola vez. No se lo pases a nadie: '
                           'nadie de Trappi te lo va a pedir.\n\nSi no fuiste vos, ignorá este email.')
    except email_service.EmailError:
        raise AccountError('No pudimos mandarte el email. Probá de nuevo en un rato.')
    request.session[EMAIL_FLOW_KEY] = {'email': email, 'h': _code_hash(email, code, nonce), 'n': nonce,
                                       'exp': int(time.time()) + EMAIL_CODE_MINUTES * 60, **flow}


def pending_email_login(request) -> dict | None:
    flow = request.session.get(EMAIL_FLOW_KEY) or None
    return flow if flow and flow.get('exp', 0) > time.time() else None


def verify_email_code(request, db: Session, code: str) -> tuple[ClientAccount, dict]:
    """Valida el codigo, lo quema y devuelve (cuenta, flujo). No hace commit."""
    flow = pending_email_login(request)
    if not flow:
        request.session.pop(EMAIL_FLOW_KEY, None)
        raise AccountError('El código venció. Pedí uno nuevo.')
    email, code = flow['email'], re.sub(r'\D', '', code or '')
    if code_failures.blocked(email):
        request.session.pop(EMAIL_FLOW_KEY, None)
        raise AccountError('Demasiados intentos. Esperá unos minutos y pedí un código nuevo.')
    if len(code) != 6 or not hmac.compare_digest(_code_hash(email, code, flow['n']), flow['h']):
        code_failures.hit(email)
        raise AccountError('El código no es correcto. Revisalo e intentá de nuevo.')
    request.session.pop(EMAIL_FLOW_KEY, None)  # un solo uso
    code_failures.reset(email)
    acct = _by_email(db, email)
    if acct and not acct.active:
        raise AccountError('Tu cuenta está bloqueada. Si creés que es un error, escribinos por WhatsApp.')
    created = acct is None
    if created:
        acct = ClientAccount(email=email)
        db.add(acct)
    acct.just_created = created
    _touch(acct)
    db.flush()
    return acct, flow


# ---------- web ----------

def start_session(request, acct: ClientAccount) -> None:
    request.session[SESSION_KEY] = {'id': acct.id, 'v': acct.session_version}


def end_session(request) -> None:
    request.session.pop(SESSION_KEY, None)


def from_session(request, db: Session) -> ClientAccount | None:
    data = request.session.get(SESSION_KEY) or {}
    acct = db.get(ClientAccount, data.get('id')) if data.get('id') else None
    if not acct or not acct.active or data.get('v') != acct.session_version:
        acct = None
    request.state.client_account = acct  # las plantillas la reusan sin volver a consultar
    return acct


# ---------- app ----------

def app_token(acct: ClientAccount) -> str:
    return _signer.dumps({'a': acct.id, 'v': acct.session_version})


def from_token(db: Session, token: str) -> ClientAccount | None:
    try:
        data = _signer.loads(token, max_age=TOKEN_DAYS * 86400)
    except BadSignature:
        return None
    acct = db.get(ClientAccount, data.get('a'))
    if not acct or not acct.active or data.get('v') != acct.session_version:
        return None
    return acct


def from_bearer(db: Session, authorization: str | None) -> ClientAccount | None:
    if not authorization or not authorization.lower().startswith('bearer '):
        return None
    return from_token(db, authorization.split(' ', 1)[1].strip())


def app_code(acct: ClientAccount, challenge: str) -> str:
    """Codigo de un solo uso (3 minutos) que la app cambia por su token mostrando el verifier de PKCE."""
    return _code_signer.dumps({'a': acct.id, 'v': acct.session_version, 'c': challenge})


def redeem_app_code(db: Session, code: str, verifier: str) -> ClientAccount:
    """Valida el codigo (firma, 3 minutos, PKCE) y lo quema: un mismo codigo da un solo token."""
    try:
        data = _code_signer.loads(code, max_age=APP_CODE_SECONDS)
    except BadSignature:
        raise AccountError('El ingreso venció. Probá de nuevo.')
    used = PersistentRateLimiter('app-code-used', limit=1, window_seconds=APP_CODE_SECONDS + 60)
    key = hashlib.sha256(code.encode()).hexdigest()
    if used.blocked(key):
        raise AccountError('Ese ingreso ya se usó. Probá entrar de nuevo.')
    if not verifier or challenge_of(verifier) != data.get('c'):
        raise AccountError('No pudimos confirmar el ingreso. Probá de nuevo.')
    acct = db.get(ClientAccount, data.get('a'))
    if not acct or not acct.active or acct.session_version != data.get('v'):
        raise AccountError('No pudimos confirmar el ingreso. Probá de nuevo.')
    used.hit(key)  # (con el verifier correcto: un intento con verifier falso no quema el codigo del dueño)
    return acct


# ---------- datos y baja ----------

def save_contact(acct: ClientAccount, *, first_name=None, last_name=None, phone=None, address=None, reference=None) -> None:
    for field, value, size in (('first_name', first_name, 100), ('last_name', last_name, 100), ('phone', phone, 40),
                               ('address', address, 255), ('reference', reference, 255)):
        if value is not None:
            setattr(acct, field, (value or '').strip()[:size] or None)


def sign_out_everywhere(acct: ClientAccount) -> None:
    from .auth import bump_session
    bump_session(acct)


def block(acct: ClientAccount, reason: str = '') -> None:
    acct.active, acct.blocked_reason = False, (reason or '').strip()[:255] or None
    sign_out_everywhere(acct)


def unblock(acct: ClientAccount) -> None:
    acct.active, acct.blocked_reason = True, None


def delete(db: Session, acct: ClientAccount) -> int:
    """Baja de la cuenta (derecho de supresion). Los pedidos quedan para la contabilidad, sin el enlace. No hace commit."""
    db.execute(update(Customer).where(Customer.id.in_(select(Order.customer_id).where(Order.account_id == acct.id))).values(email=None))
    n = db.execute(update(Order).where(Order.account_id == acct.id).values(account_id=None)).rowcount or 0
    db.delete(acct)
    db.flush()
    return n
