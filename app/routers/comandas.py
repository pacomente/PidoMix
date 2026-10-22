"""Modo comandas: pantalla de pedidos para dejar abierta en la PC o tablet del local.

Se instala como app (PWA) desde el navegador, avisa con alarma y notificacion cuando
entra un pedido e imprime el ticket. Reusa las reglas de estado del panel de pedidos.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import DeliveryOffer, Order, OrderMessage, Product, ProductStatus, Role, Store, StorePushSubscription, StoreStatus
from ..services import audit, dispatch, owner_alerts, webpush
from ..services.ratelimit import client_ip
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
    # chat con el cadete: ultimo mensaje que no es del local (para el aviso en la tarjeta)
    chats = {}
    with_courier = [o.id for o in deliveries if o.courier_id]
    if with_courier:
        for oid, last in db.execute(select(OrderMessage.order_id, func.max(OrderMessage.id)).where(
                OrderMessage.order_id.in_(with_courier), OrderMessage.thread == 'local', OrderMessage.sender != 'store').group_by(OrderMessage.order_id)):
            chats[oid] = last
    return {'user': u, 'columns': columns, 'pending': columns[0]['orders'], 'to_local': to_local, 'offers': offers, 'courier_options': options, 'chats': chats}


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


# ---- "Estoy a full": mas demora o pausa por un rato, y agotar productos con un toque ----
BUSY_MODES = {'15': 15, '30': 30}
BUSY_FOR = timedelta(minutes=60)  # despues vuelve solo a lo normal


def _own_store(request: Request, db: Session):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u, None
    store = db.get(Store, u.store_id) if u.role != Role.SUPERADMIN and u.store_id else None
    return u, store


@router.post('/demora')
def comandas_busy(request: Request, mode: str = Form(...), db: Session = Depends(get_db)):
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse): return u
    if store and store.status == StoreStatus.ACTIVA and mode in ('normal', 'pause', *BUSY_MODES):
        old = {'busy_minutes': store.busy_extra or None, 'paused': store.is_paused}
        now = datetime.utcnow()
        store.busy_minutes, store.busy_until = (BUSY_MODES[mode], now + BUSY_FOR) if mode in BUSY_MODES else (None, None)
        store.paused_until = now + BUSY_FOR if mode == 'pause' else None
        audit.log(db, f'store.busy.{mode}', 'store', store.id, user=u, old=old, new={'busy_minutes': store.busy_minutes, 'paused_until': store.paused_until},
                  ip=client_ip(request))
        db.commit()
    return RedirectResponse('/admin/comandas', 303)


def _stock_page(request: Request, db: Session, store: Store):
    products = db.scalars(select(Product).options(joinedload(Product.section)).where(
        Product.store_id == store.id, Product.deleted.is_(False), Product.status == ProductStatus.ACTIVO)
        .order_by(Product.display_order, Product.name)).all()
    groups = {}
    for p in products:
        groups.setdefault(p.section.name if p.section else 'Otros', []).append(p)
    return templates.TemplateResponse(request, 'admin/_comandas_stock.html', {'groups': groups})


@router.get('/stock', response_class=HTMLResponse)
def comandas_stock(request: Request, db: Session = Depends(get_db)):
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse) or not store: return Response(status_code=401 if isinstance(u, RedirectResponse) else 404)
    return _stock_page(request, db, store)


@router.post('/stock/{product_id}', response_class=HTMLResponse)
def comandas_stock_toggle(product_id: int, request: Request, db: Session = Depends(get_db)):
    """Agotado (stock 0) o de nuevo disponible (sin limite de stock)."""
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse) or not store: return Response(status_code=401 if isinstance(u, RedirectResponse) else 404)
    p = db.get(Product, product_id)
    if p and p.store_id == store.id and not p.deleted:
        old = p.stock
        p.stock = None if p.stock is not None and p.stock <= 0 else 0
        audit.log(db, 'product.stock.quick', 'product', p.id, user=u, old={'stock': old}, new={'stock': p.stock}, ip=client_ip(request))
        db.commit()
    return _stock_page(request, db, store)


# ---- avisos al celular del dueño (notificacion web) ----
ALERTS = {'alert_new_order': 'Pedido nuevo', 'alert_late': 'Pedido sin aceptar a los 3 minutos', 'alert_summary': 'Resumen del día (23 h)'}


@router.get('/push/key')
def push_key(request: Request, endpoint: str = '', db: Session = Depends(get_db)):
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse) or not store: return JSONResponse({'ok': False}, status_code=401 if isinstance(u, RedirectResponse) else 404)
    count = db.scalar(select(func.count(StorePushSubscription.id)).where(StorePushSubscription.store_id == store.id)) or 0
    this = bool(endpoint) and bool(db.scalar(select(StorePushSubscription.id).where(StorePushSubscription.store_id == store.id, StorePushSubscription.endpoint == endpoint)))
    return {'ok': True, 'key': webpush.vapid_keys(db)[1], 'devices': count, 'subscribed': this,
            'alerts': {k: getattr(store, k) for k in ALERTS}, 'whatsapp': owner_alerts.whatsapp_enabled()}


@router.post('/push/subscribe')
async def push_subscribe(request: Request, db: Session = Depends(get_db)):
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse) or not store: return JSONResponse({'ok': False}, status_code=401 if isinstance(u, RedirectResponse) else 404)
    try:
        body = await request.json()
        endpoint, keys = str(body['endpoint'])[:1000], body.get('keys') or {}
        p256dh, auth = str(keys['p256dh'])[:255], str(keys['auth'])[:255]
        if len(webpush.unb64u(p256dh)) != 65 or len(webpush.unb64u(auth)) != 16: raise ValueError
    except (ValueError, KeyError, TypeError):
        return JSONResponse({'ok': False, 'error': 'Suscripción inválida.'}, status_code=400)
    if not webpush.allowed_endpoint(endpoint):
        return JSONResponse({'ok': False, 'error': 'Este navegador no es compatible con las notificaciones.'}, status_code=400)
    row = db.scalar(select(StorePushSubscription).where(StorePushSubscription.endpoint == endpoint))
    if not row:
        count = db.scalar(select(func.count(StorePushSubscription.id)).where(StorePushSubscription.store_id == store.id)) or 0
        if count >= owner_alerts.MAX_SUBSCRIPTIONS:
            return JSONResponse({'ok': False, 'error': f'Ya hay {count} dispositivos con avisos. Desactivá alguno primero.'}, status_code=400)
        row = StorePushSubscription(endpoint=endpoint)
        db.add(row)
    row.store_id, row.user_id, row.p256dh, row.auth = store.id, u.id, p256dh, auth
    row.label = (str(body.get('label') or '')[:120] or None)
    audit.log(db, 'store.push.subscribe', 'store', store.id, user=u, new={'label': row.label}, ip=client_ip(request))
    db.commit()
    owner_alerts.push_store_later(store.id, {'title': '✅ Avisos activados', 'body': f'Te vamos a avisar acá cuando entre un pedido en {store.name}.',
                                      'tag': 'push-test', 'url': '/admin/comandas'})
    return {'ok': True}


@router.post('/push/unsubscribe')
async def push_unsubscribe(request: Request, db: Session = Depends(get_db)):
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse) or not store: return JSONResponse({'ok': False}, status_code=401 if isinstance(u, RedirectResponse) else 404)
    try:
        endpoint = str((await request.json())['endpoint'])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({'ok': False}, status_code=400)
    row = db.scalar(select(StorePushSubscription).where(StorePushSubscription.endpoint == endpoint, StorePushSubscription.store_id == store.id))
    if row:
        db.delete(row)
        audit.log(db, 'store.push.unsubscribe', 'store', store.id, user=u, ip=client_ip(request))
        db.commit()
    return {'ok': True}


@router.post('/push/alerts')
async def push_alerts(request: Request, db: Session = Depends(get_db)):
    """Que avisos quiere recibir el local (los tres vienen prendidos)."""
    u, store = _own_store(request, db)
    if isinstance(u, RedirectResponse) or not store: return JSONResponse({'ok': False}, status_code=401 if isinstance(u, RedirectResponse) else 404)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({'ok': False}, status_code=400)
    changed = {k: bool(body[k]) for k in ALERTS if k in body and bool(body[k]) != getattr(store, k)}
    if changed:
        for k, v in changed.items():
            setattr(store, k, v)
        audit.log(db, 'store.alerts', 'store', store.id, user=u, new=changed, ip=client_ip(request))
        db.commit()
    return {'ok': True, 'alerts': {k: getattr(store, k) for k in ALERTS}}


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
// Avisos al dueño (pedido nuevo, sin aceptar, resumen): llegan aunque la pantalla de comandas este cerrada
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Trappi Comandas', {
    body: d.body || '', tag: d.tag || 'trappi', renotify: true, requireInteraction: !!d.urgent,
    icon: '/static/icons/comandas-192.png', badge: '/static/icons/comandas-192.png', vibrate: d.urgent ? [300, 120, 300, 120, 300] : undefined,
    data: { url: d.url || '/admin/comandas' },
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/admin/comandas';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const win = list.find(c => c.url.includes('/admin/comandas'));
    return win ? win.focus() : self.clients.openWindow(url);
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
