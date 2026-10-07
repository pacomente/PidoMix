"""API JSON para la app movil (React Native / Expo): /api/v1.

La app no usa la sesion del navegador: el carrito vive en el telefono y se manda en cada
cotizacion o pedido, igual que la ubicacion. Las reglas (horarios, zonas, cupones, estados)
son las mismas de la web porque se reusan los mismos servicios.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, object_session, selectinload

from ..config import settings
from ..db import get_db
from ..models import Banner, Category, ModifierGroup, Order, OrderStatus, Product, ProductStatus, Review, Setting, Store, StoreCategory, StoreStatus
from ..services.cart import price_lines
from ..services.checkout import CheckoutError, find_coupon, place_order
from ..services.formatting import visual
from ..services.images import cdn
from ..services.geo import coverage, parse_location
from ..services import accounts, audit, cities, deals, logistics, payments, plans, platform, push, recommendations
from ..services.orders import sequence
from ..services.ratelimit import PersistentRateLimiter, client_ip, order_limiter
from ..services.reviews import MAX_TEXT, public_name, rating_summary, refresh_store_rating
from ..services.store_hours import is_open, open_text
from .public import menu_groups, order_token, valid_order_token

router = APIRouter()
STORE_OPTS = (joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.zones))
PRODUCT_OPTS = (joinedload(Product.store), joinedload(Product.category), selectinload(Product.modifier_groups))
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
    best = deals.max_discounts(db, [i['id'] for i in items])
    for i in items:
        i['max_discount'] = best.get(i['id']) or None
    return items


def store_json(s: Store, loc=None, full=False) -> dict:
    cat = s.store_category.name if s.store_category else ''
    v = visual(s.name, cat)
    open_now = is_open(s)
    data = {
        'id': s.id, 'slug': s.slug, 'name': s.name, 'category': cat or None, 'description': s.description,
        'logo_url': cdn(s.logo_url, 'logo'), 'cover_url': cdn(s.cover_url, 'card'), 'emoji': v['emoji'], 'hue': v['hue'],
        'featured': s.featured, 'is_open': open_now, 'open_text': None if open_now else open_text(s),
        'rating': round(num(s.rating_avg), 1) if s.rating_count else None, 'rating_count': s.rating_count,
        'eta_min': s.estimated_minutes, 'eta_max': s.estimated_minutes + 10,
        'delivery_enabled': s.delivery_enabled, 'delivery_cost': num(s.delivery_cost), 'minimum_order': num(s.minimum_order),
        'coverage': coverage_json(s, loc), 'fleet': plans.fleet_kind(s),
        'transfer_alias': (s.transfer_alias or None) if plans.accepts_transfer(s) else None,
        # medios de pago que acepta (Trappi Delivery: sin transferencia); Mercado Pago se agrega en mp_available
        'payment_methods': ['efectivo', 'transferencia'] if plans.accepts_transfer(s) else ['efectivo'],
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
            'min_app_version': status['min_version'], 'app': status,
            'orders': {'enabled': cfg['orders_enabled'], 'message': cfg['orders_message']},
            # cuentas: con required, para pedir hay que entrar (codigo por email: login_path abre el navegador del sistema)
            'ai': _ai_status(db),
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
        'store_categories': [{'id': c.id, 'name': c.name, 'emoji': visual(c.name)['emoji']} for c in store_cats],
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
def store_detail(slug: str, lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
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
        'menu': [{'key': key, 'title': title, 'products': [product_json(p) for p in items]} for key, title, items in menu_groups(products, sections, categories)],
        'reviews': [review_json(r) for r in reviews],
        'rating_summary': rating_summary(db, Review.store_id == s.id, Review.hidden.is_(False)),
    }


@router.get('/search')
def search(q: str = '', lat: float | None = None, lng: float | None = None, city: str | None = None, db: Session = Depends(get_db)):
    q = q.strip()[:100]
    if len(q) < 2:
        return {'stores': [], 'products': []}
    term = f'%{q}%'
    here = city_for(db, city, loc_from(lat, lng))
    cid = here.id if here else None
    found_stores = db.scalars(select(Store).options(*STORE_OPTS).where(Store.status == StoreStatus.ACTIVA, Store.account_status == 'activo', cities.store_clause(cid), or_(Store.name.ilike(term), Store.description.ilike(term))).order_by(Store.name).limit(20)).all()
    found_products = db.scalars(select(Product).options(*PRODUCT_OPTS).where(Product.status == ProductStatus.ACTIVO, plans.visible_product_clause(), cities.product_clause(cid), or_(Product.name.ilike(term), Product.description.ilike(term))).order_by(Product.featured.desc(), Product.name).limit(40)).all()
    loc = loc_from(lat, lng)
    return {'stores': with_discounts(db, [store_json(s, loc) for s in found_stores]), 'products': [product_json(p, with_store=True) for p in found_products]}


@router.get('/products/{product_id}')
def product_detail(product_id: int, db: Session = Depends(get_db)):
    p = db.scalar(select(Product).options(*PRODUCT_OPTS, selectinload(Product.modifier_groups).selectinload(ModifierGroup.options))
                  .where(Product.id == product_id, Product.status == ProductStatus.ACTIVO, plans.visible_product_clause()))
    if not p:
        return JSONResponse({'error': 'Ese producto ya no está disponible.'}, status_code=404)
    return {**product_json(p, with_store=True), 'groups': [
        {'id': g.id, 'name': g.name, 'required': g.required, 'min_select': g.min_select, 'max_select': g.max_select,
         'options': [{'id': o.id, 'name': o.name, 'price_extra': num(o.price_extra)} for o in g.options if o.active]}
        for g in p.modifier_groups]}


# ---------- carrito y pedidos ----------

class CartLine(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1, le=99)
    modifiers: list[int] = Field(default_factory=list, max_length=30)


class QuoteIn(BaseModel):
    items: list[CartLine] = Field(default_factory=list, max_length=60)
    lat: float | None = None
    lng: float | None = None
    delivery_method: str = 'delivery'
    coupon: str = ''


class OrderIn(QuoteIn):
    first_name: str = Field(max_length=100)
    last_name: str = Field('', max_length=100)
    phone: str = Field(max_length=40)
    address: str = Field('', max_length=255)
    reference: str = Field('', max_length=255)
    notes: str = Field('', max_length=1000)
    # token de Firebase del telefono, para avisarle por push cada cambio de estado
    push_token: str = Field('', max_length=512)
    platform: str = Field('android', max_length=10)
    payment_method: str = Field('efectivo', max_length=20)
    cash_with: float | None = Field(None, ge=0, le=100_000_000)  # "pago con" en efectivo


def mp_available(db: Session, store) -> bool:
    from ..services import mercadopago
    return mercadopago.available_for(db, store)


def quote_json(db: Session, body: QuoteIn) -> tuple[dict, dict, dict | None]:
    loc = loc_from(body.lat, body.lng)
    cart = price_lines(db, [line.model_dump() for line in body.items], loc)
    store = cart['store']
    shipping = cart['shipping'] if body.delivery_method == 'delivery' else Decimal('0')
    discount, coupon_error = Decimal('0'), None
    if store and body.coupon.strip():
        coupon, result = find_coupon(db, store.id, body.coupon, cart['subtotal'])
        if coupon: discount = result
        else: coupon_error = result
    data = {
        'store': ({**store_json(store, loc), 'coverage': coverage_json(store, loc, cart['coverage']), 'mp_available': mp_available(db, store)} if store else None),
        'items': [{'product_id': i['product'].id, 'name': i['product'].name, 'quantity': i['quantity'], 'unit_price': num(i['unit_price']),
                   'line_total': num(i['line_total']), 'modifiers': [o.id for o in i['modifiers']], 'modifiers_text': i['modifiers_text'] or None,
                   'line_key': i['line_key']} for i in cart['items']],
        'dropped': len(body.items) - len(cart['items']),  # lineas que ya no se pueden pedir (producto pausado, otro local...)
        'subtotal': num(cart['subtotal']), 'shipping': num(shipping), 'discount': num(discount), 'coupon_error': coupon_error,
        'total': num(cart['subtotal'] + shipping - discount),
        'minimum_order': num(store.minimum_order) if store else 0,
    }
    return data, cart, loc


@router.post('/cart/quote')
def cart_quote(body: QuoteIn, db: Session = Depends(get_db)):
    return quote_json(db, body)[0]


# ---------- cuenta del cliente ----------

def account_json(a) -> dict:
    return {'id': a.id, 'email': a.email, 'name': a.name, 'picture_url': a.picture_url, 'first_name': a.first_name or '', 'last_name': a.last_name or '',
            'phone': a.phone or '', 'address': a.address or '', 'reference': a.reference or '', 'personalize': a.personalize is not False}


def current_account(db: Session, authorization: str | None):
    return accounts.from_bearer(db, authorization)


def no_session() -> JSONResponse:
    return JSONResponse({'ok': False, 'error': 'Tu sesión venció. Volvé a entrar.', 'login_required': True}, status_code=401)


exchange_limiter = PersistentRateLimiter('app-exchange', limit=20, window_seconds=600)


class ExchangeIn(BaseModel):
    code: str = Field(..., max_length=2000)
    verifier: str = Field(..., min_length=43, max_length=128)


@router.post('/auth/exchange')
def auth_exchange(body: ExchangeIn, request: Request, db: Session = Depends(get_db)):
    """La app cambia el codigo que le devolvio el ingreso (codigo por email, por deep link) por su token, mostrando el verifier de PKCE."""
    if not exchange_limiter.check(client_ip(request)):
        return JSONResponse({'ok': False, 'error': 'Demasiados intentos. Esperá unos minutos.'}, status_code=429)
    try:
        acct = accounts.redeem_app_code(db, body.code, body.verifier)
    except accounts.AccountError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    return {'ok': True, 'token': accounts.app_token(acct), 'account': account_json(acct)}


@router.get('/me')
def me(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    return {'ok': True, 'account': account_json(acct)} if acct else no_session()


class MeIn(BaseModel):
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=255)
    reference: str | None = Field(None, max_length=255)
    personalize: bool | None = None  # "Recomendado para vos" con sus pedidos


@router.put('/me')
def me_update(body: MeIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    data = body.model_dump()
    personalize = data.pop('personalize')
    accounts.save_contact(acct, **data)
    if personalize is not None:
        acct.personalize = personalize
    db.commit()
    return {'ok': True, 'account': account_json(acct)}


@router.get('/recommendations')
def recommendations_for_me(lat: float | None = None, lng: float | None = None, city: str | None = None,
                           authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Recomendado para vos: solo con la cuenta del cliente y sus propios pedidos. Sin cuenta o apagado: vacío."""
    acct = current_account(db, authorization)
    loc = loc_from(lat, lng)
    here = city_for(db, city, loc)
    picks = recommendations.recommend(db, acct, here.id if here else None, loc)
    return {'enabled': recommendations.enabled(acct), 'title': 'Recomendado para vos',
            'items': [{**product_json(x.product, with_store=True), 'reason': x.reason} for x in picks]}


