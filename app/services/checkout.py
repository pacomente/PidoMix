"""Confirmacion de pedidos: reglas compartidas por el checkout web y la app movil."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Coupon, Customer, Order, OrderItem, OrderStatus
from .geo import format_km
from .orders import record
from .store_hours import is_open
from .whatsapp import build_message, whatsapp_url


class CheckoutError(Exception):
    """Motivo, en castellano y listo para mostrar al cliente, por el que no se puede confirmar."""


def find_coupon(db: Session, store_id: int, code: str, subtotal: Decimal):
    """(cupon, descuento) si aplica; (None, motivo) si no; (None, None) si no se ingreso codigo."""
    code = (code or '').strip().upper()
    if not code:
        return None, None
    c = db.scalar(select(Coupon).where(Coupon.store_id == store_id, func.upper(Coupon.code) == code, Coupon.active.is_(True)))
    if not c:
        return None, 'Ese cupón no existe o ya no está activo.'
    if c.expires_at and c.expires_at < datetime.utcnow():
        return None, 'Ese cupón venció.'
    if c.max_uses and c.uses_count >= c.max_uses:
        return None, 'Ese cupón alcanzó el máximo de usos.'
    if subtotal < Decimal(c.min_order or 0):
        return None, f'Ese cupón requiere un pedido mínimo de ${Decimal(c.min_order):,.2f}.'
    discount = (subtotal * Decimal(c.discount_value) / 100) if c.discount_type == 'percent' else Decimal(c.discount_value)
    return c, min(discount, subtotal)


def place_order(db: Session, cart: dict, loc: dict | None, *, first_name: str, last_name: str, phone: str,
                delivery_method: str, address: str = "", reference: str = "", notes: str = "", coupon_code: str = "") -> Order:
    """Valida el carrito ya calculado (price_lines) y crea el pedido. No hace commit."""
    store = cart["store"]
    if not cart["items"] or not store:
        raise CheckoutError("Tu pedido está vacío.")
    customer_data = {k: (v or "").strip() for k, v in dict(first_name=first_name, last_name=last_name, phone=phone, address=address, reference=reference, notes=notes).items()}
    if not customer_data["first_name"] or not customer_data["phone"]:
        raise CheckoutError("Completá tu nombre y teléfono.")
    if not is_open(store):
        raise CheckoutError("Este local está cerrado por ahora. Probá de nuevo cuando abra.")
    if delivery_method not in {"delivery", "retiro"}:
        raise CheckoutError("Seleccioná una modalidad de entrega válida.")
    if delivery_method == "delivery" and not store.delivery_enabled:
        raise CheckoutError("Esta tienda no realiza envíos.")
    if delivery_method == "delivery" and not customer_data["address"]:
        raise CheckoutError("Ingresá una dirección para delivery.")
    cov = cart["coverage"]
    if delivery_method == "delivery" and cov and cov.zoned:
        if not loc:
            raise CheckoutError("Marcá tu ubicación en el mapa para calcular el envío.")
        if not cov.covered:
            raise CheckoutError(f"Tu ubicación está fuera de la zona de entrega de {store.name} (llega hasta {format_km(cov.max_km)}). Podés retirar en el local.")
    if cart["subtotal"] < Decimal(store.minimum_order or 0):
        raise CheckoutError(f"El pedido mínimo es ${Decimal(store.minimum_order):,.2f}.")
    coupon, discount = None, Decimal("0")
    if coupon_code:
        coupon, result = find_coupon(db, store.id, coupon_code, cart["subtotal"])
        if coupon:
            discount = result
    shipping = cart["shipping"] if delivery_method == "delivery" else Decimal("0")
    customer = Customer(**{k: customer_data[k] for k in ("first_name", "last_name", "phone", "address", "reference")})
    order = Order(store_id=store.id, customer=customer, delivery_method=delivery_method, payment_method="whatsapp",
                  address=customer_data["address"], reference=customer_data["reference"], notes=customer_data["notes"],
                  subtotal=cart["subtotal"], shipping=shipping, discount=discount, coupon_id=coupon.id if coupon else None,
                  total=cart["subtotal"] + shipping - discount)
    if delivery_method == "delivery" and loc:
        order.lat, order.lng = loc["lat"], loc["lng"]
        order.distance_km = round(cov.distance, 2) if cov and cov.distance is not None else None
    db.add(order)
    record(order, OrderStatus.PENDIENTE)
    if coupon:
        coupon.uses_count += 1
    message_items = []
    for item in cart["items"]:
        p = item["product"]
        order.items.append(OrderItem(product_id=p.id, product_name=p.name, unit_price=item["unit_price"], quantity=item["quantity"], modifiers_text=item["modifiers_text"] or None))
        message_items.append({"name": p.name, "unit_price": item["unit_price"], "quantity": item["quantity"], "modifiers_text": item["modifiers_text"]})
    message = build_message(store, customer_data, message_items, order.subtotal, shipping, order.total,
                            "Delivery" if delivery_method == "delivery" else "Retiro en local", discount=discount, coupon_code=coupon.code if coupon else None)
    order.whatsapp_url = whatsapp_url(store.whatsapp, message)
    return order
