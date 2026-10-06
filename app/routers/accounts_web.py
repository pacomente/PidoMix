"""Cuentas de clientes en la web (y el ingreso con Google de la app).

  /ingresar                     pantalla para entrar con Google
  /ingresar/google              manda a Google (web, o la app con ?app=1&challenge=...&redirect=trappi://...)
  /cuenta/google/callback       vuelta de Google: crea o actualiza la cuenta
  /cuenta                       datos, pedidos, salir y eliminar la cuenta
"""
import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..db import get_db
from ..models import Order
from ..services import accounts, audit, csrf, google_auth
from ..services.ratelimit import client_ip
from .public import ctx, order_token, public_base, templates

router = APIRouter()
templates.env.globals['csrf_input'] = csrf.csrf_input
templates.env.globals['client_account'] = lambda request: _account_for_templates(request)
PROTECT = [Depends(csrf.protect)]


def _account_for_templates(request):
    """La cuenta del visitante para el encabezado: la que ya busco la ruta, o una consulta (una sola vez por pedido)."""
    from ..db import SessionLocal
    if not (request.session.get(accounts.SESSION_KEY) or {}).get('id'):
        return None
    if hasattr(request.state, 'client_account'):
        return request.state.client_account
    with SessionLocal() as db:
        acct = accounts.from_session(request, db)
        if acct is not None:
            db.expunge(acct)
        request.state.client_account = acct
        return acct


def safe_next(value: str | None) -> str:
    """Solo rutas internas de la tienda (nada de redirecciones a otros sitios ni al panel)."""
    if value and value.startswith('/') and not value.startswith(('//', '/admin', '/ingresar', '/cuenta/google')) and '\\' not in value:
        return value
    return '/'


def allowed_app_redirect(url: str) -> bool:
    """La vuelta a la app: solo el esquema propio (y el de Expo Go en desarrollo)."""
    scheme = urlsplit(url or '').scheme.lower()
    return scheme == 'trappi' or (scheme in ('exp', 'exps') and not settings.is_production)


def callback_url(request: Request) -> str:
    return public_base(request) + '/cuenta/google/callback'


@router.get('/ingresar', response_class=HTMLResponse)
def login_page(request: Request, next: str = '/', db: Session = Depends(get_db)):
    if accounts.from_session(request, db):
        return RedirectResponse(safe_next(next), 303)
    return templates.TemplateResponse(request, 'public/login.html', ctx(request, next=safe_next(next), available=accounts.available(),
                                                                            error=request.session.pop('login_error', None)))


@router.get('/ingresar/google')
def login_google(request: Request, next: str = '/', app: str = '', challenge: str = '', redirect: str = ''):
    if not google_auth.configured():
        return RedirectResponse('/ingresar', 303)
    verifier, pkce_challenge = google_auth.new_pkce()
    flow = {'state': secrets.token_urlsafe(24), 'nonce': secrets.token_urlsafe(24), 'verifier': verifier, 'next': safe_next(next)}
    if app:
        if not allowed_app_redirect(redirect) or not 32 <= len(challenge) <= 128:
            return HTMLResponse('Ingreso de la app inválido. Volvé a la app y probá de nuevo.', status_code=400)
        flow.update(app_redirect=redirect, app_challenge=challenge)
    request.session['google_flow'] = flow
    return RedirectResponse(google_auth.authorization_url(redirect_uri=callback_url(request), state=flow['state'], nonce=flow['nonce'],
                                                          challenge=pkce_challenge), 303)


def _app_back(flow: dict, **params) -> RedirectResponse:
    sep = '&' if '?' in flow['app_redirect'] else '?'
    return RedirectResponse(flow['app_redirect'] + sep + urlencode(params), 303)


