"""Trappi Mandados: el cliente manda algo de una dirección a otra con la flota de Trappi.

- Es un pedido como cualquier otro (lo reparte la flota, se sigue en vivo, tiene PIN de entrega y entra en la caja del
  repartidor), pero se retira en la dirección que puso el cliente, no en un local. Lo "vende" un local interno por ciudad,
  "Trappi Mandados", que no aparece en la app (inactivo) y no cobra comisión: lo que paga el cliente es el envío.
- El precio lo calcula el servidor con las zonas y tarifas de la flota (la misma cuenta que el envío de un pedido),
  desde la dirección de retiro hasta la de entrega. Las dos tienen que estar dentro de la zona de la flota.
- No hay local que lo acepte: queda confirmado al pedirlo y se le ofrece a los repartidores enseguida.
- Se paga en efectivo al repartidor al entregarlo (entra en su caja), o con Mercado Pago si el local interno de la ciudad
  tiene conectada la cuenta de Mercado Pago de Trappi (Panel → Mandados): hasta que se aprueba el pago no sale a buscar repartidor.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Customer, Order, OrderStatus, Store, StoreStatus
from . import cities, logistics, payments, plans, platform
from .orders import record

KINDS = {'documentos': '📄 Documentos', 'llaves': '🔑 Llaves', 'paquete': '📦 Paquete', 'regalo': '🎁 Regalo', 'otro': '➕ Otro'}
SIZES = {'chico': 'Chico (entra en la mano)', 'mediano': 'Mediano (mochila)', 'grande': 'Grande (caja de moto)'}
FORBIDDEN = 'No se mandan plata, armas, drogas, animales ni nada prohibido o peligroso.'


class ErrandError(Exception):
    pass


def enabled(db: Session, city_id: int | None) -> bool:
    return bool(platform.for_city(db, city_id).get('errands_enabled'))


def hub(db: Session, city_id: int | None) -> Store:
    """El local interno "Trappi Mandados" de la ciudad (lo crea la primera vez). Inactivo: no aparece en la app."""
    slug = f'trappi-mandados-{city_id or 0}'
    store = db.scalar(select(Store).where(Store.slug == slug))
    if store is None:
        store = Store(name='Trappi Mandados', slug=slug, city_id=city_id, status=StoreStatus.INACTIVA, account_status='activo',
                      plan=plans.DELIVERY, logistics='trappi', delivery_enabled=True, delivery_cost=Decimal('0'),
                      commission_rate=Decimal('0'), commission_fixed=Decimal('0'), commission_min=Decimal('0'), commission_max=Decimal('0'),
                      description='Mandados de los clientes (lo usa Trappi, no es un local real).')
        db.add(store)
        db.flush()
    return store


def hub_of(db: Session, city_id: int | None) -> Store | None:
    """El local interno de la ciudad, sin crearlo."""
    return db.scalar(select(Store).where(Store.slug == f'trappi-mandados-{city_id or 0}'))


def payment_methods(db: Session, city_id: int | None) -> list[str]:
    """Cómo se puede pagar un mandado en esta ciudad."""
    from . import mercadopago
    store = hub_of(db, city_id)
    return ['efectivo'] + (['mercadopago'] if store is not None and mercadopago.available_for(db, store) else [])


def on_paid(order: Order) -> None:
    """Mercado Pago aprobó el pago de un mandado: recién ahí sale a buscar repartidor. No hace commit."""
    if is_errand(order) and order.status == OrderStatus.PENDIENTE:
        _ready(order)


def _ready(order: Order) -> None:
    # no hay local que lo acepte ni que lo prepare: queda listo para retirar y sale a buscar repartidor
    from datetime import datetime
    order.confirmed_at, order.ready_minutes = datetime.utcnow(), 0
    for st in (OrderStatus.CONFIRMADO, OrderStatus.LISTO):
        order.status = st
        record(order, st)


def is_errand(order: Order) -> bool:
    return order.pickup_lat is not None and order.pickup_lng is not None


def data(order: Order) -> dict:
    try:
        return json.loads(order.errand or '{}')
    except ValueError:
        return {}


def origin(order: Order) -> SimpleNamespace:
    """Dónde retira el repartidor: la dirección del mandado o el local."""
    if is_errand(order):
        d = data(order)
        who = d.get('pickup') or {}
        return SimpleNamespace(name=f'Mandado · {who.get("name") or "retiro"}', address=order.pickup_address, lat=order.pickup_lat,
                               lng=order.pickup_lng, phone=who.get('phone'), whatsapp=who.get('phone'), note=who.get('note'))
    s = order.store
    return SimpleNamespace(name=s.name, address=s.address, lat=s.lat, lng=s.lng, phone=s.phone, whatsapp=s.whatsapp or s.phone, note=None)


def _place(p: dict | None, what: str) -> dict:
    if not p:
        raise ErrandError(f'Marcá {what} en el mapa.')
    try:
        lat, lng = float(p['lat']), float(p['lng'])
    except (KeyError, TypeError, ValueError):
        raise ErrandError(f'Marcá {what} en el mapa.')
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ErrandError(f'Marcá {what} en el mapa.')
    address = ' '.join(str(p.get('address') or '').split())[:255]
    if not address:
        raise ErrandError(f'Escribí la dirección de {what}.')
    return {'lat': lat, 'lng': lng, 'address': address}


@dataclass
class Quote:
    price: Decimal
    km: float
    eta_min: int | None
    eta_max: int | None
    raw: logistics.DeliveryQuote
    city_id: int | None


def quote(db: Session, pickup: dict, dropoff: dict, city_id: int | None = None) -> Quote:
    """Precio del mandado con las tarifas de la flota, de la dirección de retiro a la de entrega."""
    a, b = _place(pickup, 'dónde se retira'), _place(dropoff, 'dónde se entrega')
    if city_id is None:
        c = cities.detect(db, a['lat'], a['lng'])
        city_id = c.id if c is not None else None
    if not enabled(db, city_id):
        raise ErrandError('Los mandados todavía no están disponibles en tu ciudad.')
    zones = [z for z in logistics.zones(db) if cities.same_city(z.city_id, city_id)]
    if not zones:
        raise ErrandError('Los mandados todavía no están disponibles en tu ciudad.')
    if not logistics.matching(zones, a['lat'], a['lng']):
        raise ErrandError('Todavía no retiramos en esa dirección: está fuera de la zona de Trappi.')
    fake = SimpleNamespace(delivery_enabled=True, logistics='trappi', city_id=city_id, lat=a['lat'], lng=a['lng'], prep_minutes=0,
                           delivery_fee_payer='CUSTOMER', fee_share_mode=None, fee_share_value=None)
    q = logistics.delivery_quote(db, fake, {'lat': b['lat'], 'lng': b['lng']})
    if q.mode != 'trappi' or not q.zoned or not q.covered or q.fee_real is None:
        raise ErrandError(q.reason or 'No llegamos a esa dirección de entrega.')
    if q.fee_customer is None:
        raise ErrandError('No pudimos calcular el precio. Probá de nuevo en un rato.')
    return Quote(price=logistics.money(q.fee_customer), km=round(q.route_km or 0, 1), eta_min=q.eta_min, eta_max=q.eta_max, raw=q, city_id=city_id)


def _phone(v) -> str:
    v = ''.join(ch for ch in str(v or '') if ch.isdigit() or ch == '+')[:20]
    return v if len(''.join(ch for ch in v if ch.isdigit())) >= 6 else ''


def create(db: Session, *, account, pickup: dict, dropoff: dict, kind: str, size: str, what: str = '', sender: dict | None = None,
           recipient: dict | None = None, city_id: int | None = None, ip: str | None = None, payment_method: str = 'efectivo') -> Order:
    """Crea el mandado (confirmado al instante: lo toma la flota). No hace commit."""
    cfg = platform.get_all(db)
    if not cfg['orders_enabled']:
        raise ErrandError(cfg['orders_message'])
    if account is None:
        raise ErrandError('Entrá con tu cuenta para mandar algo.')
    if not account.active:
        raise ErrandError('Tu cuenta está bloqueada. Si creés que es un error, escribinos por WhatsApp.')
    if kind not in KINDS:
        raise ErrandError('Elegí qué mandás.')
    if size not in SIZES:
        raise ErrandError('Elegí el tamaño.')
    what = ' '.join((what or '').split())[:200]
    if kind == 'otro' and len(what) < 3:
        raise ErrandError('Contanos qué mandás.')
    sender, recipient = sender or {}, recipient or {}
    s_name, s_phone = ' '.join(str(sender.get('name') or '').split())[:80], _phone(sender.get('phone'))
    r_name, r_phone = ' '.join(str(recipient.get('name') or '').split())[:80], _phone(recipient.get('phone'))
    if not s_name or not s_phone:
        raise ErrandError('Poné quién entrega el mandado y su teléfono.')
    if not r_name or not r_phone:
        raise ErrandError('Poné quién lo recibe y su teléfono.')
    q = quote(db, pickup, dropoff, city_id)
    if payment_method not in payment_methods(db, q.city_id):
        raise ErrandError('Esa forma de pago no está disponible para mandados. Elegí efectivo.')
    a, b = _place(pickup, 'dónde se retira'), _place(dropoff, 'dónde se entrega')
    store = hub(db, q.city_id)
    first, _, last = r_name.partition(' ')
    customer = Customer(first_name=first[:100], last_name=last[:100], phone=r_phone, address=b['address'], email=account.email)
    detail = {'kind': kind, 'size': size, 'what': what,
              'pickup': {'name': s_name, 'phone': s_phone, 'note': ' '.join(str(pickup.get('note') or '').split())[:160]},
              'recipient': {'name': r_name, 'phone': r_phone, 'note': ' '.join(str(dropoff.get('note') or '').split())[:160]},
              'account_name': ' '.join(x for x in [account.first_name, account.last_name] if x) or None}
    order = Order(store_id=store.id, customer=customer, account_id=account.id, origin='app', ip=(ip or '')[:64] or None,
                  delivery_method='delivery', payment_method=payment_method, address=b['address'], reference=detail['recipient']['note'] or None,
                  notes=f'{KINDS[kind]} · {SIZES[size]}' + (f' · {what}' if what else ''),
                  subtotal=Decimal('0'), shipping=q.price, discount=Decimal('0'), total=q.price,
                  delivery_pin=payments.new_pin(), pickup_code=None, lat=b['lat'], lng=b['lng'], distance_km=round(q.raw.distance, 2) if q.raw.distance is not None else None,
                  pickup_address=a['address'], pickup_lat=a['lat'], pickup_lng=a['lng'], errand=json.dumps(detail, ensure_ascii=False))
    order.store = store
    plans.snapshot(order, store, db=db, quote=q.raw)
    db.add(order)
    record(order, OrderStatus.PENDIENTE)
    if payment_method in payments.ONLINE:
        order.payment_status = 'pending'  # lo aprueba solo la consulta a Mercado Pago (webhook verificado): ahí pasa a listo
    else:
        _ready(order)
    return order


def public(order: Order) -> dict | None:
    """Lo que ve el cliente del mandado (en el seguimiento)."""
    if not is_errand(order):
        return None
    d = data(order)
    return {'kind': d.get('kind'), 'kind_label': KINDS.get(d.get('kind'), ''), 'size': d.get('size'), 'size_label': SIZES.get(d.get('size'), ''),
            'what': d.get('what') or None,
            'pickup': {'address': order.pickup_address, 'lat': order.pickup_lat, 'lng': order.pickup_lng, **(d.get('pickup') or {})},
            'recipient': d.get('recipient') or {}}


def for_courier(order: Order) -> dict | None:
    """Lo que ve el repartidor: qué lleva, quién entrega y quién recibe."""
    if not is_errand(order):
        return None
    d = data(order)
    return {'kind_label': KINDS.get(d.get('kind'), 'Mandado'), 'size_label': SIZES.get(d.get('size'), ''), 'what': d.get('what') or None,
            'pickup': d.get('pickup') or {}, 'recipient': d.get('recipient') or {}}
