"""Herramientas de Trappi AI para clientes. Todas leen datos reales y validan en el backend.

Lo que vuelve al modelo es lo minimo para responder: nombres, precios, valoraciones, distancias y
estados. Nunca datos personales (telefono, direccion, email) ni coordenadas.
"""
import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..models import (Category, ModifierGroup, Order, OrderStatus, Product, ProductStatus, Store, StoreCategory)
from ..services import cities, payments, plans
from ..services.cart import line_key, price_lines, validate_modifiers
from ..services.formatting import money
from ..services.orders import sequence
from ..services.store_hours import is_open, open_text, to_local
from .tools import ToolContext, ToolError, tool

MAX_CART_QTY = 20
STOPWORDS = {'de', 'del', 'la', 'las', 'el', 'los', 'con', 'sin', 'y', 'o', 'un', 'una', 'unos', 'unas', 'para', 'por', 'que', 'algo', 'me',
             'quiero', 'busco', 'cerca', 'mio', 'mi', 'en', 'al', 'lo', 'mas', 'muy', 'rico', 'rica', 'buena', 'buenas', 'bueno', 'buenos'}
STATUS_TEXT = {'PENDIENTE': 'recibido, esperando que el local lo confirme', 'CONFIRMADO': 'confirmado por el local', 'PREPARANDO': 'en preparación',
               'LISTO': 'listo', 'EN_CAMINO': 'en camino', 'ENTREGADO': 'entregado', 'CANCELADO': 'cancelado'}


def plain(text: str | None) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return ''.join(ch if ch.isalnum() else ' ' for ch in text)


def words(text: str | None) -> list[str]:
    """Palabras utiles de la busqueda, en singular aproximado ("hamburguesas" -> "hamburguesa")."""
    out = []
    for w in plain(text).split():
        if len(w) < 3 or w in STOPWORDS:
            continue
        if w.endswith('es') and len(w) > 5 and w[-3] not in 'aeiou':
            w = w[:-2]
        elif w.endswith('s') and len(w) > 4:
            w = w[:-1]
        out.append(w)
    return out[:6]


