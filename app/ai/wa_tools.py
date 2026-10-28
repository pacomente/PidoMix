"""Herramientas del agente de WhatsApp de un local. Es lo UNICO que puede hacer el agente.

Todas trabajan con UN local (ctx.extra['store']): no ven ni cargan productos de otros comercios.
El agente arma el carrito y el link para confirmar; el pedido lo confirma y lo paga el cliente en
Trappi. No puede confirmar ni cancelar pedidos, cobrar, dar descuentos ni cambiar precios.
"""
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from ..config import settings
from ..models import ModifierGroup, Order, OrderStatus, Product, ProductStatus
from ..services import schedule
from ..services.cart import line_key, price_lines, validate_modifiers
from ..services.formatting import money
from ..services.store_hours import is_open, open_text
from . import client_tools
from .client_tools import _int, plain, words
from .tools import ToolContext, ToolError, tool

AUDIENCE = 'whatsapp'
LINK_HOURS = 2
_link = URLSafeTimedSerializer(settings.secret_key, salt='trappi-wa-order')


def link_token(conv) -> str:
    return _link.dumps({'c': conv.id, 's': conv.store_id})


def read_link(token: str) -> dict | None:
    try:
        data = _link.loads(token, max_age=LINK_HOURS * 3600)
    except Exception:  # firma mala o vencido
        return None
    return data if isinstance(data, dict) and isinstance(data.get('c'), int) and isinstance(data.get('s'), int) else None


def _store(ctx: ToolContext):
    return ctx.extra['store']


def _products(ctx: ToolContext):
    return select(Product).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(
        Product.store_id == _store(ctx).id, Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False))


def _product(ctx: ToolContext, producto_id) -> Product:
    p = ctx.db.scalar(_products(ctx).where(Product.id == _int(producto_id, 0)))
    if not p:
        raise ToolError('Ese producto no es del menú de este local o ya no está disponible.')
    return p


def _can_order(store) -> tuple[bool, str]:
    """(se puede pedir, motivo): abierto ahora, o cerrado pero con horarios para programar."""
    if is_open(store):
        return True, ''
    if schedule.options(store):
        return True, f'El local está cerrado ahora ({open_text(store) or "sin horario"}): el pedido tiene que quedar programado.'
    return False, f'El local está cerrado ({open_text(store) or "sin horario"}) y no hay horarios para programar.'


def _item(p: Product) -> dict:
    promo = bool(p.previous_price and p.previous_price > p.price)
    return {'producto_id': p.id, 'nombre': p.name, 'precio': money(p.price), 'precio_anterior': money(p.previous_price) if promo else None,
            'agotado': p.stock is not None and p.stock <= 0, 'tiene_opciones': bool(p.modifier_groups),
            'descripcion': (p.description or '')[:120] or None}


@tool('ver_menu', 'El menú del local con precios actuales. Con texto, solo lo que coincide ("hamburguesa", "sin tacc", "bebidas").',
      {'texto': {'type': 'string', 'description': 'Qué busca el cliente (opcional).'}}, audience=AUDIENCE)
def ver_menu(ctx: ToolContext, texto: str = ''):
    rows = ctx.db.scalars(_products(ctx).order_by(Product.featured.desc(), Product.display_order, Product.name).limit(120)).all()
    want = words(texto)
    if want:
        scored = [(sum(1 for w in want if w in plain(f'{p.name} {p.description or ""}')), p) for p in rows]
        rows = [p for score, p in sorted(scored, key=lambda x: -x[0]) if score > 0]
    ok, why = _can_order(_store(ctx))
    return {'local': _store(ctx).name, 'productos': [_item(p) for p in rows[:30]], 'hay_mas': len(rows) > 30,
            'se_puede_pedir': ok, 'nota': why or None,
            'sin_resultados': 'No hay nada así en el menú. Decíselo y ofrecé lo más parecido, o pedir_persona si pregunta algo que el menú no dice.' if want and not rows else None}


@tool('ver_producto', 'Detalle de un producto del local con sus opciones (opcion_id) para cargarlo bien.',
      {'producto_id': {'type': 'integer'}}, ['producto_id'], audience=AUDIENCE)
