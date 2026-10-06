"""Control de clientes para el superadmin: la ficha completa de una cuenta (seguridad y fraude).

Junta lo que Trappi tiene de una cuenta: sus datos, todos sus pedidos (con los telefonos, direcciones e IPs
que uso), los ingresos (con IP y si fue por la web o la app), los bloqueos, los pedidos de arrepentimiento y
otras cuentas que comparten telefono o IP. Cada vez que alguien abre la ficha o descarga los datos queda en
la auditoria (quien miro que y cuando).
"""
from collections import OrderedDict
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..models import AuditLog, ClientAccount, Customer, Order, OrderStatus, WithdrawalRequest
from .formatting import money
from .store_hours import to_local

LOGIN_ACTIONS = ('client.login', 'client.signup')
ACTION_TEXT = {'client.signup': 'Creó la cuenta', 'client.login': 'Entró', 'client.block': 'Bloqueada', 'client.unblock': 'Desbloqueada',
               'client.sessions': 'Se cerraron sus sesiones', 'client.view': 'Ficha vista', 'client.export': 'Datos descargados',
               'client.delete': 'Eliminó la cuenta'}


def _orders(db: Session, acct: ClientAccount) -> list[Order]:
    return db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer), selectinload(Order.items))
                      .where(Order.account_id == acct.id).order_by(Order.created_at.desc())).unique().all()


def _activity(db: Session, acct: ClientAccount, limit: int = 200) -> list[AuditLog]:
    return db.scalars(select(AuditLog).options(joinedload(AuditLog.user)).where(AuditLog.entity == 'client_account', AuditLog.entity_id == str(acct.id))
                      .order_by(AuditLog.created_at.desc()).limit(limit)).unique().all()


def _seen(rows) -> list[dict]:
    """[(valor, fecha, de_donde)] -> lista sin repetidos: veces, primera y ultima vez."""
    out: OrderedDict[str, dict] = OrderedDict()
    for value, when, source in rows:
        value = (value or '').strip()
        if not value:
            continue
        item = out.setdefault(value, {'value': value, 'times': 0, 'first': when, 'last': when, 'sources': set()})
        item['times'] += 1
        item['first'], item['last'] = min(item['first'], when), max(item['last'], when)
        item['sources'].add(source)
    return sorted(({**i, 'sources': sorted(i['sources'])} for i in out.values()), key=lambda i: i['last'], reverse=True)


def profile(db: Session, acct: ClientAccount) -> dict:
    orders = _orders(db, acct)
    activity = _activity(db, acct)
    logins = [a for a in activity if a.action in LOGIN_ACTIONS]
    valid = [o for o in orders if o.status != OrderStatus.CANCELADO]
    phones = _seen([(acct.phone, acct.created_at, 'cuenta')] + [(o.customer.phone if o.customer else None, o.created_at, f'pedido #{o.id}') for o in orders])
    addresses = _seen([(acct.address, acct.created_at, 'cuenta')] +
                      [(o.address, o.created_at, f'pedido #{o.id}') for o in orders if o.delivery_method == 'delivery'])
    ips = _seen([(a.ip, a.created_at, 'ingreso') for a in logins] + [(o.ip, o.created_at, f'pedido #{o.id}') for o in orders])
    stats = {
        'orders': len(orders), 'delivered': sum(1 for o in orders if o.status == OrderStatus.ENTREGADO),
        'cancelled': sum(1 for o in orders if o.status == OrderStatus.CANCELADO),
        'spent': money(sum((Decimal(o.total) for o in valid), Decimal('0'))),
        'average': money(sum((Decimal(o.total) for o in valid), Decimal('0')) / len(valid)) if valid else None,
        'failed_deliveries': sum(1 for o in orders if o.delivery_failed_at),
        'first_order': orders[-1].created_at if orders else None, 'last_order': orders[0].created_at if orders else None,
        'stores': len({o.store_id for o in orders}),
        'logins': len(logins), 'last_login_ip': logins[0].ip if logins else None,
        'app_logins': sum(1 for a in logins if '"via": "app"' in (a.new_value or '')),
    }
    withdrawals = db.scalars(select(WithdrawalRequest).where(or_(WithdrawalRequest.account_id == acct.id, WithdrawalRequest.email == acct.email))
                             .order_by(WithdrawalRequest.id.desc())).all()
    return {'acct': acct, 'orders': orders, 'activity': activity, 'stats': stats, 'phones': phones, 'addresses': addresses, 'ips': ips,
            'related': related(db, acct, [p['value'] for p in phones], [i['value'] for i in ips]), 'withdrawals': withdrawals}


