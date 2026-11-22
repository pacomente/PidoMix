"""API JSON para la app movil (React Native / Expo): /api/v1.

La app no usa la sesion del navegador: el carrito vive en el telefono y se manda en cada
cotizacion o pedido, igual que la ubicacion. Las reglas (horarios, zonas, cupones, estados)
son las mismas de la web porque se reusan los mismos servicios.
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, object_session, selectinload

from ..config import settings
from ..db import get_db
from ..models import Banner, Category, ModifierGroup, Order, OrderStatus, Product, ProductStatus, Review, Setting, Store, StoreCategory, StoreStatus
from ..services.cart import price_lines
from ..services.checkout import CheckoutError, resolve_discount, place_order, points_preview, resolve_coupon
from ..services.formatting import visual
from ..services.images import cdn
from ..services.geo import coverage, parse_location
from ..services import accounts, addresses, audit, cities, claims, deals, delivery_safety, errands, logistics, loyalty, menu3d, payments, plans, platform, push, online_promos, recommendations, referrals, retention, rubro_ui, schedule, search, stamps, tracking, weight
from ..services.orders import eta_text, sequence
from ..services.ratelimit import PersistentRateLimiter, client_ip, order_limiter
from ..services.reviews import MAX_TEXT, public_name, rating_summary, refresh_store_rating
from ..services.store_hours import is_open, open_text, product_closed_text
from .public import menu_groups, order_token, valid_order_token

chat_limiter = PersistentRateLimiter('customer-chat', limit=40, window_seconds=300)  # chat con el repartidor
errand_quote_limiter = PersistentRateLimiter('errand-quote', limit=60, window_seconds=600)  # cada cotizacion consulta el servidor de rutas
router = APIRouter()
STORE_OPTS = (joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.zones))
PRODUCT_OPTS = (joinedload(Product.store), joinedload(Product.category), selectinload(Product.modifier_groups))
ERRAND_LABEL = {'LISTO': 'Retiro', 'EN_CAMINO': 'En camino', 'ENTREGADO': 'Entregado'}  # etapas de un mandado
STATUS_LABEL = {'PENDIENTE': 'Pedido recibido', 'CONFIRMADO': 'Confirmado por el local', 'PREPARANDO': 'Preparando tu pedido',
                'LISTO': 'Listo', 'EN_CAMINO': 'En camino', 'ENTREGADO': 'Entregado', 'CANCELADO': 'Cancelado'}


def num(value) -> float:
    return float(value or 0)


def loc_from(lat: float | None, lng: float | None) -> dict | None:
    return parse_location({'lat': lat, 'lng': lng}) if lat is not None and lng is not None else None


def iso(dt) -> str | None:
    return dt.isoformat() + 'Z' if dt else None


def coverage_json(store, loc, cov=None):
    """Cobertura y envio. En listados se estima sin consultar rutas; el carrito trae la cotizacion exacta."""
    if cov is None:
        cov = logistics.delivery_quote(object_session(store), store, loc, precise=False)
    return {
        'zoned': cov.zoned, 'covered': cov.covered, 'delivers': cov.delivers,
        'distance_km': round(cov.distance, 2) if cov.distance is not None else None,
        'cost': num(cov.cost) if cov.cost is not None else None,
        'from_cost': num(cov.from_cost) if cov.from_cost is not None else None,
        'max_km': cov.max_km,
        # flota Trappi (zona, km por ruta, demora). mode: store = envia el comercio, trappi = la flota
        'mode': getattr(cov, 'mode', 'store'), 'zone': getattr(cov, 'zone_name', None),
        'route_km': getattr(cov, 'route_km', None), 'route_estimated': getattr(cov, 'route_source', None) == 'estimate',
        'eta_min': getattr(cov, 'eta_min', None), 'eta_max': getattr(cov, 'eta_max', None),
        'reason': getattr(cov, 'reason', None), 'pickup_allowed': getattr(cov, 'pickup_allowed', True),
    }


def with_discounts(db: Session, items: list[dict]) -> list[dict]:
    """Agrega a cada comercio su mayor descuento vigente (para la etiqueta "Hasta 30% OFF")."""
    ids = [i['id'] for i in items]
    best = deals.max_discounts(db, ids)
    # los que venden por kilo (carnicerías, verdulerías, fiambrerías): filtro «Venden por kg»
    by_kg = set(db.scalars(select(Product.store_id).where(Product.store_id.in_(ids), Product.sold_by_weight.is_(True), Product.status == ProductStatus.ACTIVO,
                                                           Product.deleted.is_(False)).distinct()).all()) if ids else set()
    for i in items:
        i['max_discount'] = best.get(i['id']) or None
        i['sells_by_weight'] = i['id'] in by_kg
    return items


def _coupon_label(store_id: int) -> str | None:
    from ..db import SessionLocal
    from ..services import coupons
    with SessionLocal() as db:
        return coupons.offers(db).get(store_id)


def store_json(s: Store, loc=None, full=False) -> dict:
    cat = s.store_category.name if s.store_category else ''
    v = visual(s.name, cat)
    open_now = is_open(s)
    data = {
        'id': s.id, 'slug': s.slug, 'name': s.name, 'category': cat or None, 'description': s.description,
        'logo_url': cdn(s.logo_url, 'logo'), 'cover_url': cdn(s.cover_url, 'card'), 'emoji': v['emoji'], 'hue': v['hue'],
        'featured': s.featured, 'is_open': open_now, 'open_text': None if open_now else open_text(s),
        # cerrado ahora pero se puede programar el pedido para cuando abra
        'can_schedule': open_now or bool(schedule.options(s)),
        'schedule_hint': None if open_now else schedule.hint(s),
        'rating': round(num(s.rating_avg), 1) if s.rating_count else None, 'rating_count': s.rating_count,
        'eta_min': s.prep_minutes, 'eta_max': s.prep_minutes + 10, 'busy': s.busy_extra > 0,
        'delivery_enabled': s.delivery_enabled, 'delivery_cost': num(s.delivery_cost), 'minimum_order': num(s.minimum_order),
        'coverage': coverage_json(s, loc), 'fleet': plans.fleet_kind(s),
        'transfer_alias': (s.transfer_alias or None) if plans.accepts_transfer(s) else None,
        # medios de pago que acepta (Trappi Delivery: sin transferencia); Mercado Pago se agrega en mp_available
        'payment_methods': ['efectivo', 'transferencia'] if plans.accepts_transfer(s) else ['efectivo'],
        # cupon automatico del local ("10% OFF"): se aplica solo en el pedido
        'coupon': _coupon_label(s.id),
        # rubro: catalogo como carta ("menu") o gondola ("grid") y el color de acento del local
        'prep_min': s.prep_minutes,  # para retirar: lo que tarda en prepararlo
        'catalog_style': weight.catalog_style(s), 'rubro': weight.theme(s)['key'], 'accent': weight.theme(s)['accent'],
        'free_shipping_from': num(logistics.free_shipping_from(s)) if logistics.free_shipping_from(s) is not None else None,
    }
    if full:
        data.update({'address': s.address, 'lat': s.lat, 'lng': s.lng, 'whatsapp': s.whatsapp})
    return data


def product_json(p: Product, with_store=False) -> dict:
    v = visual(p.name, p.category.name if p.category else '', default='🍽️')
    data = {
        'id': p.id, 'name': p.name, 'description': p.description, 'price': num(p.price),
        'previous_price': num(p.previous_price) if p.previous_price and p.previous_price > p.price else None,
        'image_url': cdn(p.image_url, 'product'), 'emoji': v['emoji'], 'hue': v['hue'], 'featured': p.featured,
        'sold_out': p.stock is not None and p.stock <= 0, 'customizable': bool(p.modifier_groups),
        # seccion con franja horaria (desayunos...): se puede agregar y programar, pero ahora no se pide
        'hours_text': product_closed_text(p),
        # menu en 3D: la app abre la pagina del visor (girar el plato y "Ver en tu mesa" con la camara)
        'model_3d_path': f'/plato/{p.id}/3d' if menu3d.visible(p) else None,
        # por peso: price es por kg; la app ofrece estos pesos (gramos) y manda grams en la linea
        'weight': {'step': weight.step(p), 'min': weight.minimum(p), 'presets': weight.presets(p)} if p.sold_by_weight else None,
        'unit_price_text': weight.unit_price_text(p),  # "$1.350 / L" (precio por unidad de medida)
        'section_id': p.section_id,  # para saber a qué productos les toca una promo de sección
    }
    if with_store:
        data['store'] = {'slug': p.store.slug, 'name': p.store.name}
    return data


def review_json(r: Review) -> dict:
    return {'id': r.id, 'rating': r.rating, 'comment': r.comment, 'reply': r.reply, 'created_at': iso(r.created_at),
            'author': public_name(r.order.customer if r.order else None)}


# ---------- catalogo ----------

@router.get('/config')
def config(db: Session = Depends(get_db)):
    cfg = platform.get_all(db)
    lat, lng = (float(x) for x in settings.map_default_center.split(','))
    status = platform.app_status(cfg, 'clientes')
    return {'name': 'Trappi', 'map_center': {'lat': lat, 'lng': lng}, 'support_whatsapp': cfg['platform_whatsapp'] or None,
            'map_style': platform.map_style_url(cfg),  # el mismo mapa gratis de la app de repartidores (seguimiento en vivo)
            'min_app_version': status['min_version'], 'app': status,
            'orders': {'enabled': cfg['orders_enabled'], 'message': cfg['orders_message']},
            # cuentas: con required, para pedir hay que entrar (codigo por email: login_path abre el navegador del sistema)
            'ai': _ai_status(db),
            # Trappi Viajes: el inicio muestra el modulo si esta prendido (GET /rides/available dice si hay empresas en la ciudad)
            'rides': {'enabled': bool(cfg['rides_enabled'])},
            # Trappi Mandados: mandar algo de una direccion a otra con la flota (GET /errands/config dice si hay en la ciudad)
            'errands': {'enabled': bool(cfg['errands_enabled'])},
            'account': {'required': accounts.required(db), 'available': accounts.available(), 'login_path': '/ingresar?app=1',
                        'methods': accounts.methods(),
                        'terms_url': '/terminos', 'privacy_url': '/privacidad', 'withdrawal_url': '/arrepentimiento'},
            # multi-ciudad: la app manda ?city=<slug> (o la ubicacion) en el catalogo
            'cities': [city_json(c) for c in cities.all_cities(db)]}


def _ai_status(db: Session) -> dict:
    from .ai_api import ai_status
    return ai_status(db)


def city_json(c) -> dict:
    return {'id': c.id, 'slug': c.slug, 'name': c.name, 'province': c.province, 'center': {'lat': c.center_lat, 'lng': c.center_lng}}


def city_for(db: Session, city: str | None, loc: dict | None):
    """Ciudad del catalogo: la que eligio en la app (city), la de su ubicacion o la principal."""
    return cities.resolve(db, city, loc)


class AppDisabled(Exception):
    def __init__(self, message: str):
        self.message = message


def require_app_enabled(request: Request, db: Session = Depends(get_db)) -> None:
    """La app de clientes apagada desde el panel: todo responde "en mantenimiento" salvo /config."""
    if request.url.path.endswith('/config'):
        return
    cfg = platform.get_all(db)
    if not cfg['app_clientes_enabled']:
        raise AppDisabled(platform.app_status(cfg, 'clientes')['message'])


@router.get('/home')
def home(lat: float | None = None, lng: float | None = None, city: str | None = None, db: Session = Depends(get_db)):
    loc = loc_from(lat, lng)
    here = city_for(db, city, loc)
    cid = here.id if here else None
    banners = db.scalars(select(Banner).where(Banner.active).order_by(Banner.display_order, Banner.id)).all()
    store_cats = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    cats = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    stores = db.scalars(select(Store).options(*STORE_OPTS).where(plans.visible_clause(), cities.store_clause(cid)).order_by(Store.featured.desc(), Store.name).limit(30)).all()
    promos = db.scalars(select(Product).options(*PRODUCT_OPTS).where(Product.status == ProductStatus.ACTIVO, plans.visible_product_clause(), cities.product_clause(cid), Product.previous_price.is_not(None), Product.previous_price > Product.price).order_by(Product.featured.desc(), Product.display_order).limit(10)).all()
    popular = db.scalars(select(Product).options(*PRODUCT_OPTS).where(Product.status == ProductStatus.ACTIVO, plans.visible_product_clause(), cities.product_clause(cid)).order_by(Product.featured.desc(), Product.display_order).limit(12)).all()
    store_items = with_discounts(db, [store_json(s, loc) for s in stores])
    if loc:  # con ubicacion: primero los que llegan, y entre ellos los mas cercanos
        store_items.sort(key=lambda s: (not s['coverage']['delivers'], s['coverage']['distance_km'] is None, s['coverage']['distance_km'] or 0))
    return {
        'banners': [{'id': b.id, 'title': b.title, 'subtitle': b.subtitle, 'image_url': cdn(b.image_url, 'banner'), 'button_text': b.button_text, 'link': b.link} for b in banners],
        'store_categories': [{'id': c.id, 'name': c.name, 'emoji': visual(c.name)['emoji'], **weight.theme_for(f'{c.slug} {c.name}')} for c in store_cats],
        'categories': [{'id': c.id, 'slug': c.slug, 'name': c.name, 'image_url': cdn(c.image_url, 'category'), **{k: visual(c.name, default='🍽️')[k] for k in ('emoji', 'hue')}} for c in cats],
        'promos': [product_json(p, with_store=True) for p in promos],
        'popular': [product_json(p, with_store=True) for p in popular],  # lo mas pedido (destacados primero)
        'stores': store_items,
        'city': city_json(here) if here else None,
        'cities': [city_json(c) for c in cities.all_cities(db)] if cities.multi(db) else [],  # para el selector (con una sola, vacio)
    }


@router.get('/stores')
def stores(q: str = '', category_id: int | None = None, lat: float | None = None, lng: float | None = None,
           sort: str = '', delivery: bool = False, city: str | None = None, db: Session = Depends(get_db)):
    loc = loc_from(lat, lng)
    here = city_for(db, city, loc)
    stmt = select(Store).options(*STORE_OPTS).where(plans.visible_clause(), cities.store_clause(here.id if here else None))
    if q.strip():
        stmt = stmt.where(Store.name.ilike(f'%{q.strip()[:100]}%'))
    if category_id:
        stmt = stmt.where(Store.store_category_id == category_id)
    rows = with_discounts(db, [store_json(s, loc) for s in db.scalars(stmt.order_by(Store.featured.desc(), Store.name)).all()])
    if delivery:
        rows = [s for s in rows if s['delivery_enabled'] and s['coverage']['delivers']]
    if sort == 'cerca' and loc:
        rows.sort(key=lambda s: (s['coverage']['distance_km'] is None, s['coverage']['distance_km'] or 0))
    elif sort == 'rapidos':
        rows.sort(key=lambda s: s['eta_min'])
    return {'stores': rows}


@router.get('/stores/{slug}')
def store_detail(slug: str, lat: float | None = None, lng: float | None = None, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    s = db.scalar(select(Store).options(*STORE_OPTS, selectinload(Store.sections)).where(Store.slug == slug, plans.visible_clause()))
    if not s:
        return JSONResponse({'error': 'Ese comercio no existe o ya no está disponible.'}, status_code=404)
    products = db.scalars(select(Product).options(joinedload(Product.category), selectinload(Product.modifier_groups))
                          .where(Product.store_id == s.id, Product.status == ProductStatus.ACTIVO).order_by(Product.display_order, Product.name)).all()
    sections = [sec for sec in s.sections if sec.active]
    categories = [] if sections else db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    reviews = db.scalars(select(Review).options(joinedload(Review.order).joinedload(Order.customer))
                         .where(Review.store_id == s.id, Review.hidden.is_(False)).order_by(Review.created_at.desc()).limit(10)).all()
    return {
        'store': store_json(s, loc_from(lat, lng), full=True),
        # cada sección con su emoji (en la góndola del súper se ven como categorías con ilustración)
        'menu': [{'key': key, 'title': title, 'emoji': visual(title, *(p.name for p in items[:3]), default='🛒')['emoji'], 'products': [product_json(p) for p in items]}
                 for key, title, items in menu_groups(products, sections, categories)],
        'reviews': [review_json(r) for r in reviews],
        'rating_summary': rating_summary(db, Review.store_id == s.id, Review.hidden.is_(False)),
        'stamp_card': stamp_card_json(db, s, current_account(db, authorization)),
        # promos de la caja que valen en la app: 2x1, combos, happy hour (on: vale ahora; ends_at: para la cuenta regresiva)
        'promos': [{**b, 'ends_at': iso(b['ends_at']) if b['ends_at'] else None} for b in online_promos.badges(db, s)],
    }


def stamp_card_json(db: Session, s: Store, acct) -> dict | None:
    """Tarjeta de sellos del local (si la tiene) y, con cuenta, cuantos sellos lleva el cliente."""
    info = stamps.info(s)
    if info is None:
        return None
    mine = stamps.progress(db, s, acct)
    return {'goal': info['goal'], 'reward': info['reward'], 'min_order': num(info['min_order']),
            'mine': {'stamps': mine['stamps'], 'missing': mine['missing'], 'rewards': len(mine['rewards'])} if mine else None}


@router.get('/search')
def search_catalog(q: str = '', lat: float | None = None, lng: float | None = None, city: str | None = None, db: Session = Depends(get_db)):
    """Busqueda inteligente: tolera errores, sinonimos y pedidos como "algo dulce por menos de 5000"."""
    q = q.strip()[:100]
    if len(q) < 2:
        return {'stores': [], 'products': [], 'corrected': None, 'understood': [], 'suggestion': None}
    loc = loc_from(lat, lng)
    here = city_for(db, city, loc)
    cid = here.id if here else None
    res = search.run(db, q, cid, loc, product_limit=40, store_limit=20)
    search.log(db, q, res, cid, 'app')
    return {'stores': with_discounts(db, [store_json(s, loc) for s in res.stores]), 'products': [product_json(p, with_store=True) for p in res.products],
            'corrected': res.query.corrected, 'understood': res.query.labels,
            'suggestion': search.suggestion(db, q, cid) if res.empty else None}


@router.get('/products/{product_id}')
def product_detail(product_id: int, db: Session = Depends(get_db)):
    p = db.scalar(select(Product).options(*PRODUCT_OPTS, selectinload(Product.modifier_groups).selectinload(ModifierGroup.options))
                  .where(Product.id == product_id, Product.status == ProductStatus.ACTIVO, plans.visible_product_clause()))
    if not p:
        return JSONResponse({'error': 'Ese producto ya no está disponible.'}, status_code=404)
    rubro = weight.theme(p.store)['key']
    return {**product_json(p, with_store=True), 'rubro': rubro, 'groups': [group_json(rubro, g) for g in p.modifier_groups]}


def group_json(rubro: str, g: ModifierGroup) -> dict:
    # display: 'flavors' (gustos de helado con su color) o 'sizes' (tamaños del café); si no, la lista de siempre
    extra = rubro_ui.group_json_extra(rubro, g)
    return {'id': g.id, 'name': g.name, 'required': g.required, 'min_select': g.min_select, 'max_select': g.max_select, **extra,
            'options': [{'id': o.id, 'name': o.name, 'price_extra': num(o.price_extra), **rubro_ui.option_json_extra(rubro, extra.get('display'), o)}
                        for o in g.options if o.active]}


# ---------- carrito y pedidos ----------

class CartLine(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1, le=99)
    modifiers: list[int] = Field(default_factory=list, max_length=30)
    grams: int | None = Field(None, ge=1, le=100000)  # productos por peso: el servidor lo lleva a un salto valido


class QuoteIn(BaseModel):
    items: list[CartLine] = Field(default_factory=list, max_length=60)
    lat: float | None = None
    lng: float | None = None
    delivery_method: str = 'delivery'
    coupon: str = ''
    use_points: bool = False  # puntos Trappi: el descuento lo calcula el servidor
    use_voucher: bool = True  # descuento de retencion de Trappi (si tiene uno)


class OrderIn(QuoteIn):
    first_name: str = Field(max_length=100)
    last_name: str = Field('', max_length=100)
    phone: str = Field(max_length=40)
    address: str = Field('', max_length=255)
    reference: str = Field('', max_length=255)
    notes: str = Field('', max_length=1000)
    scheduled_for: str = Field('', max_length=20)  # pedido programado: '2026-10-22T20:15' (hora local), uno de los de quote.schedule
    # token de Firebase del telefono, para avisarle por push cada cambio de estado
    push_token: str = Field('', max_length=512)
    platform: str = Field('android', max_length=10)
    payment_method: str = Field('efectivo', max_length=20)
    cash_with: float | None = Field(None, ge=0, le=100_000_000)  # "pago con" en efectivo
    call_if_missing: bool = False  # "si falta algo (un corte), llamame"; si no, lo reemplazan por uno parecido


def mp_available(db: Session, store) -> bool:
    from ..services import mercadopago
    return mercadopago.available_for(db, store)


def quote_json(db: Session, body: QuoteIn, acct=None) -> tuple[dict, dict, dict | None]:
    loc = loc_from(body.lat, body.lng)
    cart = price_lines(db, [line.model_dump() for line in body.items], loc)
    store = cart['store']
    shipping = cart['shipping'] if body.delivery_method == 'delivery' else Decimal('0')
    discount, coupon_error, coupon_code, coupon_auto = Decimal('0'), None, None, False
    if store:
        coupon, discount, coupon_error, coupon_auto = resolve_discount(db, cart, body.coupon, acct, getattr(acct, 'phone', '') or '')
        coupon_code = coupon.code if coupon else None
    data = {
        'store': ({**store_json(store, loc), 'coverage': coverage_json(store, loc, cart['coverage']), 'mp_available': mp_available(db, store)} if store else None),
        'items': [{'product_id': i['product'].id, 'name': i['product'].name, 'quantity': i['quantity'], 'unit_price': num(i['unit_price']),
                   'line_total': num(i['line_total']), 'modifiers': [o.id for o in i['modifiers']], 'modifiers_text': i['modifiers_text'] or None,
                   'line_key': i['line_key'], 'grams': i.get('grams')} for i in cart['items']],
        'dropped': len(body.items) - len(cart['items']),  # lineas que ya no se pueden pedir (producto pausado, otro local...)
        'subtotal': num(cart['subtotal']), 'shipping': num(shipping), 'discount': num(discount), 'coupon_error': coupon_error,
        'coupon_code': coupon_code, 'coupon_auto': coupon_auto,  # el automatico del local se aplica solo
        # promos de la caja que valen online (2x1, combos, happy hour): ya están dentro de discount
        'promos': [{'name': a['name'], 'amount': a['amount']} for a in cart.get('promos') or []], 'promo_discount': num(cart.get('promo_discount') or 0),
        # "los que pidieron esto también llevaron" (pedidos del local en conjunto, sin datos de nadie)
        # horarios para programar el pedido (hoy, mañana, pasado; cada 15 min). value: '2026-10-22T20:15'
        'schedule': [{**d, 'values': [f"{d['date']}T{t}" for t in d['slots']]} for d in schedule.options(store)] if store else [],
        'together': [product_json(p) for p in recommendations.bought_together(db, store.id, [i['product'].id for i in cart['items']], limit=3)] if store and cart['items'] else [],
        'total': num(cart['subtotal'] + shipping - discount),
        'minimum_order': num(store.minimum_order) if store else 0,
        # envío gratis desde un monto (solo locales con cadetería propia): {'from', 'missing'} o None
        'free_shipping': {'from': num(cart['free_shipping']['from']), 'missing': num(cart['free_shipping']['missing'])} if cart.get('free_shipping') else None,
    }
    pts = points_preview(db, cart, body.delivery_method, discount, acct, use_voucher=body.use_voucher)
    vd = pts['voucher_discount']
    v = retention.active_voucher(db, acct.id) if acct is not None else None
    potential = vd if body.use_voucher or v is None else points_preview(db, cart, body.delivery_method, discount, acct)['voucher_discount']
    data['voucher'] = ({**retention.voucher_json(v), 'discount': num(potential), 'usable': potential > 0} if v else None)
    if vd > 0 and body.use_voucher:
        data['voucher_discount'] = num(vd)
        data['total'] = num(cart['subtotal'] + shipping - discount - vd)
    data['points'] = {'enabled': pts['enabled'] and acct is not None, 'balance': pts['balance'], 'usable': pts['points'],
                      'discount': num(pts['discount']), 'reason': pts['reason'], 'earn': pts.get('earn', 0)}
    if body.use_points and pts['points']:
        data['points_discount'] = num(pts['discount'])
        data['total'] = num(cart['subtotal'] + shipping - discount - (vd if body.use_voucher else 0) - pts['discount'])
    return data, cart, loc


@router.post('/cart/quote')
def cart_quote(body: QuoteIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    return quote_json(db, body, current_account(db, authorization))[0]


# ---------- cuenta del cliente ----------

def account_json(a) -> dict:
    return {'id': a.id, 'email': a.email, 'name': a.name, 'picture_url': a.picture_url, 'first_name': a.first_name or '', 'last_name': a.last_name or '',
            'phone': a.phone or '', 'address': a.address or '', 'reference': a.reference or '', 'personalize': a.personalize is not False,
            'marketing_opt_in': bool(a.marketing_opt_in)}


def current_account(db: Session, authorization: str | None):
    return accounts.from_bearer(db, authorization)


def no_session() -> JSONResponse:
    return JSONResponse({'ok': False, 'error': 'Tu sesión venció. Volvé a entrar.', 'login_required': True}, status_code=401)


@router.post('/orders')
def create_order(body: OrderIn, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if acct is None and accounts.required(db):
        return JSONResponse({'ok': False, 'login_required': True,
                             'error': 'Para pedir tenés que entrar con tu cuenta. Si no ves el botón para entrar, actualizá la app.'}, status_code=401)
    ip = client_ip(request)
    if order_limiter.blocked(ip):
        return JSONResponse({'ok': False, 'error': 'Hiciste muchos pedidos seguidos. Esperá unos minutos.'}, status_code=429)
    _, cart, loc = quote_json(db, body, acct)
    try:
        order = place_order(db, cart, loc, use_points=body.use_points, use_voucher=body.use_voucher, first_name=body.first_name, last_name=body.last_name, phone=body.phone, delivery_method=body.delivery_method,
                            address=body.address, reference=body.reference, notes=body.notes, coupon_code=body.coupon,
                            payment_method=body.payment_method, cash_with=body.cash_with, account=acct, origin='app', ip=ip,
                            scheduled_for=body.scheduled_for or '', call_if_missing=body.call_if_missing)
    except CheckoutError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    if body.push_token:
        push.register(db, order, body.push_token, body.platform)
    db.commit()
    order_limiter.hit(ip)
    token = order_token(order.id)
    return {'ok': True, 'id': order.id, 'token': token, 'whatsapp_url': order.whatsapp_url, 'total': num(order.total),
            # pago online: la app abre esta pagina del sitio, que crea el link de Mercado Pago en el servidor
            'pay_path': f'/pedido/{order.id}/pagar?t={token}' if payments.awaiting_online(order) else None}


def order_json(o: Order) -> dict:
    steps = sequence(o) if o.status != OrderStatus.CANCELADO else []
    current = steps.index(o.status) if o.status in steps else -1
    return {
        'id': o.id, 'status': o.status.value, 'status_label': STATUS_LABEL[o.status.value], 'created_at': iso(o.created_at),
        'scheduled_for': iso(o.scheduled_for) if o.scheduled_for else None, 'scheduled_label': schedule.label(o.scheduled_for) or None,
        'store': {'slug': o.store.slug, 'name': o.store.name, 'whatsapp': o.store.whatsapp, 'eta_min': o.store.prep_minutes},
        'errand': errands.public(o),  # mandado: qué es, dónde se retira y quién recibe (None en un pedido de un local)
        'eta_text': eta_text(o),  # "Llega aprox. 21:40–21:55" (con lo que eligio el local al aceptar o la demora actual)
        'delivery_method': o.delivery_method, 'address': o.address,
        'steps': [{'status': st.value, 'label': (ERRAND_LABEL.get(st.value) if o.pickup_lat is not None else None) or (STATUS_LABEL[st.value] if st != OrderStatus.LISTO or o.delivery_method == 'delivery' else 'Listo para retirar'),
                   'done': i < current, 'current': i == current, 'at': iso(o.status_time(st)) if i <= current else None} for i, st in enumerate(steps)],
        'items': [{'product_id': it.product_id, 'name': it.product_name, 'quantity': it.quantity, 'unit_price': num(it.unit_price),
                   'line_total': num(it.unit_price * it.quantity), 'modifiers_text': it.modifiers_text,
                   'image_url': cdn(it.product.image_url, 'product') if it.product else None,
                   # para "Repetir": el producto sigue a la venta (sin opciones obligatorias, que hay que volver a elegir)
                   'available': bool(it.product and it.product.status == ProductStatus.ACTIVO and not it.product.deleted
                                     and not (it.product.stock is not None and it.product.stock <= 0)),
                   'grams': it.weight_grams,  # por peso: «Repetir» pide el mismo peso
                   'current_price': (num(weight.price_for(it.product.price, it.weight_grams)) if it.weight_grams else num(it.product.price)) if it.product else None} for it in o.items],
        'subtotal': num(o.subtotal), 'shipping': num(o.shipping), 'discount': num(o.discount), 'total': num(o.total),
        'points_used': o.points_used or 0, 'points_discount': num(o.points_discount), 'voucher_discount': num(o.voucher_discount),
        'whatsapp_url': o.whatsapp_url if o.status == OrderStatus.PENDIENTE else None,
        'can_review': o.status == OrderStatus.ENTREGADO and not o.review,
        'review': {'rating': o.review.rating, 'comment': o.review.comment, 'reply': o.review.reply} if o.review else None,
        'final': o.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO),
        'courier': {'name': o.courier.name.split()[0], 'vehicle': o.courier.vehicle} if o.courier else None,
        'payment': payment_json(o),
        'pay_path': f'/pedido/{o.id}/pagar?t={order_token(o.id)}' if payments.awaiting_online(o) and o.status == OrderStatus.PENDIENTE else None,
        'delivery_pin': o.delivery_pin if o.status not in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO) else None,
        # seguridad de la entrega: el repartidor marcó que llegó, y el chat con él (con fotos)
        'courier_arrived': o.courier_arrived_at is not None and o.status == OrderStatus.EN_CAMINO,
        'chat': object_session(o) is not None and delivery_safety.chat_open(object_session(o), o)[0],  # apagado en el panel: no se muestra
        'delivery_issue': o.delivery_fail_reason if o.delivery_failed_at else None,
        'proof_photo': f'/api/v1/orders/{o.id}/photos/{o.proof_photo_id}?t={order_token(o.id)}' if o.proof_photo_id else None,
        # seguimiento en vivo: dónde está el repartidor y cuánto falta (solo mientras el pedido está en curso)
        'tracking': tracking.for_order(object_session(o), o) if object_session(o) is not None else None,
        'claim': claim_json(o),
        # entregado: los Puntos Trappi que sumó con este pedido (para el festejo de la app)
        'points_earned': _points_earned(o),
        'call_if_missing': bool(o.call_if_missing),
        # peso real: lo que pesó cada producto por peso y el total ajustado (si hay que aceptarlo, status = pending)
        'weight': _weight_json(o),
        'promo_discount': num(o.promo_discount or 0), 'promo_text': o.promo_text,
        'table_name': o.table_name,  # pedido desde el QR de la mesa: la app muestra la cuenta de la mesa  # promos de la caja que valen online (dentro de discount)
        'rubro': None if o.pickup_lat is not None else weight.theme(o.store)['key'],
        'cold': rubro_ui.cold(o, datetime.now(timezone.utc)),  # heladería en camino: hace cuánto salió (estimado por tiempo)
        'pickup': _pickup_json(o),  # para retirar: el número grande y para cuándo está
    }


def _pickup_json(o: Order) -> dict | None:
    pk = rubro_ui.pickup(o)
    return {**pk, 'ready_at': iso(pk['ready_at'])} if pk else None


def _weight_json(o: Order) -> dict | None:
    if not any(it.weight_grams for it in o.items):
        return None
    w = weight.preview(o)
    return {'status': w['status'], 'adjusts': w['adjusts'], 'diff': num(w['diff']), 'margin': weight.margin(o.store),
            'lines': [{'id': ln['id'], 'name': ln['name'], 'ordered': ln['ordered'], 'real': ln['real'], 'old': num(ln['old']),
                       'new': num(ln['new']) if ln['new'] is not None else None, 'pct': ln['pct']} for ln in w['lines']]}


def _points_earned(o: Order) -> int:
    db = object_session(o)
    if db is None or o.status != OrderStatus.ENTREGADO or not o.account_id:
        return 0
    from ..models import LoyaltyEntry
    return int(db.scalar(select(LoyaltyEntry.points).where(LoyaltyEntry.dedupe_key == f'earn:{o.id}')) or 0)


def claim_json(o: Order) -> dict | None:
    """El reclamo del pedido, o si todavia se puede reclamar (hasta 48 h despues de entregado o si no llego)."""
    db = object_session(o)
    c = claims.of_order(db, o.id) if db is not None else None
    if c is None:
        return {'can_claim': True, 'reasons': [{'key': k, 'label': v} for k, v in claims.REASONS.items()]} if claims.can_claim(o) else None
    return {'can_claim': False, 'status': c.status, 'reason': claims.REASONS.get(c.reason, c.reason), 'text': c.text,
            'answer': c.answer, 'resolution': claims.RESOLUTIONS.get(c.resolution) if c.resolution else None, 'created_at': iso(c.created_at)}


def payment_json(o: Order) -> dict:
    change = payments.change_for(o)
    return {'method': o.payment_method, 'label': payments.method_label(o), 'paid': payments.is_paid(o),
            'online': o.payment_method in payments.ONLINE, 'status': o.payment_status, 'status_text': payments.status_text(o),
            'transfer_alias': (o.store.transfer_alias or None) if o.payment_method == 'transferencia' else None,
            'cash_with': num(o.cash_with) if o.cash_with else None, 'change': num(change) if change else None}


ORDER_OPTS = (joinedload(Order.store), selectinload(Order.items), selectinload(Order.events), joinedload(Order.review), joinedload(Order.courier))


@router.get('/orders/{order_id}')
def order_detail(order_id: int, t: str = '', db: Session = Depends(get_db)):
    o = db.scalar(select(Order).options(*ORDER_OPTS).where(Order.id == order_id)) if valid_order_token(t, order_id) else None
    if not o:
        return JSONResponse({'error': 'No encontramos ese pedido.'}, status_code=404)
    return order_json(o)


@router.get('/orders')
def orders_batch(refs: str = Query('', description='id:token separados por coma (los pedidos guardados en el telefono)'), db: Session = Depends(get_db)):
    wanted = {}
    for ref in refs.split(',')[:30]:
        oid, _, token = ref.partition(':')
        if oid.isdigit() and valid_order_token(token, int(oid)):
            wanted[int(oid)] = token
    rows = db.scalars(select(Order).options(*ORDER_OPTS).where(Order.id.in_(wanted)).order_by(Order.created_at.desc())).all() if wanted else []
    return {'orders': [order_json(o) for o in rows]}


class ReviewIn(BaseModel):
    t: str
    rating: int = Field(ge=1, le=5)
    comment: str = Field('', max_length=2000)


@router.post('/orders/{order_id}/review')
def order_review(order_id: int, body: ReviewIn, db: Session = Depends(get_db)):
    o = db.get(Order, order_id) if valid_order_token(body.t, order_id) else None
    if not o:
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    if o.status != OrderStatus.ENTREGADO or o.review:
        return JSONResponse({'ok': False, 'error': 'Este pedido ya no se puede calificar.'}, status_code=409)
    db.add(Review(order_id=o.id, store_id=o.store_id, rating=body.rating, comment=body.comment.strip()[:MAX_TEXT] or None))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return JSONResponse({'ok': False, 'error': 'Este pedido ya fue calificado.'}, status_code=409)
    refresh_store_rating(db, o.store_id)
    from ..services import owner_alerts
    owner_alerts.bad_review(o.store_id, o.id, body.rating)
    db.commit()
    return {'ok': True}


class PushIn(BaseModel):
    t: str
    token: str = Field(min_length=10, max_length=512)
    platform: str = Field('android', max_length=10)
