from datetime import datetime
from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload
from ..db import get_db
from ..models import Banner, Category, Customer, Order, OrderItem, Product, ProductStatus, Store, StoreStatus, StoreCategory
from ..services.cart import build_cart
from ..services.whatsapp import build_message, whatsapp_url
from ..services.store_hours import is_open
from ..config import settings
from itsdangerous import BadSignature, URLSafeSerializer

_signer = URLSafeSerializer(settings.secret_key, salt="trappi-order")


def order_token(order_id: int) -> str:
    return _signer.dumps(order_id)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


def ctx(request, **kwargs): return {"request": request, **kwargs}


store_open = is_open


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    banners = db.scalars(select(Banner).where(Banner.active).order_by(Banner.display_order, Banner.id)).all()
    cats = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    stores = db.scalars(select(Store).options(joinedload(Store.store_category), joinedload(Store.hours)).where(Store.status != StoreStatus.INACTIVA).order_by(Store.featured.desc(), Store.name)).unique().all()
    store_cats = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    promos = db.scalars(select(Product).options(joinedload(Product.store)).where(Product.status == ProductStatus.ACTIVO, Product.previous_price.is_not(None), Product.previous_price > Product.price).order_by(Product.featured.desc(), Product.display_order).limit(10)).unique().all()
    products = db.scalars(select(Product).options(joinedload(Product.store)).where(Product.status == ProductStatus.ACTIVO).order_by(Product.featured.desc(), Product.display_order).limit(12)).unique().all()
    return templates.TemplateResponse("public/home.html", ctx(request, banners=banners, categories=cats, store_categories=store_cats, stores=stores[:24], promos=promos, products=products, store_open=store_open))


@router.get("/tiendas", response_class=HTMLResponse)
def stores(request: Request, q: str | None = None, delivery: bool | None = None, featured: bool | None = None, category_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Store).options(joinedload(Store.store_category), joinedload(Store.hours)).where(Store.status != StoreStatus.INACTIVA)
    if q: stmt = stmt.where(Store.name.ilike(f"%{q}%"))
    if delivery is True: stmt = stmt.where(Store.delivery_enabled.is_(True))
    if featured is True: stmt = stmt.where(Store.featured.is_(True))
    if category_id: stmt = stmt.where(Store.store_category_id == category_id)
    stores = db.scalars(stmt.order_by(Store.featured.desc(), Store.name)).unique().all()
    categories = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse("public/stores.html", ctx(request, stores=stores, categories=categories, q=q, delivery=delivery, featured=featured, category_id=category_id, store_open=store_open))


@router.get("/tienda/{slug}", response_class=HTMLResponse)
def store(slug: str, request: Request, db: Session = Depends(get_db)):
    s = db.scalar(select(Store).options(joinedload(Store.products).joinedload(Product.category), joinedload(Store.hours), joinedload(Store.store_category)).where(Store.slug == slug, Store.status != StoreStatus.INACTIVA))
    if not s: return HTMLResponse("Tienda no encontrada", 404)
    categories = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    products = [p for p in s.products if p.status == ProductStatus.ACTIVO]
    return templates.TemplateResponse("public/store.html", ctx(request, store=s, categories=categories, products=products, store_open=store_open))


@router.get("/categoria/{slug}", response_class=HTMLResponse)
def category(slug: str, request: Request, q: str | None = None, min_price: Decimal | None = None, max_price: Decimal | None = None, featured: bool | None = None, db: Session = Depends(get_db)):
    cat = db.scalar(select(Category).where(Category.slug == slug, Category.active.is_(True)))
    if not cat: return HTMLResponse("Categoría no encontrada", 404)
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
    return templates.TemplateResponse("public/checkout.html", ctx(request, **cart, error=None))


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
    customer = Customer(first_name=first_name.strip(), last_name=last_name.strip(), phone=phone.strip(), address=address.strip(), reference=reference.strip())
    db.add(customer); db.flush()
    order = Order(store_id=store.id, customer_id=customer.id, delivery_method=delivery_method, payment_method="whatsapp", address=address.strip(), reference=reference.strip(), notes=notes.strip(), subtotal=cart["subtotal"], shipping=cart["shipping"] if delivery_method == "delivery" else Decimal("0"), total=cart["subtotal"] + (cart["shipping"] if delivery_method == "delivery" else Decimal("0")))
    db.add(order); db.flush()
    message_items=[]
    for item in cart["items"]:
        p=item["product"]
        db.add(OrderItem(order_id=order.id, product_id=p.id, product_name=p.name, unit_price=item["unit_price"], quantity=item["quantity"]))
        message_items.append({"name":p.name,"unit_price":item["unit_price"],"quantity":item["quantity"]})
    shipping = order.shipping
    message = build_message(store, {"first_name":first_name,"last_name":last_name,"phone":phone,"address":address,"reference":reference,"notes":notes}, message_items, order.subtotal, shipping, order.total, "Delivery" if delivery_method == "delivery" else "Retiro en local")
    order.whatsapp_url = whatsapp_url(store.whatsapp, message)
    db.commit(); request.session["cart"]=[]
    return RedirectResponse(f"/pedido/{order.id}?t={order_token(order.id)}", 303)


@router.get("/pedido/{order_id}", response_class=HTMLResponse)
def order_tracking(order_id: int, request: Request, t: str = "", db: Session = Depends(get_db)):
    try:
        valid = _signer.loads(t) == order_id
    except BadSignature:
        valid = False
    if not valid: return HTMLResponse("Pedido no encontrado", 404)
    order = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.items), joinedload(Order.customer)).where(Order.id == order_id)).unique().first()
    if not order: return HTMLResponse("Pedido no encontrado", 404)
    return templates.TemplateResponse("public/order_success.html", ctx(request, order=order))
