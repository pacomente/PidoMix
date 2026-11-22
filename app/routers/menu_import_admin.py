"""Panel: cargar el menú del local desde una planilla (ver services/menu_import.py).

GET  /admin/menu/importar          formulario (el superadmin elige el local con ?store=)
POST /admin/menu/importar          sube la planilla y muestra la vista previa (todavía no cambia nada)
POST /admin/menu/importar/confirmar vuelve a leer la misma planilla en el servidor y crea/actualiza los productos
GET  /admin/menu/planilla-modelo.csv
"""
import base64
import binascii

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, Store
from ..services import audit, menu_import
from ..services.forms import form_int
from ..services.ratelimit import client_ip
from .admin import guard, templates

router = APIRouter()


def _store(request: Request, db: Session, u) -> Store | None:
    if u.role == Role.SUPERADMIN:
        sid = form_int(request.query_params.get('store'))
        return db.get(Store, sid) if sid else None
    return db.get(Store, u.store_id) if u.store_id else None


def _page(request, db, u, store, **ctx):
    stores = [(s.id, s.name) for s in db.scalars(select(Store).order_by(Store.name))] if u.role == Role.SUPERADMIN and store is None else None
    return templates.TemplateResponse(request, 'admin/menu_import.html', {'user': u, 'store': store, 'stores': stores,
                                                                          'store_q': f'?store={store.id}' if store and u.role == Role.SUPERADMIN else '', **ctx})


@router.get('/menu/importar', response_class=HTMLResponse)
def form(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    store = _store(request, db, u)
    if store is None and u.role != Role.SUPERADMIN:
        return RedirectResponse('/admin', 303)
    return _page(request, db, u, store)


@router.get('/menu/planilla-modelo.csv')
def template_csv(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    return Response(('﻿' + menu_import.TEMPLATE_CSV).encode('utf-8'), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="menu-trappi-modelo.csv"'})


@router.post('/menu/importar', response_class=HTMLResponse)
async def preview(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    store = _store(request, db, u)
    if store is None:
        return RedirectResponse('/admin/menu/importar', 303)
    data = await file.read(menu_import.MAX_BYTES + 1)
    try:
        rows = menu_import.plan(db, store, menu_import.parse(data))
    except menu_import.ImportError_ as exc:
        return _page(request, db, u, store, error=str(exc))
    return _page(request, db, u, store, rows=rows, raw=base64.b64encode(data).decode(),
                 counts={'crear': sum(r.action == 'crear' for r in rows), 'actualizar': sum(r.action == 'actualizar' for r in rows),
                         'errores': sum(not r.ok for r in rows)})


@router.post('/menu/importar/confirmar')
def confirm(request: Request, raw: str = Form(...), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    store = _store(request, db, u)
    if store is None:
        return RedirectResponse('/admin/menu/importar', 303)
    try:
        data = base64.b64decode(raw, validate=True)
        result = menu_import.apply(db, store, menu_import.parse(data))  # se valida todo de nuevo en el servidor
    except (binascii.Error, ValueError, menu_import.ImportError_) as exc:
        db.rollback()
        return _page(request, db, u, store, error=str(exc) if isinstance(exc, menu_import.ImportError_) else 'No pudimos leer la planilla. Subila de nuevo.')
    audit.log(db, 'menu.import', 'store', store.id, user=u, new=result, ip=client_ip(request))
    db.commit()
    return _page(request, db, u, store, done=result)
