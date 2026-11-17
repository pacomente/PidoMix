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
    text = _rubro_text(store) if store is not None else ''
    for word, key, accent in THEMES:
        if word in text:
            return {'key': key, 'accent': accent}
    return {'key': 'restaurante', 'accent': '#6C2BD9'}
