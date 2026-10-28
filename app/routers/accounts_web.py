"""Cuentas de clientes en la web (y el ingreso de la app, que abre estas mismas pantallas en el navegador).

  /ingresar                     pantalla para entrar con el email (la app la abre con ?app=1&challenge=...&redirect=trappi://...)
  /ingresar/email               manda el codigo de 6 numeros al email
  /ingresar/codigo              se escribe el codigo: crea o abre la cuenta (o vuelve a la app con un codigo de un solo uso)
  /ingresar/google              solo redirige a /ingresar (la app 1.4 y 1.5 abren esta direccion)
  /cuenta                       datos, pedidos, salir y eliminar la cuenta
"""
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..db import get_db
from ..models import Order
from ..services import accounts, addresses, audit, csrf
from ..services.formatting import money
from ..services.ratelimit import client_ip
from .public import ctx, order_token, templates

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
    if value and value.startswith('/') and not value.startswith(('//', '/admin', '/ingresar')) and '\\' not in value:
        return value
    return '/'


def allowed_app_redirect(url: str) -> bool:
    """La vuelta a la app: solo el esquema propio (y el de Expo Go en desarrollo)."""
    scheme = urlsplit(url or '').scheme.lower()
    return scheme == 'trappi' or (scheme in ('exp', 'exps') and not settings.is_production)


def _app_flow(app: str, challenge: str, redirect: str) -> dict | None:
    """Parametros del ingreso de la app ({} si es la web, None si son invalidos)."""
    if not app:
        return {}
    if not allowed_app_redirect(redirect) or not 32 <= len(challenge) <= 128:
        return None
    return {'app_redirect': redirect, 'app_challenge': challenge}


BAD_APP = 'Ingreso de la app inválido. Volvé a la app y probá de nuevo.'


def _login_page(request: Request, next: str, app_flow: dict, error: str | None = None, email: str = '', status_code: int = 200):
    return templates.TemplateResponse(request, 'public/login.html', ctx(
        request, next=next, available=accounts.available(), app_flow=app_flow, error=error or request.session.pop('login_error', None),
        email=email), status_code=status_code)


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
    if not accounts.available():
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
              new={'via': 'app' if is_app else 'web'}, ip=client_ip(request))
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
def old_app_login(request: Request, next: str = '/', app: str = '', challenge: str = '', redirect: str = ''):
    """Ya no hay ingreso con Google: la app 1.4 y 1.5 abren esta direccion y se las manda al ingreso con email, con sus datos."""
    app_flow = _app_flow(app, challenge, redirect)
    if app_flow is None:
        return HTMLResponse(BAD_APP, status_code=400)
    qs = {'next': safe_next(next), **({'app': '1', 'challenge': challenge, 'redirect': redirect} if app_flow else {})}
    return RedirectResponse('/ingresar?' + urlencode(qs), 303)


def _app_back(flow: dict, **params) -> RedirectResponse:
    sep = '&' if '?' in flow['app_redirect'] else '?'
    return RedirectResponse(flow['app_redirect'] + sep + urlencode(params), 303)


def _require(request: Request, db: Session):
    acct = accounts.from_session(request, db)
    return acct if acct else RedirectResponse('/ingresar?' + urlencode({'next': '/cuenta'}), 303)


