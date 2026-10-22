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
