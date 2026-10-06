from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse as _JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload
from ..db import get_db
from ..services import plans
from ..models import ModifierGroup, Product, ProductStatus, StoreStatus
from ..services.cart import build_cart, get_cart, line_key, save_cart, validate_modifiers
from ..services.store_hours import is_open
from ..services.geo import parse_location


class JSONResponse(_JSONResponse):
    """JSONResponse sin cache: las respuestas del carrito nunca deben quedar guardadas por el navegador."""
    def init_headers(self, headers):
        super().init_headers(headers)
        self.raw_headers.append((b"cache-control", b"no-store"))

router = APIRouter(default_response_class=JSONResponse)


async def json_body(request: Request) -> dict:
    """Lee el JSON en el event loop; los endpoints son sincronos (corren en el threadpool)
    para que las consultas a la base no bloqueen al resto de los requests."""
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def cart_payload(db, request):
    data = build_cart(db, request)
    return {
        "items": [{"product_id": x["product"].id, "name": x["product"].name, "price": float(x["unit_price"]), "quantity": x["quantity"], "line_total": float(x["line_total"]), "modifiers_text": x["modifiers_text"], "line_key": x["line_key"]} for x in data["items"]],
        "store": {"id": data["store"].id, "name": data["store"].name} if data["store"] else None,
        "subtotal": float(data["subtotal"]), "shipping": float(data["shipping"]), "total": float(data["total"]), "count": data["count"],
    }


_validate_modifiers = validate_modifiers


@router.post("/cart/add")
def add(request: Request, data: dict = Depends(json_body), db: Session = Depends(get_db)):
    try:
        pid = int(data.get("product_id", 0)); qty = max(1, int(data.get("quantity", 1)))
        option_ids = [int(x) for x in data.get("modifiers", []) if str(x).isdigit()]
        product = db.scalar(select(Product).options(joinedload(Product.store), selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == pid, Product.status == ProductStatus.ACTIVO))
        if not product or not plans.is_visible(product.store):
            return JSONResponse({"ok": False, "error": "Producto no disponible."}, status_code=404)
        if not is_open(product.store):
            return JSONResponse({"ok": False, "error": "Este local está cerrado por ahora."}, status_code=409)
        error = _validate_modifiers(product, option_ids)
        if error:
            return JSONResponse({"ok": False, "error": error}, status_code=422)
        valid_ids = {o.id for g in product.modifier_groups for o in g.options if o.active}
        option_ids = sorted(set(option_ids) & valid_ids)
        cart = get_cart(request)
        current_store = db.scalar(select(Product.store_id).where(Product.id == int(cart[0]["product_id"]))) if cart else None
        if current_store and current_store != product.store_id:
            return JSONResponse({"ok": False, "code": "DIFFERENT_STORE", "message": "Tu carrito contiene productos de otra tienda."}, status_code=409)
        key = line_key(pid, option_ids)
        existing = next((x for x in cart if line_key(x["product_id"], x.get("modifiers", [])) == key), None)
        if existing: existing["quantity"] += qty
        else: cart.append({"product_id": pid, "quantity": qty, "modifiers": option_ids})
        save_cart(request, cart)
        return JSONResponse({"ok": True, **cart_payload(db, request)})
    except SQLAlchemyError:
        return JSONResponse({"ok": False, "error": "No se pudo agregar el producto: hay un problema con la base de datos. Probablemente falte aplicar una migración reciente en el servidor."}, status_code=500)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"No se pudo agregar el producto ({type(exc).__name__}). Contactá al soporte con este detalle."}, status_code=500)


@router.post("/cart/update")
def update(request: Request, data: dict = Depends(json_body), db: Session = Depends(get_db)):
    try:
        pid = int(data.get("product_id", 0)); qty = int(data.get("quantity", 0))
        cart = get_cart(request)
        target = data.get("line_key")
        matches = (lambda x: line_key(x["product_id"], x.get("modifiers", [])) == target) if target else (lambda x: int(x["product_id"]) == pid)
        if qty <= 0:
            cart = [x for x in cart if not matches(x)]
        else:
            for x in cart:
                if matches(x): x["quantity"] = qty
        save_cart(request, cart)
        return {"ok": True, **cart_payload(db, request)}
    except SQLAlchemyError:
        return JSONResponse({"ok": False, "error": "No se pudo actualizar el pedido: hay un problema con la base de datos."}, status_code=500)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"No se pudo actualizar el pedido ({type(exc).__name__})."}, status_code=500)


@router.post("/cart/clear")
def clear(request: Request, db: Session = Depends(get_db)):
    save_cart(request, [])
    return {"ok": True, **cart_payload(db, request)}


@router.get("/cart")
def get_cart_endpoint(request: Request, db: Session = Depends(get_db)):
    return cart_payload(db, request)


@router.post("/ubicacion")
def set_location(request: Request, data: dict = Depends(json_body)):
    """Guarda en la sesion donde esta el cliente (no se persiste en la base hasta que hace un pedido)."""
    loc = parse_location(data)
    if not loc:
        return JSONResponse({"ok": False, "error": "No pudimos leer esa ubicación."}, status_code=422)
    request.session["loc"] = loc
    from ..db import SessionLocal
    from ..services import cities
    with SessionLocal() as db:
        found = cities.detect(db, loc["lat"], loc["lng"])
    if found:
        request.session["city"] = found.slug  # la ubicacion manda: si se mudo de ciudad, ve la nueva
    return {"ok": True, "location": loc, "city": found.slug if found else None}


@router.delete("/ubicacion")
def clear_location(request: Request):
    request.session.pop("loc", None)
    return {"ok": True}


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
