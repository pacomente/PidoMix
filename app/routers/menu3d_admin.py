"""Panel: menú en 3D ("Ver en tu mesa").

- Superadmin: lo habilita comercio por comercio y puede cargar modelos en cualquier local.
- Local habilitado: sube el .glb (y si quiere el .usdz de iPhone) de cada plato, lo ve girando con su medida
  antes de mostrarlo, y lo prende o apaga plato por plato.
"""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..csp import with_3d_viewer
from ..db import get_db
from ..models import Product, Role, Store
from ..services import audit, menu3d
from ..services.forms import form_int
from ..services.ratelimit import client_ip
from .admin import can_manage_store, guard, templates

router = APIRouter()


def _store(request: Request, db: Session, u) -> Store | None:
    if u.role == Role.SUPERADMIN:
        sid = form_int(request.query_params.get('store'))
        return db.get(Store, sid) if sid else None
    s = db.get(Store, u.store_id) if u.store_id else None
    return s if menu3d.enabled(s) else None


def _product(db: Session, u, product_id: int) -> Product | None:
    p = db.get(Product, product_id)
    if p is None or p.deleted or not can_manage_store(u, p.store_id):
        return None
    if u.role != Role.SUPERADMIN and not menu3d.enabled(p.store):
        return None
    return p


def _back(p: Product, ok: str = '') -> RedirectResponse:
    return RedirectResponse(f'/admin/menu-3d/producto/{p.id}' + (f'?ok={ok}' if ok else ''), 303)


@router.get('/menu-3d', response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if s is None and u.role != Role.SUPERADMIN:
        return RedirectResponse('/admin', 303)
    ctx = {'user': u, 's': s, 'ok': request.query_params.get('ok')}
    if s is None:
        stores = db.scalars(select(Store).order_by(Store.ar_enabled.desc(), Store.name)).all()
        models = dict(db.execute(select(Product.store_id, func.count(Product.id)).where(Product.model_url.is_not(None), Product.deleted.is_(False))
                                 .group_by(Product.store_id)).all())
        ctx.update(stores=stores, models=models)
    else:
        ctx['products'] = db.scalars(select(Product).where(Product.store_id == s.id, Product.deleted.is_(False))
                                     .order_by(Product.model_url.is_(None), Product.display_order, Product.name)).all()
    return templates.TemplateResponse(request, 'admin/menu3d.html', ctx)


@router.post('/menu-3d/habilitar')
def enable(request: Request, store_id: int = Form(...), on: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    s = db.get(Store, store_id)
    if s is None: return RedirectResponse('/admin/menu-3d', 303)
    old, s.ar_enabled = s.ar_enabled, on == '1'
    audit.log(db, 'menu3d.enable', 'store', s.id, user=u, old={'enabled': old}, new={'enabled': s.ar_enabled}, ip=client_ip(request))
    db.commit()
    return RedirectResponse('/admin/menu-3d?ok=enabled', 303)


@router.get('/menu-3d/producto/{product_id}', response_class=HTMLResponse)
def product_page(product_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = _product(db, u, product_id)
    if p is None: return RedirectResponse('/admin/menu-3d', 303)
    return with_3d_viewer(templates.TemplateResponse(request, 'admin/menu3d.html', {
        'user': u, 's': p.store, 'p': p, 'ok': request.query_params.get('ok'), 'error': request.session.pop('menu3d_error', None),
        'max_mb': menu3d.MAX_BYTES // (1024 * 1024)}))


@router.post('/menu-3d/producto/{product_id}/subir')
def upload(product_id: int, request: Request, glb: UploadFile | None = File(None), usdz: UploadFile | None = File(None), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = _product(db, u, product_id)
    if p is None: return RedirectResponse('/admin/menu-3d', 303)
    files = [(k, f) for k, f in (('glb', glb), ('usdz', usdz)) if f is not None and f.filename]
    if not files:
        request.session['menu3d_error'] = 'Elegí el archivo .glb del plato.'
        return _back(p)
    if not p.model_url and not any(k == 'glb' for k, _ in files):
        request.session['menu3d_error'] = 'Primero subí el .glb: es el que se ve en Android, en la PC y también en iPhone.'
        return _back(p)
    try:
        for kind, f in files:
            menu3d.save(db, p, kind, f.file.read(menu3d.MAX_BYTES + 1))
    except menu3d.Model3DError as exc:
        db.rollback()
        request.session['menu3d_error'] = str(exc)
        return _back(p)
    audit.log(db, 'menu3d.upload', 'product', p.id, user=u, new={'files': [k for k, _ in files]}, ip=client_ip(request))
    db.commit()
    return _back(p, 'uploaded')


@router.post('/menu-3d/producto/{product_id}/visible')
def set_visible(product_id: int, request: Request, on: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = _product(db, u, product_id)
    if p is None: return RedirectResponse('/admin/menu-3d', 303)
    p.model_visible = on == '1'
    db.commit()
    return _back(p, 'visible')


@router.post('/menu-3d/producto/{product_id}/borrar')
def remove(product_id: int, request: Request, kind: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = _product(db, u, product_id)
    if p is None: return RedirectResponse('/admin/menu-3d', 303)
    # sin el .glb no hay 3D: borrarlo se lleva tambien el de iPhone
    menu3d.remove(db, p, 'usdz' if kind == 'usdz' else None)
    audit.log(db, 'menu3d.remove', 'product', p.id, user=u, old={'files': [kind or 'todos']}, ip=client_ip(request))
    db.commit()
    return _back(p, 'removed')
