"""Cuentas de clientes: alta/ingreso con Google, sesion web, token de la app, bloqueo y baja.

- Web: la sesion guarda {'id', 'v'}; si Trappi bloquea la cuenta o el cliente sale de todos lados,
  sube session_version y la sesion deja de valer.
- App: token firmado (90 dias) con el mismo id y version, en el encabezado Authorization: Bearer.
- Obligatoria para pedir cuando la opcion "Pedir cuenta para hacer pedidos" esta prendida y Google
  esta configurado (sin credenciales de Google se sigue pidiendo como invitado, para no frenar las ventas).
"""
from datetime import datetime

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ClientAccount, Customer, Order
from . import google_auth, platform

# version de los terminos y la politica de privacidad: al cambiarla, los clientes la vuelven a aceptar al entrar
TERMS_VERSION = '2026-10-06'
SESSION_KEY = 'client'
TOKEN_DAYS = 90
_signer = URLSafeTimedSerializer(settings.secret_key, salt='trappi-client')
_code_signer = URLSafeTimedSerializer(settings.secret_key, salt='trappi-client-app-code')
APP_CODE_SECONDS = 180


class AccountError(Exception):
    pass


def required(db: Session) -> bool:
    return bool(platform.get_all(db).get('customer_login_required')) and google_auth.configured()


def available() -> bool:
    return google_auth.configured()


def upsert_from_google(db: Session, claims: dict) -> ClientAccount:
    """Crea o actualiza la cuenta con los datos de Google. No hace commit."""
    sub = str(claims['sub'])
    acct = db.scalar(select(ClientAccount).where(ClientAccount.google_sub == sub))
    if acct and not acct.active:
        raise AccountError('Tu cuenta está bloqueada. Si creés que es un error, escribinos por WhatsApp.')
    created = acct is None
    if created:
        acct = ClientAccount(google_sub=sub, email='')
        db.add(acct)
    acct.just_created = created  # solo para la auditoria (no se guarda)
    acct.email = str(claims.get('email') or '').strip().lower()[:255]
    acct.name = (claims.get('name') or '')[:160] or None
    acct.first_name = acct.first_name or (claims.get('given_name') or '')[:100] or None
    acct.last_name = acct.last_name or (claims.get('family_name') or '')[:100] or None
    acct.picture_url = (claims.get('picture') or '')[:1000] or None
    acct.last_login_at = datetime.utcnow()
    if acct.terms_version != TERMS_VERSION:  # entrar con el aviso a la vista = aceptar los terminos vigentes
        acct.terms_version, acct.terms_accepted_at = TERMS_VERSION, datetime.utcnow()
    db.flush()
    return acct


# ---------- web ----------

def start_session(request, acct: ClientAccount) -> None:
    request.session[SESSION_KEY] = {'id': acct.id, 'v': acct.session_version}


def end_session(request) -> None:
    request.session.pop(SESSION_KEY, None)


def from_session(request, db: Session) -> ClientAccount | None:
    data = request.session.get(SESSION_KEY) or {}
    acct = db.get(ClientAccount, data.get('id')) if data.get('id') else None
    if not acct or not acct.active or data.get('v') != acct.session_version:
        return None
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
    try:
        data = _code_signer.loads(code, max_age=APP_CODE_SECONDS)
    except BadSignature:
        raise AccountError('El ingreso venció. Probá de nuevo.')
    if not verifier or google_auth.challenge_of(verifier) != data.get('c'):
        raise AccountError('No pudimos confirmar el ingreso. Probá de nuevo.')
    acct = db.get(ClientAccount, data.get('a'))
    if not acct or not acct.active or acct.session_version != data.get('v'):
        raise AccountError('No pudimos confirmar el ingreso. Probá de nuevo.')
    return acct


# ---------- datos y baja ----------

def save_contact(acct: ClientAccount, *, first_name=None, last_name=None, phone=None, address=None, reference=None) -> None:
    for field, value, size in (('first_name', first_name, 100), ('last_name', last_name, 100), ('phone', phone, 40),
                               ('address', address, 255), ('reference', reference, 255)):
        if value is not None:
            setattr(acct, field, (value or '').strip()[:size] or None)


def sign_out_everywhere(acct: ClientAccount) -> None:
    acct.session_version = (acct.session_version or 1) + 1


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
