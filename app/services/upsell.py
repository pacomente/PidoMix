"""Para vender más sin molestar: "Pedí de nuevo", "¿Le sumás algo?" y "Lo más pedido".

Todo se calcula en el servidor con los pedidos reales del local; el navegador solo muestra.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import ModifierGroup, Order, OrderItem, OrderStatus, Product, ProductStatus
from . import plans
from .cart import validate_modifiers

POPULAR_DAYS = 60
REPEAT_DAYS = 90


def _sales(db: Session, store_id: int, days: int = POPULAR_DAYS) -> dict[int, int]:
    """Unidades vendidas por producto en los pedidos entregados de los últimos días."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.execute(select(OrderItem.product_id, func.sum(OrderItem.quantity)).join(Order, Order.id == OrderItem.order_id)
                      .where(Order.store_id == store_id, Order.status == OrderStatus.ENTREGADO, Order.created_at >= since)
                      .group_by(OrderItem.product_id)).all()
    return {pid: int(n or 0) for pid, n in rows}


def _orderable(p: Product) -> bool:
    return p.status == ProductStatus.ACTIVO and not (p.stock is not None and p.stock <= 0)


def popular(db: Session, store_id: int, products: list[Product], limit: int = 4, min_sold: int = 2) -> list[Product]:
    """«Lo más pedido» del local (entre los productos que se muestran en su menú)."""
    sold = _sales(db, store_id)
    ranked = sorted((p for p in products if sold.get(p.id, 0) >= min_sold and _orderable(p)), key=lambda p: (-sold[p.id], p.name))
    return ranked[:limit]


def _simple(p: Product) -> bool:
    """Se agrega con un toque: sin opciones obligatorias."""
    return not any(g.required or g.min_select > 0 for g in p.modifier_groups)


def suggestions(db: Session, store, cart_items: list[dict], limit: int = 3) -> list[Product]:
    """«¿Le sumás algo?»: lo que más se vende del local y no está en el pedido, de otras secciones primero
    (si pidió hamburguesas, una bebida o un postre). Solo productos que se agregan con un toque."""
    if store is None or not cart_items:
        return []
    in_cart = {x['product'].id for x in cart_items}
    from . import recommendations
    together = [p for p in recommendations.bought_together(db, store.id, list(in_cart), limit=limit) if _orderable(p) and _simple(p)]  # lo que se pide junto
    groups_in_cart = {(x['product'].section_id, x['product'].category_id) for x in cart_items}
    subtotal = sum((x['line_total'] for x in cart_items), Decimal('0'))
    rows = db.scalars(select(Product).options(selectinload(Product.modifier_groups))
                      .where(Product.store_id == store.id, Product.status == ProductStatus.ACTIVO, Product.id.not_in(in_cart))).all()
    sold = _sales(db, store.id)
    cap = max(Decimal('1500'), subtotal * Decimal('0.6'))  # algo chico al lado de lo que ya pidió
    pool = [p for p in rows if _orderable(p) and _simple(p) and Decimal(p.price) <= cap]
    pool.sort(key=lambda p: ((p.section_id, p.category_id) in groups_in_cart, -sold.get(p.id, 0), Decimal(p.price)))
    seen = {p.id for p in together}
    return (together + [p for p in pool if p.id not in seen])[:limit]


def suggestion_json(p: Product) -> dict:
    from .images import cdn
    return {'id': p.id, 'name': p.name, 'price': float(p.price), 'image': cdn(p.image_url, 'product') if p.image_url else None}


# ---------- pedí de nuevo ----------

def _options_by_name(p: Product, text: str | None) -> list[int] | None:
    """Las opciones del pedido viejo (se guardó el texto "Cheddar, Sin cebolla") por nombre; None si alguna ya no está."""
    names = [n.strip() for n in (text or '').split(',') if n.strip()]
    if not names:
        return []
    opts = {o.name.strip().lower(): o.id for g in p.modifier_groups for o in g.options if o.active}
    ids = [opts.get(n.lower()) for n in names]
    return None if any(i is None for i in ids) else ids


def repeat_lines(db: Session, order: Order) -> tuple[list[dict], int]:
    """Las líneas del carrito para repetir un pedido y cuántos productos quedaron afuera (sin stock, sin opciones que ya no existen...)."""
    ids = {it.product_id for it in order.items}
    products = {p.id: p for p in db.scalars(select(Product).options(joinedload(Product.store), selectinload(Product.modifier_groups).selectinload(ModifierGroup.options))
                                                 .where(Product.id.in_(ids))).unique()} if ids else {}
    lines, skipped = [], 0
    for it in order.items:
        p = products.get(it.product_id)
        mods = _options_by_name(p, it.modifiers_text) if p else None
        if p is None or not _orderable(p) or not plans.is_visible(p.store) or p.store_id != order.store_id or mods is None or validate_modifiers(p, mods):
            skipped += 1
            continue
        lines.append({'product_id': p.id, 'quantity': max(1, min(99, it.quantity)), 'modifiers': mods})
    return lines, skipped


def last_delivered(db: Session, order_ids: list[int], account_id: int | None) -> Order | None:
    """Su último pedido entregado (de este navegador o de su cuenta) de los últimos 90 días, para «Pedí de nuevo»."""
    conds = []
    if order_ids:
        conds.append(Order.id.in_(order_ids))
    if account_id:
        conds.append(Order.account_id == account_id)
    if not conds:
        return None
    from sqlalchemy import or_
    since = datetime.utcnow() - timedelta(days=REPEAT_DAYS)
    o = db.scalar(select(Order).options(joinedload(Order.store), selectinload(Order.items))
                  .where(or_(*conds), Order.status == OrderStatus.ENTREGADO, Order.created_at >= since, Order.table_name.is_(None))
                  .order_by(Order.created_at.desc()).limit(1))
    return o if o is not None and plans.is_visible(o.store) else None
