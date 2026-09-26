from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Product, ProductStatus
from ..services.cart import build_cart, get_cart, save_cart

router = APIRouter()


def cart_payload(db, request):
    data = build_cart(db, request)
    return {
        "items": [{"product_id": x["product"].id, "name": x["product"].name, "price": float(x["unit_price"]), "quantity": x["quantity"], "line_total": float(x["line_total"])} for x in data["items"]],
        "store": {"id": data["store"].id, "name": data["store"].name} if data["store"] else None,
        "subtotal": float(data["subtotal"]), "shipping": float(data["shipping"]), "total": float(data["total"]), "count": data["count"],
    }


@router.post("/cart/add")
async def add(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    pid = int(data.get("product_id", 0)); qty = max(1, int(data.get("quantity", 1)))
    product = db.scalar(select(Product).where(Product.id == pid, Product.status == ProductStatus.ACTIVO))
    if not product or not product.store or product.store.status.value != "ACTIVA":
        return JSONResponse({"ok": False, "error": "Producto no disponible."}, status_code=404)
    cart = get_cart(request)
    current_store = None
    if cart:
        first = db.scalar(select(Product).where(Product.id == int(cart[0]["product_id"])))
        current_store = first.store_id if first else None
    if current_store and current_store != product.store_id:
        return JSONResponse({"ok": False, "code": "DIFFERENT_STORE", "message": "Tu carrito contiene productos de otra tienda."}, status_code=409)
    existing = next((x for x in cart if int(x["product_id"]) == pid), None)
    if existing: existing["quantity"] += qty
    else: cart.append({"product_id": pid, "quantity": qty})
    save_cart(request, cart)
    return JSONResponse({"ok": True, **cart_payload(db, request)})


@router.post("/cart/update")
async def update(request: Request, db: Session = Depends(get_db)):
    data = await request.json(); pid = int(data.get("product_id", 0)); qty = int(data.get("quantity", 0))
    cart = get_cart(request)
    if qty <= 0:
        cart = [x for x in cart if int(x["product_id"]) != pid]
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
