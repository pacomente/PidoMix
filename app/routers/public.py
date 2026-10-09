from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload
from markupsafe import Markup, escape

from ..asset_version import ASSET_VERSION
from ..config import settings
from ..services import platform as platform_settings
from ..services import accounts, cities, deals, logistics, mercadopago, plans, recommendations, retention, search
from ..services.images import cdn
from ..db import get_db
from ..models import Banner, Category, Order, OrderStatus, Product, ProductStatus, Review, Setting, Store, StoreCategory, StoreStatus
from ..services.cart import build_cart, save_cart
from ..services.checkout import CheckoutError, find_coupon, place_order, points_preview
from ..services.formatting import money, visual
from ..services.forms import form_float
from ..services import payments
from ..services.geo import coverage, format_km, parse_location
from ..services.ratelimit import client_ip, order_limiter
from ..services.whatsapp import whatsapp_url
from ..services.store_hours import is_open, local_now, open_text, to_local
from ..services.reviews import MAX_TEXT, public_name, rating_summary, refresh_store_rating

_signer = URLSafeSerializer(settings.secret_key, salt="trappi-order")


def order_token(order_id: int) -> str:
    return _signer.dumps(order_id)


def valid_order_token(token: str, order_id: int) -> bool:
    try:
        return _signer.loads(token) == order_id
    except BadSignature:
        return False


# Las tarjetas de producto solo necesitan saber si hay modificadores (no sus opciones) y
# las de tienda necesitan los horarios para saber si esta abierta. Las colecciones van con
# selectinload: un joinedload multiplicaria filas (productos x horarios) y rompe los LIMIT.
PRODUCT_CARD = (joinedload(Product.store), joinedload(Product.category), selectinload(Product.modifier_groups))
STORE_CARD = (joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.zones))

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))
templates.env.filters['cdn'] = cdn
templates.env.globals['platform'] = platform_settings.current  # mapas, mantenimiento (con cache)
templates.env.globals['ASSET_VERSION'] = ASSET_VERSION


def icon(name: str, cls: str = '') -> Markup:
    """Icono del juego de la web (public/_sprite.html): {{ icon('pin') }}."""
    name = ''.join(ch for ch in name if ch.isalnum() or ch == '-')
    return Markup(f'<svg class="i {escape(cls)}" aria-hidden="true" focusable="false"><use href="#i-{name}"/></svg>')


templates.env.globals['icon'] = icon
templates.env.globals['current_year'] = lambda: local_now().year
templates.env.globals.setdefault('to_local', to_local)
templates.env.globals['fleet_kind'] = plans.fleet_kind
templates.env.globals['FLEET_LABELS'] = plans.FLEET_LABELS


def initials(name: str | None) -> str:
    """Iniciales para el logo de un comercio sin foto: "Burger Mix" -> "BM"."""
    words = [w for w in (name or '').replace('-', ' ').split() if w[:1].isalnum()]
    return ''.join(w[0] for w in words[:2]).upper() or 'T'


templates.env.filters['initials'] = initials
templates.env.globals['open_text'] = open_text
templates.env.globals['public_name'] = public_name
templates.env.globals['visual'] = visual
templates.env.globals['coverage'] = coverage
templates.env.globals['MAP_CENTER'] = settings.map_default_center
templates.env.globals['city_of'] = cities.for_request  # ciudad del visitante (multi-ciudad)
templates.env.globals['multi_city'] = cities.multi_for_templates
templates.env.filters['km'] = format_km


def _ai_available() -> bool:
    """Para el encabezado: con la configuracion en cache (no abre una sesion de base en cada pagina)."""
    from ..ai import providers
    return providers.configured() and bool(platform_settings.current().get("ai_enabled"))


templates.env.globals['ai_available'] = _ai_available
templates.env.filters['money'] = money
store_open = is_open


def opt_int(value: str | None) -> int | None:
    """Los formularios GET mandan "" para "Todos": eso es "sin filtro", no un error 422."""
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def opt_decimal(value: str | None) -> Decimal | None:
    try:
        return Decimal((value or "").strip().replace(",", ".")) if (value or "").strip() else None
    except ArithmeticError:
        return None


