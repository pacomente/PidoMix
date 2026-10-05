"""Multi-ciudad en el panel (superadmin).

  /admin/ciudades                      ciudades: alta, datos y resumen
  /admin/ciudades/{id}                 datos de la ciudad y su configuracion propia (flota, costos, pagos, efectivo)
  /admin/filtro-ciudad                 mirar una sola ciudad en todo el panel
  /admin/comercios/{id}/ciudad         ciudad de un comercio
  /admin/repartidores/{id}/ciudad      ciudad de un repartidor de la flota
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import City, Courier, LogisticsZone, Order, Role, Store
from ..services import audit, cities, platform
from ..services.forms import form_float, form_int
from ..services.ratelimit import client_ip
from .admin import form_data, guard, templates

router = APIRouter()
templates.env.globals['cities_list'] = lambda: _all_for_templates()
templates.env.globals['city_label'] = cities.label


def _all_for_templates():
    from ..db import SessionLocal
    with SessionLocal() as db:
        return cities.all_cities(db, include_inactive=True)


def superadmin(request: Request, db: Session):
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u
    return u if u.role == Role.SUPERADMIN else RedirectResponse('/admin', 303)


def flash(request: Request, kind: str, text: str) -> None:
    request.session['city_flash'] = [kind, text]


def go(path: str) -> RedirectResponse:
    return RedirectResponse(path, 303)


def _counts(db: Session) -> dict[int, dict]:
    since = datetime.utcnow() - timedelta(days=30)
    out: dict[int, dict] = {}
    for label, q in (('stores', select(Store.city_id, func.count(Store.id)).group_by(Store.city_id)),
                     ('couriers', select(Courier.city_id, func.count(Courier.id)).where(Courier.store_id.is_(None), Courier.active.is_(True)).group_by(Courier.city_id)),
                     ('zones', select(LogisticsZone.city_id, func.count(LogisticsZone.id)).where(LogisticsZone.deleted.is_(False)).group_by(LogisticsZone.city_id)),
                     ('orders', select(Order.city_id, func.count(Order.id)).where(Order.created_at >= since).group_by(Order.city_id))):
        for cid, n in db.execute(q).all():
            out.setdefault(cid, {})[label] = int(n)
    return out


@router.get('/ciudades', response_class=HTMLResponse)
def cities_page(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    rows = db.scalars(select(City).order_by(City.display_order, City.name)).all()
    return templates.TemplateResponse(request, 'admin/cities.html', {'user': u, 'cities': rows, 'counts': _counts(db),
                                                                     'flash': request.session.pop('city_flash', None)})


def _apply(c: City, form) -> None:
    name = (form.get('name') or '').strip()[:120]
    if not name:
        raise ValueError('Poné el nombre de la ciudad.')
    c.name = name
    c.province = (form.get('province') or '').strip()[:120] or None
    c.active = form.get('active') in ('1', 'on', 'true')

    def coord(key):
        try:
            return float(str(form.get(key) or '').replace(',', '.'))
        except ValueError:
            return None
    lat, lng = coord('center_lat'), coord('center_lng')
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError('Marcá el centro de la ciudad en el mapa (o poné latitud y longitud).')
    c.center_lat, c.center_lng = lat, lng
    radius = form_float(form.get('radius_km'), 25) or 25
    if not 1 <= radius <= 200:
        raise ValueError('El radio tiene que estar entre 1 y 200 km.')
    c.radius_km = radius
    c.whatsapp = ''.join(ch for ch in (form.get('whatsapp') or '') if ch.isdigit())[:40] or None
    c.display_order = form_int(form.get('display_order'), 0) or 0


@router.post('/ciudades')
def city_save(request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    cid = form_int(form.get('id'))
    c = db.get(City, cid) if cid else City()
    if cid and not c:
        return go('/admin/ciudades')
    before = {'name': c.name, 'active': c.active, 'center': [c.center_lat, c.center_lng], 'radius': c.radius_km} if cid else None
    try:
        _apply(c, form)
    except ValueError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go(f'/admin/ciudades/{cid}' if cid else '/admin/ciudades')
    if not cid:
        base, n = cities.slugify(c.name), 1
        slug = base
        while db.scalar(select(City.id).where(City.slug == slug)):
            n += 1
            slug = f'{base}-{n}'
        c.slug = slug
        db.add(c)
    db.flush()
    if cid and not c.active and db.scalar(select(func.count(City.id)).where(City.active.is_(True))) == 0:
        db.rollback()
        flash(request, 'error', 'Tiene que quedar al menos una ciudad activa.')
        return go(f'/admin/ciudades/{cid}')
    audit.log(db, 'city.update' if cid else 'city.create', 'city', c.id, user=u, old=before,
              new={'name': c.name, 'active': c.active, 'center': [c.center_lat, c.center_lng], 'radius': c.radius_km}, ip=client_ip(request))
    db.commit()
    cities.invalidate()
    flash(request, 'ok', f'Ciudad "{c.name}" guardada.' + ('' if cid else ' Ahora asignale comercios, repartidores y zonas.'))
    return go(f'/admin/ciudades/{c.id}')


@router.get('/ciudades/{city_id}', response_class=HTMLResponse)
def city_detail(city_id: int, request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(City, city_id)
    if not c:
        return go('/admin/ciudades')
    general = platform.get_all(db)
    own = platform.city_overrides(db, c.id)
    keys = [platform.BY_KEY[k] for k in platform.CITY_KEYS]
    groups: dict[str, list] = {}
    for opt in keys:
        title = platform.SECTIONS.get(opt.section, (opt.section,))[0]
        groups.setdefault(title, []).append(opt)
    stores = db.scalars(select(Store).where(Store.city_id == c.id).order_by(Store.name)).all()
    unassigned = db.scalars(select(Store).where(Store.city_id.is_(None)).order_by(Store.name)).all()
    couriers = db.scalars(select(Courier).where(Courier.store_id.is_(None), Courier.city_id == c.id).order_by(Courier.name)).all()
    free_couriers = db.scalars(select(Courier).where(Courier.store_id.is_(None), Courier.city_id.is_(None)).order_by(Courier.name)).all()
    return templates.TemplateResponse(request, 'admin/city_detail.html', {
        'user': u, 'c': c, 'groups': groups, 'general': general, 'own': own, 'stores': stores, 'unassigned': unassigned,
        'couriers': couriers, 'free_couriers': free_couriers, 'counts': _counts(db).get(c.id, {}),
        'tiles': general['web_tiles_url'], 'flash': request.session.pop('city_flash', None)})


@router.post('/ciudades/{city_id}/configuracion')
def city_settings_save(city_id: int, request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(City, city_id)
    if not c:
        return go('/admin/ciudades')
    changed = platform.save_city(db, c.id, {k: v for k, v in form.items() if isinstance(v, str)})
    for key, (old, new) in changed.items():
        audit.log(db, 'city.config', 'city', c.id, user=u, old={key: old}, new={key: new}, ip=client_ip(request))
    db.commit()
    flash(request, 'ok', 'Configuración de la ciudad guardada.' if changed else 'No había cambios.')
    return go(f'/admin/ciudades/{c.id}#configuracion')


@router.post('/filtro-ciudad')
def city_filter_set(request: Request, city: str = Form(''), back: str = Form('/admin'), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    cid = form_int(city)
    if cid and db.get(City, cid):
        request.session['admin_city'] = cid
    else:
        request.session.pop('admin_city', None)
    return go(back if back.startswith('/admin') and '//' not in back else '/admin')


@router.post('/comercios/{store_id}/ciudad')
def store_city_save(store_id: int, request: Request, city: str = Form(''), back: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.get(Store, store_id)
    cid = form_int(city)
    if s and (cid is None or db.get(City, cid)):
        old = s.city_id
        s.city_id = cid
        audit.log(db, 'store.city', 'store', s.id, user=u, old=old, new=cid, ip=client_ip(request))
        db.commit()
        request.session['commercial_flash'] = ['ok', 'Ciudad del comercio guardada. Los pedidos nuevos se rigen por ella.']
    target = back if back.startswith('/admin') and '//' not in back else f'/admin/comercios/{store_id}'
    return go(target)


@router.post('/repartidores/{courier_id}/ciudad')
def courier_city_save(courier_id: int, request: Request, city: str = Form(''), back: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    courier = db.get(Courier, courier_id)
    cid = form_int(city)
    if courier and courier.store_id is None and (cid is None or db.get(City, cid)):
        old = courier.city_id
        courier.city_id = cid
        audit.log(db, 'courier.city', 'courier', courier.id, user=u, old=old, new=cid, ip=client_ip(request))
        db.commit()
    target = back if back.startswith('/admin') and '//' not in back else '/admin/repartidores'
    return go(target)
