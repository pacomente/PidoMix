"""Pedido por teléfono cargado desde la caja: entra como un pedido más (tablero de Comandas, seguimiento, repartidores).

  - Lo toma el local, así que entra aceptado (en cocina). Delivery con los repartidores del local o retiro en el mostrador.
  - Los precios y el envío los pone el servidor: el envío fijo del local o el de la zona (anillo de km) que elige el cajero,
    porque por teléfono no hay ubicación en el mapa.
  - La comisión es la de la caja (no la de los pedidos de la app): el cliente lo pidió al local, no a Trappi.
  - Hace falta internet. La caja manda un client_uuid: si reintenta, no se duplica.
"""
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Customer, Order, OrderItem, OrderStatus, PosCashier, Product, Store
from . import audit, plans, pos
from .logistics import DeliveryQuote
from .orders import record

PAY = ('efectivo', 'transferencia')


def delivery_options(store: Store) -> dict:
    """Lo que la caja muestra para elegir el envío: fijo o por zona (hasta X km)."""
    if not store.delivery_enabled:
        return {'enabled': False, 'zones': [], 'fixed': None, 'merchant_pays': False}
    zones = list(store.zones or []) if store.lat is not None and store.lng is not None else []
    return {'enabled': True, 'merchant_pays': store.delivery_fee_payer == 'MERCHANT',
            'fixed': None if zones else float(pos.money(store.delivery_cost)),
            'zones': [{'id': z.id, 'label': f'Hasta {str(z.max_km).rstrip("0").rstrip(".").replace(".", ",")} km', 'cost': float(pos.money(z.cost))} for z in zones]}


def create(db: Session, store: Store, cashier: PosCashier, data: dict) -> Order:
    """Crea el pedido. No hace commit."""
    uuid = str(data.get('client_uuid') or '').strip()[:40]
    if len(uuid) < 8:
        raise pos.PosError('Falta el identificador del pedido.')
    existing = db.scalar(select(Order).where(Order.store_id == store.id, Order.pos_uuid == uuid))
    if existing:
        return existing
    name = ' '.join(str(data.get('first_name') or '').split())[:100]
    phone = ''.join(ch for ch in str(data.get('phone') or '') if ch.isdigit() or ch in '+ -')[:40].strip()
    if not name or sum(ch.isdigit() for ch in phone) < 6:
        raise pos.PosError('Poné el nombre y el teléfono del cliente.')
    method = data.get('delivery_method')
    if method not in ('delivery', 'retiro'):
        raise pos.PosError('Elegí delivery o retiro.')
    pay = data.get('payment_method') or 'efectivo'
    if pay not in PAY:
        raise pos.PosError('Por teléfono se cobra en efectivo o por transferencia.')
    address = ' '.join(str(data.get('address') or '').split())[:255]
    reference = ' '.join(str(data.get('reference') or '').split())[:255]
    notes = ' '.join(str(data.get('notes') or '').split())[:500]
    lines, subtotal = pos._lines(db, store, data.get('items'))
    if any(not l['product_id'] for l in lines):
        raise pos.PosError('En un pedido por teléfono van productos del menú (sin montos libres).')
    shipping, fee, zone = Decimal('0'), None, None
    if method == 'delivery':
        opts = delivery_options(store)
        if not opts['enabled']:
            raise pos.PosError('El local no tiene el delivery activado (Mi tienda → Envíos).')
        if not address:
            raise pos.PosError('Poné la dirección de entrega.')
        if opts['zones']:
            try:
                zone = next((z for z in store.zones if z.id == int(data.get('zone_id') or 0)), None)
            except (TypeError, ValueError):
                zone = None
            if not zone:
                raise pos.PosError('Elegí hasta cuántos km es el envío.')
            fee = pos.money(zone.cost)
        else:
            fee = pos.money(store.delivery_cost)
        shipping = Decimal('0') if opts['merchant_pays'] else fee
    total = subtotal + shipping
    cash_with = pos.money(data.get('cash_with')) if pay == 'efectivo' and data.get('cash_with') not in (None, '', 0) else None
    if cash_with is not None and cash_with < total:
        raise pos.PosError('El cliente paga con menos que el total.')
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_({l['product_id'] for l in lines}), Product.store_id == store.id))}
    customer = Customer(first_name=name, last_name='', phone=phone, address=address if method == 'delivery' else '', reference=reference)
    order = Order(store_id=store.id, customer=customer, origin='caja', pos_uuid=uuid, delivery_method=method, payment_method=pay, cash_with=cash_with,
                  address=address if method == 'delivery' else '', reference=reference, notes=notes, subtotal=subtotal, shipping=shipping,
                  discount=Decimal('0'), total=total, delivery_pin=None, pickup_code=None, status=OrderStatus.CONFIRMADO,
                  confirmed_at=datetime.utcnow(), ready_minutes=store.prep_minutes)
    quote = None
    if method == 'delivery':  # reparte el local (no la flota): el envío es del local
        quote = DeliveryQuote(zoned=zone is not None, covered=True, cost=shipping, mode='store', fee_real=fee, fee_customer=shipping,
                              fee_merchant=fee - shipping, fee_trappi=Decimal('0.00'),
                              snapshot={'mode': 'store', 'pricing': 'store', 'note': 'pedido por teléfono (caja)', 'fee': str(fee),
                                        'zone': zone.id if zone else None, 'payer': 'MERCHANT' if shipping == 0 and fee else 'CUSTOMER'})
    plans.snapshot(order, store, db=db, quote=quote)
    pct, _ = pos.commission(db, store)  # la comisión de la caja, no la de la app
    snap = plans.read_snapshot(order)
    snap['commission'] = {'rate': str(pct), 'fixed': '0.00', 'min': '0.00', 'max': '0.00', 'source': 'caja (pedido por teléfono)'}
    order.commission_rate = pct
    order.pricing_snapshot = json.dumps(snap, ensure_ascii=False, default=str)
    plans.settle(order)
    for l in lines:
        extra = l.get('modifiers_text') or ''
        if l.get('note'):
            extra = f'{extra} · Aclaración: {l["note"]}' if extra else f'Aclaración: {l["note"]}'
        order.items.append(OrderItem(product_id=l['product_id'], product_name=l['name'], unit_price=Decimal(str(l['unit_price'])),
                                     quantity=l['quantity'], modifiers_text=extra[:255] or None))
    db.add(order)
    record(order, OrderStatus.PENDIENTE)
    record(order, OrderStatus.CONFIRMADO)
    from . import stock
    try:
        stock.reserve(db, order, [{'product': products[l['product_id']], 'quantity': l['quantity']} for l in lines])
    except stock.OutOfStock as exc:
        raise pos.PosError(str(exc), 409)
    try:
        db.flush()
    except IntegrityError:  # el mismo pedido llegó dos veces a la vez
        db.rollback()
        again = db.scalar(select(Order).where(Order.store_id == store.id, Order.pos_uuid == uuid))
        if again:
            return again
        raise
    audit.log(db, 'pos.phone_order', 'order', order.id, new={'total': str(total), 'delivery_method': method}, reason=f'Cargado en la caja por {cashier.name}')
    return order