def get_location(request) -> dict | None:
    return parse_location(request.session.get("loc") or {})


def ctx(request, **kwargs): return {"request": request, "loc": get_location(request), **kwargs}


def get_favorites(request) -> set[int]:
    return set(request.session.get("favorites", []))


def not_found(request, message='No encontramos lo que buscás.'):
    return templates.TemplateResponse(request, 'public/404.html', ctx(request, message=message), status_code=404)


def menu_groups(products, sections, categories):
    """Agrupa el menu una sola vez en Python: [(ancla, titulo, productos), ...].

    Con secciones propias del local se agrupa por seccion; si no, por categoria global.
    Los productos sin grupo van a "Otros"; los de una seccion/categoria inactiva no se muestran.
    """
    if sections:
        key, prefix, groups = 'section_id', 'sec', sections
    else:
        key, prefix, groups = 'category_id', 'cat', categories
    by_group = {}
    for p in products:
        by_group.setdefault(getattr(p, key), []).append(p)
    result = [(f'{prefix}-{g.id}', g.name, by_group[g.id]) for g in groups if g.id in by_group]
    if None in by_group:
        result.append((f'{prefix}-otros', 'Otros', by_group[None]))
    return result


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    city = cities.for_request(request, db)
    cid = city.id if city else None
    banners = db.scalars(select(Banner).where(Banner.active).order_by(Banner.display_order, Banner.id)).all()
    cats = db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    stores = db.scalars(select(Store).options(*STORE_CARD).where(plans.visible_clause(), cities.store_clause(cid)).order_by(Store.featured.desc(), Store.name).limit(24)).all()
    store_cats = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    active = select(Product).options(*PRODUCT_CARD).where(Product.status == ProductStatus.ACTIVO, plans.visible_product_clause(), cities.product_clause(cid)).order_by(Product.featured.desc(), Product.display_order)
    promos = db.scalars(active.where(Product.previous_price.is_not(None), Product.previous_price > Product.price).limit(10)).all()
    products = db.scalars(active.limit(12)).all()
    acct = accounts.from_session(request, db)
    picks = recommendations.recommend(db, acct, cid, get_location(request), get_favorites(request), limit=10)
    comeback = retention.offer(db, acct) if acct else {'reminder': None, 'voucher': None}
    return templates.TemplateResponse(request, "public/home.html", ctx(request, picks=picks, comeback=comeback, banners=banners, categories=cats, store_categories=store_cats, stores=stores, promos=promos, products=products, store_open=store_open, deals=deals.max_discounts(db, [s.id for s in stores]), favorites=get_favorites(request), join=join_trappi(db, city), city=city))


def join_trappi(db: Session, city=None) -> dict:
    """Boton "Sumá tu comercio": abre WhatsApp con el numero y el mensaje de la configuracion comercial
    (o el contacto de la ciudad). No hay registro publico: el alta la hace el administrador despues de hablar."""
    cfg = platform_settings.get_all(db)
    number = (city.whatsapp if city and city.whatsapp else None) or cfg["platform_whatsapp"]
    link = whatsapp_url(number, cfg["commercial_message"]) if number else None
    return {"open": cfg["new_stores_open"], "link": link if cfg["new_stores_open"] else None}


@router.get("/ciudades", response_class=HTMLResponse)
def city_list(request: Request, db: Session = Depends(get_db)):
    """Elegir la ciudad (solo tiene sentido con mas de una)."""
    return templates.TemplateResponse(request, "public/cities.html", ctx(request, cities=cities.all_cities(db), city=cities.for_request(request, db)))


@router.get("/ciudad/{slug}")
def city_choose(slug: str, request: Request, db: Session = Depends(get_db)):
    city = cities.by_ref(db, slug)
    if not city:
        return not_found(request, "Todavía no estamos en esa ciudad.")
    request.session["city"] = city.slug
    loc = get_location(request)
    if loc and cities.detect(db, loc["lat"], loc["lng"]) not in (None, city):
        request.session.pop("loc", None)  # la ubicacion guardada es de otra ciudad
    return RedirectResponse("/", 303)