class LogoutIn(BaseModel):
    everywhere: bool = False


@router.post('/me/logout')
def me_logout(body: LogoutIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if acct and body.everywhere:
        accounts.sign_out_everywhere(acct)
        db.commit()
    return {'ok': True}


@router.delete('/me')
def me_delete(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    audit.log(db, 'client.delete', 'client_account', acct.id, new={'via': 'app'}, ip=client_ip(request))
    accounts.delete(db, acct)
    db.commit()
    return {'ok': True}


@router.get('/me/orders')
def me_orders(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    rows = db.scalars(select(Order).options(*ORDER_OPTS).where(Order.account_id == acct.id).order_by(Order.created_at.desc()).limit(30)).all()
    return {'orders': [{**order_json(o), 'token': order_token(o.id)} for o in rows]}


@router.post('/orders')
def create_order(body: OrderIn, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    acct = current_account(db, authorization)
    if acct is None and accounts.required(db):
        return JSONResponse({'ok': False, 'login_required': True,
                             'error': 'Para pedir tenés que entrar con tu cuenta. Si no ves el botón para entrar, actualizá la app.'}, status_code=401)
    ip = client_ip(request)
    if order_limiter.blocked(ip):
        return JSONResponse({'ok': False, 'error': 'Hiciste muchos pedidos seguidos. Esperá unos minutos.'}, status_code=429)
    _, cart, loc = quote_json(db, body)
    try:
        order = place_order(db, cart, loc, first_name=body.first_name, last_name=body.last_name, phone=body.phone, delivery_method=body.delivery_method,
                            address=body.address, reference=body.reference, notes=body.notes, coupon_code=body.coupon,
                            payment_method=body.payment_method, cash_with=body.cash_with, account=acct, origin='app', ip=ip)
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
        'store': {'slug': o.store.slug, 'name': o.store.name, 'whatsapp': o.store.whatsapp, 'eta_min': o.store.estimated_minutes},
        'delivery_method': o.delivery_method, 'address': o.address,
        'steps': [{'status': st.value, 'label': STATUS_LABEL[st.value] if st != OrderStatus.LISTO or o.delivery_method == 'delivery' else 'Listo para retirar',
                   'done': i < current, 'current': i == current, 'at': iso(o.status_time(st)) if i <= current else None} for i, st in enumerate(steps)],
        'items': [{'product_id': it.product_id, 'name': it.product_name, 'quantity': it.quantity, 'unit_price': num(it.unit_price),
                   'line_total': num(it.unit_price * it.quantity), 'modifiers_text': it.modifiers_text,
                   'image_url': cdn(it.product.image_url, 'product') if it.product else None,
                   # para "Repetir": el producto sigue a la venta (sin opciones obligatorias, que hay que volver a elegir)
                   'available': bool(it.product and it.product.status == ProductStatus.ACTIVO and not it.product.deleted)} for it in o.items],
        'subtotal': num(o.subtotal), 'shipping': num(o.shipping), 'discount': num(o.discount), 'total': num(o.total),
        'whatsapp_url': o.whatsapp_url if o.status == OrderStatus.PENDIENTE else None,
        'can_review': o.status == OrderStatus.ENTREGADO and not o.review,
        'review': {'rating': o.review.rating, 'comment': o.review.comment, 'reply': o.review.reply} if o.review else None,
        'final': o.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO),
        'courier': {'name': o.courier.name.split()[0], 'vehicle': o.courier.vehicle} if o.courier else None,
        'payment': payment_json(o),
        'pay_path': f'/pedido/{o.id}/pagar?t={order_token(o.id)}' if payments.awaiting_online(o) and o.status == OrderStatus.PENDIENTE else None,
        'delivery_pin': o.delivery_pin if o.status not in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO) else None,
    }


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
    db.commit()
    return {'ok': True}


class PushIn(BaseModel):
    t: str
    token: str = Field(min_length=10, max_length=512)
    platform: str = Field('android', max_length=10)


@router.post('/orders/{order_id}/push')
def order_push(order_id: int, body: PushIn, db: Session = Depends(get_db)):
    """Registra el telefono para recibir notificaciones de este pedido."""
    o = db.get(Order, order_id) if valid_order_token(body.t, order_id) else None
    if not o:
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    ok = push.register(db, o, body.token, body.platform)
    try:
        db.commit()
    except IntegrityError:  # el mismo telefono registrado dos veces a la vez
        db.rollback()
    return {'ok': ok, 'enabled': push.enabled()}
