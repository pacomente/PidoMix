"""Reiniciar un comercio: borra sus ventas, estadisticas y comisiones para empezar de cero.

Lo hace solo el superadmin (si el comercio pudiera, borraria lo que le debe a Trappi).

Se borra, de ese comercio:
  - los pedidos y todo lo que cuelga de ellos (items, historial, ofertas a cadetes, avisos, resenas, pagos)
  - sus movimientos de saldo con Trappi (comisiones, ventas en efectivo, splits, ajustes) y sus liquidaciones
  - opcional: los abonos mensuales cargados
  - los productos que el local ya habia eliminado (quedaban solo por los pedidos viejos)
y se ponen en cero la calificacion y los usos de los cupones.

Queda igual: el comercio, su plan, productos, horarios, cupones, usuarios, Mercado Pago y la auditoria.
La plata de los cadetes no se toca: sus viajes y el efectivo que tienen siguen en su cuenta, solo
pierden el enlace al pedido (que deja de existir).
"""
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models import (Coupon, DeliveryOffer, LedgerEntry, MerchantSettlement, Order, OrderEvent, OrderItem, OrderStatus, Payment,
                      Product, PushToken, Review, Store, SubscriptionPayment)
from . import audit, finance
from .formatting import money as ars

ACTIVE = (OrderStatus.PENDIENTE, OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO)


class ResetError(Exception):
    pass


def _order_ids(store_id: int):
    return select(Order.id).where(Order.store_id == store_id)


def preview(db: Session, store: Store) -> dict:
    """Que se va a borrar y que conviene revisar antes."""
    ids = _order_ids(store.id)
    count = lambda model, *conds: int(db.scalar(select(func.count(model.id)).where(*conds)) or 0)
    delivered = db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0), func.coalesce(func.sum(Order.platform_commission), 0))
                           .where(Order.store_id == store.id, Order.status == OrderStatus.ENTREGADO)).one()
    balance = finance.merchant_balance(db, store.id)
    courier_cash = finance.money(db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
        LedgerEntry.account == 'courier_cash', LedgerEntry.settled.is_(False), LedgerEntry.order_id.in_(ids))))
    approved = db.execute(select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.order_id.in_(ids), Payment.status == 'approved')).one()
    out = {
        'orders': count(Order, Order.store_id == store.id),
        'active_orders': count(Order, Order.store_id == store.id, Order.status.in_(ACTIVE)),
        'delivered': int(delivered[0]), 'sales': finance.money(delivered[1]), 'commission': finance.money(delivered[2]),
        'reviews': count(Review, Review.store_id == store.id),
        'payments': count(Payment, Payment.order_id.in_(ids)),
        'approved_payments': int(approved[0]), 'approved_amount': finance.money(approved[1]),
        'merchant_entries': count(LedgerEntry, LedgerEntry.account == 'merchant', LedgerEntry.store_id == store.id),
        'settlements': count(MerchantSettlement, MerchantSettlement.store_id == store.id),
        'open_settlements': count(MerchantSettlement, MerchantSettlement.store_id == store.id, MerchantSettlement.status.in_(('pending', 'processing'))),
        'subscriptions': count(SubscriptionPayment, SubscriptionPayment.store_id == store.id),
        'courier_entries': count(LedgerEntry, LedgerEntry.account != 'merchant', LedgerEntry.order_id.in_(ids)),
        'courier_cash': courier_cash,
        'balance_pending': balance['pending'], 'balance_in_settlement': balance['in_settlement'],
    }
    warnings = []
    if out['balance_pending'] or out['balance_in_settlement']:
        amount = out['balance_pending'] + out['balance_in_settlement']
        warnings.append(f'Tiene saldo con Trappi sin cerrar ({"Trappi le debe" if amount > 0 else "le debe a Trappi"} {ars(abs(amount))}). '
                        'Al reiniciar se borra: cobralo o pagalo antes, o anotalo.')
    if out['open_settlements']:
        warnings.append(f'Tiene {out["open_settlements"]} liquidación(es) sin pagar: se borran.')
    if out['courier_cash']:
        warnings.append(f'Hay cadetes con {ars(out["courier_cash"])} en efectivo de estos pedidos sin rendir. '
                        'Lo siguen debiendo igual (queda en su cuenta, sin el número de pedido).')
    if out['approved_payments']:
        warnings.append(f'{out["approved_payments"]} pago(s) aprobados en Mercado Pago. En Mercado Pago no cambia nada '
                        '(ni se devuelve plata): solo se borra el registro acá.')
    out['warnings'] = warnings
    out['blocked'] = ('Tiene pedidos en curso. Esperá a que se entreguen o cancelalos antes de reiniciar.' if out['active_orders'] else None)
    return out


def reset(db: Session, store: Store, *, include_subscriptions: bool = False, user=None, ip=None, reason: str = '') -> dict:
    """Borra las ventas del comercio. No hace commit (va en la misma transaccion que la auditoria)."""
    summary = preview(db, store)
    if summary['blocked']:
        raise ResetError(summary['blocked'])
    ids = _order_ids(store.id)
    # la plata de los cadetes queda: solo pierde el enlace al pedido
    for e in db.scalars(select(LedgerEntry).where(LedgerEntry.account != 'merchant', LedgerEntry.order_id.in_(ids))):
        note = f'#{e.order_id} {store.name} (pedido borrado al reiniciar el comercio)'
        e.description = (f'{e.description} · {note}' if e.description else note)[:255]
        e.order_id = None
    db.flush()
    db.execute(delete(LedgerEntry).where(LedgerEntry.account == 'merchant', LedgerEntry.store_id == store.id))
    db.execute(delete(LedgerEntry).where(LedgerEntry.account == 'merchant', LedgerEntry.order_id.in_(ids)))
    db.execute(delete(MerchantSettlement).where(MerchantSettlement.store_id == store.id))
    for model in (OrderItem, OrderEvent, DeliveryOffer, PushToken, Payment):
        db.execute(delete(model).where(model.order_id.in_(ids)))
    db.execute(delete(Review).where(Review.store_id == store.id))
    db.execute(delete(Review).where(Review.order_id.in_(ids)))
    db.execute(delete(Order).where(Order.store_id == store.id))
    if include_subscriptions:
        db.execute(delete(SubscriptionPayment).where(SubscriptionPayment.store_id == store.id))
    removed = 0
    for p in db.scalars(select(Product).where(Product.store_id == store.id, Product.deleted.is_(True))):
        db.delete(p)
        removed += 1
    db.execute(update(Coupon).where(Coupon.store_id == store.id).values(uses_count=0))
    store.rating_avg, store.rating_count = Decimal('0'), 0
    db.flush()
    summary = {k: v for k, v in summary.items() if k not in ('warnings', 'blocked')}
    summary.update(subscriptions_deleted=include_subscriptions, deleted_products=removed)
    audit.log(db, 'store.reset', 'store', store.id, user=user, old=summary, new={'store': store.name},
              amount_old=summary['sales'], amount_new=0, reason=reason or 'Reinicio del comercio', ip=ip)
    return summary