@router.get("/tiendas", response_class=HTMLResponse)
def stores(request: Request, q: str | None = None, delivery: bool | None = None, featured: bool | None = None, category_id: str | None = None, sort: str = "", db: Session = Depends(get_db)):
    category_id = opt_int(category_id)
    city = cities.for_request(request, db)
    stmt = select(Store).options(*STORE_CARD).where(plans.visible_clause(), cities.store_clause(city.id if city else None))
    if q: stmt = stmt.where(Store.name.ilike(f"%{q}%"))
    if delivery is True: stmt = stmt.where(Store.delivery_enabled.is_(True))
    if featured is True: stmt = stmt.where(Store.featured.is_(True))
    if category_id: stmt = stmt.where(Store.store_category_id == category_id)
    order = {"rapidos": (Store.estimated_minutes, Store.name), "envio": (Store.delivery_cost, Store.name)}.get(sort, (Store.featured.desc(), Store.name))
    stores = db.scalars(stmt.order_by(*order)).all()
    loc = get_location(request)
    if loc:
        covs = {s.id: logistics.delivery_quote(db, s, loc, precise=False) for s in stores}
        if delivery is True:  # con ubicacion, "con delivery" significa "que llegue hasta aca"
            stores = [s for s in stores if covs[s.id].delivers]
        if sort == "cerca":
            stores.sort(key=lambda s: (covs[s.id].distance is None, covs[s.id].distance or 0))
    categories = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse(request, "public/stores.html", ctx(request, stores=stores, categories=categories, q=q, delivery=delivery, featured=featured, category_id=category_id, sort=sort, store_open=store_open, deals=deals.max_discounts(db, [s.id for s in stores]), favorites=get_favorites(request)))


@router.get("/tienda/{slug}", response_class=HTMLResponse)
def store(slug: str, request: Request, db: Session = Depends(get_db)):
    s = db.scalar(select(Store).options(
        joinedload(Store.store_category), selectinload(Store.hours), selectinload(Store.sections), selectinload(Store.zones),
    ).where(Store.slug == slug, plans.visible_clause()))
    if not s: return not_found(request, "Ese comercio no existe o ya no está disponible.")
    products = db.scalars(
        select(Product).options(joinedload(Product.category), selectinload(Product.modifier_groups))
        .where(Product.store_id == s.id, Product.status == ProductStatus.ACTIVO)
        .order_by(Product.display_order, Product.name)
    ).all()
    sections = [sec for sec in s.sections if sec.active]
    categories = [] if sections else db.scalars(select(Category).where(Category.active).order_by(Category.display_order, Category.name)).all()
    menu = menu_groups(products, sections, categories)
    reviews = db.scalars(visible_reviews(s.id).where(Review.comment.is_not(None), Review.comment != "").limit(4)).all() if s.rating_count else []
    return templates.TemplateResponse(request, "public/store.html", ctx(request, store=s, menu=menu, products=products, reviews=reviews, store_open=store_open, favorites=get_favorites(request)))


def visible_reviews(store_id):
    return select(Review).options(joinedload(Review.order).joinedload(Order.customer)).where(Review.store_id == store_id, Review.hidden.is_(False)).order_by(Review.created_at.desc())


REVIEWS_PER_PAGE = 20


@router.get("/tienda/{slug}/opiniones", response_class=HTMLResponse)
def store_reviews(slug: str, request: Request, page: int = 1, db: Session = Depends(get_db)):
    s = db.scalar(select(Store).where(Store.slug == slug, plans.visible_clause()))
    if not s: return not_found(request, "Ese comercio no existe o ya no está disponible.")
    page = max(1, page)
    summary = rating_summary(db, Review.store_id == s.id, Review.hidden.is_(False))
    reviews = db.scalars(visible_reviews(s.id).offset((page - 1) * REVIEWS_PER_PAGE).limit(REVIEWS_PER_PAGE)).all()
    has_next = summary["count"] > page * REVIEWS_PER_PAGE
    return templates.TemplateResponse(request, "public/reviews.html", ctx(request, store=s, summary=summary, reviews=reviews, page=page, has_next=has_next))


