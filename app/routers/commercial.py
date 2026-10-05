"""Comercios y planes: alta manual, condiciones comerciales, estado, abonos (/admin/comercios)
y "Mi plan Trappi" para cada local (/admin/mi-plan).

Los comercios no se registran solos: el administrador los da de alta acá después de hablar por
WhatsApp. Todo lo comercial (plan, abono, comisión, logística, estado) lo cambia solo el superadmin.
"""
import secrets
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Product, ProductStatus, Role, Store, StoreCategory, StoreHour, StorePlanChange, SubscriptionPayment, User
from ..services import cities, plans, platform, store_reset
from ..services.auth import hash_password
from ..services.forms import form_float, form_int
from ..services.store_hours import local_day_start_utc, local_now, to_local
from ..services.ratelimit import client_ip
from .admin import guard, safe_slug, templates, wa_link

router = APIRouter()

FILTERS = {
    'todos': ('Todos', None),
    'comercio': ('Trappi Comercio', lambda s: s.plan == plans.COMERCIO),
    'delivery': ('Trappi Delivery', lambda s: s.plan == plans.DELIVERY),
    'sin_plan': ('Sin plan', lambda s: s.plan is None),
    'activos': ('Activos', lambda s: s.account_status == 'activo'),
    'pendientes': ('Pendientes', lambda s: s.account_status == 'pendiente'),
    'suspendidos': ('Suspendidos', lambda s: s.account_status == 'suspendido'),
}

templates.env.globals['plans'] = plans
templates.env.globals.setdefault('to_local', to_local)


