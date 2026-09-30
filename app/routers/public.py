from datetime import datetime
from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload
from ..db import get_db
from datetime import timezone
from ..models import Banner, Category, Coupon, Customer, ModifierGroup, Order, OrderItem, OrderStatus, Product, ProductStatus, Review, Store, StoreStatus, StoreCategory
from ..services.cart import build_cart, save_cart
from ..services.whatsapp import build_message, whatsapp_url
from ..services.store_hours import is_open, open_text
from ..config import settings
from itsdangerous import BadSignature, URLSafeSerializer

_signer = URLSafeSerializer(settings.secret_key, salt="trappi-order")


def order_token(order_id: int) -> str:
    return _signer.dumps(order_id)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


def ctx(request, **kwargs): return {"request": request, **kwargs}


def get_favorites(request) -> set[int]:
    return set(request.session.get("favorites", []))


store_open = is_open
templates.env.globals['open_text'] = open_text


def find_coupon(db, store_id, code, subtotal):
    code = (code or '').strip().upper()
    if not code:
        return None, None
    c = db.scalar(select(Coupon).where(Coupon.store_id == store_id, func.upper(Coupon.code) == code, Coupon.active.is_(True)))
    if not c:
        return None, 'Ese cupón no existe o ya no está activo.'
    if c.expires_at and c.expires_at < datetime.utcnow():
        return None, 'Ese cupón venció.'
    if c.max_uses and c.uses_count >= c.max_uses:
        return None, 'Ese cupón alcanzó el máximo de usos.'
    if subtotal < Decimal(c.min_order or 0):
        return None, f'Ese cupón requiere un pedido mínimo de ${Decimal(c.min_order):,.2f}.'
    discount = (subtotal * Decimal(c.discount_value) / 100) if c.discount_type == 'percent' else Decimal(c.discount_value)
    return c, min(discount, subtotal)


def not_found(request, message='No encontramos lo que buscás.'):
    return templates.TemplateResponse('public/404.html', ctx(request, message=message), status_code=404)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    banners = db.scalars(select(Banner).where(Banner.active).order_by(Banner.display_order, Banner.id)).all()
    cats = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    stores = db.scalars(select(Store).options(joinedload(Store.store_category), joinedload(Store.hours)).where(Store.status != StoreStatus.INACTIVA).order_by(Store.featured.desc(), Store.name)).unique().all()
    store_cats = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    promos = db.scalars(select(Product).options(joinedload(Product.store)).where(Product.status == ProductStatus.ACTIVO, Product.previous_price.is_not(None), Product.previous_price > Product.price).order_by(Product.featured.desc(), Product.display_order).limit(10)).unique().all()
    products = db.scalars(select(Product).options(joinedload(Product.store)).where(Product.status == ProductStatus.ACTIVO).order_by(Product.featured.desc(), Product.display_order).limit(12)).unique().all()
    return templates.TemplateResponse("public/home.html", ctx(request, banners=banners, categories=cats, store_categories=store_cats, stores=stores[:24], promos=promos, products=products, store_open=store_open, favorites=get_favorites(request)))


@router.get("/tiendas", response_class=HTMLResponse)
def stores(request: Request, q: str | None = None, delivery: bool | None = None, featured: bool | None = None, category_id: int | None = None, sort: str = "", db: Session = Depends(get_db)):
    stmt = select(Store).options(joinedload(Store.store_category), joinedload(Store.hours)).where(Store.status != StoreStatus.INACTIVA)
    if q: stmt = stmt.where(Store.name.ilike(f"%{q}%"))
    if delivery is True: stmt = stmt.where(Store.delivery_enabled.is_(True))
    if featured is True: stmt = stmt.where(Store.featured.is_(True))
    if category_id: stmt = stmt.where(Store.store_category_id == category_id)
    order = {"rapidos": (Store.estimated_minutes, Store.name), "envio": (Store.delivery_cost, Store.name)}.get(sort, (Store.featured.desc(), Store.name))
    stores = db.scalars(stmt.order_by(*order)).unique().all()
    categories = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse("public/stores.html", ctx(request, stores=stores, categories=categories, q=q, delivery=delivery, featured=featured, category_id=category_id, sort=sort, store_open=store_open, favorites=get_favorites(request)))