def _int(value, default=None, lo=None, hi=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None: n = max(lo, n)
    if hi is not None: n = min(hi, n)
    return n


def _price(value) -> float | None:
    """Precio que manda el modelo: 15000, 15000.5, "15000.50", "15.000", "$15.000,50"."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or '').replace('$', '').replace(' ', '').strip()
    if re.fullmatch(r'\d{1,3}(\.\d{3})+(,\d+)?', text):  # formato argentino con puntos de miles
        text = text.replace('.', '').replace(',', '.')
    else:
        text = text.replace(',', '.')
    try:
        return float(text)
    except ValueError:
        return None


# ---------- formato para el modelo y para las tarjetas ----------

def _store_cards():
    from ..routers.mobile_api import product_json, store_json  # mismas tarjetas que la app ya sabe mostrar
    return store_json, product_json


def store_brief(ctx: ToolContext, s: Store, extra: dict | None = None, card: bool = True) -> dict:
    store_json, _ = _store_cards()
    j = store_json(s, ctx.loc)
    if card:
        ctx.add_card({'type': 'store', 'id': s.id, 'store': j})
    cov = j['coverage']
    eta = (cov.get('eta_min'), cov.get('eta_max')) if cov.get('eta_min') else (j['eta_min'], j['eta_max'])
    data = {
        'comercio_id': s.id, 'nombre': s.name, 'rubro': j['category'],
        'abierto_ahora': j['is_open'], 'horario': None if j['is_open'] else (j['open_text'] or 'cerrado'),
        'valoracion': j['rating'], 'cantidad_resenas': j['rating_count'],
        'distancia_km': cov.get('distance_km') if ctx.loc else None,
        'hace_envios': j['delivery_enabled'],
        'llega_a_tu_ubicacion': (cov.get('delivers') if ctx.loc else None),
        'costo_envio': (money(cov['cost']) if cov.get('cost') is not None else None) if ctx.loc else None,
        'demora_minutos': f'{eta[0]}–{eta[1]}',
        'pedido_minimo': money(j['minimum_order']) if j['minimum_order'] else None,
    }
    if extra:
        data.update(extra)
    return data


def product_brief(ctx: ToolContext, p: Product, with_store=True) -> dict:
    _, product_json = _store_cards()
    ctx.add_card({'type': 'product', 'id': p.id, 'product': product_json(p, with_store=True)})
    promo = bool(p.previous_price and p.previous_price > p.price)
    data = {
        'producto_id': p.id, 'nombre': p.name, 'descripcion': (p.description or '')[:160] or None,
        'precio': money(p.price), 'precio_numero': float(p.price),
        'precio_anterior': money(p.previous_price) if promo else None, 'en_promocion': promo,
        'agotado': p.stock is not None and p.stock <= 0,
        'tiene_opciones': bool(p.modifier_groups), 'opciones_obligatorias': any(g.required or g.min_select for g in p.modifier_groups),
    }
    if with_store:
        data['comercio'] = {'comercio_id': p.store.id, 'nombre': p.store.name, 'abierto_ahora': is_open(p.store),
                            'valoracion': round(float(p.store.rating_avg), 1) if p.store.rating_count else None}
    return data


def _visible_stores(ctx: ToolContext):
    return select(Store).options(joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.zones)).where(
        plans.visible_clause(), cities.store_clause(ctx.city_id))


def _products_query(ctx: ToolContext):
    return select(Product).options(joinedload(Product.store).selectinload(Store.hours), joinedload(Product.category), selectinload(Product.modifier_groups)).where(
        Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False), plans.visible_product_clause(), cities.product_clause(ctx.city_id))


def _match_score(text_words: list[str], *fields) -> int:
    hay = ' '.join(plain(f) for f in fields if f)
    return sum(1 for w in text_words if w in hay)


def _store_score(brief: dict, history: int = 0) -> float:
    """Recomendado: abierto y con envio primero; despues valoracion (con peso por cantidad de reseñas), cercania e historial."""
    rating = brief['valoracion'] or 0
    n = brief['cantidad_resenas'] or 0
    bayes = (rating * n + 4.0 * 3) / (n + 3) if n else 3.5
    dist = brief['distancia_km'] if brief['distancia_km'] is not None else 3
    return (2 if brief['abierto_ahora'] else 0) + (1 if brief['llega_a_tu_ubicacion'] is not False else -2) + bayes - 0.25 * dist + min(history, 5) * 0.2


def _history_by_store(ctx: ToolContext) -> dict[int, int]:
    if ctx.account is None:
        return {}
    rows = ctx.db.execute(select(Order.store_id, func.count(Order.id)).where(Order.account_id == ctx.account.id, Order.status == OrderStatus.ENTREGADO)
                          .group_by(Order.store_id)).all()
    return {sid: int(n) for sid, n in rows}


# ---------- busquedas ----------

@tool('buscar_comercios',
      'Busca comercios reales de Trappi en la ciudad del cliente. Sirve para "¿qué tengo cerca?", "hamburgueserías", "¿qué está abierto?", '
      '"¿cuál tiene mejores reseñas?". Devuelve valoración, cantidad de reseñas, distancia, si llega, costo de envío, demora y horario.',
      {'texto': {'type': 'string', 'description': 'Qué busca: comida, producto, rubro o nombre del comercio (ej: "hamburguesas", "farmacia"). Vacío = todos.'},
       'abierto_ahora': {'type': 'boolean', 'description': 'Solo los que están abiertos ahora.'},
       'con_envio': {'type': 'boolean', 'description': 'Solo los que hacen envío hasta la ubicación del cliente.'},
       'orden': {'type': 'string', 'enum': ['recomendado', 'cercania', 'valoracion', 'rapidez', 'precio'], 'description': 'Cómo ordenar.'},
       'limite': {'type': 'integer', 'description': 'Cuántos devolver (máximo 8).'}})
def buscar_comercios(ctx: ToolContext, texto: str = '', abierto_ahora: bool = False, con_envio: bool = False, orden: str = 'recomendado', limite: int = 5):
    limite = _int(limite, 5, 1, 8)
    ws = words(texto)
    stores = ctx.db.scalars(_visible_stores(ctx)).unique().all()
    # precios y coincidencias de productos por comercio (una sola consulta)
    prod_rows = ctx.db.execute(select(Product.store_id, Product.name, Product.description, Product.price).where(
        Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False), Product.store_id.in_([s.id for s in stores] or [0]))).all()
    matches: dict[int, list] = {}
    cheapest: dict[int, Decimal] = {}
    for sid, name, desc, price in prod_rows:
        if not ws or _match_score(ws, name, desc):
            matches.setdefault(sid, []).append((name, price))
            cheapest[sid] = min(cheapest.get(sid, price), price)
    history = _history_by_store(ctx)
    found = []
    for s in stores:
        own = _match_score(ws, s.name, s.description, s.store_category.name if s.store_category else '') if ws else 0
        if ws and not own and s.id not in matches:
            continue
        found.append((s, own, matches.get(s.id, [])))
    rows = []
    for s, own, prods in found:
        extra = {'productos_que_coinciden': [n for n, _ in prods[:3]] or None, 'precio_desde': money(cheapest[s.id]) if s.id in cheapest else None}
        if history.get(s.id):
            extra['ya_pediste_aca'] = history[s.id]
        b = store_brief(ctx, s, extra, card=False)
        if abierto_ahora and not b['abierto_ahora']:
            continue
        if con_envio and not (b['hace_envios'] and b['llega_a_tu_ubicacion'] is not False):
            continue
        rows.append((b, s, cheapest.get(s.id), own + len(prods)))
    keys = {
        'cercania': lambda r: (r[0]['distancia_km'] is None, r[0]['distancia_km'] or 0),
        'valoracion': lambda r: (-(r[0]['valoracion'] or 0), -(r[0]['cantidad_resenas'] or 0)),
        'rapidez': lambda r: (r[1].estimated_minutes, r[0]['distancia_km'] or 0),
        'precio': lambda r: (r[2] is None, r[2] or 0),
    }
    rows.sort(key=keys.get(orden) or (lambda r: -_store_score(r[0], history.get(r[1].id, 0)) - 0.3 * r[3]))
    for _, s, _, _ in rows[:limite]:
        store_brief(ctx, s, card=True)
    return {'cantidad': len(rows), 'ubicacion_del_cliente': bool(ctx.loc), 'comercios': [r[0] for r in rows[:limite]],
            'nota': None if ctx.loc else 'El cliente no compartió su ubicación: no hay distancias ni costo de envío exacto.'}


@tool('buscar_productos',
      'Busca productos reales (con precio actual) en los comercios de la ciudad. Sirve para "hamburguesa doble con cheddar", '
      '"algo barato para cenar", "opciones por menos de $15.000". Se puede limitar a un comercio.',
      {'texto': {'type': 'string', 'description': 'Qué producto busca (ej: "hamburguesa doble cheddar", "coca cola"). Puede ir vacío si busca por precio.'},
       'comercio_id': {'type': 'integer', 'description': 'Buscar solo en este comercio.'},
       'precio_max': {'type': 'number', 'description': 'Precio máximo en pesos.'},
       'solo_promociones': {'type': 'boolean', 'description': 'Solo productos en oferta.'},
       'solo_abiertos': {'type': 'boolean', 'description': 'Solo de comercios abiertos ahora.'},
       'orden': {'type': 'string', 'enum': ['relevancia', 'precio', 'valoracion'], 'description': 'Cómo ordenar.'},
       'limite': {'type': 'integer', 'description': 'Cuántos devolver (máximo 10).'}})
def buscar_productos(ctx: ToolContext, texto: str = '', comercio_id: int | None = None, precio_max=None, solo_promociones: bool = False,
                     solo_abiertos: bool = False, orden: str = 'relevancia', limite: int = 6):
    limite = _int(limite, 6, 1, 10)
    ws = words(texto)
    q = _products_query(ctx)
    if comercio_id is not None:
        q = q.where(Product.store_id == _int(comercio_id, 0))
    cap = _price(precio_max) if precio_max is not None else None
    if cap:
        q = q.where(Product.price <= cap)
    if solo_promociones:
        q = q.where(Product.previous_price.is_not(None), Product.previous_price > Product.price)
    if ws:
        q = q.where(or_(*[Product.name.ilike(f'%{w}%') for w in ws], *[Product.description.ilike(f'%{w}%') for w in ws]))
    items = ctx.db.scalars(q.limit(400)).unique().all()
    scored = []
    for p in items:
        if solo_abiertos and not is_open(p.store):
            continue
        score = (2 * _match_score(ws, p.name) + _match_score(ws, p.description)) if ws else 0
        scored.append((score, p))
    if orden == 'precio':
        scored.sort(key=lambda x: (-x[0] if ws else 0, x[1].price))
    elif orden == 'valoracion':
        scored.sort(key=lambda x: (-x[0], -float(x[1].store.rating_avg or 0)))
    else:
        scored.sort(key=lambda x: (-x[0], not is_open(x[1].store), not x[1].featured, x[1].price))
    if ws and scored and scored[0][0] > 1:  # con varias palabras, primero los que coinciden con mas
        best = scored[0][0]
        scored = [x for x in scored if x[0] >= max(1, best - 1)]
    corrected = None
    if not scored and texto and comercio_id is None:
        # sin coincidencias exactas: la busqueda inteligente (errores de tipeo, sinonimos, plurales)
        from ..services import search
        res = search.run(ctx.db, texto, ctx.city_id, ctx.loc, product_limit=40)
        maxp = _price(precio_max)
        scored = [(1, p) for p in res.products if (not solo_promociones or (p.previous_price and p.previous_price > p.price))
                  and (maxp is None or float(p.price) <= maxp) and (not solo_abiertos or is_open(p.store))]
        corrected = res.query.corrected
    return {'cantidad': len(scored), 'productos': [product_brief(ctx, p) for _, p in scored[:limite]],
            'busqueda_corregida': corrected,
            'nota': None if scored else 'No hay productos que coincidan en los comercios de Trappi de esta ciudad.'}


@tool('buscar_promociones', 'Productos en oferta (precio rebajado) en los comercios de la ciudad, o de un comercio.',
      {'comercio_id': {'type': 'integer', 'description': 'Solo las de este comercio.'},
       'limite': {'type': 'integer', 'description': 'Cuántas devolver (máximo 10).'}})
def buscar_promociones(ctx: ToolContext, comercio_id: int | None = None, limite: int = 6):
    return buscar_productos(ctx, comercio_id=comercio_id, solo_promociones=True, limite=limite, orden='relevancia')


@tool('ver_comercio', 'Datos de un comercio y su menú con precios actuales: horario, si está abierto, envío, demora, valoración y productos.',
      {'comercio_id': {'type': 'integer', 'description': 'El comercio_id que devolvió otra herramienta.'}}, ['comercio_id'])
def ver_comercio(ctx: ToolContext, comercio_id: int):
    s = ctx.db.scalar(_visible_stores(ctx).where(Store.id == _int(comercio_id, 0)))
    if not s:
        raise ToolError('Ese comercio no existe o no está disponible en esta ciudad.')
    brief = store_brief(ctx, s, {'descripcion': (s.description or '')[:200] or None, 'direccion_del_local': s.address})
    products = ctx.db.scalars(select(Product).options(selectinload(Product.modifier_groups)).where(
        Product.store_id == s.id, Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False)).order_by(Product.featured.desc(), Product.display_order, Product.name).limit(40)).all()
    menu = [{'producto_id': p.id, 'nombre': p.name, 'precio': money(p.price),
             'en_promocion': bool(p.previous_price and p.previous_price > p.price), 'agotado': p.stock is not None and p.stock <= 0,
             'tiene_opciones': bool(p.modifier_groups)} for p in products]
    return {**brief, 'menu': menu, 'menu_completo': len(menu) < 40}


@tool('ver_producto', 'Detalle de un producto: precio actual, si está disponible ahora y sus opciones (con producto_id y opcion_id) para agregarlo bien al carrito.',
      {'producto_id': {'type': 'integer'}}, ['producto_id'])
def ver_producto(ctx: ToolContext, producto_id: int):
    p = ctx.db.scalar(_products_query(ctx).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == _int(producto_id, 0)))
    if not p:
        raise ToolError('Ese producto no existe o ya no está disponible.')
    data = product_brief(ctx, p)
    data['disponible_ahora'] = is_open(p.store) and not data['agotado']
    if not is_open(p.store):
        data['motivo'] = f'El comercio está cerrado ({open_text(p.store) or "sin horario"}).'
    data['grupos_de_opciones'] = [{
        'grupo': g.name, 'obligatorio': bool(g.required or g.min_select), 'minimo': g.min_select or (1 if g.required else 0), 'maximo': g.max_select or None,
        'opciones': [{'opcion_id': o.id, 'nombre': o.name, 'precio_extra': money(o.price_extra) if o.price_extra else None} for o in g.options if o.active]}
        for g in p.modifier_groups]
    return data


# ---------- carrito (el del cliente: el del telefono o el de la sesion de la web) ----------

def _cart_view(ctx: ToolContext) -> dict:
    cart = price_lines(ctx.db, ctx.cart, ctx.loc, precise=False)
    if cart['lines'] != ctx.cart:
        ctx.cart, ctx.cart_changed = cart['lines'], True
    return {
        'comercio': cart['store'].name if cart['store'] else None,
        'lineas': [{'linea': i + 1, 'producto_id': it['product'].id, 'nombre': it['product'].name, 'opciones': it['modifiers_text'] or None,
                    'cantidad': it['quantity'], 'precio_unitario': money(it['unit_price']), 'total': money(it['line_total'])}
                   for i, it in enumerate(cart['items'])],
        'subtotal': money(cart['subtotal']),
        'envio_estimado': money(cart['shipping']) if cart['store'] else None,
        'nota': 'Para confirmar el pedido el cliente toca "Mi pedido" y finaliza ahí: el asistente no puede hacer ni pagar pedidos.',
    }


@tool('ver_carrito', 'Muestra el carrito actual del cliente con precios actuales.')
def ver_carrito(ctx: ToolContext):
    return _cart_view(ctx)


@tool('agregar_al_carrito',
      'Agrega un producto al carrito. Usalo solo si el cliente lo pidió o lo confirmó. Si el producto tiene opciones obligatorias, '
      'primero usá ver_producto y preguntale cuáles quiere. El carrito es de un solo comercio.',
      {'producto_id': {'type': 'integer'}, 'cantidad': {'type': 'integer', 'description': 'De 1 a 20.'},
       'opciones_ids': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'opcion_id elegidas (de ver_producto).'},
       'reemplazar_carrito': {'type': 'boolean', 'description': 'true solo si el cliente aceptó vaciar el carrito de otro comercio.'}},
      ['producto_id'])
def agregar_al_carrito(ctx: ToolContext, producto_id: int, cantidad: int = 1, opciones_ids=None, reemplazar_carrito: bool = False):
    qty = _int(cantidad, 1, 1, MAX_CART_QTY)
    options = sorted({_int(x) for x in (opciones_ids or []) if _int(x) is not None})
    p = ctx.db.scalar(_products_query(ctx).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == _int(producto_id, 0)))
    if not p:
        raise ToolError('Ese producto no existe o ya no está disponible.')
    if p.stock is not None and p.stock <= 0:
        raise ToolError(f'"{p.name}" está agotado.')
    if not is_open(p.store):
        raise ToolError(f'{p.store.name} está cerrado ahora ({open_text(p.store) or "sin horario"}). No se puede agregar.')
    valid = {o.id for g in p.modifier_groups for o in g.options if o.active}
    if set(options) - valid:
        raise ToolError('Alguna opción no corresponde a este producto. Usá ver_producto para ver las opciones válidas.')
    problem = validate_modifiers(p, options)
    if problem:
        raise ToolError(problem + ' Preguntale al cliente qué opción quiere.')
    current = price_lines(ctx.db, ctx.cart, ctx.loc, precise=False)
    other_store = current['store'] is not None and current['store'].id != p.store_id
    if other_store and not reemplazar_carrito:
        raise ToolError(f'El carrito tiene productos de {current["store"].name}. Preguntale si quiere vaciarlo para pedir en {p.store.name}.')
    cart = [] if other_store else [dict(x) for x in current['lines']]
    key = line_key(p.id, options)
    existing = next((x for x in cart if line_key(x['product_id'], x.get('modifiers', [])) == key), None)
    if existing:
        existing['quantity'] = min(99, existing['quantity'] + qty)
    else:
        cart.append({'product_id': p.id, 'quantity': qty, 'modifiers': options})
    ctx.cart, ctx.cart_changed = cart, True
    product_brief(ctx, p)
    return {'ok': True, 'agregado': f'{qty} × {p.name}', 'carrito': _cart_view(ctx)}


def _line(ctx: ToolContext, linea) -> int:
    n = _int(linea)
    lines = price_lines(ctx.db, ctx.cart, ctx.loc, precise=False)['lines']
    if n is None or not 1 <= n <= len(lines):
        raise ToolError('Esa línea no existe en el carrito. Usá ver_carrito.')
    ctx.cart = [dict(x) for x in lines]
    return n - 1


@tool('actualizar_cantidad', 'Cambia la cantidad de una línea del carrito (0 la saca).',
      {'linea': {'type': 'integer', 'description': 'Número de línea de ver_carrito.'}, 'cantidad': {'type': 'integer'}}, ['linea', 'cantidad'])
def actualizar_cantidad(ctx: ToolContext, linea: int, cantidad: int):
    i = _line(ctx, linea)
    qty = _int(cantidad, 1, 0, MAX_CART_QTY)
    if qty == 0:
        ctx.cart.pop(i)
    else:
        ctx.cart[i]['quantity'] = qty
    ctx.cart_changed = True
    return {'ok': True, 'carrito': _cart_view(ctx)}


@tool('eliminar_del_carrito', 'Saca una línea del carrito.', {'linea': {'type': 'integer'}}, ['linea'])
def eliminar_del_carrito(ctx: ToolContext, linea: int):
    i = _line(ctx, linea)
    ctx.cart.pop(i)
    ctx.cart_changed = True
    return {'ok': True, 'carrito': _cart_view(ctx)}


# ---------- pedidos del usuario autenticado ----------

def _own_orders(ctx: ToolContext):
    return select(Order).options(joinedload(Order.store), selectinload(Order.items), selectinload(Order.events), joinedload(Order.courier)).where(
        Order.account_id == ctx.account.id)


def _order_brief(o: Order, detail=False) -> dict:
    delivered = o.status_time(OrderStatus.ENTREGADO) if o.status == OrderStatus.ENTREGADO else None
    data = {
        'pedido_id': o.id, 'comercio': o.store.name, 'fecha': to_local(o.created_at).strftime('%d/%m/%Y %H:%M'),
        'estado': STATUS_TEXT[o.status.value], 'total': money(o.total),
        'productos': [f'{it.quantity} × {it.product_name}' + (f' ({it.modifiers_text})' if it.modifiers_text else '') for it in o.items][:8],
        'entrega': 'delivery' if o.delivery_method == 'delivery' else 'retiro en el local',
        'tardo_minutos': int((delivered - o.created_at).total_seconds() // 60) if delivered else None,
    }
    if detail:
        steps = sequence(o) if o.status != OrderStatus.CANCELADO else []
        data['etapas'] = [{'etapa': STATUS_TEXT[st.value], 'hora': to_local(t).strftime('%H:%M')} for st in steps if (t := o.status_time(st))]
        data['pago'] = payments.status_text(o) or payments.method_label(o)
        data['repartidor'] = o.courier.name.split()[0] if o.courier and o.status == OrderStatus.EN_CAMINO else None
        if o.status not in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
            eta = o.created_at + timedelta(minutes=(o.store.estimated_minutes or 30) + 10)
            data['llegada_estimada_aprox'] = to_local(eta).strftime('%H:%M') if eta > datetime.utcnow() else 'ya debería estar por llegar'
    return data


@tool('mis_pedidos', 'Los últimos pedidos del cliente autenticado ("¿qué pedí ayer?", "¿cuánto tardó mi último pedido?").',
      {'limite': {'type': 'integer', 'description': 'Cuántos (máximo 5).'}}, needs_account=True)
def mis_pedidos(ctx: ToolContext, limite: int = 3):
    rows = ctx.db.scalars(_own_orders(ctx).order_by(Order.created_at.desc()).limit(_int(limite, 3, 1, 5))).unique().all()
    return {'pedidos': [_order_brief(o) for o in rows], 'nota': None if rows else 'Todavía no hizo pedidos con su cuenta.'}


@tool('recomendados_para_mi',
      'Productos recomendados para el cliente autenticado según SUS pedidos, comercios, categorías, precios y horarios '
      '("¿qué me recomendás?", "sorprendeme", "lo de siempre"). Cada uno trae el motivo real. Si las recomendaciones están apagadas '
      'o todavía no pidió nada, lo dice.',
      {'limite': {'type': 'integer', 'description': 'Cuántos (máximo 8).'}}, needs_account=True)
def recomendados_para_mi(ctx: ToolContext, limite: int = 5):
    from ..services import recommendations
    if not recommendations.enabled(ctx.account):
        return {'productos': [], 'nota': 'El cliente apagó las recomendaciones personalizadas en su cuenta.'}
    picks = recommendations.recommend(ctx.db, ctx.account, ctx.city_id, ctx.loc, limit=_int(limite, 5, 1, 8))
    if not picks:
        return {'productos': [], 'nota': 'Todavía no hay pedidos suficientes para recomendarle algo personal. Ofrecé buscar o ver promociones.'}
    return {'productos': [{**product_brief(ctx, x.product), 'motivo': x.reason} for x in picks]}


@tool('consultar_pedido', 'Estado actual y etapas de un pedido del cliente ("¿dónde está mi pedido?"). Sin pedido_id, el último en curso.',
      {'pedido_id': {'type': 'integer'}}, needs_account=True)
def consultar_pedido(ctx: ToolContext, pedido_id: int | None = None):
    q = _own_orders(ctx)
    if pedido_id is not None:
        o = ctx.db.scalar(q.where(Order.id == _int(pedido_id, 0)))
    else:
        o = ctx.db.scalar(q.where(Order.status.not_in((OrderStatus.ENTREGADO, OrderStatus.CANCELADO))).order_by(Order.created_at.desc()).limit(1)) \
            or ctx.db.scalar(q.order_by(Order.created_at.desc()).limit(1))
    if not o:
        raise ToolError('No encontramos ese pedido entre los pedidos de esta cuenta.')
    return _order_brief(o, detail=True)