@router.get('/cuenta/google/callback')
def google_callback(request: Request, code: str = '', state: str = '', error: str = '', db: Session = Depends(get_db)):
    flow = request.session.pop('google_flow', None) or {}
    if not flow or not state or not secrets.compare_digest(state, flow.get('state', '')):
        request.session['login_error'] = 'El ingreso venció. Probá de nuevo.'
        return RedirectResponse('/ingresar', 303)
    is_app = bool(flow.get('app_redirect'))
    if error or not code:  # el cliente cancelo en Google
        return _app_back(flow, error='cancelado') if is_app else RedirectResponse('/ingresar?' + urlencode({'next': flow.get('next', '/')}), 303)
    try:
        claims = google_auth.exchange_code(code, verifier=flow['verifier'], redirect_uri=callback_url(request), nonce=flow['nonce'])
        acct = accounts.upsert_from_google(db, claims)
    except (google_auth.GoogleAuthError, accounts.AccountError) as exc:
        db.rollback()
        if is_app:
            return _app_back(flow, error=str(exc))
        request.session['login_error'] = str(exc)
        return RedirectResponse('/ingresar', 303)
    audit.log(db, 'client.signup' if acct.just_created else 'client.login', 'client_account', acct.id, new={'via': 'app' if is_app else 'web'}, ip=client_ip(request))
    db.commit()
    if is_app:
        return _app_back(flow, code=accounts.app_code(acct, flow['app_challenge']))
    accounts.start_session(request, acct)
    return RedirectResponse(flow.get('next') or '/', 303)


def _require(request: Request, db: Session):
    acct = accounts.from_session(request, db)
    return acct if acct else RedirectResponse('/ingresar?' + urlencode({'next': '/cuenta'}), 303)


@router.get('/cuenta', response_class=HTMLResponse)
def account_page(request: Request, db: Session = Depends(get_db)):
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    orders = db.scalars(select(Order).options(joinedload(Order.store), selectinload(Order.items)).where(Order.account_id == acct.id)
                        .order_by(Order.created_at.desc()).limit(50)).all()
    return templates.TemplateResponse(request, 'public/account.html', ctx(request, acct=acct, orders=orders, tokens={o.id: order_token(o.id) for o in orders},
                                                                          flash=request.session.pop('account_flash', None)))


@router.post('/cuenta', dependencies=PROTECT)
def account_save(request: Request, first_name: str = Form(''), last_name: str = Form(''), phone: str = Form(''), address: str = Form(''),
                 reference: str = Form(''), db: Session = Depends(get_db)):
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    accounts.save_contact(acct, first_name=first_name, last_name=last_name, phone=phone, address=address, reference=reference)
    db.commit()
    request.session['account_flash'] = 'Datos guardados.'
    return RedirectResponse('/cuenta', 303)


@router.post('/cuenta/salir', dependencies=PROTECT)
def account_logout(request: Request, everywhere: str = Form(''), db: Session = Depends(get_db)):
    acct = accounts.from_session(request, db)
    if acct and everywhere:
        accounts.sign_out_everywhere(acct)  # tambien cierra la app
        db.commit()
    accounts.end_session(request)
    return RedirectResponse('/', 303)


@router.post('/cuenta/eliminar', dependencies=PROTECT)
def account_delete(request: Request, confirm: str = Form(''), db: Session = Depends(get_db)):
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    if confirm != 'si':
        request.session['account_flash'] = 'Para eliminar la cuenta marcá la confirmación.'
        return RedirectResponse('/cuenta#eliminar', 303)
    audit.log(db, 'client.delete', 'client_account', acct.id, new={'via': 'web'}, ip=client_ip(request))
    accounts.delete(db, acct)
    db.commit()
    accounts.end_session(request)
    request.session.pop('orders', None)
    return templates.TemplateResponse(request, 'public/message.html', ctx(request, title='Cuenta eliminada', icon='👋',
                                      message='Eliminamos tu cuenta. Los pedidos que ya hiciste (con los datos de cada entrega) se guardan solo el tiempo que exigen las normas contables y fiscales, y no se usan para nada más.'))
