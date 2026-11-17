from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import ModifierGroup, Product, ProductStatus, Store, StoreStatus
from . import logistics, plans, weight
from .geo import parse_location


def get_cart(request):
    return request.session.get("cart", [])


def save_cart(request, cart):
    # En Starlette la sesion es un dict comun: basta con escribir la clave.
    # (No existe un flag ".modified" como en Django; asignarlo rompia esto cada vez
    # que se guardaba el carrito.)
    request.session["cart"] = cart


def line_key(product_id, modifier_ids, grams=None) -> str:
    """Identifica una linea del carrito: mismo producto con distintos extras (o distinto peso) son lineas distintas."""
    key = f"{product_id}:{'-'.join(str(i) for i in sorted(int(x) for x in modifier_ids))}"
    return f"{key}@{int(grams)}" if grams else key


def modifiers_summary(product, option_ids):
    """Opciones (ModifierOption) elegidas para un producto, solo las activas y validas para ese producto."""
    # dentro de cada grupo, en el orden en que los eligio el cliente (los gustos de helado se sirven asi)
    pos: dict[int, int] = {}
    for i, x in enumerate(option_ids):
        pos.setdefault(int(x), i)
    return [o for g in product.modifier_groups
            for o in sorted((o for o in g.options if o.active and o.id in pos), key=lambda o: pos[o.id])]


def validate_modifiers(product, option_ids: list[int]):
    """Chequea reglas de cada grupo (requerido, min/max). Devuelve None si esta OK o un mensaje de error."""
    chosen = set(option_ids)
    for group in product.modifier_groups:
        group_option_ids = {o.id for o in group.options if o.active}
        picked = chosen & group_option_ids
        if group.required and len(picked) < max(1, group.min_select):
            return f"Elegí una opción en \u201c{group.name}\u201d."
        if group.min_select and len(picked) < group.min_select:
            return f"\u201c{group.name}\u201d requiere al menos {group.min_select} opción(es)."
        if group.max_select and len(picked) > group.max_select:
            return f"\u201c{group.name}\u201d permite hasta {group.max_select} opción(es)."
    return None


def price_lines(db: Session, lines: list, loc: dict | None = None, precise: bool = True) -> dict:
    """Valida y calcula un carrito a partir de lineas {product_id, quantity, modifiers}.

    Lo usan la web (lineas guardadas en la sesion) y la app movil (lineas que manda el telefono).
    Las lineas invalidas, de productos inactivos o de otro local se descartan sin romper el resto.
    """
    empty = {"items": [], "lines": [], "store": None, "subtotal": Decimal("0"), "shipping": Decimal("0"), "total": Decimal("0"), "count": 0, "coverage": None,
             "promo_discount": Decimal("0"), "promos": []}
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
            if p.stock is not None and p.stock <= 0:  # agotado (por ejemplo desde comandas): no se puede pedir
                continue
            if store is None:
                store = p.store
            if p.store_id != store.id:
                continue
            chosen = modifiers_summary(p, option_ids)
            extra = sum((Decimal(o.price_extra) for o in chosen), Decimal("0"))
            grams = weight.clean_grams(p, line.get("grams")) if p.sold_by_weight else None
            # por peso: el precio del producto (y de los extras) es por kg y se cobra lo que pidio
            unit_price = weight.price_for(Decimal(p.price) + extra, grams) if grams else Decimal(p.price) + extra
            line_total = unit_price * qty
        except (TypeError, ValueError, KeyError, AttributeError):
            continue  # linea de carrito invalida/vieja: se descarta en silencio, no rompe el resto
        subtotal += line_total
        line_out = {"product_id": p.id, "quantity": qty, "modifiers": [o.id for o in chosen]}
        if grams:
            line_out["grams"] = grams
        clean.append(line_out)
        text = ", ".join([weight.label(grams)] * bool(grams) + [o.name for o in chosen])
        items.append({
            "product": p, "quantity": qty, "unit_price": unit_price, "line_total": line_total,
            "modifiers": chosen, "modifiers_text": text, "grams": grams, "weight_label": weight.label(grams),
            "per_kg": (Decimal(p.price) + extra) if grams else None,
            "line_key": line_key(p.id, (o.id for o in chosen), grams),
        })
    # con zonas de entrega el envio depende de donde esta el cliente
    cov = logistics.delivery_quote(db, store, loc, precise=precise) if store else None
    cov = logistics.apply_free_shipping(store, cov, subtotal) if store else None  # envío gratis desde un monto (cadetería propia)
    shipping = (cov.cost if cov.cost is not None else (cov.from_cost or Decimal("0"))) if cov and cov.delivers else Decimal("0")
    free_from = logistics.free_shipping_from(store) if store else None
    free = {"from": free_from, "missing": max(Decimal("0"), free_from - subtotal)} if free_from is not None and cov is not None and cov.delivers else None
    # promos de la caja que el local marco "tambien en la app" (2x1, combos, happy hour): las calcula el servidor
    from . import online_promos
    promo_discount, promos = online_promos.for_cart(db, store, items) if store else (Decimal("0"), [])
    promo_discount = min(promo_discount, subtotal)
    return {"items": items, "lines": clean, "store": store, "subtotal": subtotal, "shipping": shipping, "total": subtotal + shipping,
            "count": sum(x["quantity"] for x in clean), "coverage": cov, "free_shipping": free, "promo_discount": promo_discount, "promos": promos}


def build_cart(db: Session, request):
    """Carrito de la web: las lineas y la ubicacion viven en la sesion del navegador."""
    cart = get_cart(request)
    data = price_lines(db, cart, parse_location(request.session.get("loc") or {}))
    if data["lines"] != cart:
        save_cart(request, data["lines"])
    return data
