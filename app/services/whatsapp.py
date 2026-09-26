from urllib.parse import quote


def normalize_number(value: str | None):
    return "".join(ch for ch in (value or "") if ch.isdigit())


def build_message(store, customer, items, subtotal, shipping, total, delivery_method):
    lines = ["Hola, quiero realizar el siguiente pedido en PidoMix:", "", f"🏪 Tienda: {store.name}", "", "🛒 PEDIDO:"]
    for item in items:
        lines.append(f"{item['quantity']}x {item['name']} — ${item['unit_price'] * item['quantity']:,.2f}")
    lines += ["", f"Subtotal: ${subtotal:,.2f}", f"Envío: ${shipping:,.2f}", f"TOTAL: ${total:,.2f}", "", "👤 Cliente:", f"{customer['first_name']} {customer['last_name']}", f"📞 Teléfono: {customer['phone']}"]
    if customer.get("address"):
        lines.append(f"📍 Dirección: {customer['address']}")
    if customer.get("reference"):
        lines.append(f"📝 Referencia: {customer['reference']}")
    if customer.get("notes"):
        lines.append(f"💬 Observaciones: {customer['notes']}")
    lines.append(f"🚚 Entrega: {delivery_method}")
    return "\n".join(lines)


def whatsapp_url(number, message):
    normalized = normalize_number(number)
    if not normalized:
        return None
    return f"https://wa.me/{normalized}?text={quote(message)}"