@router.get("/tienda/{slug}", response_class=HTMLResponse)
def store(slug: str, request: Request, db: Session = Depends(get_db)):
    s = db.scalar(select(Store).options(
        joinedload(Store.products).joinedload(Product.category),
        joinedload(Store.products).selectinload(Product.modifier_groups).selectinload(ModifierGroup.options),
        joinedload(Store.hours), joinedload(Store.store_category), selectinload(Store.sections),
    ).where(Store.slug == slug, Store.status != StoreStatus.INACTIVA))
    if not s: return not_found(request, "Ese comercio no existe o ya no está disponible.")
    categories = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    products = [p for p in s.products if p.status == ProductStatus.ACTIVO]
    sections = [sec for sec in s.sections if sec.active]
    return templates.TemplateResponse("public/store.html", ctx(request, store=s, categories=categories, sections=sections, products=products, store_open=store_open, favorites=get_favorites(request)))


@router.get("/categoria/{slug}", response_class=HTMLResponse)
def category(slug: str, request: Request, q: str | None = None, min_price: Decimal | None = None, max_price: Decimal | None = None, featured: bool | None = None, db: Session = Depends(get_db)):
    cat = db.scalar(select(Category).where(Category.slug == slug, Category.active.is_(True)))
    if not cat: return not_found(request, "Esa categoría no existe.")
    stmt = select(Product).options(joinedload(Product.store)).where(Product.category_id == cat.id, Product.status == ProductStatus.ACTIVO)
    if q: stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%")))
    if min_price is not None: stmt = stmt.where(Product.price >= min_price)
    if max_price is not None: stmt = stmt.where(Product.price <= max_price)
    if featured is True: stmt = stmt.where(Product.featured.is_(True))
    products = db.scalars(stmt.order_by(Product.display_order, Product.name)).all()
    return templates.TemplateResponse("public/category.html", ctx(request, category=cat, products=products, q=q, min_price=min_price, max_price=max_price, featured=featured))


@router.get("/buscar", response_class=HTMLResponse)
def search(request: Request, q: str = "", db: Session = Depends(get_db)):
    q = q.strip(); products=[]; stores=[]; categories=[]
    if q:
        term=f"%{q}%"
        products=db.scalars(select(Product).options(joinedload(Product.store)).where(Product.status==ProductStatus.ACTIVO, or_(Product.name.ilike(term), Product.description.ilike(term)))).all()
        stores=db.scalars(select(Store).where(Store.status==StoreStatus.ACTIVA, or_(Store.name.ilike(term), Store.description.ilike(term)))).all()
        categories=db.scalars(select(Category).where(Category.active, Category.name.ilike(term))).all()
    return templates.TemplateResponse("public/search.html", ctx(request, q=q, products=products, stores=stores, categories=categories))


@router.get("/checkout", response_class=HTMLResponse)
def checkout(request: Request, db: Session = Depends(get_db)):
    cart = build_cart(db, request)
    coupon_code = request.session.get("coupon", "")
    discount = Decimal("0"); coupon_error = None
    if coupon_code and cart["store"]:
        c, result = find_coupon(db, cart["store"].id, coupon_code, cart["subtotal"])
        if c: discount = result
        else: coupon_error = result; request.session["coupon"] = ""
    return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error=None, coupon_code=coupon_code if discount else "", coupon_error=coupon_error, discount=discount, grand_total=cart["total"] - discount))


