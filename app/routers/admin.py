from pathlib import Path
import csv
import io
import time
from urllib.parse import quote, urlencode
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import and_, case, desc, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload
from ..db import get_db
from ..models import Banner, Category, ClientAccount, WithdrawalRequest, Coupon, Courier, Customer, DeliveryZone, ModifierGroup, ModifierOption, Order, OrderEvent, OrderItem, OrderStatus, Product, ProductStatus, Review, Role, Setting, Store, StoreCategory, StoreHour, StoreSection, StoreStatus, User
from ..services.auth import bump_session, current_user, end_other_sessions, hash_password, start_session, verify_password
from ..services.cloudinary_service import delete, upload
from .public import order_token
from ..services.formatting import money
from ..services.forms import form_float, form_int, required_float
from ..services.geo import MAX_ZONE_KM, parse_location
from ..config import settings
from ..services import platform as platform_settings
from ..services.images import cdn
from ..services.ratelimit import PersistentRateLimiter, client_ip
from ..services.store_hours import LOCAL_TZ, is_open, local_day_start_utc, local_now, to_local
from ..services import accounts, audit, crypto, csrf, dispatch, finance, mercadopago, payments, plans, push, totp
from ..services.orders import FINAL, FLOW, advance, allowed_statuses, customer_message, minutes_since, previous, set_status
from ..services.reviews import MAX_TEXT as REVIEW_MAX_TEXT, public_name, rating_summary, refresh_store_rating

from ..asset_version import ASSET_VERSION
router = APIRouter()
login_limiter = PersistentRateLimiter('admin-login', limit=5, window_seconds=300)
# X-Forwarded-For lo puede inventar el cliente: ademas de IP+email se limita por cuenta,
# asi rotar el header no permite seguir probando contraseñas contra el mismo email.
account_limiter = PersistentRateLimiter('admin-account', limit=20, window_seconds=900)
# codigos de la verificacion en dos pasos: por usuario, para que no se puedan adivinar
totp_limiter = PersistentRateLimiter('admin-2fa', limit=5, window_seconds=300)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))
templates.env.filters['cdn'] = cdn
templates.env.globals['platform'] = platform_settings.current  # mapas, mantenimiento (con cache)
templates.env.globals['ASSET_VERSION'] = ASSET_VERSION
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # límite de Cloudinary (plan gratis); al subir se achica y recomprime
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/heic', 'image/heif'}

STATUS_TONE = {
    'ACTIVA': 'good', 'ACTIVO': 'good', 'ENTREGADO': 'good', 'LISTO': 'good',
    'INACTIVA': 'neutral', 'INACTIVO': 'neutral',
    'CERRADA': 'bad', 'CANCELADO': 'bad', 'SIN_STOCK': 'warn',
    'PENDIENTE': 'warn', 'CONFIRMADO': 'accent', 'PREPARANDO': 'accent', 'EN_CAMINO': 'accent',
}


def _human_label(value: str) -> str:
    return str(value).replace('_', ' ').capitalize()


def wa_link(phone, text=None):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if not digits: return ''
    return f'https://wa.me/{digits}' + (f'?text={quote(text)}' if text else '')


templates.env.globals['advance'] = advance
templates.env.globals['previous_status'] = previous
templates.env.globals['customer_message'] = customer_message
templates.env.globals['minutes_since'] = minutes_since
templates.env.globals['wa_link'] = wa_link
templates.env.globals['public_name'] = public_name
templates.env.globals['store_is_open'] = is_open
templates.env.globals['payments'] = payments
templates.env.globals['pickup_info'] = dispatch.pickup_info
templates.env.filters['tone'] = lambda v: STATUS_TONE.get(str(v), 'neutral')
templates.env.filters['human'] = _human_label


templates.env.globals['csrf_input'] = csrf.csrf_input
templates.env.globals['csrf_meta'] = csrf.csrf_meta
templates.env.filters['money'] = money


def auth(request, db):
    u = current_user(request, db)
    if not (u and u.active and u.role in (Role.SUPERADMIN, Role.STORE_ADMIN)):
        return None
    # multi-ciudad: el superadmin puede mirar una sola ciudad (se elige en el menu); los locales ven lo suyo
    u.city_filter = request.session.get('admin_city') if u.role == Role.SUPERADMIN else None
    return u


def city_filter(u) -> int | None:
    return getattr(u, 'city_filter', None)


def stores_in_city(city_id: int):
    return select(Store.id).where(Store.city_id == city_id)


def safe_next(value: str | None) -> str:
    """Destino despues del login: solo rutas internas del panel (evita redirecciones abiertas)."""
    return value if value and value.startswith('/admin') and not value.startswith('/admin/login') and '//' not in value and '\\' not in value else '/admin'


# lo unico que puede usar el superadmin mientras no active la verificacion en dos pasos obligatoria
TWO_FACTOR_SETUP_PATHS = ('/admin/account/2fa', '/admin/logout')


def must_setup_2fa(u) -> bool:
    return u.role == Role.SUPERADMIN and settings.require_admin_2fa and not totp.enabled(u)


def guard(request, db):
    u = auth(request, db)
    if u:
        if must_setup_2fa(u) and not request.url.path.startswith(TWO_FACTOR_SETUP_PATHS):
            return RedirectResponse('/admin/account/2fa', 303)
        return u
    # el formulario de login no tiene action: al enviarse conserva ?next= y vuelve a esta pantalla
    nxt = request.url.path if request.method == 'GET' and request.url.path not in ('/admin', '/admin/') else ''
    return RedirectResponse('/admin/login' + (f'?{urlencode({"next": nxt})}' if nxt else ''), 303)


async def form_data(request: Request):
    return await request.form()


def can_manage_store(user, store_id):
    return user.role == Role.SUPERADMIN or user.store_id == store_id


def image_upload(file: UploadFile | None, folder: str):
    if not file or not file.filename:
        return None, None
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError('Formato de imagen no permitido.')
    content = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError('La imagen supera el máximo de 10 MB.')
    return upload(content, folder)


def safe_slug(value: str) -> str:
    return '-'.join(value.strip().lower().split())


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, 'admin/login.html')


@router.post('/login')
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    ip = client_ip(request)
    account = email.strip().lower()
    key = f'{ip}|{account}'
    if login_limiter.blocked(key) or account_limiter.blocked(account):
        return templates.TemplateResponse(request, 'admin/login.html', {'error': 'Demasiados intentos. Esperá unos minutos e intentá de nuevo.'}, status_code=429)
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not u or not u.active or not verify_password(password, u.password_hash):
        login_limiter.hit(key); account_limiter.hit(account)
        return templates.TemplateResponse(request, 'admin/login.html', {'error': 'Email o contraseña incorrectos.'}, status_code=401)
    login_limiter.reset(key); account_limiter.reset(account)
    nxt = safe_next(request.query_params.get('next'))
    if totp.enabled(u):
        # falta el segundo paso: la sesion todavia no tiene usuario
        request.session.clear()
        request.session['2fa'] = {'uid': u.id, 'at': int(time.time()), 'next': nxt}
        return RedirectResponse('/admin/login/2fa', 303)
    start_session(request, u)
    return RedirectResponse('/admin/account/2fa' if must_setup_2fa(u) else nxt, 303)


TWO_FACTOR_WINDOW = 300  # segundos para poner el codigo despues de la contrasena


def _pending_2fa(request, db):
    data = request.session.get('2fa') or {}
    if not data or time.time() - float(data.get('at') or 0) > TWO_FACTOR_WINDOW:
        return None, data
    u = db.get(User, data.get('uid'))
    return (u if u and u.active and totp.enabled(u) else None), data


@router.get('/login/2fa', response_class=HTMLResponse)
def login_2fa_page(request: Request, db: Session = Depends(get_db)):
    u, _ = _pending_2fa(request, db)
    if not u:
        request.session.pop('2fa', None)
        return RedirectResponse('/admin/login', 303)
    return templates.TemplateResponse(request, 'admin/login_2fa.html', {})


@router.post('/login/2fa')
def login_2fa(request: Request, code: str = Form(''), db: Session = Depends(get_db)):
    u, data = _pending_2fa(request, db)
    if not u:
        request.session.pop('2fa', None)
        return templates.TemplateResponse(request, 'admin/login.html', {'error': 'Pasó mucho tiempo. Volvé a poner tu email y contraseña.'}, status_code=401)
    key = str(u.id)
    if totp_limiter.blocked(key):
        return templates.TemplateResponse(request, 'admin/login_2fa.html', {'error': 'Demasiados códigos incorrectos. Esperá unos minutos.'}, status_code=429)
    code = (code or '').strip()
    used_recovery = False
    ok = totp.check_user(u, code)
    if not ok and len(code) > totp.DIGITS:
        ok = used_recovery = totp.use_recovery_code(u, code)
    if not ok:
        totp_limiter.hit(key)
        return templates.TemplateResponse(request, 'admin/login_2fa.html', {'error': 'Código incorrecto o ya usado.'}, status_code=401)
    totp_limiter.reset(key)
    if used_recovery:
        audit.log(db, 'user.2fa.recovery_code', 'user', u.id, user=u, new={'left': totp.recovery_left(u)}, ip=client_ip(request))
    db.commit()
    start_session(request, u)
    if used_recovery:
        request.session['account_flash'] = ['error', f'Entraste con un código de recuperación. Te quedan {totp.recovery_left(u)}. Si perdiste el celular, volvé a configurar la verificación.']
        return RedirectResponse('/admin/account', 303)
    return RedirectResponse(safe_next(data.get('next')), 303)


