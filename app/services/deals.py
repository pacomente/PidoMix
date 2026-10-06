"""Mayor descuento vigente de cada comercio, para la etiqueta "Hasta 30% OFF"."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, ProductStatus


def max_discounts(db: Session, store_ids) -> dict[int, int]:
    """{store_id: porcentaje} con los productos activos que tienen precio anterior mayor al actual."""
    ids = list(store_ids)
    best: dict[int, int] = {}
    if not ids:
        return best
    rows = db.execute(select(Product.store_id, Product.price, Product.previous_price).where(
        Product.store_id.in_(ids), Product.status == ProductStatus.ACTIVO, Product.deleted.is_(False),
        Product.previous_price.is_not(None), Product.previous_price > Product.price)).all()
    for sid, price, prev in rows:
        pct = int(round((1 - float(price) / float(prev)) * 100))
        if pct > best.get(sid, 0):
            best[sid] = pct
    return best
