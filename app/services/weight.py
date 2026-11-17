"""Productos que se venden por peso y catalogo segun el rubro del local.

Un producto por peso guarda en `price` el precio por kg. El cliente elige cuantos gramos quiere
(en saltos de `weight_step`, desde `weight_min`) y la linea del carrito lleva `grams`: el precio de
esa linea lo calcula siempre el servidor. En el pedido queda `weight_grams` y el peso tambien va
adelante del texto de opciones ("750 g"), asi lo ven la comanda, el ticket y la caja sin cambios.
"""
from decimal import ROUND_HALF_UP, Decimal

DEFAULT_STEP = 250
MAX_GRAMS = 20000  # 20 kg por linea
PRESETS = (100, 250, 500, 750, 1000, 1500, 2000, 3000)

# rubros que se ven como gondola (grilla de productos con "+") en vez de carta de restaurante
GRID_WORDS = ('super', 'almac', 'kiosc', 'carnic', 'verdul', 'fiambr', 'dietet', 'farmac', 'pollo', 'polleri', 'pescad',
              'bebid', 'drugst', 'mascot', 'limpiez', 'mayorist', 'autoserv', 'despens')
THEMES = (  # (palabra del rubro, clave, color de acento)
    ('carnic', 'carniceria', '#B91C1C'), ('pollo', 'carniceria', '#B91C1C'), ('pescad', 'carniceria', '#0E7490'),
    ('verdul', 'verduleria', '#15803D'), ('fiambr', 'fiambreria', '#B45309'), ('kiosc', 'kiosco', '#DB2777'),
    ('super', 'super', '#16A34A'), ('almac', 'super', '#16A34A'), ('autoserv', 'super', '#16A34A'), ('despens', 'super', '#16A34A'),
    ('farmac', 'farmacia', '#0284C7'), ('bebid', 'bebidas', '#7C3AED'), ('helad', 'heladeria', '#EC4899'),
    ('panad', 'panaderia', '#A16207'), ('cafe', 'cafeteria', '#92400E'),
)


def step(p) -> int:
    return min(5000, max(10, int(p.weight_step or DEFAULT_STEP)))


def minimum(p) -> int:
    return min(MAX_GRAMS, max(step(p), int(p.weight_min or 0)))


def clean_grams(p, grams) -> int:
    """Lo que pidio, en saltos validos para ese producto (un pedido raro no rompe: queda el minimo)."""
    try:
        g = int(float(grams))
    except (TypeError, ValueError):
        return minimum(p)
    st = step(p)
    g = int(round(g / st)) * st
    return min(MAX_GRAMS, max(minimum(p), g))