@router.get('/cuenta', response_class=HTMLResponse)
def account_page(request: Request, db: Session = Depends(get_db)):
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    orders = db.scalars(select(Order).options(joinedload(Order.store), selectinload(Order.items)).where(Order.account_id == acct.id)
                        .order_by(Order.created_at.desc()).limit(50)).all()
    from ..services import loyalty, referrals, retention, stamps
    invite = referrals.summary(db, acct)
    if invite:
        db.commit()  # el codigo se crea la primera vez
        invite['url'] = f"{(settings.public_base_url or str(request.base_url)).rstrip('/')}/invitar/{invite['code']}"
    return templates.TemplateResponse(request, 'public/account.html', ctx(request, acct=acct, orders=orders, tokens={o.id: order_token(o.id) for o in orders},
                                                                          stamp_cards=stamps.my_cards(db, acct), invite=invite,
                                                                          points=loyalty.summary(db, acct), voucher=retention.active_voucher(db, acct.id),
                                                                          saved=addresses.for_account(db, acct.id), addr_error=request.session.pop('address_error', None),
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


@router.post('/cuenta/direcciones', dependencies=PROTECT)
def address_add(request: Request, label: str = Form(''), address: str = Form(''), reference: str = Form(''), use_loc: str = Form(''),
                db: Session = Depends(get_db)):
    """Guarda una direccion (con la ubicacion del mapa si la marco). La misma lista aparece en la app."""
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    loc = request.session.get('loc') if use_loc == '1' else None
    try:
        addresses.save(db, acct.id, {'label': label, 'address': address, 'reference': reference,
                                     'lat': (loc or {}).get('lat'), 'lng': (loc or {}).get('lng')})
    except addresses.AddressError as exc:
        request.session['address_error'] = str(exc)
        return RedirectResponse('/cuenta#direcciones', 303)
    db.commit()
    request.session['account_flash'] = 'Dirección guardada.'
    return RedirectResponse('/cuenta#direcciones', 303)


@router.post('/cuenta/direcciones/{address_id}/borrar', dependencies=PROTECT)
def address_delete(address_id: int, request: Request, db: Session = Depends(get_db)):
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    row = addresses.get(db, acct.id, address_id)
    if row:
        db.delete(row)
        db.commit()
        request.session['account_flash'] = 'Dirección borrada.'
    return RedirectResponse('/cuenta#direcciones', 303)


@router.post('/cuenta/recomendaciones', dependencies=PROTECT)
def account_personalize(request: Request, personalize: str = Form(''), db: Session = Depends(get_db)):
    """Prender o apagar "Recomendado para vos" (usa solo los pedidos, favoritos y calificaciones de esta cuenta)."""
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    acct.personalize = personalize == '1'
    db.commit()
    request.session['account_flash'] = 'Listo: vas a ver recomendaciones según tus pedidos.' if acct.personalize else 'Listo: no usamos tus pedidos para recomendarte.'
    return RedirectResponse('/cuenta#recomendaciones', 303)


@router.post('/cuenta/novedades', dependencies=PROTECT)
def account_marketing(request: Request, marketing: str = Form(''), db: Session = Depends(get_db)):
    """Aceptar o no novedades y promociones por email o notificacion (arranca en no)."""
    acct = _require(request, db)
    if isinstance(acct, RedirectResponse): return acct
    acct.marketing_opt_in = marketing == '1'
    db.commit()
    request.session['account_flash'] = 'Listo: te vamos a avisar de novedades y descuentos.' if acct.marketing_opt_in else 'Listo: no te vamos a mandar novedades.'
    return RedirectResponse('/cuenta#novedades', 303)


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
    return templates.TemplateResponse(request, 'public/message.html', ctx(request, title='Cuenta eliminada',
                                      message='Eliminamos tu cuenta. Los pedidos que ya hiciste (con los datos de cada entrega) se guardan solo el tiempo que exigen las normas contables y fiscales, y no se usan para nada más.'))


# ---------- QR de Puntos Trappi de una compra en el mostrador (programa Trappi Caja) ----------

@router.get('/puntos/q/{code}', response_class=HTMLResponse)
def points_claim_page(code: str, request: Request, db: Session = Depends(get_db)):
    from ..models import Store
    from ..services import pos
    c, problem = pos.claim_status(db, code)
    acct = accounts.from_session(request, db)
    store = db.get(Store, c.store_id) if c else None
    return templates.TemplateResponse(request, 'public/points_claim.html', ctx(request, claim=c, problem=problem, store=store, acct=acct, code=code.upper(),
                                                                               done=False), status_code=404 if not c else 200)


@router.post('/puntos/q/{code}', dependencies=PROTECT)
def points_claim(code: str, request: Request, db: Session = Depends(get_db)):
    from ..models import Store
    from ..services import loyalty, pos
    acct = accounts.from_session(request, db)
    if acct is None:
        return RedirectResponse(f'/ingresar?next=/puntos/q/{code}', 303)
    try:
        c = pos.claim(db, code, acct)
        db.commit()
    except pos.PosError as exc:
        db.rollback()
        c, _ = pos.claim_status(db, code)
        return templates.TemplateResponse(request, 'public/points_claim.html', ctx(request, claim=c, problem=str(exc), store=db.get(Store, c.store_id) if c else None,
                                                                                   acct=acct, code=code.upper(), done=False), status_code=409)
    return templates.TemplateResponse(request, 'public/points_claim.html', ctx(request, claim=c, problem=None, store=db.get(Store, c.store_id), acct=acct,
                                                                               code=code.upper(), done=True, points=loyalty.summary(db, acct)))


# ---------- pagar con Puntos Trappi en el mostrador (QR fijo del local) ----------

def _counter_page(request, db, counter, acct, **extra):
    from ..services import pos_points
    store = pos_points.store_by_counter(db, counter)
    data = dict(store=store, acct=acct, counter=counter, problem=None, payment=None, quote=None, done=False, code='',
                enabled=pos_points.enabled(db, store))
    data.update(extra)
    if not store:
        data['problem'] = 'Este QR no es de ningún local de Trappi.'
    elif not data['enabled'] and not data['done']:
        data['problem'] = 'Este local no acepta Puntos Trappi en el mostrador por ahora.'
    return templates.TemplateResponse(request, 'public/points_counter.html', ctx(request, **data), status_code=404 if not store else 200)


@router.get('/puntos/local/{counter}', response_class=HTMLResponse)
def points_counter_page(counter: str, request: Request, codigo: str = '', db: Session = Depends(get_db)):
    from ..services import pos_points
    acct = accounts.from_session(request, db)
    if acct is None or not codigo:
        return _counter_page(request, db, counter, acct)
    try:
        store, p, q = pos_points.lookup(db, counter, codigo, acct)
    except pos_points.PointsPayError as exc:
        return _counter_page(request, db, counter, acct, code_error=str(exc), code=codigo[:4])
    return _counter_page(request, db, counter, acct, payment=p, quote=q, code=p.code)


@router.post('/puntos/local/{counter}', dependencies=PROTECT)
def points_counter_confirm(counter: str, request: Request, codigo: str = Form(''), db: Session = Depends(get_db)):
    from ..services import loyalty, pos_points
    acct = accounts.from_session(request, db)
    if acct is None:
        return RedirectResponse(f'/ingresar?next=/puntos/local/{counter}', 303)
    try:
        store, p, _ = pos_points.lookup(db, counter, codigo, acct)
        pos_points.confirm(db, store, p, acct)
        db.commit()
    except pos_points.PointsPayError as exc:
        db.rollback()
        return _counter_page(request, db, counter, acct, code_error=str(exc), code=codigo[:4])
    return _counter_page(request, db, counter, acct, payment=p, done=True, points=loyalty.summary(db, acct))


@router.get('/invitar/{code}', response_class=HTMLResponse)
def invite_link(code: str, request: Request, db: Session = Depends(get_db)):
    """Link de "Invitá a un amigo": queda guardado para cuando el amigo cree su cuenta."""
    from ..services import referrals
    if accounts.from_session(request, db) is not None:
        return RedirectResponse('/', 303)  # ya tiene cuenta: las invitaciones son solo para cuentas nuevas
    inviter = referrals.remember(request, db, code)
    if inviter is None:
        return RedirectResponse('/', 303)
    cfg = referrals.config(db)
    who = inviter.first_name or 'Un amigo'
    minimum = f' de {money(cfg["min_order"])} o más' if cfg['min_order'] else ''
    return templates.TemplateResponse(request, 'public/message.html', ctx(
        request, title=f'{who} te invitó a Trappi',
        message=f'Creá tu cuenta y, cuando recibas tu primer pedido{minimum}, ganás {cfg["friend"]} Puntos Trappi para usar en tus próximas compras.',
        action=('Crear mi cuenta', '/ingresar?next=/')))