@router.post("/checkout/coupon")
def checkout_coupon(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    cart = build_cart(db, request)
    if cart["store"]:
        c, result = find_coupon(db, cart["store"].id, code, cart["subtotal"])
        request.session["coupon"] = code.strip().upper() if c else ""
    return RedirectResponse("/checkout", 303)


@router.post("/checkout")
def checkout_post(request: Request, db: Session = Depends(get_db), first_name: str = Form(...), last_name: str = Form(...), phone: str = Form(...), address: str = Form(""), reference: str = Form(""), delivery_method: str = Form(...), notes: str = Form("")):
    cart = build_cart(db, request)
    if not cart["items"]: return RedirectResponse("/", 303)
    store = cart["store"]
    if not store_open(store):
        return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error="Este local está cerrado por ahora. Probá de nuevo cuando abra."), status_code=400)
    if delivery_method not in {"delivery", "retiro"}:
        return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error="Seleccioná una modalidad de entrega válida."), status_code=400)
    if delivery_method == "delivery" and not store.delivery_enabled:
        return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error="Esta tienda no realiza envíos."), status_code=400)
    if delivery_method == "delivery" and not address.strip():
        return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error="Ingresá una dirección para delivery."), status_code=400)
    if cart["subtotal"] < Decimal(store.minimum_order or 0):
        return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error=f"El pedido mínimo es ${Decimal(store.minimum_order):,.2f}."), status_code=400)
    coupon, discount = None, Decimal("0")
    coupon_code = request.session.get("coupon", "")
    if coupon_code:
        coupon, result = find_coupon(db, store.id, coupon_code, cart["subtotal"])
        if coupon: discount = result
    shipping = cart["shipping"] if delivery_method == "delivery" else Decimal("0")
    customer = Customer(first_name=first_name.strip(), last_name=last_name.strip(), phone=phone.strip(), address=address.strip(), reference=reference.strip())
    db.add(customer); db.flush()
    order = Order(store_id=store.id, customer_id=customer.id, delivery_method=delivery_method, payment_method="whatsapp", address=address.strip(), reference=reference.strip(), notes=notes.strip(), subtotal=cart["subtotal"], shipping=shipping, discount=discount, coupon_id=coupon.id if coupon else None, total=cart["subtotal"] + shipping - discount)
    db.add(order); db.flush()
    if coupon:
        coupon.uses_count += 1
    message_items=[]
    for item in cart["items"]:
        p=item["product"]
        db.add(OrderItem(order_id=order.id, product_id=p.id, product_name=p.name, unit_price=item["unit_price"], quantity=item["quantity"], modifiers_text=item["modifiers_text"] or None))
        message_items.append({"name":p.name,"unit_price":item["unit_price"],"quantity":item["quantity"],"modifiers_text":item["modifiers_text"]})
    shipping = order.shipping
    message = build_message(store, {"first_name":first_name,"last_name":last_name,"phone":phone,"address":address,"reference":reference,"notes":notes}, message_items, order.subtotal, shipping, order.total, "Delivery" if delivery_method == "delivery" else "Retiro en local", discount=discount, coupon_code=coupon.code if coupon else None)
    order.whatsapp_url = whatsapp_url(store.whatsapp, message)
    db.commit(); request.session["cart"]=[]; request.session["coupon"]=""
    request.session["orders"] = (request.session.get("orders", []) + [[order.id, order_token(order.id)]])[-10:]
    return RedirectResponse(f"/pedido/{order.id}?t={order_token(order.id)}", 303)


@router.get("/pedido/{order_id}", response_class=HTMLResponse)
def order_tracking(order_id: int, request: Request, t: str = "", db: Session = Depends(get_db)):
    try:
        valid = _signer.loads(t) == order_id
    except BadSignature:
        valid = False
    if not valid: return not_found(request, "No encontramos ese pedido.")
    order = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.items), joinedload(Order.customer), joinedload(Order.coupon), joinedload(Order.review)).where(Order.id == order_id)).unique().first()
    if not order: return not_found(request, "No encontramos ese pedido.")
    return templates.TemplateResponse("public/order_success.html", ctx(request, order=order))


