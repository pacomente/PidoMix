from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import ModifierGroup, Product, ProductStatus, StoreStatus


def get_cart(request):
    return request.session.get("cart", [])


def save_cart(request, cart):
    request.session["cart"] = cart
    request.session.modified = True


def modifiers_summary(product, option_ids):
    """Lista ordenada de (ModifierOption, ) elegidas para un producto, validas para ese producto."""
    valid_ids = {o.id for g in product.modifier_groups for o in g.options if o.active}
    chosen = [o for g in product.modifier_groups for o in g.options if o.id in set(option_ids) and o.id in valid_ids]
    return chosen


def build_cart(db: Session, request):
    cart = get_cart(request)
    if not cart:
        return {"items": [], "store": None, "subtotal": Decimal("0"), "shipping": Decimal("0"), "total": Decimal("0"), "count": 0}
    ids = [int(x["product_id"]) for x in cart]
    products = db.scalars(
        select(Product).options(joinedload(Product.store), selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id.in_(ids))
    ).unique().all()
    by_id = {p.id: p for p in products}
    items, clean = [], []
    store = None
    subtotal = Decimal("0")
    for line in cart:
        try:
            p = by_id.get(int(line["product_id"]))
            qty = max(1, int(line.get("quantity", 1)))
            option_ids = [int(x) for x in line.get("modifiers", [])]
            # el local puede desactivar el producto, o el producto puede haber quedado
            # huerfano (sin tienda valida) por datos viejos de un reseteo de base anterior;
            # en cualquiera de esos casos se descarta la linea en vez de romper todo el carrito.
            if not p or p.status != ProductStatus.ACTIVO or not p.store or p.store.status == StoreStatus.INACTIVA:
                continue
            if store is None:
                store = p.store
            if p.store_id != store.id:
                continue
            chosen = modifiers_summary(p, option_ids)
            extra = sum((Decimal(o.price_extra) for o in chosen), Decimal("0"))
            unit_price = Decimal(p.price) + extra
            line_total = unit_price * qty
        except (TypeError, ValueError, KeyError, AttributeError):
            continue  # linea de carrito invalida/vieja: se descarta en silencio, no rompe el resto
        subtotal += line_total
        clean.append({"product_id": p.id, "quantity": qty, "modifiers": [o.id for o in chosen]})
        items.append({
            "product": p, "quantity": qty, "unit_price": unit_price, "line_total": line_total,
            "modifiers": chosen, "modifiers_text": ", ".join(o.name for o in chosen),
            "line_key": f"{p.id}:{'-'.join(str(o.id) for o in sorted(chosen, key=lambda o: o.id))}",
        })
    if clean != cart:
        save_cart(request, clean)
    shipping = Decimal(store.delivery_cost or 0) if store and store.delivery_enabled else Decimal("0")
    total = subtotal + shipping
    return {"items": items, "store": store, "subtotal": subtotal, "shipping": shipping, "total": total, "count": sum(x["quantity"] for x in clean)}
