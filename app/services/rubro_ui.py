"""Detalles de pantalla según el rubro (heladería y cafetería).

No cambia cómo se pide ni cuánto se cobra: sólo da datos para mostrar mejor lo que ya existe
(el color de cada gusto, qué grupo es el tamaño, el código para retirar, cuánto hace que salió el helado).
"""
from __future__ import annotations

import re
import unicodedata

from ..models import OrderStatus
from . import weight


def _plain(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', text).strip()


# ---------- heladería: el color de cada gusto ----------

# el primero que aparece en el nombre gana (por eso "dulce de leche" va antes que "leche" y "chocolate blanco" antes que "chocolate")
FLAVOR_COLORS = (
    ('chocolate blanco', '#F5EBDD'), ('dulce de leche', '#B8794A'), ('ddl', '#B8794A'), ('sambayon', '#F2C14E'),
    ('chocolate', '#5B3A29'), ('choco', '#5B3A29'), ('cacao', '#5B3A29'), ('brownie', '#5B3A29'),
    ('frutilla', '#F9A8D4'), ('frambuesa', '#E11D74'), ('frutos rojos', '#BE185D'), ('cereza', '#C81E4A'), ('mora', '#7E22CE'),
    ('limon', '#FDE68A'), ('maracuya', '#FACC15'), ('mango', '#FDBA74'), ('durazno', '#FDBA74'), ('anana', '#FDE047'),
    ('banana', '#FEF08A'), ('menta', '#A7F3D0'), ('pistacho', '#BEF264'), ('kiwi', '#86EFAC'), ('naranja', '#FB923C'),
    ('cafe', '#8B5A3C'), ('tiramisu', '#C8A27A'), ('mascarpone', '#FFF7E6'), ('vainilla', '#FFF3C4'), ('crema americana', '#FFF8E7'),
    ('americana', '#FFF8E7'), ('granizado', '#E7D3C1'), ('coco', '#FFFFFF'), ('mani', '#D6A35C'), ('nutella', '#6B3F2A'),
    ('oreo', '#D4D4D8'), ('cookies', '#D4D4D8'), ('kinoto', '#F59E0B'),
    ('arandano', '#4F46E5'), ('uva', '#7C3AED'), ('sandia', '#FB7185'), ('melon', '#FDBA74'), ('crema', '#FFF3D6'),
)


def flavor_color(name: str) -> str | None:
    """Color del gusto según su nombre ("Frutilla a la crema" → rosa). None si no lo reconoce."""
    text = _plain(name)
    for word, color in FLAVOR_COLORS:
        if word in text:
            return color
    return None


def option_tags(name: str) -> list[str]:
    """Marcas que el local ya escribe en el nombre: "Limón (vegano)", "Frutilla sin TACC"."""
    text = _plain(name)
    tags = []
    if 'sin tacc' in text or 'sin gluten' in text or 'celiac' in text:
        tags.append('SIN TACC')
    if 'vegan' in text:
        tags.append('VEGANO')
    if 'sin azucar' in text or 'light' in text:
        tags.append('SIN AZÚCAR')
    return tags


def is_flavor_group(rubro: str, group) -> bool:
    """Grupo de gustos de helado: en una heladería, un grupo que deja elegir más de uno sin costo extra."""
    if rubro != 'heladeria' or (group.max_select or 0) < 2:
        return False
    name = _plain(group.name)
    return 'gust' in name or 'sabor' in name or all(not o.price_extra for o in group.options if o.active)


# ---------- cafetería: el tamaño ----------

SIZE_WORDS = ('tamano', 'medida', 'size', 'vaso')


def is_size_group(group) -> bool:
    return (group.max_select or 0) == 1 and any(w in _plain(group.name) for w in SIZE_WORDS)


def option_ml(name: str) -> int | None:
    """"Mediano 350 ml" → 350 (para mostrarlo debajo del tamaño)."""
    m = re.search(r'(\d{2,4})\s*(ml|cc)\b', _plain(name))
    return int(m.group(1)) if m else None


def is_without_group(group) -> bool:
    """"Sacale": todas las opciones son "Sin cebolla", "Sin ajo"... (se muestran punteadas)."""
    opts = [o for o in group.options if getattr(o, 'active', True)]
    return bool(opts) and all(_plain(o.name).startswith('sin ') for o in opts)


def group_json_extra(rubro: str, group) -> dict:
    """Lo que se agrega a cada grupo de opciones en la API: cómo dibujarlo."""
    if is_flavor_group(rubro, group):
        return {'display': 'flavors'}
    if is_size_group(group):
        return {'display': 'sizes'}
    if is_without_group(group):
        return {'display': 'without'}
    return {}


def option_json_extra(rubro: str, display: str | None, option) -> dict:
    extra: dict = {}
    tags = option_tags(option.name)
    if tags:
        extra['tags'] = tags
    if display == 'flavors':
        extra['color'] = flavor_color(option.name) or '#F3D3E2'
    if display == 'sizes':
        ml = option_ml(option.name)
        if ml:
            extra['ml'] = ml
    return extra


# ---------- seguimiento ----------

COLD_KEEPS_MIN = 40  # un pote cerrado aguanta bien ~40 min fuera del freezer (estimado, no se mide)


def cold(order, now) -> dict | None:
    """Heladería con envío: cuánto hace que salió del local. Es una estimación por tiempo, no hay sensor."""
    if order.delivery_method != 'delivery' or weight.theme(order.store)['key'] != 'heladeria':
        return None
    if order.status != OrderStatus.EN_CAMINO:
        return None
    left = order.status_time(OrderStatus.EN_CAMINO)
    minutes = 0
    if left is not None:
        if left.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        minutes = max(0, int((now - left).total_seconds() // 60))
    return {'minutes_out': minutes, 'keeps_min': COLD_KEEPS_MIN, 'level': round(min(1.0, minutes / COLD_KEEPS_MIN), 2)}


def pickup(order) -> dict | None:
    """Para retirar: el número del pedido grande (es el que el local ve en la comanda) y para cuándo está."""
    if order.delivery_method != 'retiro' or getattr(order, 'table_name', None) or order.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
        return None
    from .orders import ready_at
    return {'code': f'#{order.id}', 'ready_at': ready_at(order), 'rubro': weight.theme(order.store)['key']}