@router.post("/pedido/{order_id}/review")
def order_review(order_id: int, request: Request, t: str = Form(""), rating: int = Form(...), comment: str = Form(""), db: Session = Depends(get_db)):
    try:
        valid = _signer.loads(t) == order_id
    except BadSignature:
        valid = False
    order = db.get(Order, order_id) if valid else None
    if not order or order.status != OrderStatus.ENTREGADO or order.review:
        return RedirectResponse(f"/pedido/{order_id}?t={t}", 303)
    rating = max(1, min(5, rating))
    db.add(Review(order_id=order.id, store_id=order.store_id, rating=rating, comment=comment.strip()[:500]))
    store = db.get(Store, order.store_id)
    total = Decimal(store.rating_avg) * store.rating_count + rating
    store.rating_count += 1
    store.rating_avg = (total / store.rating_count).quantize(Decimal("0.01"))
    db.commit()
    return RedirectResponse(f"/pedido/{order_id}?t={t}", 303)


@router.post("/tienda/{slug}/favorito")
def toggle_favorite(slug: str, request: Request, back: str = Form("/tiendas"), db: Session = Depends(get_db)):
    s = db.scalar(select(Store.id).where(Store.slug == slug))
    if s:
        favs = get_favorites(request)
        favs.symmetric_difference_update({s})
        request.session["favorites"] = list(favs)
    return RedirectResponse(back if back.startswith("/") and "://" not in back else "/tiendas", 303)


@router.get("/favoritos", response_class=HTMLResponse)
def favorites_page(request: Request, db: Session = Depends(get_db)):
    favs = get_favorites(request)
    stores = db.scalars(select(Store).options(joinedload(Store.store_category), joinedload(Store.hours)).where(Store.id.in_(favs))).unique().all() if favs else []
    return templates.TemplateResponse("public/favorites.html", ctx(request, stores=stores, store_open=store_open, favorites=favs))


@router.get("/mis-pedidos", response_class=HTMLResponse)
def my_orders(request: Request, db: Session = Depends(get_db)):
    saved = request.session.get("orders", [])
    tokens = {int(i): t for i, t in saved}
    orders = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.items)).where(Order.id.in_(tokens.keys())).order_by(Order.created_at.desc())).unique().all() if tokens else []
    return templates.TemplateResponse("public/my_orders.html", ctx(request, orders=orders, tokens=tokens))


@router.post("/pedido/{order_id}/repetir")
def order_repeat(order_id: int, request: Request, t: str = Form(""), db: Session = Depends(get_db)):
    try:
        valid = _signer.loads(t) == order_id
    except BadSignature:
        valid = False
    order = db.scalars(select(Order).options(joinedload(Order.items), joinedload(Order.store)).where(Order.id == order_id)).unique().first() if valid else None
    if not order: return not_found(request, "No encontramos ese pedido.")
    cart = []
    for it in order.items:
        p = db.get(Product, it.product_id)
        if p and p.status == ProductStatus.ACTIVO and p.store.status == StoreStatus.ACTIVA:
            cart.append({"product_id": p.id, "quantity": it.quantity})
    if not cart: return RedirectResponse(f"/tienda/{order.store.slug}", 303)
    save_cart(request, cart)
    return RedirectResponse("/checkout", 303)


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nDisallow: /admin\nDisallow: /api\nDisallow: /checkout\nDisallow: /pedido\nSitemap: {request.base_url}sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    urls = [f"{base}/", f"{base}/tiendas"] + [f"{base}/tienda/{s.slug}" for s in db.scalars(select(Store).where(Store.status != StoreStatus.INACTIVA)).all()] + [f"{base}/categoria/{c.slug}" for c in db.scalars(select(Category).where(Category.active)).all()]
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', media_type="application/xml")
