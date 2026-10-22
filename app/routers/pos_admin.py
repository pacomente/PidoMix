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
from ..services import audit, platform, pos, pos_points
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
