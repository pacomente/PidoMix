from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import Product, ProductStatus, Store, StoreStatus


def get_cart(request):
    return request.session.get("cart", [])


def save_cart(request, cart):
    request.session["cart"] = cart
    request.session.modified = True


def build_cart(db: Session, request):
    cart = get_cart(request)
    if not cart:
        return {"items": [], "store": None, "subtotal": Decimal("0"), "shipping": Decimal("0"), "total": Decimal("0"), "count": 0}
    ids = [int(x["product_id"]) for x in cart]
    products = db.scalars(select(Product).where(Product.id.in_(ids))).all()
    by_id = {p.id: p for p in products}
    items = []
    store = None
    subtotal = Decimal("0")
    clean = []
    for line in cart:
        p = by_id.get(int(line["product_id"]))
        qty = max(1, int(line.get("quantity", 1)))
        if not p or p.status != ProductStatus.ACTIVO or p.store.status != StoreStatus.ACTIVA:
            continue
        if store is None:
            store = p.store
        if p.store_id != store.id:
            continue
        line_total = Decimal(p.price) * qty
        subtotal += line_total
        clean.append({"product_id": p.id, "quantity": qty})
        items.append({"product": p, "quantity": qty, "unit_price": Decimal(p.price), "line_total": line_total})
    if clean != cart:
        save_cart(request, clean)
    shipping = Decimal(store.delivery_cost or 0) if store and store.delivery_enabled else Decimal("0")
    total = subtotal + shipping
    return {"items": items, "store": store, "subtotal": subtotal, "shipping": shipping, "total": total, "count": sum(x["quantity"] for x in clean)}
