from urllib.parse import quote


def normalize_number(value: str | None):
    return "".join(ch for ch in (value or "") if ch.isdigit())


def build_message(store, customer, items, subtotal, shipping, total, delivery_method, discount=0, coupon_code=None, payment=None, cash_with=None, points_discount=0):
    lines = ["Hola, quiero realizar el siguiente pedido en Trappi:", "", f"🏪 Tienda: {store.name}", "", "🛒 PEDIDO:"]
    for item in items:
        lines.append(f"{item['quantity']}x {item['name']} — ${item['unit_price'] * item['quantity']:,.2f}")
        if item.get("modifiers_text"):
            lines.append(f"   + {item['modifiers_text']}")
    lines += ["", f"Subtotal: ${subtotal:,.2f}", f"Envío: ${shipping:,.2f}"]
    if discount:
        lines.append(f"Descuento ({coupon_code}): -${discount:,.2f}")
    if points_discount:
        lines.append(f"Puntos Trappi: -${points_discount:,.2f}")
    lines += [f"TOTAL: ${total:,.2f}", "", "👤 Cliente:", f"{customer['first_name']} {customer['last_name']}", f"📞 Teléfono: {customer['phone']}"]
    if customer.get("address"):
        lines.append(f"📍 Dirección: {customer['address']}")
    if customer.get("reference"):
        lines.append(f"📝 Referencia: {customer['reference']}")
    if customer.get("notes"):
        lines.append(f"💬 Observaciones: {customer['notes']}")
    lines.append(f"🚚 Entrega: {delivery_method}")
    if payment:
        lines.append(f"💳 Pago: {payment}" + (f" (pago con ${cash_with:,.2f})" if cash_with else ""))
    return "\n".join(lines)


def whatsapp_url(number, message):
    normalized = normalize_number(number)
    if not normalized:
        return None
    return f"https://wa.me/{normalized}?text={quote(message)}"
