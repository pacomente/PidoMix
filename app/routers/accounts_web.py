"""Cuentas de clientes en la web (y el ingreso de la app, que abre estas mismas pantallas en el navegador).

  /ingresar                     pantalla para entrar (email y/o Google; la app la abre con ?app=1&challenge=...&redirect=trappi://...)
  /ingresar/email               manda el codigo de 6 numeros al email
  /ingresar/codigo              se escribe el codigo: crea o abre la cuenta (o vuelve a la app con un codigo de un solo uso)
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


def _app_flow(app: str, challenge: str, redirect: str) -> dict | None:
    """Parametros del ingreso de la app ({} si es la web, None si son invalidos)."""
    if not app:
        return {}
    if not allowed_app_redirect(redirect) or not 32 <= len(challenge) <= 128:
        return None
    return {'app_redirect': redirect, 'app_challenge': challenge}


BAD_APP = 'Ingreso de la app inválido. Volvé a la app y probá de nuevo.'


def _login_page(request: Request, next: str, app_flow: dict, error: str | None = None, email: str = '', status_code: int = 200):
    google_qs = urlencode({'next': next, **({'app': '1', 'challenge': app_flow['app_challenge'], 'redirect': app_flow['app_redirect']} if app_flow else {})})
    return templates.TemplateResponse(request, 'public/login.html', ctx(
        request, next=next, available=accounts.available(), email_login=accounts.email_login_available(), google_login=google_auth.configured(),
        google_qs=google_qs, app_flow=app_flow, error=error or request.session.pop('login_error', None), email=email), status_code=status_code)


@router.get('/ingresar', response_class=HTMLResponse)
def login_page(request: Request, next: str = '/', app: str = '', challenge: str = '', redirect: str = '', db: Session = Depends(get_db)):
    app_flow = _app_flow(app, challenge, redirect)
    if app_flow is None:
        return HTMLResponse(BAD_APP, status_code=400)
    if not app_flow and accounts.from_session(request, db):
        return RedirectResponse(safe_next(next), 303)
    return _login_page(request, safe_next(next), app_flow)


@router.post('/ingresar/email', dependencies=PROTECT)
def login_email(request: Request, email: str = Form(''), next: str = Form('/'), app: str = Form(''), challenge: str = Form(''),
                redirect: str = Form('')):
    app_flow = _app_flow(app, challenge, redirect)
    if app_flow is None:
        return HTMLResponse(BAD_APP, status_code=400)
    if not accounts.email_login_available():
        return RedirectResponse('/ingresar', 303)
    try:
        accounts.send_email_code(request, email, client_ip(request), next=safe_next(next), **app_flow)
    except accounts.AccountError as exc:
        return _login_page(request, safe_next(next), app_flow, error=str(exc), email=email[:255], status_code=400)
    return RedirectResponse('/ingresar/codigo', 303)


@router.get('/ingresar/codigo', response_class=HTMLResponse)
def login_code_page(request: Request):
    flow = accounts.pending_email_login(request)
    if not flow:
        request.session['login_error'] = 'El código venció. Pedí uno nuevo.'
        return RedirectResponse('/ingresar', 303)
    return templates.TemplateResponse(request, 'public/login_code.html', ctx(request, email=flow['email'], minutes=accounts.EMAIL_CODE_MINUTES,
                                                                                 error=request.session.pop('login_error', None),
                                                                                 notice=request.session.pop('login_notice', None)))


@router.post('/ingresar/codigo', dependencies=PROTECT)
def login_code(request: Request, code: str = Form(''), db: Session = Depends(get_db)):
    try:
        acct, flow = accounts.verify_email_code(request, db, code)
    except accounts.AccountError as exc:
        db.rollback()
        request.session['login_error'] = str(exc)
        return RedirectResponse('/ingresar/codigo' if accounts.pending_email_login(request) else '/ingresar', 303)
    is_app = bool(flow.get('app_redirect'))
    audit.log(db, 'client.signup' if acct.just_created else 'client.login', 'client_account', acct.id,
              new={'via': 'app' if is_app else 'web', 'method': 'email'}, ip=client_ip(request))
    db.commit()
    if is_app:
        return _app_back(flow, code=accounts.app_code(acct, flow['app_challenge']))
    accounts.start_session(request, acct)
    return RedirectResponse(flow.get('next') or '/', 303)


@router.post('/ingresar/codigo/reenviar', dependencies=PROTECT)
def login_code_resend(request: Request):
    flow = accounts.pending_email_login(request) or request.session.get(accounts.EMAIL_FLOW_KEY)
    if not flow:
        return RedirectResponse('/ingresar', 303)
    extra = {k: flow[k] for k in ('next', 'app_redirect', 'app_challenge') if flow.get(k)}
    try:
        accounts.send_email_code(request, flow['email'], client_ip(request), **extra)
        request.session['login_notice'] = 'Te mandamos un código nuevo. El anterior ya no sirve.'
    except accounts.AccountError as exc:
        request.session['login_error'] = str(exc)
    return RedirectResponse('/ingresar/codigo', 303)


@router.get('/ingresar/google')
def login_google(request: Request, next: str = '/', app: str = '', challenge: str = '', redirect: str = ''):
    app_flow = _app_flow(app, challenge, redirect)
    if app_flow is None:
        return HTMLResponse(BAD_APP, status_code=400)
    if not google_auth.configured():
        # sin Google (o la app 1.5 que abre esta direccion): a la pantalla de ingreso, con los datos de la app
        qs = {'next': safe_next(next), **({'app': '1', 'challenge': challenge, 'redirect': redirect} if app_flow else {})}
        return RedirectResponse('/ingresar?' + urlencode(qs), 303)
    verifier, pkce_challenge = google_auth.new_pkce()
    flow = {'state': secrets.token_urlsafe(24), 'nonce': secrets.token_urlsafe(24), 'verifier': verifier, 'next': safe_next(next), **app_flow}
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
    audit.log(db, 'client.signup' if acct.just_created else 'client.login', 'client_account', acct.id,
              new={'via': 'app' if is_app else 'web', 'method': 'google'}, ip=client_ip(request))
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
