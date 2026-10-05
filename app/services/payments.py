"""Pago del pedido y PIN de entrega.

El cliente elige como paga (efectivo al recibir o transferencia al local). El pedido queda "pagado"
cuando el local confirma la transferencia (o cobro en el mostrador) o cuando el repartidor lo entrega
y cobra. Asi el repartidor sabe siempre si tiene que cobrar y cuanto.
"""
import secrets
from datetime import datetime
from decimal import Decimal

from ..models import Order

METHODS = {'efectivo': 'Efectivo', 'transferencia': 'Transferencia', 'mercadopago': 'Mercado Pago'}
ONLINE = {'mercadopago'}
PIN_ATTEMPTS = 5  # intentos fallidos antes de bloquear la carga del PIN un rato


class PaymentError(Exception):
    pass


def new_pin() -> str:
    return f'{secrets.randbelow(10_000):04d}'


def check_method(method: str) -> str:
    method = (method or 'efectivo').strip().lower()
    if method not in METHODS:
        raise PaymentError('Elegí cómo vas a pagar.')
    return method


def method_label(order: Order) -> str:
    return METHODS.get(order.payment_method, 'A coordinar')


def is_paid(order: Order) -> bool:
    return order.paid_at is not None


def awaiting_online(order: Order) -> bool:
    """Eligio pagar online y todavia no esta aprobado: no se prepara ni se despacha."""
    return order.payment_method in ONLINE and not is_paid(order)


def to_collect(order: Order) -> Decimal:
    """Lo que tiene que cobrar quien entrega: nada si ya esta pagado."""
    return Decimal('0') if is_paid(order) else Decimal(order.total or 0)


def change_for(order: Order) -> Decimal | None:
    """Vuelto a llevar si paga en efectivo con un billete mayor."""
    if is_paid(order) or order.payment_method != 'efectivo' or not order.cash_with:
        return None
    change = Decimal(order.cash_with) - Decimal(order.total or 0)
    return change if change > 0 else None


def mark_paid(order: Order, by: str, now: datetime | None = None) -> None:
    if not is_paid(order):
        order.paid_at, order.paid_by = now or datetime.utcnow(), by


def mark_unpaid(order: Order) -> None:
    order.paid_at = order.paid_by = None


def status_text(order: Order) -> str:
    """Resumen corto para el local y el ticket: "Pagado (transferencia)", "Cobrar $X en efectivo"."""
    if is_paid(order):
        return f'Pagado ({method_label(order).lower()})'
    if order.payment_method == 'transferencia':
        return 'Transferencia sin confirmar'
    if order.payment_method in ONLINE:
        return {'rejected': 'Pago online rechazado', 'expired': 'Pago online vencido', 'cancelled': 'Pago online cancelado'}.get(order.payment_status or '', 'Esperando el pago online')
    return 'Paga en efectivo al recibir'


def pin_matches(order: Order, pin: str) -> bool:
    expected = order.delivery_pin or ''
    given = ''.join(ch for ch in (pin or '') if ch.isdigit())
    return bool(expected) and secrets.compare_digest(given, expected)
