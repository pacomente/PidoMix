"""Modo comandas: pantalla de pedidos para dejar abierta en la PC o tablet del local.

Se instala como app (PWA) desde el navegador, avisa con alarma y notificacion cuando
entra un pedido e imprime el ticket. Reusa las reglas de estado del panel de pedidos.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import DeliveryOffer, Order, Role, Store
from ..services import dispatch
from ..services.orders import FINAL
from ..services.store_hours import to_local
from .admin import ORDER_CARD, _order_scope, can_manage_store, courier_options, guard, templates

router = APIRouter()


def _active_orders(db: Session, u):
    return db.scalars(select(Order).options(*ORDER_CARD).where(*_order_scope(u), Order.status.not_in(FINAL)).order_by(Order.created_at)).all()


# Columnas de la pantalla de cocina: que hay que aceptar, que se esta cocinando, que hay que despachar
COLUMNS = (
    ('nuevos', 'Nuevos', ('PENDIENTE',)),
    ('cocina', 'En cocina', ('CONFIRMADO', 'PREPARANDO')),
    ('entregar', 'Para entregar', ('LISTO', 'EN_CAMINO')),
)


def _board_context(db: Session, u):
    orders = _active_orders(db, u)  # ya vienen del mas viejo al mas nuevo: lo urgente arriba
    columns = [{'key': key, 'title': title, 'orders': [o for o in orders if o.status.value in statuses]} for key, title, statuses in COLUMNS]
    # repartidores: a quien se le esta ofreciendo cada delivery y a quien se lo puede asignar a mano
    deliveries = [o for o in orders if o.delivery_method == 'delivery' and o.status.value != 'PENDIENTE']
    offers = {}
    if deliveries:
        for off in db.scalars(select(DeliveryOffer).options(joinedload(DeliveryOffer.courier)).where(
                DeliveryOffer.order_id.in_([o.id for o in deliveries]), DeliveryOffer.status == 'pending')):
            offers[off.order_id] = off
    options = {o.id: courier_options(db, o) for o in deliveries if o.status.value != 'EN_CAMINO'}
    return {'user': u, 'columns': columns, 'pending': columns[0]['orders'], 'to_local': to_local, 'offers': offers, 'courier_options': options}


@router.get('', response_class=HTMLResponse)
def comandas(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    store = db.scalar(select(Store).options(joinedload(Store.hours)).where(Store.id == u.store_id)) if u.role != Role.SUPERADMIN and u.store_id else None
    return templates.TemplateResponse(request, 'admin/comandas.html', {**_board_context(db, u), 'store': store})


@router.get('/board', response_class=HTMLResponse)
def comandas_board(request: Request, db: Session = Depends(get_db)):
    """Solo las tarjetas: la pantalla las vuelve a pedir cuando cambia algun pedido."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return Response(status_code=401)
    response = templates.TemplateResponse(request, 'admin/_comandas_board.html', _board_context(db, u))
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/manifest.webmanifest')
def comandas_manifest():
    return JSONResponse({
        'name': 'Trappi Comandas', 'short_name': 'Comandas', 'id': '/admin/comandas',
        'description': 'Recibí los pedidos de Trappi en la PC del local',
        'start_url': '/admin/comandas', 'scope': '/admin/comandas', 'display': 'standalone',
        'background_color': '#1B1230', 'theme_color': '#1B1230', 'lang': 'es-AR',
        'icons': [
            {'src': '/static/icons/comandas-192.png', 'sizes': '192x192', 'type': 'image/png'},
            {'src': '/static/icons/comandas-512.png', 'sizes': '512x512', 'type': 'image/png'},
            {'src': '/static/icons/comandas.svg', 'sizes': 'any', 'type': 'image/svg+xml'},
        ],
    }, media_type='application/manifest+json')


SERVICE_WORKER = """
// Trappi Comandas: necesario para instalar la app y para que el clic en la notificacion
// traiga la ventana al frente. No cachea nada: los pedidos siempre vienen del servidor.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const win = list.find(c => c.url.includes('/admin/comandas'));
    return win ? win.focus() : self.clients.openWindow('/admin/comandas');
  }));
});
"""


@router.get('/sw.js')
def comandas_sw():
    return Response(SERVICE_WORKER, media_type='application/javascript', headers={'Service-Worker-Allowed': '/admin/comandas', 'Cache-Control': 'no-cache'})


@router.get('/ticket/{order_id}', response_class=HTMLResponse)
def comandas_ticket(order_id: int, request: Request, db: Session = Depends(get_db)):
    """Ticket para impresora termica de 80 mm (tambien sirve en 58 mm)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    o = db.scalar(select(Order).options(*ORDER_CARD, joinedload(Order.coupon)).where(Order.id == order_id))
    if not o or not can_manage_store(u, o.store_id): return Response('Pedido no encontrado', status_code=404)
    return templates.TemplateResponse(request, 'admin/ticket.html', {'o': o, 'to_local': to_local})