def superadmin(request: Request, db: Session):
    """El usuario si es superadmin; si no, a donde mandarlo."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u
    return u if u.role == Role.SUPERADMIN else RedirectResponse('/admin/mi-plan', 303)


def flash(request: Request, kind: str, text: str) -> None:
    request.session['commercial_flash'] = [kind, text]


def back_to(store_id: int | None = None, anchor: str = '') -> RedirectResponse:
    return RedirectResponse(f'/admin/comercios/{store_id}{anchor}' if store_id else '/admin/comercios', 303)


def unique_slug(db: Session, name: str, wanted: str = '') -> str:
    base = safe_slug(wanted or name) or 'comercio'
    base = ''.join(ch for ch in base if ch.isalnum() or ch == '-').strip('-') or 'comercio'
    slug, n = base, 2
    while db.scalar(select(Store.id).where(Store.slug == slug)):
        slug, n = f'{base}-{n}', n + 1
    return slug


def checklist(db: Session, s: Store) -> list[tuple[str, bool, str]]:
    """Lo que tiene que estar listo antes de publicar el comercio."""
    products = db.scalar(select(func.count(Product.id)).where(Product.store_id == s.id, Product.status == ProductStatus.ACTIVO)) or 0
    owners = db.scalar(select(func.count(User.id)).where(User.store_id == s.id, User.active.is_(True))) or 0
    hours = db.scalar(select(func.count(StoreHour.id)).where(StoreHour.store_id == s.id)) or 0
    return [
        ('Plan asignado', s.plan is not None, plans.plan_name(s.plan)),
        ('Productos activos', products > 0, f'{products} cargados' if products else 'Cargá al menos uno en Productos'),
        ('Horarios', hours > 0, 'Configurados' if hours else 'Sin horarios: se toma como siempre abierto'),
        ('Acceso del comercio', owners > 0, f'{owners} usuario(s)' if owners else 'Sin usuario para entrar al panel'),
        ('Dirección y WhatsApp', bool(s.address and s.whatsapp), 'Completos' if s.address and s.whatsapp else 'Faltan datos de contacto'),
    ]


def required_ready(items) -> list[str]:
    # para publicar hacen falta plan, productos y acceso; horarios y contacto son recomendados
    return [label for label, ok, _ in items[:2] + items[3:4] if not ok]


# ---------- listado ----------

@router.get('/comercios', response_class=HTMLResponse)
def stores_list(request: Request, f: str = 'todos', db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    f = f if f in FILTERS else 'todos'
    q = select(Store).options(selectinload(Store.store_category), selectinload(Store.city)).order_by(Store.name)
    if getattr(u, 'city_filter', None):
        q = q.where(Store.city_id == u.city_filter)
    stores = db.scalars(q).all()
    counts = {k: (len(stores) if not test else sum(1 for s in stores if test(s))) for k, (_, test) in FILTERS.items()}
    test = FILTERS[f][1]
    shown = [s for s in stores if not test or test(s)]
    ids = [s.id for s in shown]
    sales, subs = plans.sales_summary(db, ids), plans.subscription_summary(db, ids)
    zero = plans.money(0)
    totals = {
        'sales': sum((sales.get(i, {}).get('sales', zero) for i in ids), zero),
        'commission': sum((sales.get(i, {}).get('commission', zero) for i in ids), zero),
        'trappi_income': sum((sales.get(i, {}).get('trappi_income', zero) for i in ids), zero),
        'subs_paid': sum((subs.get(i, {}).get('paid', zero) for i in ids), zero),
        'subs_pending': sum((subs.get(i, {}).get('pending', zero) for i in ids), zero),
    }
    return templates.TemplateResponse(request, 'admin/commercial_list.html', {
        'user': u, 'stores': shown, 'filters': FILTERS, 'f': f, 'counts': counts, 'sales': sales, 'subs': subs, 'totals': totals,
        'flash': request.session.pop('commercial_flash', None)})


# ---------- alta manual ----------

@router.get('/comercios/nuevo', response_class=HTMLResponse)
def new_store_form(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    categories = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse(request, 'admin/commercial_new.html', {
        'user': u, 'categories': categories, 'defaults': {p: plans.defaults(db, p) for p in plans.PLANS},
        'flash': request.session.pop('commercial_flash', None), 'form': request.session.pop('commercial_form', {}),
        'cities': cities.all_cities(db, include_inactive=True), 'default_city': getattr(u, 'city_filter', None) or (cities.default(db).id if cities.default(db) else None)})


@router.post('/comercios/nuevo')
def new_store(request: Request, name: str = Form(...), slug: str = Form(''), owner_name: str = Form(''), phone: str = Form(''),
              whatsapp: str = Form(''), contact_email: str = Form(''), address: str = Form(''), store_category_id: str = Form(''),
              open_time: str = Form(''), close_time: str = Form(''), commercial_notes: str = Form(''),
              login_email: str = Form(...), login_password: str = Form(''),
              plan: str = Form(...), monthly_fee: str = Form(''), commission_rate: str = Form(''), logistics: str = Form(''),
              next_due_date: str = Form(''), city_id: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    form = dict(name=name, slug=slug, owner_name=owner_name, phone=phone, whatsapp=whatsapp, contact_email=contact_email, address=address,
                store_category_id=store_category_id, open_time=open_time, close_time=close_time, commercial_notes=commercial_notes,
                login_email=login_email, plan=plan, monthly_fee=monthly_fee, commission_rate=commission_rate, logistics=logistics,
                next_due_date=next_due_date, city_id=city_id)  # para volver a llenar el formulario si hay un error (sin la contraseña)

    def fail(message: str):
        flash(request, 'error', message)
        request.session['commercial_form'] = form
        return RedirectResponse('/admin/comercios/nuevo', 303)

    name, login_email = name.strip(), login_email.strip().lower()
    if not name:
        return fail('Poné el nombre del comercio.')
    if '@' not in login_email or db.scalar(select(User.id).where(User.email == login_email)):
        return fail('El usuario de acceso tiene que ser un email válido que no esté en uso.')
    password = login_password.strip()
    generated = not password
    if generated:
        password = secrets.token_urlsafe(9)  # ~12 caracteres al azar: se muestra una sola vez
    elif len(password) < 8:
        return fail('La contraseña inicial tiene que tener 8 caracteres o más (o dejala vacía y la generamos).')
    if plan not in plans.PLANS:
        return fail('Elegí la modalidad comercial.')
    every = cities.all_cities(db, include_inactive=True)
    city = cities.get(db, form_int(city_id)) or (every[0] if len(every) == 1 else None)  # con una sola ciudad, va a esa
    if every and not city:
        return fail('Elegí la ciudad del comercio.')
    base = plans.defaults(db, plan, city.id if city else None)  # abono y comisión de esa ciudad (si tiene los suyos)
    fee = form_float(monthly_fee, None)
    rate = form_float(commission_rate, None)
    try:
        due = date.fromisoformat(next_due_date) if next_due_date.strip() else None
    except ValueError:
        return fail('La fecha de vencimiento no es válida.')
    store = Store(name=name[:160], slug=unique_slug(db, name, slug), phone=phone.strip()[:40] or None, whatsapp=whatsapp.strip()[:40] or None,
                  address=address.strip()[:255] or None, store_category_id=form_int(store_category_id), owner_name=owner_name.strip()[:160] or None,
                  contact_email=contact_email.strip().lower()[:255] or None, commercial_notes=commercial_notes.strip() or None,
                  account_status='pendiente', next_due_date=due, city_id=city.id if city else None)
    db.add(store)
    db.flush()
    try:
        plans.set_plan(db, store, plan, base['monthly_fee'] if fee is None else fee, base['commission_rate'] if rate is None else rate,
                       logistics or base['logistics'], u, note='Alta del comercio')
    except plans.PlanError as exc:
        db.rollback()
        return fail(str(exc))
    if open_time and close_time:
        for weekday in range(7):
            db.add(StoreHour(store_id=store.id, weekday=weekday, open_time=open_time[:5], close_time=close_time[:5], closed=False))
    db.add(User(email=login_email, password_hash=hash_password(password), role=Role.STORE_ADMIN, store_id=store.id))
    db.commit()
    request.session['commercial_credentials'] = [store.id, login_email, password if generated else None]
    flash(request, 'ok', f'Comercio "{store.name}" creado como pendiente: cargá sus productos y activalo cuando esté listo.')
    return back_to(store.id)


# ---------- ficha del comercio ----------

@router.get('/comercios/{store_id}', response_class=HTMLResponse)
def store_detail(store_id: int, request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.scalar(select(Store).options(selectinload(Store.admins), selectinload(Store.store_category)).where(Store.id == store_id))
    if not s:
        return RedirectResponse('/admin/comercios', 303)
    creds = request.session.pop('commercial_credentials', None)
    creds = creds if creds and creds[0] == s.id else None
    history = db.scalars(select(StorePlanChange).options(selectinload(StorePlanChange.user)).where(StorePlanChange.store_id == s.id).order_by(StorePlanChange.created_at.desc(), StorePlanChange.id.desc())).all()
    payments_ = db.scalars(select(SubscriptionPayment).where(SubscriptionPayment.store_id == s.id).order_by(SubscriptionPayment.period.desc())).all()
    month_start = local_day_start_utc(local_now().day - 1)  # 1.º del mes, hora local
    items = checklist(db, s)
    cred_msg = None
    if creds:
        cred_msg = (f'¡Hola! Ya está listo tu acceso a Trappi para {s.name}.\nEntrá en {str(request.base_url).rstrip("/")}/admin/login\n'
                    f'Usuario: {creds[1]}' + (f'\nContraseña: {creds[2]}' if creds[2] else '') + '\nTe recomendamos cambiar la contraseña desde "Mi cuenta".')
    return templates.TemplateResponse(request, 'admin/commercial_detail.html', {
        'user': u, 's': s, 't': plans.terms(s), 'history': history, 'payments': payments_, 'checklist': items, 'missing': required_ready(items),
        'sales': plans.sales_summary(db, [s.id]).get(s.id), 'sales_month': plans.sales_summary(db, [s.id], month_start).get(s.id),
        'subs': plans.subscription_summary(db, [s.id]).get(s.id), 'defaults': {p: plans.defaults(db, p) for p in plans.PLANS},
        'credentials': creds, 'credentials_wa': wa_link(s.whatsapp or s.phone, cred_msg) if cred_msg else '',
        'this_period': local_now().strftime('%Y-%m'), 'flash': request.session.pop('commercial_flash', None)})


@router.post('/comercios/{store_id}/plan')
def change_plan(store_id: int, request: Request, plan: str = Form(...), monthly_fee: str = Form(''), commission_rate: str = Form(''),
                logistics: str = Form(''), note: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.get(Store, store_id)
    if not s:
        return back_to()
    try:
        base = plans.defaults(db, plan)
        fee, rate = form_float(monthly_fee, None), form_float(commission_rate, None)
        changed = plans.set_plan(db, s, plan, base['monthly_fee'] if fee is None else fee, base['commission_rate'] if rate is None else rate,
                                 logistics or base['logistics'], u, note)
    except plans.PlanError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return back_to(s.id, '#plan')
    db.commit()
    flash(request, 'ok', 'Condiciones actualizadas. Rigen para los pedidos nuevos; los anteriores conservan las suyas.' if changed else 'No había cambios.')
    return back_to(s.id, '#plan')


@router.post('/comercios/{store_id}/estado')
def change_status(store_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.get(Store, store_id)
    if not s:
        return back_to()
    if status == 'activo':
        missing = required_ready(checklist(db, s))
        if missing:
            flash(request, 'error', 'Para activarlo falta: ' + ', '.join(missing).lower() + '.')
            return back_to(s.id)
    try:
        plans.set_status(s, status)
    except plans.PlanError as exc:
        flash(request, 'error', str(exc))
        return back_to(s.id)
    db.commit()
    flash(request, 'ok', {'activo': 'Comercio activo: ya aparece en Trappi y recibe pedidos.', 'suspendido': 'Comercio suspendido: no aparece ni recibe pedidos.',
                          'desactivado': 'Comercio desactivado.', 'pendiente': 'Comercio vuelto a pendiente: no aparece hasta activarlo.'}[status])
    return back_to(s.id)


@router.get('/comercios/{store_id}/reiniciar', response_class=HTMLResponse)
def reset_form(store_id: int, request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.get(Store, store_id)
    if not s:
        return back_to()
    return templates.TemplateResponse(request, 'admin/commercial_reset.html', {
        'user': u, 's': s, 'r': store_reset.preview(db, s), 'flash': request.session.pop('commercial_flash', None)})


@router.post('/comercios/{store_id}/reiniciar')
def reset_store(store_id: int, request: Request, confirm_name: str = Form(''), subscriptions: str = Form(''), reason: str = Form(''),
                db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.get(Store, store_id)
    if not s:
        return back_to()
    if ' '.join(confirm_name.split()).casefold() != ' '.join(s.name.split()).casefold():
        flash(request, 'error', 'El nombre no coincide: no se borró nada.')
        return RedirectResponse(f'/admin/comercios/{s.id}/reiniciar', 303)
    try:
        done = store_reset.reset(db, s, include_subscriptions=subscriptions in ('1', 'on'), user=u, ip=client_ip(request), reason=reason)
    except store_reset.ResetError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return RedirectResponse(f'/admin/comercios/{s.id}/reiniciar', 303)
    db.commit()
    flash(request, 'ok', f'{s.name} quedó en cero: se borraron {done["orders"]} pedidos, sus comisiones, liquidaciones y reseñas. '
                         'Productos, plan y datos siguen igual.')
    return back_to(s.id)


@router.post('/comercios/{store_id}/datos')
def update_data(store_id: int, request: Request, owner_name: str = Form(''), contact_email: str = Form(''), phone: str = Form(''),
                whatsapp: str = Form(''), commercial_notes: str = Form(''), next_due_date: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.get(Store, store_id)
    if not s:
        return back_to()
    try:
        s.next_due_date = date.fromisoformat(next_due_date) if next_due_date.strip() else None
    except ValueError:
        flash(request, 'error', 'La fecha de vencimiento no es válida.')
        return back_to(s.id, '#datos')
    s.owner_name, s.contact_email = owner_name.strip()[:160] or None, contact_email.strip().lower()[:255] or None
    s.phone, s.whatsapp = phone.strip()[:40] or None, whatsapp.strip()[:40] or None
    s.commercial_notes = commercial_notes.strip() or None
    db.commit()
    flash(request, 'ok', 'Datos comerciales guardados.')
    return back_to(s.id, '#datos')


# ---------- abonos mensuales (registro manual) ----------

@router.post('/comercios/{store_id}/abonos')
def add_payment(store_id: int, request: Request, period: str = Form(...), amount: str = Form(''), status: str = Form('pendiente'),
                note: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    s = db.get(Store, store_id)
    if not s:
        return back_to()
    try:
        period = plans.valid_period(period)
    except plans.PlanError as exc:
        flash(request, 'error', str(exc))
        return back_to(s.id, '#abonos')
    value = form_float(amount, None)
    value = plans.money(s.monthly_fee if value is None else value)
    if value < 0:
        flash(request, 'error', 'El importe no puede ser negativo.')
        return back_to(s.id, '#abonos')
    if db.scalar(select(SubscriptionPayment.id).where(SubscriptionPayment.store_id == s.id, SubscriptionPayment.period == period)):
        flash(request, 'error', f'Ya hay un abono registrado para {period}.')
        return back_to(s.id, '#abonos')
    paid = status == 'pagado'
    db.add(SubscriptionPayment(store_id=s.id, period=period, amount=value, status='pagado' if paid else 'pendiente',
                               paid_at=datetime.utcnow() if paid else None, note=note.strip()[:255] or None, user_id=u.id))
    db.commit()
    flash(request, 'ok', f'Abono de {period} registrado.')
    return back_to(s.id, '#abonos')


@router.post('/comercios/{store_id}/abonos/{payment_id}')
def toggle_payment(store_id: int, payment_id: int, request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse):
        return u
    p = db.get(SubscriptionPayment, payment_id)
    if not p or p.store_id != store_id:
        return back_to(store_id, '#abonos')
    if p.status == 'pagado':
        p.status, p.paid_at = 'pendiente', None
    else:
        p.status, p.paid_at = 'pagado', datetime.utcnow()
    p.user_id = u.id
    db.commit()
    return back_to(store_id, '#abonos')


# ---------- panel del comercio: Mi plan Trappi ----------

@router.get('/mi-plan', response_class=HTMLResponse)
def my_plan(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u
    if u.role == Role.SUPERADMIN or not u.store_id:
        return RedirectResponse('/admin/comercios', 303)
    s = db.get(Store, u.store_id)
    cfg = platform.get_all(db)
    month_start = local_day_start_utc(local_now().day - 1)  # 1.º del mes, hora local
    message = f'Hola, soy de {s.name} y quiero consultar por un cambio de plan en Trappi (hoy tengo {plans.plan_name(s.plan)}).'
    payments_ = db.scalars(select(SubscriptionPayment).where(SubscriptionPayment.store_id == s.id).order_by(SubscriptionPayment.period.desc()).limit(12)).all()
    return templates.TemplateResponse(request, 'admin/my_plan.html', {
        'user': u, 's': s, 't': plans.terms(s), 'payments': payments_,
        'sales': plans.sales_summary(db, [s.id]).get(s.id), 'sales_month': plans.sales_summary(db, [s.id], month_start).get(s.id),
        'change_wa': wa_link(cfg['platform_whatsapp'], message)})