@router.get('/account', response_class=HTMLResponse)
def account(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    return templates.TemplateResponse(request, 'admin/account.html', {
        'user': u, 'two_factor': totp.enabled(u), 'recovery_left': totp.recovery_left(u), 'two_factor_required': u.role == Role.SUPERADMIN and settings.require_admin_2fa,
        'recovery_codes': request.session.pop('recovery_codes', None), 'flash': request.session.pop('account_flash', None)})


@router.post('/account/password')
def account_password(request: Request, current: str = Form(...), new: str = Form(...), confirm: str = Form(...), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not verify_password(current, u.password_hash): return RedirectResponse('/admin/account?error=pw_current', 303)
    if len(new) < 8 or new != confirm: return RedirectResponse('/admin/account?error=pw_new', 303)
    u.password_hash = hash_password(new)
    end_other_sessions(request, u)  # si alguien tenia la contrasena vieja y estaba adentro, queda afuera
    audit.log(db, 'user.password', 'user', u.id, user=u, ip=client_ip(request))
    db.commit()
    request.session['account_flash'] = ['ok', 'Contraseña cambiada. Se cerraron tus sesiones en otros dispositivos.']
    return RedirectResponse('/admin/account', 303)


@router.post('/account/sessions')
def account_sessions(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    end_other_sessions(request, u)
    audit.log(db, 'user.sessions.close', 'user', u.id, user=u, ip=client_ip(request))
    db.commit()
    request.session['account_flash'] = ['ok', 'Listo: se cerraron tus sesiones en los otros dispositivos.']
    return RedirectResponse('/admin/account', 303)


@router.get('/account/2fa', response_class=HTMLResponse)
def account_2fa_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if totp.enabled(u):
        return RedirectResponse('/admin/account', 303)
    secret = totp.secret_of(u)
    if not secret:  # secreto nuevo (todavia sin activar) guardado cifrado
        secret = totp.new_secret()
        u.totp_secret_enc = crypto.encrypt(secret)
        db.commit()
    uri = totp.provisioning_uri(secret, u.email)
    return templates.TemplateResponse(request, 'admin/account_2fa.html', {
        'user': u, 'qr': totp.qr_svg(uri), 'secret': totp.group(secret), 'required': must_setup_2fa(u),
        'flash': request.session.pop('account_flash', None)})


@router.post('/account/2fa')
def account_2fa_enable(request: Request, code: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if totp.enabled(u) or not u.totp_secret_enc:
        return RedirectResponse('/admin/account', 303)
    key = str(u.id)
    if totp_limiter.blocked(key):
        request.session['account_flash'] = ['error', 'Demasiados códigos incorrectos. Esperá unos minutos.']
        return RedirectResponse('/admin/account/2fa', 303)
    if not totp.check_user(u, code):
        totp_limiter.hit(key)
        request.session['account_flash'] = ['error', 'El código no coincide. Fijate que la hora del celular esté bien y probá con el código nuevo.']
        return RedirectResponse('/admin/account/2fa', 303)
    totp_limiter.reset(key)
    u.totp_enabled_at = datetime.utcnow()
    codes = totp.new_recovery_codes(u)
    end_other_sessions(request, u)
    audit.log(db, 'user.2fa.enable', 'user', u.id, user=u, ip=client_ip(request))
    db.commit()
    request.session['recovery_codes'] = codes
    request.session['account_flash'] = ['ok', 'Verificación en dos pasos activada. Guardá los códigos de recuperación.']
    return RedirectResponse('/admin/account', 303)


@router.post('/account/2fa/codigos')
def account_2fa_codes(request: Request, code: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not totp.enabled(u) or totp_limiter.blocked(str(u.id)) or not totp.check_user(u, code):
        if totp.enabled(u): totp_limiter.hit(str(u.id))
        request.session['account_flash'] = ['error', 'Código incorrecto: no se generaron códigos nuevos.']
        return RedirectResponse('/admin/account', 303)
    codes = totp.new_recovery_codes(u)
    audit.log(db, 'user.2fa.recovery_new', 'user', u.id, user=u, ip=client_ip(request))
    db.commit()
    request.session['recovery_codes'] = codes
    request.session['account_flash'] = ['ok', 'Códigos de recuperación nuevos. Los anteriores ya no sirven.']
    return RedirectResponse('/admin/account', 303)


@router.post('/account/2fa/desactivar')
def account_2fa_disable(request: Request, password: str = Form(''), code: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not totp.enabled(u):
        return RedirectResponse('/admin/account', 303)
    if u.role == Role.SUPERADMIN and settings.require_admin_2fa:
        request.session['account_flash'] = ['error', 'Para el superadmin la verificación en dos pasos es obligatoria.']
        return RedirectResponse('/admin/account', 303)
    if totp_limiter.blocked(str(u.id)) or not verify_password(password, u.password_hash) or not totp.check_user(u, code):
        totp_limiter.hit(str(u.id))
        request.session['account_flash'] = ['error', 'Contraseña o código incorrectos: la verificación sigue activa.']
        return RedirectResponse('/admin/account', 303)
    totp.disable(u)
    end_other_sessions(request, u)
    audit.log(db, 'user.2fa.disable', 'user', u.id, user=u, ip=client_ip(request))
    db.commit()
    request.session['account_flash'] = ['ok', 'Verificación en dos pasos desactivada.']
    return RedirectResponse('/admin/account', 303)


@router.get('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/admin/login', 303)


@router.get('', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    is_super = u.role == Role.SUPERADMIN
    of = _order_scope(u)  # el local ve lo suyo; el superadmin, la ciudad que esta mirando (o todas)
    valid = Order.status != OrderStatus.CANCELADO
    today, month = local_day_start_utc(), local_day_start_utc(local_now().day - 1)
    in_today, in_month = and_(Order.created_at >= today, valid), and_(Order.created_at >= month, valid)
    # Una sola pasada sobre los pedidos (agregacion condicional) en vez de una consulta por numero.
    today_orders, today_revenue, month_orders, month_revenue, pending, in_progress = db.execute(select(
        func.count(case((in_today, 1))),
        func.coalesce(func.sum(case((in_today, Order.total))), 0),
        func.count(case((in_month, 1))),
        func.coalesce(func.sum(case((in_month, Order.total))), 0),
        func.count(case((Order.status == OrderStatus.PENDIENTE, 1))),
        func.count(case((Order.status.in_([OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO]), 1))),
    ).where(*of)).one()
    stats = {
        'today_orders': today_orders, 'today_revenue': today_revenue, 'pending': pending, 'in_progress': in_progress,
        'month_revenue': month_revenue, 'avg_ticket': (Decimal(month_revenue) / month_orders) if month_orders else 0,
        'products': db.scalar(select(func.count(Product.id)).where(Product.deleted.is_(False), *([] if is_super else [Product.store_id == u.store_id]))) or 0,
        'stores': (db.scalar(select(func.count(Store.id))) or 0) if is_super else 1,
        'customers': (db.scalar(select(func.count(Customer.id))) or 0) if is_super else (db.scalar(select(func.count(func.distinct(Order.customer_id))).where(*of)) or 0),
    }
    top = db.execute(select(OrderItem.product_name, func.sum(OrderItem.quantity).label('qty'), func.sum(OrderItem.quantity * OrderItem.unit_price).label('amount')).join(Order, Order.id == OrderItem.order_id).where(Order.created_at >= month, valid, *of).group_by(OrderItem.product_name).order_by(desc('qty')).limit(5)).all()
    recent = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(*of).order_by(Order.created_at.desc()).limit(6)).all()
    my_store = db.scalar(select(Store).options(selectinload(Store.hours)).where(Store.id == u.store_id)) if not is_super and u.store_id else None
    # ventas de los ultimos 7 dias para el mini grafico
    first_day = (local_now() - timedelta(days=6)).date()
    week = {first_day + timedelta(days=i): Decimal(0) for i in range(7)}
    for created, total in db.execute(select(Order.created_at, Order.total).where(Order.created_at >= local_day_start_utc(6), valid, *of)):
        day = to_local(created).date()
        if day in week: week[day] += Decimal(total)
    peak = max(week.values()) or 1
    weekdays = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    week_series = [{'label': 'Hoy' if d == local_now().date() else weekdays[d.weekday()], 'date': d.strftime('%d/%m'), 'revenue': v, 'pct': int(v * 100 / peak)} for d, v in week.items()]
    return templates.TemplateResponse(request, 'admin/dashboard.html', {'user': u, 's': stats, 'top': top, 'recent': recent, 'my_store': my_store, 'week': week_series, 'week_total': sum(week.values()), 'hour': local_now().hour})


@router.get('/stores', response_class=HTMLResponse)
def store_list(request: Request, db: Session = Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stmt=select(Store).options(joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.admins), selectinload(Store.zones)).order_by(Store.name)
    if u.role != Role.SUPERADMIN: stmt=stmt.where(Store.id==u.store_id)
    elif city_filter(u): stmt=stmt.where(Store.city_id==city_filter(u))
    stores=db.scalars(stmt).all()
    categories=db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse(request, 'admin/stores.html', {'user':u,'stores':stores,'categories':categories})


@router.post('/stores')
def store_create(request: Request, db: Session = Depends(get_db)):
    """El alta de comercios es una sola: /admin/comercios/nuevo (con plan y acceso)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    return RedirectResponse('/admin/comercios/nuevo' if u.role == Role.SUPERADMIN else '/admin/stores', 303)


@router.post('/stores/{store_id}/edit')
def store_edit(store_id:int,request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),phone:str=Form(''),whatsapp:str=Form(''),transfer_alias:str=Form(''),address:str=Form(''),store_category_id:str|None=Form(None),delivery_enabled:bool=Form(False),delivery_cost:str=Form('0'),minimum_order:str=Form('0'),estimated_minutes:str=Form('30'),featured:bool=Form(False),logo:UploadFile|None=File(None),cover:UploadFile|None=File(None),db:Session=Depends(get_db)):
    store_category_id = form_int(store_category_id); delivery_cost = form_float(delivery_cost, 0); minimum_order = form_float(minimum_order, 0); estimated_minutes = form_int(estimated_minutes, 30)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=db.get(Store,store_id)
    if not s or not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    slug=safe_slug(slug)
    duplicate=db.scalar(select(Store).where(Store.slug==slug, Store.id!=store_id))
    if duplicate: return RedirectResponse('/admin/stores?error=slug',303)
    try:
        s.name=name.strip(); s.slug=slug; s.description=description.strip(); s.phone=phone.strip(); s.whatsapp=whatsapp.strip(); s.transfer_alias=transfer_alias.strip()[:120] or None; s.address=address.strip(); s.store_category_id=store_category_id
        s.delivery_enabled=delivery_enabled; s.delivery_cost=max(0,delivery_cost); s.minimum_order=max(0,minimum_order); s.estimated_minutes=max(1,estimated_minutes)
        if u.role == Role.SUPERADMIN: s.featured=featured
        if logo and logo.filename:
            new_url,new_pid=image_upload(logo,'pidomix/stores/logos')
            if s.logo_public_id: delete(s.logo_public_id)
            s.logo_url,s.logo_public_id=new_url,new_pid
        if cover and cover.filename:
            new_url,new_pid=image_upload(cover,'pidomix/stores/covers')
            if s.cover_public_id: delete(s.cover_public_id)
            s.cover_url,s.cover_public_id=new_url,new_pid
        db.commit()
    except (ValueError, RuntimeError):
        db.rollback(); return RedirectResponse('/admin/stores?error=image',303)
    return RedirectResponse('/admin/stores',303)


@router.get('/stores/{store_id}/zona', response_class=HTMLResponse)
def store_zone(store_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.scalar(select(Store).options(selectinload(Store.zones)).where(Store.id == store_id))
    if not s or not can_manage_store(u, store_id): return RedirectResponse('/admin/stores', 303)
    zones = [{'max_km': float(z.max_km), 'cost': float(z.cost)} for z in s.zones]
    return templates.TemplateResponse(request, 'admin/store_zone.html', {'user': u, 's': s, 'zones': zones, 'map_center': settings.map_default_center})


@router.post('/stores/{store_id}/zona')
def store_zone_save(store_id: int, request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.scalar(select(Store).options(selectinload(Store.zones)).where(Store.id == store_id))
    if not s or not can_manage_store(u, store_id): return RedirectResponse('/admin/stores', 303)
    back = f'/admin/stores/{store_id}/zona'
    if form.get('clear'):
        s.lat = s.lng = None
        s.zones.clear(); db.commit()
        return RedirectResponse(back + '?ok=1', 303)
    loc = parse_location({'lat': form.get('lat'), 'lng': form.get('lng')})
    if not loc: return RedirectResponse(back + '?error=location', 303)
    tiers = {}
    for km, cost in zip(form.getlist('max_km'), form.getlist('cost')):
        try:
            km_value, cost_value = Decimal(str(km).replace(',', '.')), Decimal(str(form_float(cost, 0)))
        except ArithmeticError:
            continue
        if 0 < km_value <= MAX_ZONE_KM and cost_value >= 0:
            tiers[km_value.quantize(Decimal('0.01'))] = cost_value.quantize(Decimal('0.01'))  # mismo radio dos veces: gana el ultimo
    if not tiers: return RedirectResponse(back + '?error=zones', 303)
    s.lat, s.lng = loc['lat'], loc['lng']
    s.zones.clear(); db.flush()
    s.zones.extend(DeliveryZone(max_km=km, cost=cost) for km, cost in sorted(tiers.items()))
    db.commit()
    return RedirectResponse(back + '?ok=1', 303)


@router.post('/stores/{store_id}/owner')
def store_owner_create(store_id:int,request:Request,owner_email:str=Form(...),owner_password:str=Form(...),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN or not db.get(Store,store_id): return RedirectResponse('/admin/stores',303)
    owner_email=owner_email.strip().lower()
    if not owner_email or len(owner_password)<8 or db.scalar(select(User).where(User.email==owner_email)):
        return RedirectResponse('/admin/stores?error=owner',303)
    db.add(User(email=owner_email,password_hash=hash_password(owner_password),role=Role.STORE_ADMIN,store_id=store_id)); db.commit()
    return RedirectResponse('/admin/stores?ok=owner_created',303)


@router.post('/stores/{store_id}/toggle')
def store_toggle(store_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=db.get(Store,store_id)
    if not s or not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    s.status = StoreStatus.INACTIVA if s.status != StoreStatus.INACTIVA else StoreStatus.ACTIVA
    db.commit(); return RedirectResponse('/admin/stores',303)


@router.post('/stores/{store_id}/hours')
def store_hours(store_id: int, request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not can_manage_store(u, store_id) or not db.get(Store, store_id): return RedirectResponse('/admin/stores', 303)
    existing = {h.weekday: h for h in db.scalars(select(StoreHour).where(StoreHour.store_id == store_id))}
    for weekday in range(7):
        op, cl = (form.get(f'd{weekday}_open') or '09:00'), (form.get(f'd{weekday}_close') or '21:00')
        hour = existing.get(weekday)
        if not hour:
            hour = StoreHour(store_id=store_id, weekday=weekday); db.add(hour)
        hour.open_time, hour.close_time, hour.closed = op[:5], cl[:5], form.get(f'd{weekday}_closed') is not None
    db.commit()
    return RedirectResponse('/admin/stores?ok=hours', 303)


@router.post('/stores/{store_id}/open-close')
def store_open_close(store_id: int, request: Request, back: str = Form('/admin'), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.get(Store, store_id)
    if s and can_manage_store(u, store_id) and s.status != StoreStatus.INACTIVA:
        s.status = StoreStatus.CERRADA if s.status == StoreStatus.ACTIVA else StoreStatus.ACTIVA; db.commit()
    return RedirectResponse(back if back.startswith('/admin') else '/admin', 303)


@router.get('/store-categories', response_class=HTMLResponse)
def store_categories(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(StoreCategory).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse(request, 'admin/store_categories.html', {'user':u,'categories':rows})


@router.post('/store-categories')
def store_category_create(request:Request,name:str=Form(...),slug:str=Form(...),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    slug=safe_slug(slug)
    if not db.scalar(select(StoreCategory).where((StoreCategory.slug==slug)|(StoreCategory.name==name.strip()))):
        db.add(StoreCategory(name=name.strip(),slug=slug)); db.commit()
    return RedirectResponse('/admin/store-categories',303)


@router.post('/store-categories/{category_id}/toggle')
def store_category_toggle(category_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    c=db.get(StoreCategory,category_id)
    if c and u.role==Role.SUPERADMIN: c.active=not c.active; db.commit()
    return RedirectResponse('/admin/store-categories',303)


@router.get('/categories', response_class=HTMLResponse)
def categories(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(Category).order_by(Category.display_order,Category.name)).all()
    return templates.TemplateResponse(request, 'admin/categories.html', {'user':u,'categories':rows})


@router.post('/categories')
def category_create(request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),display_order:str=Form('0'),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    display_order = form_int(display_order, 0)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    slug=safe_slug(slug)
    if db.scalar(select(Category).where((Category.slug==slug)|(Category.name==name.strip()))): return RedirectResponse('/admin/categories?error=duplicate',303)
    try:
        image_url=image_pid=None
        if file and file.filename: image_url,image_pid=image_upload(file,'pidomix/categories')
        db.add(Category(name=name.strip(),slug=slug,description=description.strip(),image_url=image_url,image_public_id=image_pid,display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/categories?error=image',303)
    return RedirectResponse('/admin/categories',303)


@router.post('/categories/{category_id}/edit')
def category_edit(category_id:int,request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),display_order:str=Form('0'),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    display_order = form_int(display_order, 0)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    c=db.get(Category,category_id)
    if not c: return RedirectResponse('/admin/categories',303)
    slug=safe_slug(slug)
    if db.scalar(select(Category).where(Category.slug==slug,Category.id!=category_id)): return RedirectResponse('/admin/categories?error=duplicate',303)
    try:
        c.name=name.strip(); c.slug=slug; c.description=description.strip(); c.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/categories')
            if c.image_public_id: delete(c.image_public_id)
            c.image_url,c.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/categories?error=image',303)
    return RedirectResponse('/admin/categories',303)


@router.post('/categories/{category_id}/toggle')
def category_toggle(category_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    c=db.get(Category,category_id)
    if c: c.active=not c.active; db.commit()
    return RedirectResponse('/admin/categories',303)


@router.get('/products', response_class=HTMLResponse)
def products(request:Request,q:str='',db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stores_stmt=select(Store).order_by(Store.name)
    product_stmt=select(Product).options(joinedload(Product.store),joinedload(Product.category),selectinload(Product.modifier_groups)).order_by(Product.store_id,Product.display_order,Product.name)
    if u.role != Role.SUPERADMIN:
        stores_stmt=stores_stmt.where(Store.id==u.store_id); product_stmt=product_stmt.where(Product.store_id==u.store_id)
    elif city_filter(u):
        stores_stmt=stores_stmt.where(Store.city_id==city_filter(u)); product_stmt=product_stmt.where(Product.store_id.in_(stores_in_city(city_filter(u))))
    product_stmt=product_stmt.where(Product.deleted.is_(False))
    if q.strip(): product_stmt=product_stmt.where(Product.name.ilike(f'%{q.strip()}%'))
    stores=db.scalars(stores_stmt).all(); rows=db.scalars(product_stmt).all(); cats=db.scalars(select(Category).where(Category.active).order_by(Category.name)).all()
    sections=db.scalars(select(StoreSection).where(StoreSection.store_id==u.store_id,StoreSection.active).order_by(StoreSection.display_order)).all() if u.role != Role.SUPERADMIN and u.store_id else []
    return templates.TemplateResponse(request, 'admin/products.html', {'user':u,'products':rows,'stores':stores,'categories':cats,'sections':sections,'q':q})


@router.post('/products')
def product_create(request:Request,name:str=Form(...),price:str=Form(...),store_id:int=Form(...),category_id:str|None=Form(None),section_id:str|None=Form(None),description:str=Form(''),previous_price:str|None=Form(None),stock:str|None=Form(None),featured:bool=Form(False),display_order:str=Form('0'),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    price = required_float(price, 'price'); category_id = form_int(category_id); section_id = form_int(section_id); previous_price = form_float(previous_price); stock = form_int(stock); display_order = form_int(display_order, 0)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if not can_manage_store(u,store_id): return RedirectResponse('/admin/products',303)
    try:
        url=pid=None
        if file and file.filename: url,pid=image_upload(file,'pidomix/products')
        db.add(Product(name=name.strip(),price=max(0,price),store_id=store_id,category_id=category_id,section_id=section_id,description=description.strip(),previous_price=previous_price, image_url=url,image_public_id=pid,stock=stock,featured=featured,display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/products?error=image',303)
    except SQLAlchemyError: db.rollback(); return RedirectResponse('/admin/products?error=db',303)
    return RedirectResponse('/admin/products',303)


@router.post('/products/{product_id}/edit')
def product_edit(product_id:int,request:Request,name:str=Form(...),price:str=Form(...),store_id:int=Form(...),category_id:str|None=Form(None),section_id:str|None=Form(None),description:str=Form(''),previous_price:str|None=Form(None),stock:str|None=Form(None),featured:bool=Form(False),display_order:str=Form('0'),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    price = required_float(price, 'price'); category_id = form_int(category_id); section_id = form_int(section_id); previous_price = form_float(previous_price); stock = form_int(stock); display_order = form_int(display_order, 0)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    p=db.get(Product,product_id)
    if not p or p.deleted or not can_manage_store(u,p.store_id) or not can_manage_store(u,store_id): return RedirectResponse('/admin/products',303)
    try:
        p.name=name.strip(); p.price=max(0,price); p.store_id=store_id; p.category_id=category_id; p.section_id=section_id; p.description=description.strip(); p.previous_price=previous_price; p.stock=stock; p.featured=featured; p.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/products')
            if p.image_public_id: delete(p.image_public_id)
            p.image_url,p.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/products?error=image',303)
    except SQLAlchemyError: db.rollback(); return RedirectResponse('/admin/products?error=db',303)
    return RedirectResponse('/admin/products',303)


@router.post('/products/{product_id}/duplicate')
def product_duplicate(product_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.get(Product, product_id)
    if p and not p.deleted and can_manage_store(u, p.store_id):
        db.add(Product(name=f'{p.name} (copia)'[:180], description=p.description, price=p.price, previous_price=p.previous_price, status=ProductStatus.INACTIVO, stock=p.stock, featured=False, display_order=p.display_order, store_id=p.store_id, category_id=p.category_id)); db.commit()
    return RedirectResponse('/admin/products?ok=duplicated', 303)


@router.post('/products/bulk-price')
def products_bulk_price(request: Request, store_id: int = Form(...), percent: str = Form(...), db: Session = Depends(get_db)):
    percent = required_float(percent, 'percent')
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not can_manage_store(u, store_id) or not -50 <= percent <= 100 or percent == 0: return RedirectResponse('/admin/products?error=percent', 303)
    factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
    db.execute(update(Product).where(Product.store_id == store_id, Product.deleted.is_(False)).values(price=func.round(Product.price * factor, 2)))
    db.commit()
    return RedirectResponse('/admin/products?ok=prices', 303)


@router.post('/products/{product_id}/delete')
def product_delete(product_id:int,request:Request,db:Session=Depends(get_db)):
    """El local elimina un producto. Si nunca se vendio se borra; si ya esta en pedidos, se oculta para siempre
    (los pedidos viejos lo siguen mostrando con su nombre y precio)."""
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    p=db.get(Product,product_id)
    if not p or p.deleted or not can_manage_store(u,p.store_id): return RedirectResponse('/admin/products',303)
    sold=db.scalar(select(OrderItem.id).where(OrderItem.product_id==p.id).limit(1))
    if sold:
        p.deleted, p.status, p.featured = True, ProductStatus.INACTIVO, False
    else:
        if p.image_public_id:
            try: delete(p.image_public_id)
            except Exception: pass  # la imagen en Cloudinary no frena el borrado
        db.delete(p)
    db.commit()
    return RedirectResponse('/admin/products?ok=product_deleted',303)


@router.post('/products/{product_id}/toggle')
def product_toggle(product_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    p=db.get(Product,product_id)
    if p and not p.deleted and can_manage_store(u,p.store_id): p.status=ProductStatus.INACTIVO if p.status==ProductStatus.ACTIVO else ProductStatus.ACTIVO; db.commit()
    return RedirectResponse('/admin/products',303)


@router.get('/banners', response_class=HTMLResponse)
def banners(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(Banner).order_by(Banner.display_order,Banner.id)).all()
    return templates.TemplateResponse(request, 'admin/banners.html', {'user':u,'banners':rows})


@router.post('/banners')
def banner_create(request:Request,file:UploadFile=File(...),title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:str=Form('0'),db:Session=Depends(get_db)):
    display_order = form_int(display_order, 0)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    try:
        url,pid=image_upload(file,'pidomix/banners'); db.add(Banner(image_url=url,image_public_id=pid,title=title.strip(),subtitle=subtitle.strip(),button_text=button_text.strip(),link=link.strip(),display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/banners?error=image',303)
    return RedirectResponse('/admin/banners',303)


@router.post('/banners/{banner_id}/edit')
def banner_edit(banner_id:int,request:Request,title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:str=Form('0'),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    display_order = form_int(display_order, 0)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    b=db.get(Banner,banner_id)
    if not b: return RedirectResponse('/admin/banners',303)
    try:
        b.title=title.strip(); b.subtitle=subtitle.strip(); b.button_text=button_text.strip(); b.link=link.strip(); b.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/banners')
            if b.image_public_id: delete(b.image_public_id)
            b.image_url,b.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/banners?error=image',303)
    return RedirectResponse('/admin/banners',303)


@router.post('/banners/{banner_id}/toggle')
def banner_toggle(banner_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    b=db.get(Banner,banner_id)
    if b: b.active=not b.active; db.commit()
    return RedirectResponse('/admin/banners',303)


def _order_scope(u):
    if u.role != Role.SUPERADMIN:
        return [Order.store_id == u.store_id]
    return [Order.store_id.in_(stores_in_city(city_filter(u)))] if city_filter(u) else []


ORDER_CARD = (joinedload(Order.store), joinedload(Order.customer), selectinload(Order.items), selectinload(Order.events), joinedload(Order.courier))
HISTORY_PER_PAGE = 50


def _history_filters(u, q='', status='', date_from='', date_to=''):
    where = [*_order_scope(u)]
    where.append(Order.status == OrderStatus(status) if status in ('ENTREGADO', 'CANCELADO') else Order.status.in_(FINAL))
    q = q.strip()
    if q:
        term = f'%{q.lstrip("#")}%'
        conds = [Customer.first_name.ilike(term), Customer.last_name.ilike(term), Customer.phone.ilike(term)]
        if q.lstrip('#').isdigit(): conds.append(Order.id == int(q.lstrip('#')))
        where.append(or_(*conds))
    for value, op in ((date_from, '>='), (date_to, '<')):
        try:
            day = datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
        if op == '<': day += timedelta(days=1)
        utc = day.astimezone(timezone.utc).replace(tzinfo=None)
        where.append(Order.created_at >= utc if op == '>=' else Order.created_at < utc)
    return where


@router.get('/orders', response_class=HTMLResponse)
def orders(request: Request, q: str = '', status: str = '', date_from: str = '', date_to: str = '', page: int = 1, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    active = db.scalars(select(Order).options(*ORDER_CARD).where(*_order_scope(u), Order.status.not_in(FINAL)).order_by(Order.created_at)).all()
    columns = [(st, [o for o in active if o.status == st]) for st in FLOW[:-1]]
    page = max(1, page)
    where = _history_filters(u, q, status, date_from, date_to)
    history = db.scalars(select(Order).outerjoin(Customer, Customer.id == Order.customer_id).options(joinedload(Order.store), joinedload(Order.customer))
                         .where(*where).order_by(Order.created_at.desc()).offset((page - 1) * HISTORY_PER_PAGE).limit(HISTORY_PER_PAGE + 1)).all()
    has_next = len(history) > HISTORY_PER_PAGE
    filters = {'q': q, 'status': status, 'date_from': date_from, 'date_to': date_to}
    return templates.TemplateResponse(request, 'admin/orders.html', {'user': u, 'columns': columns, 'history': history[:HISTORY_PER_PAGE], 'has_next': has_next, 'page': page, 'filters': filters, 'filtering': any(filters.values()), 'qs': urlencode({k: v for k, v in filters.items() if v}), 'to_local': to_local})


@router.get('/orders/pending')
def orders_pending(request: Request, db: Session = Depends(get_db)):
    u = auth(request, db)
    if not u or must_setup_2fa(u): return JSONResponse({'error': 'auth'}, status_code=401)  # sin los dos pasos obligatorios, nada del panel
    dispatch.tick(db)  # comandas consulta esto cada 10 s: hace avanzar las ofertas a repartidores
    mercadopago.expire_stale_throttled(db)  # y cancela los pedidos online que no se pagaron a tiempo
    where = _order_scope(u)
    pending, latest, stamp = db.execute(select(
        func.count(case((Order.status == OrderStatus.PENDIENTE, 1))), func.max(Order.id), func.max(Order.updated_at),
    ).where(*where)).one()
    # 'stamp' cambia con cualquier pedido nuevo o cambio de estado: el tablero se refresca solo
    return JSONResponse({'pending': pending, 'latest': latest or 0, 'stamp': str(stamp or '')}, headers={'Cache-Control': 'no-store'})


@router.get('/orders/{order_id}', response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    o = db.scalar(select(Order).options(*ORDER_CARD, joinedload(Order.coupon), joinedload(Order.review), selectinload(Order.events).joinedload(OrderEvent.user)).where(Order.id == order_id))
    if not o or not can_manage_store(u, o.store_id): return RedirectResponse('/admin/orders', 303)
    timeline = []
    for i, e in enumerate(o.events):
        nxt = o.events[i + 1].created_at if i + 1 < len(o.events) else (None if o.status in FINAL else datetime.utcnow())
        timeline.append({'event': e, 'minutes': minutes_since(e.created_at, nxt) if nxt else None})
    tracking_url = f"{str(request.base_url).rstrip('/')}/pedido/{o.id}?t={order_token(o.id)}"
    return templates.TemplateResponse(request, 'admin/order_detail.html', {'user': u, 'o': o, 'timeline': timeline, 'tracking_url': tracking_url, 'to_local': to_local})


@router.post('/orders/{order_id}/status')
def order_status(order_id: int, request: Request, status: OrderStatus = Form(...), back: str = Form('/admin/orders'), resolution: str = Form(''),
                 db: Session = Depends(get_db)):
    u = guard(request, db)
    wants_json = request.headers.get('x-requested-with') == 'fetch'
    if isinstance(u, RedirectResponse):
        return JSONResponse({'ok': False, 'error': 'Tu sesión expiró. Volvé a ingresar.'}, status_code=401) if wants_json else u
    order = db.scalar(select(Order).options(selectinload(Order.events)).where(Order.id == order_id))
    error = None
    if order and can_manage_store(u, order.store_id) and status == OrderStatus.CANCELADO and status in allowed_statuses(order):
        # cancelar un pedido que el cadete de Trappi ya retiro: que paso con la plata y el pago del viaje
        if finance.needs_cancel_resolution(order):
            if resolution not in finance.CANCEL_RESOLUTIONS:
                error = 'Elegí qué pasó con la plata que el cadete le pagó al local.'
            elif resolution == 'store_keeps' and u.role != Role.SUPERADMIN:
                error = 'Si el local se queda con la plata, lo tiene que resolver Trappi. Escribinos.'
        if not error:
            try:
                dispatch.cancel_after_pickup(db, order, resolution or None, user=u, ip=client_ip(request))
            except finance.FinanceError as exc:
                error = str(exc)
    if (not error and order and u.role != Role.SUPERADMIN and status in (OrderStatus.EN_CAMINO, OrderStatus.ENTREGADO)
            and order.courier is not None and order.courier.store_id is None and plans.fleet_security(order)):
        # Trappi Delivery: el retiro lo confirma el cadete con el codigo y la entrega con el PIN del cliente
        error = ('Lo marca el cadete de Trappi al cargar el código de retiro que le das.' if status == OrderStatus.EN_CAMINO
                 else 'Lo marca el cadete de Trappi con el PIN del cliente.')
    ok = bool(not error and order and can_manage_store(u, order.store_id) and set_status(order, status, u))
    if not ok:
        db.rollback()
    if ok:
        if status == OrderStatus.ENTREGADO:  # lo entrego el local (retiro o sin la app): se cobro en ese momento
            payments.mark_paid(order, 'repartidor' if order.courier_id and order.delivery_method == 'delivery' else 'local')
            dispatch.finish_trip(db, order)
        db.commit()
        push.notify_status(db, order)
        dispatch.tick(db)  # al confirmarse un delivery arranca la oferta a repartidores
    if wants_json:
        return JSONResponse({'ok': ok, 'error': None if ok else (error or 'Ese cambio de estado ya no es posible: alguien más actualizó el pedido.')}, status_code=200 if ok else 409)
    back = back if back.startswith('/admin') else '/admin/orders'
    if error:
        request.session['order_error'] = error
    return RedirectResponse(back if ok else f"{back}{'&' if '?' in back else '?'}error=status", 303)


def _csv_safe(v):
    v = '' if v is None else str(v)
    return "'" + v if v[:1] in ('=', '+', '-', '@') else v


@router.get('/reports/export.csv')
def reports_export(request: Request, days: int = 30, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    days = days if days in (7, 14, 30, 90) else 30
    rows = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(Order.created_at >= local_day_start_utc(days - 1), *_order_scope(u)).order_by(Order.created_at.desc())).unique().all()
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(['Pedido', 'Fecha', 'Tienda', 'Cliente', 'Telefono', 'Entrega', 'Direccion', 'Subtotal', 'Envio', 'Total', 'Estado',
                'Plan', 'Comision %', 'Comision', 'Pago cadete', 'Neto comercio', 'Ingreso Trappi'])
    for o in rows:
        c = o.customer
        w.writerow([o.id, to_local(o.created_at).strftime('%Y-%m-%d %H:%M'), o.store.name, _csv_safe(f'{c.first_name} {c.last_name}') if c else '', _csv_safe(c.phone) if c else '', o.delivery_method, _csv_safe(o.address), o.subtotal, o.shipping, o.total, o.status.value,
                    o.plan or '', o.commission_rate if o.commission_rate is not None else '', o.platform_commission or 0,
                    o.courier_pay if o.courier_pay is not None else '', o.store_net if o.store_net is not None else '', o.trappi_income if o.trappi_income is not None else ''])
    return Response('\ufeff' + buf.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=trappi-pedidos-{days}d.csv'})


@router.get('/reports', response_class=HTMLResponse)
def reports(request: Request, days: int = 14, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    days = days if days in (7, 14, 30) else 14
    since = local_day_start_utc(days - 1)
    rows = db.execute(select(Order.created_at, Order.total, Order.delivery_method, Order.status).where(Order.created_at >= since, *_order_scope(u))).all()
    first_day = (local_now() - timedelta(days=days - 1)).date()
    by_day = {first_day + timedelta(days=i): [0, Decimal(0)] for i in range(days)}
    delivery = pickup = cancelled = 0
    for created, total, method, status in rows:
        if status == OrderStatus.CANCELADO: cancelled += 1; continue
        slot = by_day.get(to_local(created).date())
        if slot: slot[0] += 1; slot[1] += Decimal(total)
        if method == 'delivery': delivery += 1
        else: pickup += 1
    peak = max((v[1] for v in by_day.values()), default=0) or 1
    series = [{'label': d.strftime('%d/%m'), 'orders': v[0], 'revenue': v[1], 'pct': int(v[1] * 100 / peak)} for d, v in by_day.items()]
    total_orders, total_revenue = sum(x['orders'] for x in series), sum((x['revenue'] for x in series), Decimal(0))
    top = db.execute(select(OrderItem.product_name, func.sum(OrderItem.quantity).label('qty'), func.sum(OrderItem.quantity * OrderItem.unit_price).label('amount')).join(Order, Order.id == OrderItem.order_id).where(Order.created_at >= since, Order.status != OrderStatus.CANCELADO, *_order_scope(u)).group_by(OrderItem.product_name).order_by(desc('qty')).limit(8)).all()
    return templates.TemplateResponse(request, 'admin/reports.html', {'user': u, 'days': days, 'series': series, 'total_orders': total_orders, 'total_revenue': total_revenue, 'avg': (total_revenue / total_orders) if total_orders else 0, 'delivery': delivery, 'pickup': pickup, 'cancelled': cancelled, 'top': top})


def _coupon_scope(u):
    return [] if u.role == Role.SUPERADMIN else [Coupon.store_id == u.store_id]


@router.get('/sections', response_class=HTMLResponse)
def sections(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN and not u.store_id: return RedirectResponse('/admin', 303)
    store_id = u.store_id if u.role != Role.SUPERADMIN else (int(request.query_params.get('store_id')) if request.query_params.get('store_id', '').isdigit() else None)
    stores = db.scalars(select(Store).where(*([Store.city_id == city_filter(u)] if city_filter(u) else [])).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    rows = db.scalars(select(StoreSection).where(StoreSection.store_id == store_id).order_by(StoreSection.display_order)).all() if store_id else []
    return templates.TemplateResponse(request, 'admin/sections.html', {'user': u, 'sections': rows, 'stores': stores, 'store_id': store_id})


@router.post('/sections')
def section_create(request: Request, name: str = Form(...), display_order: str = Form('0'), store_id: str | None = Form(None), db: Session = Depends(get_db)):
    display_order = form_int(display_order, 0); store_id = form_int(store_id)
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    target = store_id if u.role == Role.SUPERADMIN else u.store_id
    if not target or not can_manage_store(u, target): return RedirectResponse('/admin/sections', 303)
    db.add(StoreSection(store_id=target, name=name.strip(), display_order=display_order)); db.commit()
    return RedirectResponse(f'/admin/sections?store_id={target}&ok=1', 303)


@router.post('/sections/{section_id}/toggle')
def section_toggle(section_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    sec = db.get(StoreSection, section_id)
    if sec and can_manage_store(u, sec.store_id): sec.active = not sec.active; db.commit()
    return RedirectResponse(f'/admin/sections?store_id={sec.store_id}' if sec else '/admin/sections', 303)


@router.get('/products/{product_id}/modifiers', response_class=HTMLResponse)
def product_modifiers_page(product_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.scalar(select(Product).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == product_id))
    if not p or p.deleted or not can_manage_store(u, p.store_id): return RedirectResponse('/admin/products', 303)
    return templates.TemplateResponse(request, 'admin/modifiers.html', {'user': u, 'p': p})


@router.post('/products/{product_id}/modifiers')
def modifier_group_create(product_id: int, request: Request, name: str = Form(...), required: bool = Form(False), max_select: str = Form('1'), db: Session = Depends(get_db)):
    max_select = form_int(max_select, 1)
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.get(Product, product_id)
    if not p or not can_manage_store(u, p.store_id): return RedirectResponse('/admin/products', 303)
    db.add(ModifierGroup(product_id=product_id, name=name.strip(), required=required, min_select=1 if required else 0, max_select=max(1, max_select))); db.commit()
    return RedirectResponse(f'/admin/products/{product_id}/modifiers', 303)


@router.post('/modifier-groups/{group_id}/delete')
def modifier_group_delete(group_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    g = db.get(ModifierGroup, group_id)
    if g and can_manage_store(u, g.product.store_id):
        pid = g.product_id; db.delete(g); db.commit()
        return RedirectResponse(f'/admin/products/{pid}/modifiers', 303)
    return RedirectResponse('/admin/products', 303)


@router.post('/modifier-groups/{group_id}/options')
def modifier_option_create(group_id: int, request: Request, name: str = Form(...), price_extra: str = Form('0'), db: Session = Depends(get_db)):
    price_extra = form_float(price_extra, 0)
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    g = db.get(ModifierGroup, group_id)
    if not g or not can_manage_store(u, g.product.store_id): return RedirectResponse('/admin/products', 303)
    db.add(ModifierOption(group_id=group_id, name=name.strip(), price_extra=max(0, price_extra))); db.commit()
    return RedirectResponse(f'/admin/products/{g.product_id}/modifiers', 303)


@router.post('/modifier-options/{option_id}/toggle')
def modifier_option_toggle(option_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    o = db.get(ModifierOption, option_id)
    if o and can_manage_store(u, o.group.product.store_id):
        o.active = not o.active; db.commit()
        return RedirectResponse(f'/admin/products/{o.group.product_id}/modifiers', 303)
    return RedirectResponse('/admin/products', 303)


@router.get('/settings', response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    return settings_form(request, db, u, platform_settings.GENERAL_SECTIONS, '/admin/settings', 'Configuración de la plataforma')


def settings_form(request: Request, db: Session, u, keys, action: str, title: str, intro: str = '', **extra):
    """Formulario de opciones de la plataforma (una parte de las secciones)."""
    values = platform_settings.get_all(db)
    sections = [(key, title_, help_, [o for o in platform_settings.OPTIONS if o.section == key]) for key, (title_, help_) in platform_settings.SECTIONS.items() if key in keys]
    return templates.TemplateResponse(request, 'admin/settings.html', {'user': u, 'sections': sections, 'values': values, 'action': action, 'title': title, 'intro': intro, **extra})


def settings_store(request: Request, db: Session, u, form, keys) -> None:
    """Guarda una parte de las opciones y deja en la auditoria lo que cambio."""
    from ..services import audit
    changed = platform_settings.save(db, {k: v for k, v in form.items() if isinstance(v, str)}, set(keys))
    for key, (old, new) in changed.items():
        audit.log(db, 'config.update', 'setting', key, user=u, old=old, new=new, ip=client_ip(request))
    db.commit()


@router.post('/settings')
def settings_save(request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    settings_store(request, db, u, form, platform_settings.GENERAL_SECTIONS)
    return RedirectResponse('/admin/settings?ok=1', 303)


@router.post('/settings/ai-test', response_class=HTMLResponse)
def settings_ai_test(request: Request, db: Session = Depends(get_db)):
    """Prueba la conexion con el modelo de Trappi AI y muestra el error tal cual (sin claves)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    from ..ai import assistant, providers
    ping = providers.diagnose()
    # si el modelo contesta, una charla de verdad (reglas, herramientas y una busqueda): ahi aparecen los errores que la pregunta corta no muestra
    talk = assistant.diagnose_chat(db, city_filter(u)) if ping['ok'] else None
    return settings_form(request, db, u, platform_settings.GENERAL_SECTIONS, '/admin/settings', 'Configuración de la plataforma', ai_test=ping, ai_chat=talk)


@router.get('/coupons', response_class=HTMLResponse)
def coupons(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    stores = db.scalars(select(Store).where(*([Store.city_id == city_filter(u)] if city_filter(u) else [])).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    rows = db.scalars(select(Coupon).options(joinedload(Coupon.store)).where(*_coupon_scope(u)).order_by(Coupon.active.desc(), Coupon.created_at.desc())).all()
    return templates.TemplateResponse(request, 'admin/coupons.html', {'user': u, 'coupons': rows, 'stores': stores})


@router.post('/coupons')
def coupon_create(request: Request, code: str = Form(...), discount_type: str = Form('percent'), discount_value: str = Form(...), min_order: str = Form('0'), max_uses: str | None = Form(None), expires_at: str = Form(''), store_id: str | None = Form(None), db: Session = Depends(get_db)):
    discount_value = required_float(discount_value, 'discount_value'); min_order = form_float(min_order, 0); max_uses = form_int(max_uses); store_id = form_int(store_id)
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    target_store = store_id if u.role == Role.SUPERADMIN else u.store_id
    if not target_store or not can_manage_store(u, target_store): return RedirectResponse('/admin/coupons?error=owner', 303)
    code = code.strip().upper()
    if not code or db.scalar(select(Coupon).where(Coupon.store_id == target_store, func.upper(Coupon.code) == code)):
        return RedirectResponse('/admin/coupons?error=duplicate', 303)
    try:
        exp = datetime.fromisoformat(expires_at) if expires_at else None
    except ValueError:
        return RedirectResponse('/admin/coupons?error=date', 303)
    db.add(Coupon(store_id=target_store, code=code, discount_type='fixed' if discount_type == 'fixed' else 'percent', discount_value=max(0, discount_value), min_order=max(0, min_order), max_uses=max_uses if max_uses and max_uses > 0 else None, expires_at=exp))
    db.commit()
    return RedirectResponse('/admin/coupons?ok=1', 303)


@router.post('/coupons/{coupon_id}/toggle')
def coupon_toggle(coupon_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Coupon, coupon_id)
    if c and can_manage_store(u, c.store_id): c.active = not c.active; db.commit()
    return RedirectResponse('/admin/coupons', 303)


REVIEW_FILTERS = {
    'sin_respuesta': lambda: [Review.reply.is_(None), Review.hidden.is_(False)],
    'con_comentario': lambda: [Review.comment.is_not(None), Review.comment != ''],
    'negativas': lambda: [Review.rating <= 2],
    'ocultas': lambda: [Review.hidden.is_(True)],
}


@router.get('/reviews', response_class=HTMLResponse)
def reviews_page(request: Request, filter: str = '', rating: int | None = None, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    scope = [] if u.role == Role.SUPERADMIN else [Review.store_id == u.store_id]
    where = scope + (REVIEW_FILTERS[filter]() if filter in REVIEW_FILTERS else [])
    if rating in range(1, 6): where.append(Review.rating == rating)
    rows = db.scalars(select(Review).options(joinedload(Review.store), joinedload(Review.order).joinedload(Order.customer)).where(*where).order_by(Review.created_at.desc()).limit(100)).all()
    summary = rating_summary(db, *scope, Review.hidden.is_(False))
    unanswered = db.scalar(select(func.count(Review.id)).where(*scope, Review.reply.is_(None), Review.hidden.is_(False))) or 0
    return templates.TemplateResponse(request, 'admin/reviews.html', {'user': u, 'reviews': rows, 'summary': summary, 'unanswered': unanswered, 'filter': filter, 'rating': rating})


def _review_back(request):
    back = request.headers.get('referer', '')
    return back[back.index('/admin/reviews'):] if '/admin/reviews' in back else '/admin/reviews'


@router.post('/reviews/{review_id}/reply')
def review_reply(review_id: int, request: Request, reply: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    r = db.get(Review, review_id)
    if r and can_manage_store(u, r.store_id):
        text = reply.strip()[:REVIEW_MAX_TEXT]
        r.reply, r.replied_at = (text, datetime.utcnow()) if text else (None, None)
        db.commit()
    return RedirectResponse(_review_back(request), 303)


@router.post('/reviews/{review_id}/hide')
def review_hide(review_id: int, request: Request, db: Session = Depends(get_db)):
    """Solo la plataforma modera: el local no puede esconder sus propias malas reseñas."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    r = db.get(Review, review_id)
    if r and u.role == Role.SUPERADMIN:
        r.hidden = not r.hidden
        refresh_store_rating(db, r.store_id)
        db.commit()
    return RedirectResponse(_review_back(request), 303)


@router.get('/customers', response_class=HTMLResponse)
def customers(request:Request,q:str='',db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    spent = func.coalesce(func.sum(case((Order.status != OrderStatus.CANCELADO, Order.total), else_=0)), 0)
    stmt = select(Customer, func.count(Order.id), spent, func.max(Order.created_at)).join(Order, Order.customer_id == Customer.id)
    if u.role != Role.SUPERADMIN: stmt = stmt.where(Order.store_id == u.store_id)
    if q.strip():
        term = f'%{q.strip()}%'
        stmt = stmt.where((Customer.first_name.ilike(term)) | (Customer.last_name.ilike(term)) | (Customer.phone.ilike(term)))
    rows = db.execute(stmt.group_by(Customer.id).order_by(func.max(Order.created_at).desc()).limit(300)).all()
    account_rows = []
    if u.role == Role.SUPERADMIN:  # cuentas (solo Trappi las ve y las puede bloquear)
        astmt = select(ClientAccount, func.count(Order.id)).outerjoin(Order, Order.account_id == ClientAccount.id)
        if q.strip():
            term = f'%{q.strip()}%'
            astmt = astmt.where(ClientAccount.email.ilike(term) | ClientAccount.name.ilike(term) | ClientAccount.phone.ilike(term))
        account_rows = db.execute(astmt.group_by(ClientAccount.id).order_by(ClientAccount.created_at.desc()).limit(300)).all()
    withdrawals = db.scalars(select(WithdrawalRequest).order_by(WithdrawalRequest.status, WithdrawalRequest.id.desc()).limit(100)).all() if u.role == Role.SUPERADMIN else []
    cfg = platform_settings.get_all(db)
    legal_missing = [label for key, label in (('legal_name', 'titular'), ('legal_cuit', 'CUIT'), ('legal_address', 'domicilio'), ('legal_email', 'email legal')) if not (cfg.get(key) or '').strip()]
    return templates.TemplateResponse(request, 'admin/customers.html', {'user':u,'rows':rows,'q':q,'to_local':to_local,'account_rows':account_rows,
                                                                        'login_required': accounts.required(db), 'google_ready': accounts.available(),
                                                                        'withdrawals': withdrawals, 'legal_missing': legal_missing})


@router.post('/customers/arrepentimiento/{request_id}')
def withdrawal_toggle(request_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    w=db.get(WithdrawalRequest,request_id)
    if w and u.role==Role.SUPERADMIN:
        w.status='nuevo' if w.status=='resuelto' else 'resuelto'
        audit.log(db,'withdrawal.status','withdrawal_request',w.id,user=u,new={'code':w.code,'status':w.status},ip=client_ip(request))
        db.commit()
    return RedirectResponse('/admin/customers#arrepentimiento',303)


@router.post('/customers/accounts/{account_id}/block')
def client_account_block(account_id:int,request:Request,reason:str=Form(''),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    acct=db.get(ClientAccount,account_id)
    if acct and u.role==Role.SUPERADMIN:
        if acct.active:
            accounts.block(acct, reason)
            audit.log(db,'client.block','client_account',acct.id,user=u,new={'email':acct.email},reason=reason,ip=client_ip(request))
        else:
            accounts.unblock(acct)
            audit.log(db,'client.unblock','client_account',acct.id,user=u,new={'email':acct.email},ip=client_ip(request))
        db.commit()
    return RedirectResponse('/admin/customers#cuentas',303)


@router.get('/users', response_class=HTMLResponse)
def users(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(User).options(joinedload(User.store)).order_by(User.email)).all()
    stores=db.scalars(select(Store).order_by(Store.name)).all()
    return templates.TemplateResponse(request, 'admin/users.html', {'user':u,'users':rows,'stores':stores,'roles':[Role.STORE_ADMIN,Role.REPARTIDOR,Role.CLIENTE]})


@router.post('/users')
def user_create(request:Request,email:str=Form(...),password:str=Form(...),role:Role=Form(Role.STORE_ADMIN),store_id:str|None=Form(None),db:Session=Depends(get_db)):
    store_id = form_int(store_id)
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    email=email.strip().lower()
    if db.scalar(select(User).where(User.email==email)) or len(password)<8: return RedirectResponse('/admin/users?error=invalid',303)
    db.add(User(email=email,password_hash=hash_password(password),role=role,store_id=store_id if role==Role.STORE_ADMIN else None)); db.commit()
    return RedirectResponse('/admin/users',303)


@router.post('/users/{user_id}/toggle')
def user_toggle(user_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    target=db.get(User,user_id)
    if target and u.role==Role.SUPERADMIN and target.id != u.id:
        target.active=not target.active
        bump_session(target)  # desactivado: se cierra su sesion
        db.commit()
    return RedirectResponse('/admin/users',303)


@router.post('/users/{user_id}/reset-2fa')
def user_reset_2fa(user_id:int,request:Request,db:Session=Depends(get_db)):
    """Para quien perdio el celular y los codigos de recuperacion: lo vuelve a configurar al entrar."""
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    target=db.get(User,user_id)
    if target and u.role==Role.SUPERADMIN and target.id != u.id and target.totp_secret_enc:
        totp.disable(target)
        bump_session(target)
        audit.log(db,'user.2fa.reset','user',target.id,user=u,new={'email':target.email},ip=client_ip(request))
        db.commit()
    return RedirectResponse('/admin/users?ok=1',303)



# ---------- repartidores ----------

VEHICLES = [('moto', '🛵 Moto'), ('bici', '🚲 Bici'), ('auto', '🚗 Auto'), ('pie', '🚶 A pie')]


def _courier_scope(u):
    if u.role != Role.SUPERADMIN:
        return [Courier.store_id == u.store_id]
    cid = city_filter(u)
    return [or_(Courier.city_id == cid, Courier.store_id.in_(stores_in_city(cid)))] if cid else []


def _new_pin() -> str:
    import secrets
    return f'{secrets.randbelow(10000):04d}'


@router.get('/repartidores', response_class=HTMLResponse)
def couriers_page(request: Request, error: str = '', db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    rows = db.scalars(select(Courier).options(joinedload(Courier.store), joinedload(Courier.city)).where(*_courier_scope(u)).order_by(Courier.active.desc(), Courier.name)).all()
    now, fresh = datetime.utcnow(), dispatch.location_fresh(db)
    trips = {o.courier_id: o.id for o in db.scalars(select(Order).where(Order.courier_id.in_([c.id for c in rows] or [0]), Order.status.in_(dispatch.ACTIVE_TRIP_STATUSES)))}
    stats = {}
    for c in rows:
        today, n_today = dispatch.earnings(db, c, local_day_start_utc(0))
        week, n_week = dispatch.earnings(db, c, local_day_start_utc(6))
        stats[c.id] = {'today': today, 'trips_today': n_today, 'week': week, 'trips_week': n_week, 'trip': trips.get(c.id),
                       'connected': c.online and c.location_at is not None and now - c.location_at <= fresh}
    stores = db.scalars(select(Store).where(*([Store.city_id == city_filter(u)] if city_filter(u) else [])).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    return templates.TemplateResponse(request, 'admin/couriers.html', {
        'user': u, 'couriers': rows, 'stats': stats, 'stores': stores, 'is_super': u.role == Role.SUPERADMIN,
        'vehicles': VEHICLES, 'vehicle_label': dict(VEHICLES), 'pin_shown': request.session.pop('courier_pin', None), 'error': error})


@router.post('/repartidores')
def courier_create(request: Request, name: str = Form(...), phone: str = Form(...), vehicle: str = Form('moto'), store_id: str | None = Form(None),
                   city_id: str | None = Form(None), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    digits = ''.join(ch for ch in phone if ch.isdigit())
    if len(digits) < 8 or not name.strip():
        return RedirectResponse('/admin/repartidores?' + urlencode({'error': 'Revisá el nombre y el teléfono (con código de área).'}), 303)
    if db.scalar(select(Courier).where(Courier.phone == digits)):
        return RedirectResponse('/admin/repartidores?' + urlencode({'error': 'Ya hay un repartidor con ese teléfono.'}), 303)
    sid = form_int(store_id) if u.role == Role.SUPERADMIN else u.store_id
    # ciudad: la del local (cadete propio) o la elegida para la flota (o la que se esta mirando)
    store = db.get(Store, sid) if sid else None
    cid = store.city_id if store else (form_int(city_id) or city_filter(u))
    pin = _new_pin()
    db.add(Courier(name=name.strip()[:120], phone=digits, pin_hash=hash_password(pin), vehicle=vehicle if vehicle in dict(VEHICLES) else 'moto', store_id=sid, city_id=cid))
    db.commit()
    request.session['courier_pin'] = [name.strip(), pin]
    return RedirectResponse('/admin/repartidores', 303)


def _managed_courier(u, db, courier_id):
    c = db.get(Courier, courier_id)
    return c if c and (u.role == Role.SUPERADMIN or c.store_id == u.store_id) else None


@router.post('/repartidores/{courier_id}/pin')
def courier_pin(courier_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    c = _managed_courier(u, db, courier_id)
    if c:
        pin = _new_pin()
        c.pin_hash, c.token_version = hash_password(pin), c.token_version + 1  # cierra la sesion abierta
        db.commit()
        request.session['courier_pin'] = [c.name, pin]
    return RedirectResponse('/admin/repartidores', 303)


@router.post('/repartidores/{courier_id}/toggle')
def courier_toggle(courier_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    c = _managed_courier(u, db, courier_id)
    if c:
        c.active = not c.active
        if not c.active:
            c.online, c.token_version = False, c.token_version + 1
        db.commit()
    return RedirectResponse('/admin/repartidores', 303)


def courier_options(db: Session, order: Order) -> list[dict]:
    """Repartidores que el local puede elegir para un pedido: los suyos y la flota, conectados primero."""
    busy = dispatch.busy_courier_ids(db)
    now, fresh = datetime.utcnow(), dispatch.location_fresh(db)
    rows = db.scalars(select(Courier).where(Courier.active.is_(True), or_(Courier.store_id.is_(None), Courier.store_id == order.store_id)).order_by(Courier.name)).all()
    out = []
    for c in rows:
        if not dispatch.allowed(order, c):  # la logistica del plan (propia / flota)
            continue
        connected = c.online and c.location_at is not None and now - c.location_at <= fresh
        d = dispatch.courier_distance(c, order) if connected else None
        out.append({'id': c.id, 'name': c.name, 'own': c.store_id == order.store_id, 'connected': connected, 'busy': c.id in busy and c.id != order.courier_id, 'km': d})
    return sorted(out, key=lambda x: (x['busy'], not x['connected'], not x['own'], x['km'] if x['km'] is not None else 999))


@router.post('/orders/{order_id}/courier')
def order_courier(order_id: int, request: Request, courier_id: str = Form(''), back: str = Form('/admin/comandas'), db: Session = Depends(get_db)):
    """Asignar (courier_id) o liberar (vacio) el repartidor de un pedido."""
    u = guard(request, db)
    wants_json = request.headers.get('x-requested-with') == 'fetch'
    if isinstance(u, RedirectResponse):
        return JSONResponse({'ok': False, 'error': 'Tu sesión expiró. Volvé a ingresar.'}, status_code=401) if wants_json else u
    order = db.scalar(select(Order).options(joinedload(Order.store)).where(Order.id == order_id))
    error = None
    if not order or not can_manage_store(u, order.store_id):
        error = 'No encontramos ese pedido.'
    else:
        try:
            cid = form_int(courier_id)
            if cid:
                c = db.get(Courier, cid)
                if not c: raise dispatch.DispatchError('No encontramos ese repartidor.')
                dispatch.assign_manual(db, order, c)
            else:
                dispatch.unassign(db, order)
            db.commit()
            dispatch.tick(db)
        except dispatch.DispatchError as exc:
            db.rollback(); error = str(exc)
    if wants_json:
        return JSONResponse({'ok': not error, 'error': error}, status_code=409 if error else 200)
    back = back if back.startswith('/admin') else '/admin/comandas'
    return RedirectResponse(back + (('&' if '?' in back else '?') + urlencode({'error': error}) if error else ''), 303)


@router.post('/orders/{order_id}/paid')
def order_paid(order_id: int, request: Request, paid: str = Form('1'), back: str = Form('/admin/comandas'), db: Session = Depends(get_db)):
    """El local confirma que el cliente ya pago (transferencia o en el mostrador): el repartidor no le cobra."""
    u = guard(request, db)
    wants_json = request.headers.get('x-requested-with') == 'fetch'
    if isinstance(u, RedirectResponse):
        return JSONResponse({'ok': False, 'error': 'Tu sesión expiró. Volvé a ingresar.'}, status_code=401) if wants_json else u
    order = db.get(Order, order_id)
    error = None
    if not order or not can_manage_store(u, order.store_id):
        error = 'No encontramos ese pedido.'
    elif order.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
        error = 'Ese pedido ya está cerrado.'
    elif order.payment_method in payments.ONLINE:
        error = 'Los pagos online solo los confirma Mercado Pago.'
    elif order.pickup_paid is not None:
        error = 'El cadete de Trappi ya te pagó este pedido al retirarlo: él se lo cobra al cliente.'
    else:
        if paid == '1':
            payments.mark_paid(order, 'local')
        else:
            payments.mark_unpaid(order)
        db.commit()
    if wants_json:
        return JSONResponse({'ok': not error, 'error': error}, status_code=409 if error else 200)
    back = back if back.startswith('/admin') else '/admin/comandas'
    return RedirectResponse(back + (('&' if '?' in back else '?') + urlencode({'error': error}) if error else ''), 303)
