"""Panel de Trappi Viajes.

- /admin/empresa/...: el panel de cada empresa de viajes (usuario RIDE_ADMIN): en vivo, viajes, conductores, tarifas,
  habilitacion y plan. Solo ve lo suyo; no entra al panel de los comercios.
- /admin/viajes/...: el superadmin da de alta las empresas, revisa la habilitacion, las aprueba o suspende y define el plan.
"""
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import City, Courier, Ride, RideCompany, RideTariff, Role, User
from ..services import audit, platform, rides
from ..services.auth import current_user, hash_password
from ..services.forms import form_int, parse_number
from ..services.ratelimit import client_ip
from ..services.store_hours import local_day_start_utc
from .admin import guard, must_setup_2fa, templates

router = APIRouter()
VIEW_KEY = 'ride_company_view'  # el superadmin puede abrir el panel de una empresa (soporte)


def slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.strip().lower()).strip('-')[:170] or 'empresa'


def company_guard(request: Request, db: Session):
    """(usuario, empresa) del panel de empresa, o la redireccion al login."""
    u = current_user(request, db)
    if u and u.active and u.role == Role.RIDE_ADMIN and u.ride_company_id:
        if must_setup_2fa(u):
            return RedirectResponse('/admin/account/2fa', 303)
        c = db.get(RideCompany, u.ride_company_id)
        return (u, c) if c else RedirectResponse('/admin/logout', 303)
    if u and u.active and u.role == Role.SUPERADMIN:
        cid = form_int(request.query_params.get('c')) or request.session.get(VIEW_KEY)
        c = db.get(RideCompany, cid) if cid else None
        if c:
            request.session[VIEW_KEY] = c.id
            return u, c
        return RedirectResponse('/admin/viajes', 303)
    return RedirectResponse('/admin/login?' + urlencode({'next': request.url.path}), 303)


def _ctx(request, u, c, db, **extra):
    return {'user': u, 'company': c, 'is_super': u.role == Role.SUPERADMIN, 'vehicles': rides.VEHICLES, 'plans': rides.PLANS,
            'status_label': rides.COMPANY_LABEL, 'error': request.query_params.get('error'), 'okmsg': request.query_params.get('ok'),
            'pin_shown': request.session.pop('ride_driver_pin', None), **extra}


def _back(path: str, **q) -> RedirectResponse:
    return RedirectResponse(path + ('?' + urlencode(q) if q else ''), 303)


def _money(v: str, default=Decimal('0')) -> Decimal:
    n = parse_number(v)
    return Decimal(str(round(max(0.0, min(n, 100_000_000.0)), 2))) if n is not None else default


