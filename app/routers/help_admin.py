"""Panel: "Cómo funciona" (tutorial del panel del local) y el recorrido guiado de la primera vez.

GET /admin/ayuda   guía paso a paso del panel, con links a cada pantalla. El personal ve solo la parte de pedidos.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, Store
from .admin import guard, templates

router = APIRouter()

# Qué parte de la ayuda corresponde a cada pantalla (el botón "Ayuda" de arriba lleva directo ahí).
HELP_FOR = [
    ('/admin/orders', 'pedidos'), ('/admin/comandas', 'pedidos'), ('/admin/products', 'menu'), ('/admin/sections', 'menu'),
    ('/admin/menu', 'menu'), ('/admin/qr-menu', 'menu'), ('/admin/menu-3d', 'menu'), ('/admin/caja', 'caja'),
    ('/admin/repartidores', 'envios'), ('/admin/pagos', 'pagos'), ('/admin/mi-plan', 'pagos'), ('/admin/customers', 'clientes'),
    ('/admin/coupons', 'clientes'), ('/admin/reviews', 'clientes'), ('/admin/reclamos', 'clientes'), ('/admin/whatsapp', 'whatsapp'),
    ('/admin/ia', 'whatsapp'), ('/admin/reports', 'reportes'), ('/admin/equipo', 'equipo'), ('/admin/account', 'equipo'),
    ('/admin/stores', 'primeros-pasos'),
]


def help_anchor(path: str) -> str:
    for prefix, anchor in HELP_FOR:
        if path.startswith(prefix):
            return anchor
    return ''


@router.get('/ayuda', response_class=HTMLResponse)
def help_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    store = db.get(Store, u.store_id) if u.store_id else None
    return templates.TemplateResponse(request, 'admin/help.html', {
        'user': u, 'store': store, 'staff': u.role == Role.STORE_STAFF, 'super': u.role == Role.SUPERADMIN})


templates.env.globals['help_anchor'] = help_anchor
