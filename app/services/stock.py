"""Stock de los productos que lo cargan con numero: baja con cada pedido y vuelve si el pedido se cancela.

Sin numero (vacio) es sin limite y no se toca. El descuento es un UPDATE condicional, asi dos pedidos a la vez
no pueden llevarse la ultima unidad los dos.
"""
from collections import Counter

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Order, Product


class OutOfStock(ValueError):
    pass


def reserve(db: Session, order: Order, items: list[dict]) -> None:
    """items: las lineas del carrito (con 'product' y 'quantity'). Marca el pedido como que desconto stock. No hace commit."""
    wanted = Counter()
    names = {}
    for item in items:
        p = item['product']
        if p.stock is not None:
            wanted[p.id] += int(item['quantity'])
            names[p.id] = p.name
    for pid, qty in wanted.items():
        res = db.execute(update(Product).where(Product.id == pid, Product.stock.is_not(None), Product.stock >= qty)
                         .values(stock=Product.stock - qty).execution_options(synchronize_session=False))
        if res.rowcount != 1:
            left = db.get(Product, pid)
            db.refresh(left)
            raise OutOfStock(f'De {names[pid]} quedan {max(0, left.stock or 0)}.' if left.stock else f'{names[pid]} se agotó recién.')
    order.stock_reserved = bool(wanted)


def release(db: Session, order: Order) -> None:
    """Pedido cancelado: devuelve lo que desconto (una sola vez). No hace commit."""
    if not order.stock_reserved:
        return
    back = Counter()
    for it in order.items:
        if it.product_id:
            back[it.product_id] += it.quantity
    for pid, qty in back.items():
        db.execute(update(Product).where(Product.id == pid, Product.stock.is_not(None))
                   .values(stock=Product.stock + qty).execution_options(synchronize_session=False))
    order.stock_reserved = False


def restock(p: Product) -> None:
    """De agotado a disponible: la cantidad que tenia antes de agotarlo, o sin limite."""
    p.stock = p.stock_before_out if p.stock_before_out and p.stock_before_out > 0 else None
    p.stock_before_out = p.out_until = None


def restock_due(db: Session, now=None) -> int:
    """Los "agotado hasta mañana" cuyo momento ya llego vuelven solos. Hace commit si cambio algo."""
    from datetime import datetime
    from sqlalchemy import select
    now = now or datetime.utcnow()
    rows = db.scalars(select(Product).where(Product.out_until.is_not(None), Product.out_until <= now)).all()
    for p in rows:
        if p.stock is not None and p.stock <= 0:
            restock(p)
        else:
            p.out_until = None
    if rows:
        db.commit()
    return len(rows)


def take_for_pos(db: Session, store_id: int, items: list[dict]) -> None:
    """Venta de la caja del local: descuenta stock sin rechazarla (la venta ya se hizo en el mostrador, quizas sin internet).
    Nunca deja el stock en negativo. Anota en cada linea cuanto desconto, para devolverlo si se anula. No hace commit."""
    for it in items:
        pid, qty = it.get('product_id'), int(it.get('quantity') or 0)
        if not pid or qty < 1:
            continue
        p = db.get(Product, pid)
        if not p or p.store_id != store_id or p.stock is None:
            continue
        taken = min(max(p.stock, 0), qty)
        if taken:
            db.execute(update(Product).where(Product.id == pid, Product.stock.is_not(None), Product.stock >= taken)
                       .values(stock=Product.stock - taken).execution_options(synchronize_session=False))
            db.refresh(p)
        it['stock_taken'] = taken


def give_back_pos(db: Session, items: list[dict]) -> None:
    """Venta de la caja anulada: vuelve lo que desconto."""
    for it in items:
        n = int(it.get('stock_taken') or 0)
        if n and it.get('product_id'):
            db.execute(update(Product).where(Product.id == it['product_id'], Product.stock.is_not(None))
                       .values(stock=Product.stock + n).execution_options(synchronize_session=False))
            it['stock_taken'] = 0