# ================================================================ panel de la empresa
@router.get('/empresa', response_class=HTMLResponse)
def live(request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    rides.tick(db)
    since = local_day_start_utc(0)
    done = db.execute(select(func.count(Ride.id), func.coalesce(func.sum(Ride.final_price), 0)).where(
        Ride.company_id == c.id, Ride.status == 'finalizado', Ride.finished_at >= since)).one()
    ok, why = rides.company_ok(c)
    return templates.TemplateResponse(request, 'admin/rides_live.html', _ctx(request, u, c, db, ok=ok, why=why,
        trips_today=done[0], billed_today=Decimal(done[1] or 0), drivers=rides.drivers_count(db, c)))


@router.get('/empresa/vivo.json')
def live_json(request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse):
        return JSONResponse({'error': 'Tu sesión expiró.'}, status_code=401)
    u, c = g
    rides.tick(db)
    now = datetime.utcnow()
    fresh = rides.FRESH * 2
    drivers = db.scalars(select(Courier).where(Courier.ride_company_id == c.id, Courier.active.is_(True))).all()
    active = db.scalars(select(Ride).options(joinedload(Ride.courier)).where(Ride.company_id == c.id, Ride.status.in_(rides.ACTIVE)).order_by(Ride.id)).all()
    by_driver = {r.courier_id: r for r in active if r.courier_id}
    out = []
    for d in drivers:
        connected = d.online and d.location_at is not None and now - d.location_at <= fresh and d.lat is not None
        r = by_driver.get(d.id)
        out.append({'id': d.id, 'name': d.name, 'vehicle': d.vehicle, 'plate': d.plate, 'online': connected,
                    'lat': round(d.lat, 5) if connected else None, 'lng': round(d.lng, 5) if connected else None,
                    'busy': bool(r), 'ride': r.id if r else None})
    waiting = [{'id': r.id, 'origin': r.origin_address or 'Ubicación del pasajero', 'vehicle': r.vehicle,
                'minutes': int((now - r.search_from).total_seconds() // 60), 'lat': r.origin_lat, 'lng': r.origin_lng}
               for r in active if r.status == 'buscando']
    current = [{'id': r.id, 'driver': r.courier.name if r.courier else '—', 'plate': r.courier.plate if r.courier else None,
                'status': r.status, 'label': rides.COMPANY_LABEL[r.status], 'dest': r.dest_address,
                'minutes': int((now - (r.started_at or r.assigned_at or r.created_at)).total_seconds() // 60)}
               for r in active if r.status != 'buscando']
    return {'drivers': out, 'waiting': waiting, 'current': current,
            'counts': {'online': sum(1 for d in out if d['online']), 'busy': len(current), 'waiting': len(waiting)}}


@router.get('/empresa/viajes', response_class=HTMLResponse)
def rides_list(request: Request, status: str = '', db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    q = select(Ride).options(joinedload(Ride.courier)).where(Ride.company_id == c.id)
    if status in rides.STATUS_LABEL:
        q = q.where(Ride.status == status)
    rows = db.scalars(q.order_by(Ride.id.desc()).limit(150)).all()
    return templates.TemplateResponse(request, 'admin/rides_list.html', _ctx(request, u, c, db, rows=rows, status=status, active=rides.ACTIVE))


@router.post('/empresa/viajes/{ride_id}/cancelar')
def ride_cancel(ride_id: int, request: Request, reason: str = Form(''), db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    r = db.get(Ride, ride_id)
    if r and r.company_id == c.id:
        try:
            audit.log(db, 'ride.cancel', 'ride', r.id, user=u, old={'status': r.status}, reason=reason[:200] or None, ip=client_ip(request))
            rides.cancel_by_company(db, r, reason)
        except rides.RideError as exc:
            return _back('/admin/empresa/viajes', error=str(exc))
    return _back('/admin/empresa/viajes', ok='Viaje cancelado.')


# ---------------------------------------------------------------- conductores
@router.get('/empresa/conductores', response_class=HTMLResponse)
def drivers_page(request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    rows = db.scalars(select(Courier).where(Courier.ride_company_id == c.id).order_by(Courier.active.desc(), Courier.name)).all()
    trips = dict(db.execute(select(Ride.courier_id, func.count(Ride.id)).where(Ride.company_id == c.id, Ride.status == 'finalizado').group_by(Ride.courier_id)).all())
    return templates.TemplateResponse(request, 'admin/rides_drivers.html', _ctx(request, u, c, db, rows=rows, trips=trips,
        cap=rides.driver_cap(db, c), count=rides.drivers_count(db, c)))


def _plate(v: str) -> str:
    return re.sub(r'[^A-Z0-9 ]', '', (v or '').upper()).strip()[:12]


@router.post('/empresa/conductores')
def driver_create(request: Request, name: str = Form(...), phone: str = Form(...), vehicle: str = Form('auto'), plate: str = Form(''),
                  car_model: str = Form(''), db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    digits = ''.join(ch for ch in phone if ch.isdigit())
    back = '/admin/empresa/conductores'
    if len(digits) < 8 or not name.strip():
        return _back(back, error='Revisá el nombre y el teléfono (con código de área).')
    if vehicle not in rides.VEHICLES:
        return _back(back, error='Elegí auto o moto.')
    if not _plate(plate):
        return _back(back, error='Cargá la patente del vehículo.')
    cap = rides.driver_cap(db, c)
    if cap is not None and rides.drivers_count(db, c) >= cap:
        return _back(back, error=f'Tu plan permite hasta {cap} conductores activos. Escribile a Trappi para pasar a un plan más grande.')
    if db.scalar(select(Courier).where(Courier.phone == digits)):
        # un conductor trabaja para una sola empresa (y no puede ser repartidor de comida a la vez)
        return _back(back, error='Ese teléfono ya está registrado en Trappi (como conductor o repartidor).')
    from .admin import _new_pin
    pin = _new_pin()
    d = Courier(name=name.strip()[:120], phone=digits, pin_hash=hash_password(pin), vehicle=vehicle, ride_company_id=c.id, city_id=c.city_id,
                plate=_plate(plate), car_model=car_model.strip()[:80] or None, cash_orders_enabled=False, online_orders_enabled=False)
    db.add(d)
    db.flush()
    audit.log(db, 'ride.driver_create', 'courier', d.id, user=u, new={'company': c.id, 'vehicle': vehicle, 'plate': d.plate}, ip=client_ip(request))
    db.commit()
    request.session['ride_driver_pin'] = [d.name, pin]
    return _back(back)


def _driver(db: Session, c: RideCompany, driver_id: int) -> Courier | None:
    d = db.get(Courier, driver_id)
    return d if d and d.ride_company_id == c.id else None


@router.post('/empresa/conductores/{driver_id}')
def driver_edit(driver_id: int, request: Request, vehicle: str = Form('auto'), plate: str = Form(''), car_model: str = Form(''), db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    d = _driver(db, c, driver_id)
    if d and vehicle in rides.VEHICLES and _plate(plate):
        if rides.current_for(db, d) and vehicle != d.vehicle:
            return _back('/admin/empresa/conductores', error='No se puede cambiar el vehículo durante un viaje.')
        d.vehicle, d.plate, d.car_model = vehicle, _plate(plate), car_model.strip()[:80] or None
        db.commit()
    return _back('/admin/empresa/conductores', ok='Conductor guardado.')


@router.post('/empresa/conductores/{driver_id}/pin')
def driver_pin(driver_id: int, request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    d = _driver(db, c, driver_id)
    if d:
        from .admin import _new_pin
        pin = _new_pin()
        d.pin_hash, d.token_version = hash_password(pin), d.token_version + 1  # cierra la sesion abierta
        audit.log(db, 'ride.driver_pin', 'courier', d.id, user=u, ip=client_ip(request))
        db.commit()
        request.session['ride_driver_pin'] = [d.name, pin]
    return _back('/admin/empresa/conductores')


@router.post('/empresa/conductores/{driver_id}/toggle')
def driver_toggle(driver_id: int, request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    d = _driver(db, c, driver_id)
    if d:
        if not d.active:
            cap = rides.driver_cap(db, c)
            if cap is not None and rides.drivers_count(db, c) >= cap:
                return _back('/admin/empresa/conductores', error=f'Tu plan permite hasta {cap} conductores activos.')
        elif rides.current_for(db, d):
            return _back('/admin/empresa/conductores', error=f'{d.name} tiene un viaje en curso.')
        d.active = not d.active
        if not d.active:
            d.online, d.token_version = False, d.token_version + 1
        audit.log(db, 'ride.driver_toggle', 'courier', d.id, user=u, new={'active': d.active}, ip=client_ip(request))
        db.commit()
    return _back('/admin/empresa/conductores')


# ---------------------------------------------------------------- tarifas
@router.get('/empresa/tarifas', response_class=HTMLResponse)
def tariffs_page(request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    by = {v: rides.tariff(c, v) for v in rides.VEHICLES}
    sample_km = 5.0
    preview = {v: rides.price_for(t, sample_km, False) for v, t in by.items() if t and t.enabled}
    return templates.TemplateResponse(request, 'admin/rides_tariffs.html', _ctx(request, u, c, db, by=by, preview=preview, sample_km=sample_km,
        free_wait=platform.get(db, 'rides_wait_free_minutes')))


@router.post('/empresa/tarifas')
async def tariffs_save(request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    form = await request.form()
    old, new = {}, {}
    for v in rides.VEHICLES:
        t = rides.tariff(c, v)
        if t is None:
            t = RideTariff(company_id=c.id, vehicle=v)
            c.tariffs.append(t)
        else:
            old[v] = rides.tariff_json(t) | {'enabled': t.enabled}
        t.enabled = form.get(f'{v}_enabled') == '1'
        t.base = _money(form.get(f'{v}_base', ''))
        t.per_km = _money(form.get(f'{v}_per_km', ''))
        t.per_wait_min = _money(form.get(f'{v}_per_wait_min', ''))
        t.minimum = _money(form.get(f'{v}_minimum', ''))
        t.night_percent = max(0, min(100, form_int(form.get(f'{v}_night_percent')) or 0))
        if t.enabled and t.per_km <= 0 and t.base <= 0:
            return _back('/admin/empresa/tarifas', error=f'Completá la tarifa de {rides.VEHICLES[v].lower()} (bajada de bandera o precio por km).')
        new[v] = rides.tariff_json(t) | {'enabled': t.enabled}
    # los viajes ya pedidos mantienen el precio con el que se pidieron
    audit.log(db, 'ride.tariffs', 'ride_company', c.id, user=u, old=old, new=new, ip=client_ip(request))
    db.commit()
    return _back('/admin/empresa/tarifas', ok='Tarifas guardadas.')


# ---------------------------------------------------------------- habilitacion y plan
@router.get('/empresa/habilitacion', response_class=HTMLResponse)
def license_page(request: Request, db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    ok, why = rides.company_ok(c)
    return templates.TemplateResponse(request, 'admin/rides_license.html', _ctx(request, u, c, db, ok=ok, why=why,
        cap=rides.driver_cap(db, c), count=rides.drivers_count(db, c), fee=rides.monthly_fee(db, c)))


def _date(v: str) -> date | None:
    try:
        return date.fromisoformat((v or '').strip())
    except ValueError:
        return None


@router.post('/empresa/habilitacion')
def license_save(request: Request, legal_name: str = Form(''), cuit: str = Form(''), municipal_license: str = Form(''), insurance_company: str = Form(''),
                 insurance_policy: str = Form(''), insurance_expires: str = Form(''), phone: str = Form(''), address: str = Form(''), db: Session = Depends(get_db)):
    g = company_guard(request, db)
    if isinstance(g, RedirectResponse): return g
    u, c = g
    c.phone, c.address = phone.strip()[:40] or None, address.strip()[:255] or None
    # una vez aprobada, los datos de la habilitacion solo los cambia Trappi (asi no se aprueba una cosa y queda otra)
    if c.approved_at is None or u.role == Role.SUPERADMIN:
        c.legal_name, c.cuit = legal_name.strip()[:200] or None, ''.join(ch for ch in cuit if ch.isdigit() or ch == '-')[:20] or None
        c.municipal_license = municipal_license.strip()[:80] or None
        c.insurance_company, c.insurance_policy = insurance_company.strip()[:120] or None, insurance_policy.strip()[:80] or None
        c.insurance_expires = _date(insurance_expires)
    elif _date(insurance_expires) and (c.insurance_expires is None or _date(insurance_expires) > c.insurance_expires):
        c.insurance_expires = _date(insurance_expires)  # renovar el seguro si se puede
        c.insurance_policy = insurance_policy.strip()[:80] or c.insurance_policy
    audit.log(db, 'ride.license', 'ride_company', c.id, user=u, ip=client_ip(request))
    db.commit()
    return _back('/admin/empresa/habilitacion', ok='Datos guardados. Trappi los revisa para habilitar la empresa.' if c.approved_at is None else 'Datos guardados.')


# ================================================================ superadmin: empresas
def _super(request: Request, db: Session):
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u
    return u if u.role == Role.SUPERADMIN else RedirectResponse('/admin', 303)


@router.get('/viajes', response_class=HTMLResponse)
def companies_page(request: Request, db: Session = Depends(get_db)):
    u = _super(request, db)
    if isinstance(u, RedirectResponse): return u
    request.session.pop(VIEW_KEY, None)
    rows = db.scalars(select(RideCompany).options(joinedload(RideCompany.city), joinedload(RideCompany.tariffs)).order_by(RideCompany.status, RideCompany.name)).unique().all()
    counts = dict(db.execute(select(Courier.ride_company_id, func.count(Courier.id)).where(Courier.ride_company_id.is_not(None), Courier.active.is_(True)).group_by(Courier.ride_company_id)).all())
    trips = dict(db.execute(select(Ride.company_id, func.count(Ride.id)).where(Ride.status == 'finalizado', Ride.finished_at >= local_day_start_utc(29)).group_by(Ride.company_id)).all())
    return templates.TemplateResponse(request, 'admin/rides_companies.html', {
        'user': u, 'rows': rows, 'counts': counts, 'trips': trips, 'plans': rides.PLANS, 'vehicles_of': rides.vehicles_of,
        'company_ok': rides.company_ok, 'cities': db.scalars(select(City).order_by(City.name)).all(), 'cfg': platform.get_all(db),
        'error': request.query_params.get('e'), 'okmsg': request.query_params.get('m'), 'fee_of': lambda c: rides.monthly_fee(db, c),
        'cap_of': lambda c: rides.driver_cap(db, c)})


@router.post('/viajes')
def company_create(request: Request, name: str = Form(...), city_id: str = Form(''), phone: str = Form(''), plan: str = Form('inicial'),
                   owner_email: str = Form(...), owner_password: str = Form(...), db: Session = Depends(get_db)):
    u = _super(request, db)
    if isinstance(u, RedirectResponse): return u
    email = owner_email.strip().lower()
    if not name.strip() or '@' not in email or len(owner_password) < 8:
        return _back('/admin/viajes', e='Completá el nombre, un email y una contraseña de 8 caracteres o más.')
    if db.scalar(select(User).where(User.email == email)):
        return _back('/admin/viajes', e='Ese email ya tiene un usuario en Trappi.')
    slug, n = slugify(name), 2
    base = slug
    while db.scalar(select(RideCompany).where(RideCompany.slug == slug)):
        slug, n = f'{base}-{n}', n + 1
    c = RideCompany(name=name.strip()[:160], slug=slug, city_id=form_int(city_id), phone=phone.strip()[:40] or None,
                    plan=plan if plan in rides.PLANS else 'inicial', status='pendiente')
    c.tariffs = [RideTariff(vehicle=v, enabled=False) for v in rides.VEHICLES]
    db.add(c)
    db.flush()
    db.add(User(email=email, password_hash=hash_password(owner_password), role=Role.RIDE_ADMIN, ride_company_id=c.id))
    audit.log(db, 'ride.company_create', 'ride_company', c.id, user=u, new={'name': c.name, 'plan': c.plan, 'owner': email}, ip=client_ip(request))
    db.commit()
    return _back('/admin/viajes', m=f'Empresa creada. Entra en /admin/login con {email} y carga su habilitación, sus tarifas y sus conductores.')


@router.post('/viajes/{company_id}')
def company_update(company_id: int, request: Request, plan: str = Form('inicial'), monthly_fee: str = Form(''), driver_cap: str = Form(''),
                   extra_driver_fee: str = Form(''), city_id: str = Form(''), action: str = Form('save'), note: str = Form(''), db: Session = Depends(get_db)):
    u = _super(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(RideCompany, company_id)
    if not c:
        return _back('/admin/viajes')
    old = {'status': c.status, 'plan': c.plan, 'fee': str(c.monthly_fee) if c.monthly_fee is not None else None, 'cap': c.driver_cap}
    c.plan = plan if plan in rides.PLANS else c.plan
    c.monthly_fee = _money(monthly_fee) if monthly_fee.strip() else None
    c.driver_cap = form_int(driver_cap) or None
    c.extra_driver_fee = _money(extra_driver_fee) if extra_driver_fee.strip() else None
    c.city_id = form_int(city_id)
    c.review_note = note.strip()[:500] or None
    if action == 'approve':
        missing = [label for label, v in (('habilitación municipal', c.municipal_license), ('seguro de pasajeros', c.insurance_policy),
                                          ('vencimiento del seguro', c.insurance_expires)) if not v]
        if missing:
            db.rollback()
            return _back('/admin/viajes', e=f'{c.name}: falta {", ".join(missing)} para aprobarla.')
        if c.insurance_expires < date.today():
            db.rollback()
            return _back('/admin/viajes', e=f'{c.name}: el seguro está vencido.')
        c.status, c.approved_at, c.approved_by = 'activa', datetime.utcnow(), u.id
    elif action == 'suspend':
        c.status = 'suspendida'
    elif action == 'reactivate' and c.approved_at:
        c.status = 'activa'
    audit.log(db, f'ride.company_{action}', 'ride_company', c.id, user=u, old=old,
              new={'status': c.status, 'plan': c.plan, 'fee': str(c.monthly_fee) if c.monthly_fee is not None else None, 'cap': c.driver_cap},
              reason=c.review_note, ip=client_ip(request))
    db.commit()
    return _back('/admin/viajes', m=f'{c.name}: guardado.')
