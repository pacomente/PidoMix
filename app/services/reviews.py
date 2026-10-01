"""Reseñas de pedidos: promedio de cada local, resumen por estrellas y nombre publico."""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Review, Store

MAX_TEXT = 500


def refresh_store_rating(db: Session, store_id: int) -> None:
    """Recalcula el promedio desde las reseñas visibles (no se acumula a mano: asi
    ocultar o volver a mostrar una reseña deja siempre el numero correcto)."""
    db.flush()  # la sesion no hace autoflush: el agregado tiene que ver los cambios pendientes
    count, avg = db.execute(
        select(func.count(Review.id), func.avg(Review.rating)).where(Review.store_id == store_id, Review.hidden.is_(False))
    ).one()
    store = db.get(Store, store_id)
    store.rating_count = count or 0
    store.rating_avg = Decimal(str(avg or 0)).quantize(Decimal("0.01"))


def rating_summary(db: Session, *where) -> dict:
    """Cantidad, promedio y distribucion 5..1 de las reseñas que cumplen `where`."""
    rows = dict(db.execute(select(Review.rating, func.count(Review.id)).where(*where).group_by(Review.rating)).all())
    total = sum(rows.values())
    avg = sum(r * n for r, n in rows.items()) / total if total else 0
    bars = [{"stars": s, "count": rows.get(s, 0), "pct": round(rows.get(s, 0) * 100 / total) if total else 0} for s in range(5, 0, -1)]
    return {"count": total, "avg": avg, "bars": bars}


def public_name(customer) -> str:
    """'Ana P.': nombre y la inicial del apellido, nunca el telefono ni el apellido completo."""
    if not customer or not customer.first_name:
        return "Cliente"
    initial = f" {customer.last_name.strip()[:1].upper()}." if customer.last_name and customer.last_name.strip() else ""
    return customer.first_name.strip().split()[0].capitalize() + initial
