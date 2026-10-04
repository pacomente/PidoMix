from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import ModifierGroup, Product, ProductStatus, Store, StoreStatus
from . import plans
from .geo import coverage, parse_location


def get_cart(request):
    return request.session.get("cart", [])


def save_cart(request, cart):
    # En Starlette la sesion es un dict comun: basta con escribir la clave.
    # (No existe un flag ".modified" como en Django; asignarlo rompia esto cada vez
    # que se guardaba el carrito.)
    request.session["cart"] = cart


def line_key(product_id, modifier_ids) -> str:
    """Identifica una linea del carrito: mismo producto con distintos extras son lineas distintas."""
    return f"{product_id}:{'-'.join(str(i) for i in sorted(int(x) for x in modifier_ids))}"


def modifiers_summary(product, option_ids):
    """Opciones (ModifierOption) elegidas para un producto, solo las activas y validas para ese producto."""
    wanted = set(option_ids)
    return [o for g in product.modifier_groups for o in g.options if o.active and o.id in wanted]


def price_lines(db: Session, lines: list, loc: dict | None = None) -> dict:
    """Valida y calcula un carrito a partir de lineas {product_id, quantity, modifiers}.

    Lo usan la web (lineas guardadas en la sesion) y la app movil (lineas que manda el telefono).
    Las lineas invalidas, de productos inactivos o de otro local se descartan sin romper el resto.
    """
    empty = {"items": [], "lines": [], "store": None, "subtotal": Decimal("0"), "shipping": Decimal("0"), "total": Decimal("0"), "count": 0, "coverage": None}
    if not lines:
        return empty
    try:
        ids = {int(x["product_id"]) for x in lines}
    except (TypeError, ValueError, KeyError):
        return empty
    products = db.scalars(
        select(Product).options(joinedload(Product.store).selectinload(Store.zones), selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id.in_(ids))
    ).unique().all()
    by_id = {p.id: p for p in products}
    items, clean = [], []
    store = None
    subtotal = Decimal("0")
    for line in lines:
        try:
            p = by_id.get(int(line["product_id"]))
            qty = min(99, max(1, int(line.get("quantity", 1))))
            option_ids = [int(x) for x in line.get("modifiers", [])]
            # el local puede desactivar el producto, o el producto puede haber quedado
            # huerfano (sin tienda valida) por datos viejos de un reseteo de base anterior;
            # en cualquiera de esos casos se descarta la linea en vez de romper todo el carrito.
            if not p or p.status != ProductStatus.ACTIVO or not plans.is_visible(p.store):
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
            "line_key": line_key(p.id, (o.id for o in chosen)),
        })
    # con zonas de entrega el envio depende de donde esta el cliente
    cov = coverage(store, loc) if store else None
    shipping = (cov.cost if cov.cost is not None else (cov.from_cost or Decimal("0"))) if cov and cov.delivers else Decimal("0")
    return {"items": items, "lines": clean, "store": store, "subtotal": subtotal, "shipping": shipping, "total": subtotal + shipping, "count": sum(x["quantity"] for x in clean), "coverage": cov}


def build_cart(db: Session, request):
    """Carrito de la web: las lineas y la ubicacion viven en la sesion del navegador."""
    cart = get_cart(request)
    data = price_lines(db, cart, parse_location(request.session.get("loc") or {}))
    if data["lines"] != cart:
        save_cart(request, data["lines"])
    return data