def related(db: Session, acct: ClientAccount, phones: list[str], ips: list[str], limit: int = 20) -> list[dict]:
    """Otras cuentas con el mismo telefono o que entraron/pidieron desde la misma IP (posibles cuentas duplicadas)."""
    found: dict[int, set] = {}
    if phones:
        for (aid,) in db.execute(select(ClientAccount.id).where(ClientAccount.phone.in_(phones), ClientAccount.id != acct.id)):
            found.setdefault(aid, set()).add('mismo teléfono')
        for (aid,) in db.execute(select(Order.account_id).join(Customer, Order.customer_id == Customer.id)
                                 .where(Customer.phone.in_(phones), Order.account_id.is_not(None), Order.account_id != acct.id).distinct()):
            found.setdefault(aid, set()).add('mismo teléfono')
    if ips:
        for (eid,) in db.execute(select(AuditLog.entity_id).where(AuditLog.entity == 'client_account', AuditLog.action.in_(LOGIN_ACTIONS),
                                                                  AuditLog.ip.in_(ips), AuditLog.entity_id != str(acct.id)).distinct()):
            if eid and eid.isdigit():
                found.setdefault(int(eid), set()).add('misma IP')
        for (aid,) in db.execute(select(Order.account_id).where(Order.ip.in_(ips), Order.account_id.is_not(None), Order.account_id != acct.id).distinct()):
            found.setdefault(aid, set()).add('misma IP')
    if not found:
        return []
    rows = db.scalars(select(ClientAccount).where(ClientAccount.id.in_(list(found)[:200])).order_by(ClientAccount.created_at.desc()).limit(limit)).all()
    return [{'acct': a, 'reasons': sorted(found[a.id])} for a in rows]


def export(db: Session, acct: ClientAccount) -> dict:
    """Todos los datos de la cuenta en un JSON (pedido de acceso de la Ley 25.326, o para una denuncia)."""
    p = profile(db, acct)
    fmt = lambda dt: to_local(dt).strftime('%Y-%m-%d %H:%M') if dt else None  # noqa: E731
    return {
        'cuenta': {'id': acct.id, 'email': acct.email, 'nombre': acct.first_name, 'apellido': acct.last_name, 'telefono': acct.phone,
                   'direccion': acct.address, 'referencia': acct.reference, 'activa': acct.active, 'motivo_bloqueo': acct.blocked_reason,
                   'alta': fmt(acct.created_at), 'ultimo_ingreso': fmt(acct.last_login_at), 'terminos_version': acct.terms_version,
                   'terminos_aceptados': fmt(acct.terms_accepted_at)},
        'resumen': {k: (fmt(v) if hasattr(v, 'strftime') else v) for k, v in p['stats'].items()},
        'pedidos': [{'id': o.id, 'fecha': fmt(o.created_at), 'comercio': o.store.name if o.store else None, 'estado': o.status.value,
                     'total': str(o.total), 'pago': o.payment_method, 'entrega': o.delivery_method, 'direccion': o.address,
                     'nombre': f'{o.customer.first_name} {o.customer.last_name}'.strip() if o.customer else None,
                     'telefono': o.customer.phone if o.customer else None, 'origen': o.origin, 'ip': o.ip,
                     'productos': [f'{it.quantity} x {it.product_name}' for it in o.items]} for o in p['orders']],
        'telefonos': [{'valor': x['value'], 'veces': x['times'], 'ultima_vez': fmt(x['last'])} for x in p['phones']],
        'direcciones': [{'valor': x['value'], 'veces': x['times'], 'ultima_vez': fmt(x['last'])} for x in p['addresses']],
        'ips': [{'valor': x['value'], 'veces': x['times'], 'ultima_vez': fmt(x['last'])} for x in p['ips']],
        'actividad': [{'fecha': fmt(a.created_at), 'accion': ACTION_TEXT.get(a.action, a.action), 'ip': a.ip,
                       'por': a.user.email if a.user else None, 'motivo': a.reason} for a in p['activity']],
        'arrepentimiento': [{'codigo': w.code, 'fecha': fmt(w.created_at), 'estado': w.status, 'pedido': w.order_ref, 'detalle': w.detail}
                            for w in p['withdrawals']],
    }
