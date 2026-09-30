from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from ..db import get_db
from ..models import ModifierGroup, Product, ProductStatus
from ..services.cart import build_cart, get_cart, save_cart
from ..services.store_hours import is_open

router = APIRouter()


def cart_payload(db, request):
    data = build_cart(db, request)
    return {
        "items": [{"product_id": x["product"].id, "name": x["product"].name, "price": float(x["unit_price"]), "quantity": x["quantity"], "line_total": float(x["line_total"]), "modifiers_text": x["modifiers_text"], "line_key": x["line_key"]} for x in data["items"]],
        "store": {"id": data["store"].id, "name": data["store"].name} if data["store"] else None,
        "subtotal": float(data["subtotal"]), "shipping": float(data["shipping"]), "total": float(data["total"]), "count": data["count"],
    }


def _validate_modifiers(product, option_ids: list[int]):
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


@router.post("/cart/add")
async def add(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        pid = int(data.get("product_id", 0)); qty = max(1, int(data.get("quantity", 1)))
        option_ids = [int(x) for x in data.get("modifiers", []) if str(x).isdigit()]
        product = db.scalar(select(Product).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == pid, Product.status == ProductStatus.ACTIVO))
        if not product or not product.store or product.store.status.value == "INACTIVA":
            return JSONResponse({"ok": False, "error": "Producto no disponible."}, status_code=404)
        if not is_open(product.store):
            return JSONResponse({"ok": False, "error": "Este local está cerrado por ahora."}, status_code=409)
        error = _validate_modifiers(product, option_ids)
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=422)
        valid_ids = {o.id for g in product.modifier_groups for o in g.options if o.active}
        option_ids = sorted(set(option_ids) & valid_ids)
        cart = get_cart(request)
        current_store = None
        if cart:
            first = db.scalar(select(Product).where(Product.id == int(cart[0]["product_id"])))
            current_store = first.store_id if first else None
        if current_store and current_store != product.store_id:
            return JSONResponse({"ok": False, "code": "DIFFERENT_STORE", "message": "Tu carrito contiene productos de otra tienda."}, status_code=409)
        existing = next((x for x in cart if int(x["product_id"]) == pid and sorted(int(i) for i in x.get("modifiers", [])) == option_ids), None)
        if existing: existing["quantity"] += qty
        else: cart.append({"product_id": pid, "quantity": qty, "modifiers": option_ids})
        save_cart(request, cart)
        return JSONResponse({"ok": True, **cart_payload(db, request)})
    except SQLAlchemyError:
        return JSONResponse({"ok": False, "error": "No se pudo agregar el producto: hay un problema con la base de datos. Probablemente falte aplicar una migración reciente en el servidor."}, status_code=500)


@router.post("/cart/update")
async def update(request: Request, db: Session = Depends(get_db)):
    data = await request.json(); pid = int(data.get("product_id", 0)); qty = int(data.get("quantity", 0))
    line_key = data.get("line_key")
    cart = get_cart(request)
    def key(x): return f"{x['product_id']}:{'-'.join(str(i) for i in sorted(x.get('modifiers', [])))}"
    if line_key:
        if qty <= 0: cart = [x for x in cart if key(x) != line_key]
        else:
            for x in cart:
                if key(x) == line_key: x["quantity"] = qty
    else:
        if qty <= 0: cart = [x for x in cart if int(x["product_id"]) != pid]
        else:
            for x in cart:
                if int(x["product_id"]) == pid: x["quantity"] = qty
    save_cart(request, cart)
    return {"ok": True, **cart_payload(db, request)}


@router.post("/cart/clear")
async def clear(request: Request, db: Session = Depends(get_db)):
    save_cart(request, [])
    return {"ok": True, **cart_payload(db, request)}


@router.get("/cart")
async def get_cart_endpoint(request: Request, db: Session = Depends(get_db)):
    return cart_payload(db, request)


@router.get("/products/{product_id}/modifiers")
def product_modifiers(product_id: int, db: Session = Depends(get_db)):
    product = db.scalar(select(Product).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == product_id, Product.status == ProductStatus.ACTIVO))
    if not product:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "product_id": product.id, "name": product.name, "base_price": float(product.price),
        "groups": [
            {"id": g.id, "name": g.name, "required": g.required, "min_select": g.min_select, "max_select": g.max_select,
             "options": [{"id": o.id, "name": o.name, "price_extra": float(o.price_extra)} for o in g.options if o.active]}
            for g in product.modifier_groups
        ],
    }
