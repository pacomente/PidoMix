"""Panel: Caja (punto de venta). El local descarga Trappi Caja, maneja sus cajeros y ve sus ventas del mostrador.
El superadmin además define, por comercio, si la tiene y cuánto se le cobra (o lo general de Configuración)."""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import PosCashier, PosSale, PosShift, Role, Store
from ..services import audit, platform, pos, pos_points, pos_salon
from ..services.auth import hash_password
from ..services.forms import form_float, form_int
from ..services.ratelimit import client_ip
from .admin import guard, templates

router = APIRouter()


def _store(request: Request, db: Session, u) -> Store | None:
    if u.role == Role.SUPERADMIN:
        sid = form_int(request.query_params.get('store'))
        return db.get(Store, sid) if sid else None
    return db.get(Store, u.store_id) if u.store_id else None


def _back(u, s, msg='') -> RedirectResponse:
    q = [f'store={s.id}'] if u.role == Role.SUPERADMIN and s else []
    if msg: q.append(f'ok={msg}')
    return RedirectResponse('/admin/caja' + ('?' + '&'.join(q) if q else ''), 303)


@router.get('/caja', response_class=HTMLResponse)
def pos_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    stores = db.scalars(select(Store).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    ctx = {'user': u, 's': s, 'stores': stores, 'cfg': platform.get_all(db), 'error': request.session.pop('pos_error', None)}
    if s:
        ctx.update(enabled=pos.available(db, s), commission=pos.commission(db, s),
                   cashiers=db.scalars(select(PosCashier).where(PosCashier.store_id == s.id).order_by(PosCashier.active.desc(), PosCashier.name)).all(),
                   shift=pos.open_shift(db, s),
                   shifts=db.scalars(select(PosShift).where(PosShift.store_id == s.id, PosShift.closed_at.is_not(None)).order_by(PosShift.id.desc()).limit(10)).all(),
                   sales=[{**pos.sale_json(db, x), 'sold': x.sold_at} for x in db.scalars(select(PosSale).where(PosSale.store_id == s.id).order_by(PosSale.id.desc()).limit(30)).all()],
                   methods=pos.METHOD_LABELS, json=json)
        if ctx['shift']:
            ctx['current'] = pos.shift_summary(db, ctx['shift'])
        ctx['points_pay'] = pos_points.enabled(db, s)
        ctx['features'], ctx['feature_names'] = pos_salon.features(s), pos_salon.FEATURES
        if ctx['features']['screen']:
            base = (settings.public_base_url or str(request.base_url)).rstrip('/')
            ctx['screen_url'] = f'{base}/llamador/{pos_salon.screen_code(db, s)}'
            db.commit()
        ctx['points_trappi_pct'] = pos_points.trappi_percent(db)
        names = {c.id: c.name for c in ctx['cashiers']}
        ctx['names'] = names
    if not s and u.role != Role.SUPERADMIN:
        return RedirectResponse('/admin', 303)
    if s and not ctx['enabled'] and u.role != Role.SUPERADMIN:
        ctx['blocked'] = True
    return templates.TemplateResponse(request, 'admin/pos.html', ctx)


def _valid_pin(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 6


@router.post('/caja/cajeros')
def cashier_add(request: Request, name: str = Form(''), pin: str = Form(''), is_owner: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    name, pin = name.strip()[:60], pin.strip()
    if not name or not _valid_pin(pin):
        request.session['pos_error'] = 'Poné un nombre y un PIN de 4 a 6 números.'
        return _back(u, s)
    db.add(PosCashier(store_id=s.id, name=name, pin_hash=hash_password(pin), is_owner=is_owner in ('1', 'on')))
    audit.log(db, 'pos.cashier_add', 'store', s.id, user=u, new={'name': name}, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'cashier')


@router.post('/caja/cajeros/{cid}')
def cashier_edit(cid: int, request: Request, pin: str = Form(''), active: str = Form(''), is_owner: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    c = db.get(PosCashier, cid)
    if not s or not c or c.store_id != s.id: return RedirectResponse('/admin', 303)
    pin = pin.strip()
    if pin:
        if not _valid_pin(pin):
            request.session['pos_error'] = 'El PIN tiene que tener de 4 a 6 números.'
            return _back(u, s)
        c.pin_hash = hash_password(pin)
    c.active, c.is_owner = active in ('1', 'on'), is_owner in ('1', 'on')
    audit.log(db, 'pos.cashier_edit', 'store', s.id, user=u, new={'cashier': c.name, 'active': c.active, 'pin_changed': bool(pin)}, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'cashier')


@router.post('/caja/desvincular')
def unlink_devices(request: Request, db: Session = Depends(get_db)):
    """Cierra la sesión de todas las cajas de este local (por si se perdió o vendió una compu)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    s.pos_device_version = (s.pos_device_version or 1) + 1
    audit.log(db, 'pos.unlink', 'store', s.id, user=u, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'unlinked')


@router.post('/caja/plan')
def pos_store_terms(request: Request, enabled: str = Form('default'), percent: str = Form(''), fee: str = Form(''), db: Session = Depends(get_db)):
    """Solo superadmin: si este comercio tiene caja y cuánto se le cobra (vacío = lo general)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin/caja', 303)
    old = {'enabled': s.pos_enabled, 'percent': str(s.pos_commission_percent), 'fee': str(s.pos_monthly_fee)}
    s.pos_enabled = {'on': True, 'off': False}.get(enabled)
    pct, mf = form_float(percent), form_float(fee)
    s.pos_commission_percent = None if pct is None else max(0, min(50, pct))
    s.pos_monthly_fee = None if mf is None else max(0, mf)
    audit.log(db, 'pos.terms', 'store', s.id, user=u, old=old, new={'enabled': s.pos_enabled, 'percent': percent, 'fee': fee}, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'terms')


@router.get('/qr-menu', response_class=HTMLResponse)
def menu_qr(request: Request, db: Session = Depends(get_db)):
    """Cartel con el QR del menu del local (mesas, vidriera, bolsas). Con la app de Trappi instalada abre el local
    en la app; si no, la tienda web."""
    import segno
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    base = (settings.public_base_url or 'https://trappi.com.ar').rstrip('/')
    url = f'{base}/tienda/{s.slug}?qr=1'
    qr = segno.make(url, error='q').svg_inline(scale=10, border=1, omitsize=True, dark='#1B1230', light='#fff')
    return templates.TemplateResponse(request, 'admin/menu_qr.html', {'user': u, 's': s, 'url': url, 'qr': qr})


@router.get('/caja/qr-mostrador', response_class=HTMLResponse)
def counter_qr(request: Request, db: Session = Depends(get_db)):
    """Cartel para imprimir y dejar en el mostrador: el cliente lo escanea para pagar con sus Puntos Trappi."""
    import segno
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    code = pos_points.counter_code(db, s)
    db.commit()
    url = pos_points.counter_url(code)
    qr = segno.make(url, error='q').svg_inline(scale=10, border=1, omitsize=True, dark='#1B1230', light='#fff')
    return templates.TemplateResponse(request, 'admin/pos_counter_qr.html', {'user': u, 's': s, 'url': url, 'qr': qr})


@router.post('/caja/qr-mostrador/nuevo')
def counter_qr_new(request: Request, db: Session = Depends(get_db)):
    """Cambia el QR del mostrador (el impreso deja de andar). Por si alguien lo copió."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    s.pos_counter_code = None
    db.flush()
    pos_points.counter_code(db, s)
    audit.log(db, 'pos.counter_qr_new', 'store', s.id, user=u, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'qr')


# ---------- salón: mesas, promos del mostrador y llamador ----------

def _salon_back(u, s, msg='') -> RedirectResponse:
    q = [f'store={s.id}'] if u.role == Role.SUPERADMIN and s else []
    if msg: q.append(f'ok={msg}')
    return RedirectResponse('/admin/caja/salon' + ('?' + '&'.join(q) if q else ''), 303)


@router.get('/caja/salon', response_class=HTMLResponse)
def salon_page(request: Request, db: Session = Depends(get_db)):
    from ..models import PosPromo, PosTable, Product, ProductStatus, StoreSection
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin/caja', 303)
    feats = pos_salon.features(s)
    if not (feats['tables'] or feats['promos']): return _back(u, s)
    tables = db.scalars(select(PosTable).where(PosTable.store_id == s.id, PosTable.active.is_(True)).order_by(PosTable.area, PosTable.row, PosTable.col, PosTable.id)).all()
    promos = db.scalars(select(PosPromo).where(PosPromo.store_id == s.id).order_by(PosPromo.active.desc(), PosPromo.id.desc())).all()
    products = db.scalars(select(Product).where(Product.store_id == s.id, Product.deleted.is_(False), Product.status == ProductStatus.ACTIVO).order_by(Product.name)).all()
    sections = db.scalars(select(StoreSection).where(StoreSection.store_id == s.id, StoreSection.active.is_(True)).order_by(StoreSection.display_order)).all()
    return templates.TemplateResponse(request, 'admin/pos_salon.html', {
        'user': u, 's': s, 'tables': tables, 'promos': promos, 'features': feats, 'products': products, 'sections': sections, 'json': json,
        'kinds': pos_salon.KINDS, 'error': request.session.pop('pos_error', None),
        'names': {p.id: p.name for p in products}, 'section_names': {x.id: x.name for x in sections}})


@router.post('/caja/mesas')
async def table_add(request: Request, db: Session = Depends(get_db)):
    """Agrega una mesa, o varias de una ("del 1 al 12")."""
    from ..models import PosTable
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    if not pos_salon.has(s, 'tables'): return _back(u, s)
    f = await request.form()
    area = ' '.join(str(f.get('area') or 'Salón').split())[:30] or 'Salón'
    seats = max(1, min(30, form_int(f.get('seats')) or 4))
    shape = f.get('shape') if f.get('shape') in ('square', 'round', 'long') else 'square'
    have = db.scalars(select(PosTable).where(PosTable.store_id == s.id, PosTable.active.is_(True))).all()
    taken = {(t.area, t.col, t.row) for t in have}
    frm, to = form_int(f.get('from')), form_int(f.get('to'))
    names = [str(n) for n in range(frm, to + 1)] if frm and to and 0 < to - frm < 60 else [' '.join(str(f.get('name') or '').split())[:20]]
    names = [n for n in names if n]
    if not names or len(have) + len(names) > 150:
        request.session['pos_error'] = 'Poné el nombre o número de la mesa (o un rango, por ejemplo del 1 al 12).'
        return _salon_back(u, s)
    per_row = 6
    for name in names:
        i = 0
        while (area, i % per_row, i // per_row) in taken:  # el primer lugar libre del plano
            i += 1
        taken.add((area, i % per_row, i // per_row))
        db.add(PosTable(store_id=s.id, name=name, area=area, seats=seats, shape=shape, col=i % per_row, row=i // per_row))
    audit.log(db, 'pos.tables_add', 'store', s.id, user=u, new={'names': names, 'area': area}, ip=client_ip(request))
    db.commit()
    return _salon_back(u, s, 'tables')


@router.post('/caja/mesas/{tid}')
async def table_edit(tid: int, request: Request, db: Session = Depends(get_db)):
    from ..models import PosTable
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    t = db.get(PosTable, tid)
    if not s or not t or t.store_id != s.id: return RedirectResponse('/admin', 303)
    f = await request.form()
    if f.get('action') == 'delete':
        t.active = False
    else:
        t.name = ' '.join(str(f.get('name') or t.name).split())[:20] or t.name
        t.area = ' '.join(str(f.get('area') or t.area).split())[:30] or t.area
        t.seats = max(1, min(30, form_int(f.get('seats')) or t.seats))
        t.shape = f.get('shape') if f.get('shape') in ('square', 'round', 'long') else t.shape
        t.col = max(0, min(20, form_int(f.get('col'), t.col)))
        t.row = max(0, min(20, form_int(f.get('row'), t.row)))
    db.commit()
    return _salon_back(u, s, 'tables')


@router.post('/caja/promos')
async def promo_add(request: Request, db: Session = Depends(get_db)):
    from ..models import PosPromo, Product, StoreSection
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    if not pos_salon.has(s, 'promos'): return _back(u, s)
    f = await request.form()
    kind = f.get('kind')
    name = ' '.join(str(f.get('name') or '').split())[:80]
    own_products = {p for p in db.scalars(select(Product.id).where(Product.store_id == s.id, Product.deleted.is_(False)))}
    own_sections = {x for x in db.scalars(select(StoreSection.id).where(StoreSection.store_id == s.id))}
    products = [int(x) for x in f.getlist('products') if str(x).isdigit() and int(x) in own_products]
    if kind == 'combo':  # el combo puede llevar dos veces el mismo producto: "cantidad × producto"
        products = []
        for pid in own_products:
            n = form_int(f.get(f'qty_{pid}')) or 0
            products += [pid] * max(0, min(10, n))
    sections = [int(x) for x in f.getlist('sections') if str(x).isdigit() and int(x) in own_sections]
    days = ''.join(d for d in '0123456' if f.get(f'day{d}'))
    start, end = (str(f.get('start') or '').strip()[:5] or None), (str(f.get('end') or '').strip()[:5] or None)
    buy, pay = form_int(f.get('buy')) or 2, form_int(f.get('pay')) or 0
    value = form_float(f.get('value')) or 0
    problem = None
    if kind not in pos_salon.KINDS or not name:
        problem = 'Poné un nombre y elegí el tipo de promo.'
    elif kind in ('nxm', 'percent') and not products and not sections:
        problem = 'Elegí a qué productos o secciones se aplica.'
    elif kind == 'nxm' and not (2 <= buy <= 10 and 0 <= pay < buy):
        problem = 'En "lleva N paga M", M tiene que ser menor que N (por ejemplo 2x1 o 3x2).'
    elif kind == 'percent' and not 0 < value <= 100:
        problem = 'El porcentaje tiene que estar entre 1 y 100.'
    elif kind == 'combo' and (len(products) < 2 or value <= 0):
        problem = 'El combo necesita al menos dos productos y un precio.'
    elif not days:
        problem = 'Elegí al menos un día.'
    elif (start or end) and not (start and end and len(start) == 5 and len(end) == 5 and start[2] == ':' and end[2] == ':'):
        problem = 'El horario va de "18:00" a "21:00" (o vacío para todo el día).'
    if problem:
        request.session['pos_error'] = problem
        return _salon_back(u, s)
    p = PosPromo(store_id=s.id, name=name, kind=kind, buy=buy if kind == 'nxm' else 2, pay=pay if kind == 'nxm' else 1, value=value if kind != 'nxm' else 0,
                 product_ids=json.dumps(products), section_ids=json.dumps(sections if kind != 'combo' else []), days=days, start=start, end=end)
    db.add(p)
    db.flush()
    audit.log(db, 'pos.promo_add', 'pos_promo', p.id, user=u, new={'name': name, 'kind': kind}, ip=client_ip(request))
    db.commit()
    return _salon_back(u, s, 'promo')


@router.post('/caja/promos/{pid}')
def promo_edit(pid: int, request: Request, action: str = Form(''), db: Session = Depends(get_db)):
    from ..models import PosPromo
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    p = db.get(PosPromo, pid)
    if not s or not p or p.store_id != s.id: return RedirectResponse('/admin', 303)
    if action == 'delete':
        db.delete(p)
    else:
        p.active = not p.active
    audit.log(db, f'pos.promo_{action or "toggle"}', 'pos_promo', pid, user=u, ip=client_ip(request))
    db.commit()
    return _salon_back(u, s, 'promo')


@router.post('/caja/llamador/nuevo')
def screen_new(request: Request, db: Session = Depends(get_db)):
    """Cambia el link del llamador (el viejo deja de andar)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin', 303)
    pos_salon.screen_code(db, s, new=True)
    audit.log(db, 'pos.screen_new', 'store', s.id, user=u, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'screen')


@router.post('/caja/funciones')
async def pos_features(request: Request, db: Session = Depends(get_db)):
    """Solo superadmin: qué funciones de la caja tiene este comercio (mesas, llamador, promos...)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    s = _store(request, db, u)
    if not s: return RedirectResponse('/admin/caja', 303)
    f = await request.form()
    old = pos_salon.features(s)
    on = [k for k in pos_salon.FEATURES if f.get(f'f_{k}') in ('1', 'on')]
    s.pos_features = json.dumps(on)
    audit.log(db, 'pos.features', 'store', s.id, user=u, old=[k for k, v in old.items() if v], new=on, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'features')