def ver_producto(ctx: ToolContext, producto_id: int):
    p = _product(ctx, producto_id)
    data = _item(p)
    data['grupos_de_opciones'] = [{
        'grupo': g.name, 'obligatorio': bool(g.required or g.min_select), 'minimo': g.min_select or (1 if g.required else 0), 'maximo': g.max_select or None,
        'opciones': [{'opcion_id': o.id, 'nombre': o.name, 'precio_extra': money(o.price_extra) if o.price_extra else None} for o in g.options if o.active]}
        for g in p.modifier_groups]
    return data


def _cart(ctx: ToolContext) -> dict:
    view = client_tools._cart_view(ctx)
    view['nota'] = 'Cuando el cliente termine, usá preparar_pedido para mandarle el link: ahí confirma y paga él.'
    return view


@tool('ver_carrito', 'El pedido que se está armando, con precios actuales.', audience=AUDIENCE)
def ver_carrito(ctx: ToolContext):
    return _cart(ctx)


@tool('agregar_al_carrito', 'Agrega un producto del local al pedido. Solo lo que el cliente pidió. Si tiene opciones obligatorias, '
      'primero ver_producto y preguntale cuáles quiere.',
      {'producto_id': {'type': 'integer'}, 'cantidad': {'type': 'integer', 'description': 'De 1 a 20.'},
       'opciones_ids': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'opcion_id elegidas (de ver_producto).'}},
      ['producto_id'], audience=AUDIENCE)
def agregar_al_carrito(ctx: ToolContext, producto_id: int, cantidad: int = 1, opciones_ids=None):
    p = _product(ctx, producto_id)
    qty = _int(cantidad, 1, 1, client_tools.MAX_CART_QTY)
    options = sorted({_int(x) for x in (opciones_ids or []) if _int(x) is not None})
    if p.stock is not None and p.stock <= 0:
        raise ToolError(f'"{p.name}" está agotado.')
    ok, why = _can_order(p.store)
    if not ok:
        raise ToolError(why)
    valid = {o.id for g in p.modifier_groups for o in g.options if o.active}
    if set(options) - valid:
        raise ToolError('Alguna opción no corresponde a este producto. Usá ver_producto para ver las opciones válidas.')
    problem = validate_modifiers(p, options)
    if problem:
        raise ToolError(problem + ' Preguntale al cliente qué opción quiere.')
    cart = [dict(x) for x in price_lines(ctx.db, ctx.cart, None, precise=False)['lines']]
    key = line_key(p.id, options)
    existing = next((x for x in cart if line_key(x['product_id'], x.get('modifiers', [])) == key), None)
    if existing:
        existing['quantity'] = min(99, existing['quantity'] + qty)
    else:
        cart.append({'product_id': p.id, 'quantity': qty, 'modifiers': options})
    ctx.cart, ctx.cart_changed = cart, True
    return {'ok': True, 'agregado': f'{qty} × {p.name}', 'carrito': _cart(ctx), 'nota': why or None}


@tool('actualizar_cantidad', 'Cambia la cantidad de una línea del pedido (0 la saca).',
      {'linea': {'type': 'integer', 'description': 'Número de línea de ver_carrito.'}, 'cantidad': {'type': 'integer'}}, ['linea', 'cantidad'], audience=AUDIENCE)
def actualizar_cantidad(ctx: ToolContext, linea: int, cantidad: int):
    client_tools.actualizar_cantidad(ctx, linea, cantidad)
    return {'ok': True, 'carrito': _cart(ctx)}


@tool('eliminar_del_carrito', 'Saca una línea del pedido.', {'linea': {'type': 'integer'}}, ['linea'], audience=AUDIENCE)
def eliminar_del_carrito(ctx: ToolContext, linea: int):
    client_tools.eliminar_del_carrito(ctx, linea)
    return {'ok': True, 'carrito': _cart(ctx)}


@tool('horarios', 'Si el local está abierto, si hace envíos y los horarios para programar un pedido (hoy, mañana y pasado).', audience=AUDIENCE)
def horarios(ctx: ToolContext):
    s = _store(ctx)
    days = schedule.options(s)
    return {'abierto_ahora': is_open(s), 'horario': open_text(s) or None, 'hace_envios': bool(s.delivery_enabled), 'demora_minutos': s.prep_minutes,
            'programar': [{'dia': d['label'], 'fecha': d['date'], 'horarios': d['slots'][::2][:10] if len(d['slots']) > 10 else d['slots']} for d in days],
            'nota': 'Para programar usá fecha y hora juntas ("2026-10-28T21:00") en preparar_pedido.'}