@router.get("/categoria/{slug}", response_class=HTMLResponse)
def category(slug: str, request: Request, q: str | None = None, min_price: str | None = None, max_price: str | None = None, featured: bool | None = None, db: Session = Depends(get_db)):
    min_price, max_price = opt_decimal(min_price), opt_decimal(max_price)
    cat = db.scalar(select(Category).where(Category.slug == slug, Category.active.is_(True)))
    if not cat: return not_found(request, "Esa categoría no existe.")
    city = cities.for_request(request, db)
    stmt = select(Product).options(*PRODUCT_CARD).where(Product.category_id == cat.id, Product.status == ProductStatus.ACTIVO, plans.visible_product_clause(),
                                                       cities.product_clause(city.id if city else None))
    if q: stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%")))
    if min_price is not None: stmt = stmt.where(Product.price >= min_price)
    if max_price is not None: stmt = stmt.where(Product.price <= max_price)
    if featured is True: stmt = stmt.where(Product.featured.is_(True))
    products = db.scalars(stmt.order_by(Product.display_order, Product.name)).all()
    return templates.TemplateResponse(request, "public/category.html", ctx(request, category=cat, products=products, q=q, min_price=min_price, max_price=max_price, featured=featured))


@router.get("/buscar", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Busqueda inteligente (errores de tipeo, sinonimos y lenguaje natural): solo resultados reales."""
    q = q.strip()[:100]
    res = None
    if q:
        city = cities.for_request(request, db)
        cid = city.id if city else None
        res = search.run(db, q, cid, get_location(request))
        search.log(db, q, res, cid, 'web')
    stores = res.stores if res else []
    return templates.TemplateResponse(request, "public/search.html", ctx(request, q=q, products=res.products if res else [], stores=stores,
                                      categories=res.categories if res else [], understood=res.query.labels if res else [],
                                      corrected=res.query.corrected if res else None,
                                      suggestion=search.suggestion(db, q, cid) if res is not None and res.empty else None,
                                      store_open=store_open, deals=deals.max_discounts(db, [s.id for s in stores]), favorites=get_favorites(request)))


def checkout_account(request: Request, db: Session):
    """(cuenta, redireccion): con la cuenta obligatoria, sin sesion se manda a ingresar."""
    acct = accounts.from_session(request, db)
    if acct is None and accounts.required(db):
        return None, RedirectResponse("/ingresar?next=/checkout", 303)
    return acct, None


@router.get("/checkout", response_class=HTMLResponse)
def checkout(request: Request, db: Session = Depends(get_db)):
    cart = build_cart(db, request)
    acct, go = checkout_account(request, db)
    if go and cart["items"]: return go
    coupon_code = request.session.get("coupon", "")
    discount = Decimal("0"); coupon_error = None
    if coupon_code and cart["store"]:
        c, result = find_coupon(db, cart["store"].id, coupon_code, cart["subtotal"])
        if c: discount = result
        else: coupon_error = result; request.session["coupon"] = ""
    return templates.TemplateResponse(request, "public/checkout.html", ctx(request, **cart, mp_available=bool(cart["store"]) and mercadopago.available_for(db, cart["store"]), accepts_transfer=plans.accepts_transfer(cart["store"]), error=None, coupon_code=coupon_code if discount else "", coupon_error=coupon_error, discount=discount, grand_total=cart["total"] - discount, acct=acct,
                                      points=_points_offer(db, cart, discount, acct)))


def _points_offer(db: Session, cart: dict, discount: Decimal, acct) -> dict | None:
    """Puntos Trappi que puede usar (con envío y retirando); None si no hay puntos o no tiene cuenta."""
    if acct is None or not cart.get("store"):
        return None
    pickup = points_preview(db, cart, "retiro", discount, acct)
    delivery = points_preview(db, cart, "delivery", discount, acct) if cart["store"].delivery_enabled else pickup
    voucher = retention.active_voucher(db, acct.id)
    if not pickup["enabled"] and voucher is None:
        return None
    return {"enabled": pickup["enabled"], "balance": pickup["balance"], "delivery": delivery, "pickup": pickup,
            "voucher": voucher, "voucher_delivery": delivery["voucher_discount"], "voucher_pickup": pickup["voucher_discount"]}


@router.post("/checkout/coupon")
def checkout_coupon(request: Request, code: str = Form(""), db: Session = Depends(get_db)):
    cart = build_cart(db, request)
    if cart["store"]:
        c, _ = find_coupon(db, cart["store"].id, code, cart["subtotal"])
        request.session["coupon"] = code.strip().upper() if c else ""
    return RedirectResponse("/checkout", 303)


@router.post("/checkout")
def checkout_post(request: Request, db: Session = Depends(get_db), first_name: str = Form(...), last_name: str = Form(...), phone: str = Form(...), address: str = Form(""), reference: str = Form(""), delivery_method: str = Form(...), notes: str = Form(""), payment_method: str = Form("efectivo"), cash_with: str = Form(""), use_points: str = Form(""), voucher_choice: str = Form(""), use_voucher: str = Form("")):
    cart = build_cart(db, request)
    if not cart["items"]: return RedirectResponse("/", 303)
    acct, go = checkout_account(request, db)
    if go: return go
    ip = client_ip(request)
    if order_limiter.blocked(ip):
        return templates.TemplateResponse(request, "public/checkout.html", ctx(request, **cart, mp_available=bool(cart["store"]) and mercadopago.available_for(db, cart["store"]), accepts_transfer=plans.accepts_transfer(cart["store"]), coupon_code="", coupon_error=None, discount=Decimal("0"), grand_total=cart["total"], acct=acct, error="Hiciste muchos pedidos seguidos. Esperá unos minutos y probá de nuevo."), status_code=429)
    try:
        order = place_order(db, cart, get_location(request), first_name=first_name, last_name=last_name, phone=phone, delivery_method=delivery_method,
                            address=address, reference=reference, notes=notes, coupon_code=request.session.get("coupon", ""),
                            payment_method=payment_method, cash_with=form_float(cash_with), account=acct, origin="web", ip=ip, use_points=use_points == "1",
                            use_voucher=use_voucher == "1" or not voucher_choice)
    except CheckoutError as exc:
        return templates.TemplateResponse(request, "public/checkout.html", ctx(request, **cart, mp_available=bool(cart["store"]) and mercadopago.available_for(db, cart["store"]), accepts_transfer=plans.accepts_transfer(cart["store"]), coupon_code="", coupon_error=None, discount=Decimal("0"), grand_total=cart["total"], acct=acct, error=str(exc)), status_code=400)
    db.commit()
    order_limiter.hit(ip)
    token = order_token(order.id)
    request.session["cart"] = []; request.session["coupon"] = ""
    request.session["orders"] = (request.session.get("orders", []) + [[order.id, token]])[-10:]
    if order.payment_method == "mercadopago":
        return RedirectResponse(f"/pedido/{order.id}/pagar?t={token}", 303)
    return RedirectResponse(f"/pedido/{order.id}?t={token}", 303)


@router.get("/pedido/{order_id}", response_class=HTMLResponse)
def order_tracking(order_id: int, request: Request, t: str = "", db: Session = Depends(get_db)):
    if not valid_order_token(t, order_id): return not_found(request, "No encontramos ese pedido.")
    order = db.scalar(select(Order).options(joinedload(Order.store), selectinload(Order.items), selectinload(Order.events), joinedload(Order.customer), joinedload(Order.coupon), joinedload(Order.review)).where(Order.id == order_id))
    if not order: return not_found(request, "No encontramos ese pedido.")
    if request.query_params.get("pago") and payments.awaiting_online(order):
        # volvio de Mercado Pago: se pregunta el estado real (por si el aviso todavia no llego)
        try:
            mercadopago.reconcile(db, order); db.commit()
        except mercadopago.MPError:
            db.rollback()
    return templates.TemplateResponse(request, "public/order_success.html", ctx(request, order=order, to_local=to_local, payments=payments,
        mp_ready=payments.awaiting_online(order) and order.status.value == "PENDIENTE" and mercadopago.available_for(db, order.store), token=t,
        # el PIN solo en el navegador que hizo el pedido: el link de seguimiento lo puede tener el local
        show_pin=any(ref[0] == order.id for ref in request.session.get("orders", []))))


def public_base(request: Request) -> str:
    base = (settings.public_base_url or str(request.base_url)).rstrip("/")
    if settings.is_production and base.startswith("http://"):
        base = "https://" + base[len("http://"):]  # Render termina el HTTPS antes de la app: el request llega como http
    return base


@router.get("/pedido/{order_id}/pagar")
def order_pay(order_id: int, request: Request, t: str = "", db: Session = Depends(get_db)):
    """Manda a pagar a Mercado Pago (crea el link con el Split en el backend)."""
    if not valid_order_token(t, order_id): return not_found(request, "No encontramos ese pedido.")
    order = db.scalar(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(Order.id == order_id))
    back = f"/pedido/{order_id}?t={t}"
    if not order or not payments.awaiting_online(order) or order.status != OrderStatus.PENDIENTE:
        return RedirectResponse(back, 303)
    try:
        payment = mercadopago.create_preference(db, order, public_base(request), f"{public_base(request)}{back}&pago=1")
        db.commit()
    except mercadopago.MPError as exc:
        db.rollback()
        return templates.TemplateResponse(request, "public/404.html", ctx(request, message=f"No pudimos abrir Mercado Pago: {exc} Probá de nuevo en un momento."), status_code=502)
    return RedirectResponse(payment.checkout_url, 303)


@router.post("/pedido/{order_id}/review")
def order_review(order_id: int, request: Request, t: str = Form(""), rating: int = Form(...), comment: str = Form(""), db: Session = Depends(get_db)):
    back = RedirectResponse(f"/pedido/{order_id}?t={t}#resena", 303)
    order = db.get(Order, order_id) if valid_order_token(t, order_id) else None
    if not order or order.status != OrderStatus.ENTREGADO or order.review or not 1 <= rating <= 5:
        return back
    db.add(Review(order_id=order.id, store_id=order.store_id, rating=rating, comment=comment.strip()[:MAX_TEXT] or None))
    try:
        db.flush()
    except IntegrityError:  # doble envio del formulario: la primera reseña ya quedo guardada
        db.rollback()
        return back
    refresh_store_rating(db, order.store_id)
    db.commit()
    return back


@router.post("/tienda/{slug}/favorito")
def toggle_favorite(slug: str, request: Request, back: str = Form("/tiendas"), db: Session = Depends(get_db)):
    s = db.scalar(select(Store.id).where(Store.slug == slug))
    if s:
        favs = get_favorites(request)
        favs.symmetric_difference_update({s})
        request.session["favorites"] = list(favs)
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") and "://" not in back else "/tiendas", 303)


@router.post("/tareas/retencion")
def retention_cron(request: Request, db: Session = Depends(get_db)):
    """Para un cron externo (por ejemplo GitHub Actions una vez por dia): manda los recordatorios que correspondan.
    Necesita el header X-Cron-Token igual a RETENTION_CRON_TOKEN (sin esa variable no hace nada)."""
    import hmac
    token = request.headers.get("x-cron-token", "")
    if not settings.retention_cron_token or not hmac.compare_digest(token, settings.retention_cron_token):
        return JSONResponse({"ok": False}, status_code=403)
    r = retention.run(db, public_base(request))
    return {"ok": True, "recordatorios": r.candidates, "emails": r.emails, "push": r.pushes, "descuentos": r.vouchers}


@router.get("/novedades/baja", response_class=HTMLResponse)
def marketing_unsubscribe(request: Request, t: str = "", db: Session = Depends(get_db)):
    """Link de los emails de novedades: deja de recibirlas sin tener que entrar."""
    from ..models import ClientAccount
    aid = retention.account_from_token(t)
    acct = db.get(ClientAccount, aid) if aid else None
    if acct is None:
        return not_found(request, "Ese link no es válido.")
    acct.marketing_opt_in = False
    db.commit()
    return templates.TemplateResponse(request, "public/message.html", ctx(request, title="Listo", message="No te vamos a mandar más novedades ni promociones. Lo podés volver a prender cuando quieras desde Mi cuenta."))


@router.get("/favoritos", response_class=HTMLResponse)
def favorites_page(request: Request, db: Session = Depends(get_db)):
    favs = get_favorites(request)
    stores = db.scalars(select(Store).options(*STORE_CARD).where(Store.id.in_(favs))).all() if favs else []
    return templates.TemplateResponse(request, "public/favorites.html", ctx(request, stores=stores, store_open=store_open, deals=deals.max_discounts(db, [s.id for s in stores]), favorites=favs))


@router.get("/mis-pedidos", response_class=HTMLResponse)
def my_orders(request: Request, db: Session = Depends(get_db)):
    tokens = {int(i): t for i, t in request.session.get("orders", [])}
    acct = accounts.from_session(request, db)
    if acct:  # con cuenta: tambien los pedidos hechos desde otros dispositivos
        for oid in db.scalars(select(Order.id).where(Order.account_id == acct.id).order_by(Order.id.desc()).limit(50)):
            tokens.setdefault(oid, order_token(oid))
    orders = db.scalars(select(Order).options(joinedload(Order.store), selectinload(Order.items), joinedload(Order.review)).where(Order.id.in_(tokens.keys())).order_by(Order.created_at.desc())).all() if tokens else []
    return templates.TemplateResponse(request, "public/my_orders.html", ctx(request, orders=orders, tokens=tokens))


@router.post("/pedido/{order_id}/repetir")
def order_repeat(order_id: int, request: Request, t: str = Form(""), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).options(selectinload(Order.items), joinedload(Order.store)).where(Order.id == order_id)) if valid_order_token(t, order_id) else None
    if not order: return not_found(request, "No encontramos ese pedido.")
    product_ids = {it.product_id for it in order.items}
    available = set(db.scalars(
        select(Product.id).join(Store, Store.id == Product.store_id)
        .where(Product.id.in_(product_ids), Product.status == ProductStatus.ACTIVO, plans.visible_clause())
    )) if product_ids else set()
    cart = [{"product_id": it.product_id, "quantity": it.quantity} for it in order.items if it.product_id in available]
    if not cart: return RedirectResponse(f"/tienda/{order.store.slug}", 303)
    save_cart(request, cart)
    return RedirectResponse("/checkout", 303)


@router.get("/asistente", response_class=HTMLResponse)
def assistant_page(request: Request, db: Session = Depends(get_db)):
    from .ai_api import ai_status
    status = ai_status(db)
    if not status["available"]:
        return not_found(request, "El asistente no está disponible en este momento.")
    return templates.TemplateResponse(request, "public/assistant.html", ctx(request, welcome=status["welcome"], acct=accounts.from_session(request, db)))


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nDisallow: /admin\nDisallow: /api\nDisallow: /checkout\nDisallow: /pedido\nSitemap: {request.base_url}sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    store_slugs = db.scalars(select(Store.slug).where(plans.visible_clause())).all()
    category_slugs = db.scalars(select(Category.slug).where(Category.active)).all()
    urls = [f"{base}/", f"{base}/tiendas", f"{base}/terminos", f"{base}/privacidad", f"{base}/eliminar-cuenta"] + [f"{base}/tienda/{slug}" for slug in store_slugs] + [f"{base}/categoria/{slug}" for slug in category_slugs]
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', media_type="application/xml")
