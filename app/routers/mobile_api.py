"""API JSON para la app movil (React Native / Expo): /api/v1.

La app no usa la sesion del navegador: el carrito vive en el telefono y se manda en cada
cotizacion o pedido, igual que la ubicacion. Las reglas (horarios, zonas, cupones, estados)
son las mismas de la web porque se reusan los mismos servicios.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..db import get_db
from ..models import Banner, Category, ModifierGroup, Order, OrderStatus, Product, ProductStatus, Review, Setting, Store, StoreCategory, StoreStatus
from ..services.cart import price_lines
from ..services.checkout import CheckoutError, find_coupon, place_order
from ..services.formatting import visual
from ..services.images import cdn
from ..services.geo import coverage, parse_location
from ..services import push
from ..services.orders import sequence
from ..services.ratelimit import client_ip, order_limiter
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


def coverage_json(store, loc):
    cov = coverage(store, loc)
    return {
        'zoned': cov.zoned, 'covered': cov.covered, 'delivers': cov.delivers,
        'distance_km': round(cov.distance, 2) if cov.distance is not None else None,
        'cost': num(cov.cost) if cov.cost is not None else None,
        'from_cost': num(cov.from_cost) if cov.from_cost is not None else None,
        'max_km': cov.max_km,
    }


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
        'coverage': coverage_json(s, loc),
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
    wa = db.scalar(select(Setting.value).where(Setting.key == 'platform_whatsapp'))
    lat, lng = (float(x) for x in settings.map_default_center.split(','))
    return {'name': 'Trappi', 'map_center': {'lat': lat, 'lng': lng}, 'support_whatsapp': wa or None, 'min_app_version': '1.0.0'}


@router.get('/home')
def home(lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
    loc = loc_from(lat, lng)
    banners = db.scalars(select(Banner).where(Banner.active).order_by(Banner.display_order, Banner.id)).all()
    store_cats = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    cats = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    stores = db.scalars(select(Store).options(*STORE_OPTS).where(Store.status != StoreStatus.INACTIVA).order_by(Store.featured.desc(), Store.name).limit(30)).all()
    promos = db.scalars(select(Product).options(*PRODUCT_OPTS).where(Product.status == ProductStatus.ACTIVO, Product.previous_price.is_not(None), Product.previous_price > Product.price).order_by(Product.featured.desc(), Product.display_order).limit(10)).all()
    store_items = [store_json(s, loc) for s in stores]
    if loc:  # con ubicacion: primero los que llegan, y entre ellos los mas cercanos
        store_items.sort(key=lambda s: (not s['coverage']['delivers'], s['coverage']['distance_km'] is None, s['coverage']['distance_km'] or 0))
    return {
        'banners': [{'id': b.id, 'title': b.title, 'subtitle': b.subtitle, 'image_url': cdn(b.image_url, 'banner'), 'button_text': b.button_text, 'link': b.link} for b in banners],
        'store_categories': [{'id': c.id, 'name': c.name, 'emoji': visual(c.name)['emoji']} for c in store_cats],
        'categories': [{'id': c.id, 'slug': c.slug, 'name': c.name, 'image_url': cdn(c.image_url, 'category'), **{k: visual(c.name, default='🍽️')[k] for k in ('emoji', 'hue')}} for c in cats],
        'promos': [product_json(p, with_store=True) for p in promos],
        'stores': store_items,
    }


@router.get('/stores')
def stores(q: str = '', category_id: int | None = None, lat: float | None = None, lng: float | None = None,
           sort: str = '', delivery: bool = False, db: Session = Depends(get_db)):
    loc = loc_from(lat, lng)
    stmt = select(Store).options(*STORE_OPTS).where(Store.status != StoreStatus.INACTIVA)
    if q.strip():
        stmt = stmt.where(Store.name.ilike(f'%{q.strip()[:100]}%'))
    if category_id:
        stmt = stmt.where(Store.store_category_id == category_id)
    rows = [store_json(s, loc) for s in db.scalars(stmt.order_by(Store.featured.desc(), Store.name)).all()]
    if delivery:
        rows = [s for s in rows if s['delivery_enabled'] and s['coverage']['delivers']]
    if sort == 'cerca' and loc:
        rows.sort(key=lambda s: (s['coverage']['distance_km'] is None, s['coverage']['distance_km'] or 0))
    elif sort == 'rapidos':
        rows.sort(key=lambda s: s['eta_min'])
    return {'stores': rows}


@router.get('/stores/{slug}')
def store_detail(slug: str, lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
    s = db.scalar(select(Store).options(*STORE_OPTS, selectinload(Store.sections)).where(Store.slug == slug, Store.status != StoreStatus.INACTIVA))
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
def search(q: str = '', lat: float | None = None, lng: float | None = None, db: Session = Depends(get_db)):
    q = q.strip()[:100]
    if len(q) < 2:
        return {'stores': [], 'products': []}
    term = f'%{q}%'
    found_stores = db.scalars(select(Store).options(*STORE_OPTS).where(Store.status == StoreStatus.ACTIVA, or_(Store.name.ilike(term), Store.description.ilike(term))).order_by(Store.name).limit(20)).all()
    found_products = db.scalars(select(Product).options(*PRODUCT_OPTS).where(Product.status == ProductStatus.ACTIVO, or_(Product.name.ilike(term), Product.description.ilike(term))).order_by(Product.featured.desc(), Product.name).limit(40)).all()
    loc = loc_from(lat, lng)
    return {'stores': [store_json(s, loc) for s in found_stores], 'products': [product_json(p, with_store=True) for p in found_products]}


@router.get('/products/{product_id}')
def product_detail(product_id: int, db: Session = Depends(get_db)):
    p = db.scalar(select(Product).options(*PRODUCT_OPTS, selectinload(Product.modifier_groups).selectinload(ModifierGroup.options))
                  .where(Product.id == product_id, Product.status == ProductStatus.ACTIVO))
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
        'store': store_json(store, loc) if store else None,
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


@router.post('/orders')
def create_order(body: OrderIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if order_limiter.blocked(ip):
        return JSONResponse({'ok': False, 'error': 'Hiciste muchos pedidos seguidos. Esperá unos minutos.'}, status_code=429)
    _, cart, loc = quote_json(db, body)
    try:
        order = place_order(db, cart, loc, first_name=body.first_name, last_name=body.last_name, phone=body.phone, delivery_method=body.delivery_method,
                            address=body.address, reference=body.reference, notes=body.notes, coupon_code=body.coupon)
    except CheckoutError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    if body.push_token:
        push.register(db, order, body.push_token, body.platform)
    db.commit()
    order_limiter.hit(ip)
    return {'ok': True, 'id': order.id, 'token': order_token(order.id), 'whatsapp_url': order.whatsapp_url, 'total': num(order.total)}


def order_json(o: Order) -> dict:
    steps = sequence(o) if o.status != OrderStatus.CANCELADO else []
    current = steps.index(o.status) if o.status in steps else -1
    return {
        'id': o.id, 'status': o.status.value, 'status_label': STATUS_LABEL[o.status.value], 'created_at': iso(o.created_at),
        'store': {'slug': o.store.slug, 'name': o.store.name, 'whatsapp': o.store.whatsapp, 'eta_min': o.store.estimated_minutes},
        'delivery_method': o.delivery_method, 'address': o.address,
        'steps': [{'status': st.value, 'label': STATUS_LABEL[st.value] if st != OrderStatus.LISTO or o.delivery_method == 'delivery' else 'Listo para retirar',
                   'done': i < current, 'current': i == current, 'at': iso(o.status_time(st)) if i <= current else None} for i, st in enumerate(steps)],
        'items': [{'name': it.product_name, 'quantity': it.quantity, 'line_total': num(it.unit_price * it.quantity), 'modifiers_text': it.modifiers_text} for it in o.items],
        'subtotal': num(o.subtotal), 'shipping': num(o.shipping), 'discount': num(o.discount), 'total': num(o.total),
        'whatsapp_url': o.whatsapp_url if o.status == OrderStatus.PENDIENTE else None,
        'can_review': o.status == OrderStatus.ENTREGADO and not o.review,
        'review': {'rating': o.review.rating, 'comment': o.review.comment, 'reply': o.review.reply} if o.review else None,
        'final': o.status in (OrderStatus.ENTREGADO, OrderStatus.CANCELADO),
    }


ORDER_OPTS = (joinedload(Order.store), selectinload(Order.items), selectinload(Order.events), joinedload(Order.review))


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