@tool('preparar_pedido', 'Cuando el pedido está completo: guarda cómo lo quiere (envío o retiro, ahora o programado) y devuelve el link '
      'que hay que mandarle para que confirme y pague. No confirma el pedido: lo confirma el cliente.',
      {'entrega': {'type': 'string', 'enum': ['retiro', 'delivery']},
       'horario': {'type': 'string', 'description': '"ahora" o fecha y hora de horarios(), por ejemplo "2026-10-28T21:00".'}},
      ['entrega'], audience=AUDIENCE)
def preparar_pedido(ctx: ToolContext, entrega: str, horario: str = 'ahora'):
    s = _store(ctx)
    cart = price_lines(ctx.db, ctx.cart, None, precise=False)
    if not cart['items']:
        raise ToolError('El pedido está vacío: primero agregá lo que quiere el cliente.')
    if entrega not in ('retiro', 'delivery'):
        raise ToolError('La entrega es "retiro" o "delivery".')
    if entrega == 'delivery' and not s.delivery_enabled:
        raise ToolError('Este local no hace envíos: solo retiro en el local.')
    when = None
    if (horario or 'ahora').strip().lower() != 'ahora':
        if not schedule.parse(s, horario):
            raise ToolError('Ese horario no está disponible. Mirá horarios() y ofrecele uno de la lista.')
        when = horario.strip()
    elif not is_open(s):
        raise ToolError(f'El local está cerrado ahora ({open_text(s) or "sin horario"}): ofrecele programarlo (horarios()).')
    if s.minimum_order and cart['subtotal'] < s.minimum_order:
        raise ToolError(f'El pedido mínimo es {money(s.minimum_order)}; ahora suma {money(cart["subtotal"])}.')
    conv = ctx.extra['conv']
    ctx.extra['plan'] = {'delivery': entrega, 'scheduled_for': when}
    url = f'{(settings.public_base_url or "https://trappi.com.ar").rstrip("/")}/wa/pedido/{link_token(conv)}'
    ctx.extra['link'] = url
    return {'ok': True, 'link': url, 'vence_en_horas': LINK_HOURS, 'subtotal': money(cart['subtotal']),
            'entrega': 'envío a domicilio (el costo se calcula con su dirección al confirmar)' if entrega == 'delivery' else 'retiro en el local',
            'programado_para': schedule.label(schedule.parse(s, when)) if when else None,
            'nota': 'Mandale el resumen y el link. En el link elige cómo pagar y confirma; vos no podés confirmarlo.'}


@tool('pedir_persona', 'Pasa la charla al dueño del local y le avisa al celular. Usala si el cliente pide hablar con alguien, '
      'hace un reclamo, o pregunta algo que no sabés (ingredientes, alérgenos, cambios que no están en el menú, demoras de un pedido).',
      {'tipo': {'type': 'string', 'enum': ['persona', 'no_se']}, 'motivo': {'type': 'string', 'description': 'En pocas palabras, qué necesita.'}},
      ['tipo', 'motivo'], audience=AUDIENCE)
def pedir_persona(ctx: ToolContext, tipo: str, motivo: str):
    ctx.extra['handoff'] = {'needs': 'person' if tipo == 'persona' else 'unknown', 'note': ' '.join(str(motivo or '').split())[:200]}
    return {'ok': True, 'nota': 'Ya le avisamos al local. Decile al cliente que en un rato le responde alguien del local y no prometas nada más.'}


@tool('consultar_pedido', 'Estado del último pedido que hizo el cliente por este WhatsApp.', audience=AUDIENCE)
def consultar_pedido(ctx: ToolContext):
    conv = ctx.extra['conv']
    o = ctx.db.scalar(select(Order).options(joinedload(Order.store), selectinload(Order.items), selectinload(Order.events), joinedload(Order.courier))
                      .where(Order.wa_conversation_id == conv.id, Order.store_id == _store(ctx).id).order_by(Order.created_at.desc()).limit(1))
    if not o:
        raise ToolError('Todavía no hizo pedidos por este WhatsApp.')
    data = client_tools._order_brief(o, detail=True)
    if o.scheduled_for and o.status not in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO):
        data['programado_para'] = schedule.label(o.scheduled_for)
    return data