def price_for(per_kg: Decimal, grams: int) -> Decimal:
    return (Decimal(per_kg) * Decimal(grams) / Decimal(1000)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def label(grams: int | None) -> str:
    """750 -> "750 g", 1000 -> "1 kg", 1500 -> "1,5 kg", 1250 -> "1,25 kg"."""
    if not grams:
        return ''
    if grams < 1000:
        return f'{grams} g'
    kg = f'{grams / 1000:.3f}'.rstrip('0').rstrip('.')
    return f'{kg.replace(".", ",")} kg'


def presets(p) -> list[int]:
    """Botones rapidos: el minimo y los pesos comunes que respetan el salto del producto."""
    st, mn = step(p), minimum(p)
    out = [mn] + [g for g in PRESETS if g > mn and g % st == 0]
    return out[:5]


def strip_label(text: str | None, grams: int | None) -> str | None:
    """El texto de opciones sin el peso de adelante ("750 g, Cheddar" -> "Cheddar")."""
    lab = label(grams)
    if lab and text and text.startswith(lab):
        text = text[len(lab):].lstrip(' ,·')
    return text or None


def _rubro_text(store) -> str:
    cat = getattr(store, 'store_category', None)
    return f'{getattr(cat, "slug", "") or ""} {getattr(cat, "name", "") or ""}'.lower()


def catalog_style(store) -> str:
    """"grid" (gondola) o "menu" (carta). El local lo puede fijar; si no, sale del rubro."""
    if store is None:
        return 'menu'
    if store.catalog_style in ('menu', 'grid'):
        return store.catalog_style
    text = _rubro_text(store)
    return 'grid' if any(w in text for w in GRID_WORDS) else 'menu'


def theme(store) -> dict:
    """Clave y color de acento del rubro (la portada y los botones del local toman ese color)."""
    return theme_for(_rubro_text(store) if store is not None else '')


def theme_for(text: str) -> dict:
    """Lo mismo a partir del nombre o slug de un rubro (para la grilla de rubros del inicio)."""
    text = (text or '').lower()
    for word, key, accent in THEMES:
        if word in text:
            return {'key': key, 'accent': accent}
    return {'key': 'restaurante', 'accent': '#6C2BD9'}


# ---------- precio por unidad de medida ("$1.350 / L") ----------

UNITS = {'kg': ('kg', 1), 'g': ('kg', 0.001), 'L': ('L', 1), 'ml': ('L', 0.001), 'u': ('u', 1)}


def unit_price_text(p) -> str | None:
    """Precio por kilo, litro o unidad segun el contenido del envase (lo exige la ley de defensa del consumidor)."""
    if p.sold_by_weight or not p.content_amount or p.content_unit not in UNITS:
        return None
    unit, factor = UNITS[p.content_unit]
    qty = float(p.content_amount) * factor
    if qty <= 0:
        return None
    from .formatting import money
    return f'{money(round(float(p.price) / qty))} / {unit}'


# ---------- peso real: el local lo pesa al prepararlo ----------

DEFAULT_MARGIN = 10
ADJUSTABLE = ('PENDIENTE', 'CONFIRMADO', 'PREPARANDO', 'LISTO')


def margin(store) -> int:
    return max(0, min(50, int(store.weight_margin if store.weight_margin is not None else DEFAULT_MARGIN)))


def adjusts_price(order) -> bool:
    """Se cobra el peso real solo si paga al recibir (efectivo) o por transferencia que todavia no se confirmo.
    Con Mercado Pago (ya cobrado) se cobra lo pedido."""
    from . import payments
    return order.payment_method in ('efectivo', 'transferencia') and not payments.is_paid(order)


def weight_items(order) -> list:
    return [it for it in order.items if it.weight_grams and it.price_per_kg]


def preview(order) -> dict:
    """Lo que ve el cliente: por linea lo pedido y lo pesado, y el total antes y despues."""
    from decimal import Decimal as D
    lines, diff = [], D('0')
    for it in weight_items(order):
        real = it.weight_real_grams
        new = price_for(it.price_per_kg, real) * it.quantity if real else None
        old = price_for(it.price_per_kg, it.weight_grams) * it.quantity
        if new is not None:
            diff += new - old
        lines.append({'id': it.id, 'name': it.product_name, 'ordered': it.weight_grams, 'real': real, 'ordered_label': label(it.weight_grams),
                      'real_label': label(real) if real else None, 'old': old, 'new': new,
                      'pct': round((real - it.weight_grams) / it.weight_grams * 100, 1) if real else None})
    return {'lines': lines, 'diff': diff, 'status': order.weight_status, 'adjusts': adjusts_price(order)}


class WeightError(ValueError):
    pass


def set_real(db, order, grams_by_item: dict[int, int], user=None) -> str:
    """El local carga lo que peso cada linea. Dentro del margen se ajusta el total (si paga al recibir);
    si alguna linea se pasa, queda pendiente hasta que el cliente acepte. Devuelve el weight_status nuevo."""
    from . import audit
    if order.status.value not in ADJUSTABLE:
        raise WeightError('El pedido ya salió: no se puede cambiar el peso.')
    items = {it.id: it for it in weight_items(order)}
    if not items:
        raise WeightError('Este pedido no tiene productos por peso.')
    for iid, g in grams_by_item.items():
        it = items.get(int(iid))
        if it is None:
            raise WeightError('Ese producto no es de este pedido.')
        try:
            g = int(g)
        except (TypeError, ValueError):
            raise WeightError('Poné el peso en gramos.')
        if g <= 0 or g > MAX_GRAMS:
            raise WeightError('El peso tiene que ser entre 1 g y 20 kg.')
        it.weight_real_grams = g
    if not adjusts_price(order):
        order.weight_status = 'fixed'
        audit.log(db, 'peso_real', 'order', order.id, user=user, new={'items': grams_by_item, 'cobro': 'sin cambio (pago online)'})
        return order.weight_status
    m = margin(order.store)
    over = any(it.weight_real_grams and abs(it.weight_real_grams - it.weight_grams) / it.weight_grams * 100 > m for it in items.values())
    if over:
        order.weight_status = 'pending'
        audit.log(db, 'peso_real', 'order', order.id, user=user, new={'items': grams_by_item, 'margen': m, 'estado': 'espera al cliente'})
        _notify(db, order, 'pending')
        return order.weight_status
    _apply(db, order, user)
    order.weight_status = 'ok'
    return order.weight_status


def _apply(db, order, user=None) -> None:
    """Pasa los precios de las lineas al peso real y ajusta subtotal y total (lo calcula siempre el servidor)."""
    from . import audit, plans
    before = order.total
    diff = preview(order)['diff']
    for it in weight_items(order):
        if it.weight_real_grams:
            it.unit_price = price_for(it.price_per_kg, it.weight_real_grams)
    order.subtotal = (order.subtotal or 0) + diff
    order.total = (order.total or 0) + diff
    plans.settle(order)
    audit.log(db, 'peso_real_ajuste', 'order', order.id, user=user, amount_old=before, amount_new=order.total,
              new={'items': {it.id: it.weight_real_grams for it in weight_items(order)}})


def customer_answer(db, order, accept: bool) -> str:
    """El cliente acepta (se cobra el peso real) o no (el local lo tiene que volver a pesar)."""
    if order.weight_status != 'pending':
        raise WeightError('No hay ningún peso para aceptar.')
    if order.status.value not in ADJUSTABLE:
        raise WeightError('El pedido ya salió.')
    if accept:
        _apply(db, order)
        order.weight_status = 'accepted'
    else:
        order.weight_status = 'rejected'
        from . import audit
        audit.log(db, 'peso_real_rechazado', 'order', order.id, new={'por': 'cliente'})
    _notify(db, order, order.weight_status)
    return order.weight_status


def _notify(db, order, what: str) -> None:
    """Aviso al local (si el cliente no acepto) o al cliente (si tiene que aceptar). Sin romper si falla."""
    try:
        if what == 'pending':
            from . import push
            push.notify_order(db, order, f'⚖️ {order.store.name} pesó tu pedido', 'Se pasó un poco de lo que pediste. Entrá para aceptar el nuevo total.', kind='weight')
        elif what == 'rejected':
            from . import owner_alerts
            owner_alerts.push_store(db, order.store_id, {'title': f'⚖️ Pedido #{order.id}: el cliente no aceptó el peso', 'tag': f'peso-{order.id}',
                                                         'url': f'/admin/orders/{order.id}', 'body': 'Volvé a pesarlo más cerca de lo que pidió.'})
    except Exception:  # los avisos nunca frenan el pedido
        pass


# portadas por rubro en la web (los mismos degradados e ilustraciones que la app)
LOOKS = {
    'restaurante': (('#FB923C', '#EA580C'), ('🥤', '🍟', '🍔'), '#FFF3E2'), 'super': (('#34D399', '#15803D'), ('🥕', '🍌', '🧺', '🥛'), '#E6F8EE'),
    'carniceria': (('#FDA4AF', '#E11D48'), ('🍗', '🥩'), '#FFE4EC'), 'kiosco': (('#DB2777', '#2A1638'), ('🍭', '🍫', '🥤'), '#FCE7F3'),
    'verduleria': (('#4ADE80', '#16A34A'), ('🥑', '🥕', '🍅'), '#E6F8EE'), 'farmacia': (('#38BDF8', '#2563EB'), ('🧴', '💊'), '#E0F2FE'),
    'heladeria': (('#F9A8D4', '#DB2777'), ('🍨', '🍦'), '#FCE7F3'), 'bebidas': (('#A78BFA', '#6D28D9'), ('🧊', '🍺', '🥤'), '#F3E8FF'),
    'panaderia': (('#FCD34D', '#D97706'), ('🥖', '🥐'), '#FEF6C3'), 'fiambreria': (('#FDE68A', '#D97706'), ('🥓', '🧀'), '#FEF6C3'),
}


def look(store) -> dict:
    key = theme(store)['key']
    grad, ills, soft = LOOKS.get(key, (('#8B5CF6', '#6C2BD9'), ('🛍️',), '#F3E8FF'))
    logo = {'super': '🛒', 'carniceria': '🥩', 'kiosco': '🍫', 'verduleria': '🥕', 'farmacia': '💊', 'bebidas': '🥤'}.get(key, ills[-1])
    return {'key': key, 'grad': grad, 'ills': ills, 'soft': soft, 'logo': logo}
