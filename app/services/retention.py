"""Retención: que el cliente vuelva a pedir, sin regalar plata sin control.

1. Recordatorio: "Hace 7 días pediste Fugazzeta en Pizzería La Esquina. ¿Querés pedir de nuevo?".
   Se muestra en el inicio (web y app) con sus propios pedidos (si no apagó las recomendaciones) y se manda por
   email o notificación solo a quien aceptó recibir novedades (marketing_opt_in), como mucho cada N días.
2. Descuento para volver: "Tenés $2.000 de descuento en tu próximo pedido". Lo pone Trappi (no el comercio), con límites:
   - monto fijo, pedido mínimo en productos y vencimiento,
   - como mucho uno cada N días por cliente y uno activo a la vez,
   - presupuesto por mes: se suma lo comprometido (activos + usados del mes); al llegar, no se dan más,
   - en cada pedido nunca descuenta más de lo que Trappi gana en ese pedido.
   Todo se calcula y se valida en el backend. Arranca apagado (Configuración → Retención).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..models import ClientAccount, Order, OrderStatus, RetentionVoucher
from . import platform
from .formatting import money as fmt
from .store_hours import LOCAL_TZ, local_now, to_local

ZERO = Decimal('0.00')


def money(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal('0.01'))
_signer = URLSafeSerializer(settings.secret_key, salt='trappi-novedades')


def config(db: Session) -> dict:
    c = platform.get_all(db)
    return {
        'reminders': bool(c['retention_reminders']), 'reminder_days': int(c['retention_reminder_days']), 'send_every': int(c['retention_send_every_days']),
        'vouchers': bool(c['retention_vouchers']), 'amount': Decimal(str(c['retention_voucher_amount'])),
        'min_order': Decimal(str(c['retention_voucher_min_order'])), 'valid_days': int(c['retention_voucher_days']),
        'after_first': bool(c['retention_after_first']), 'inactive_days': int(c['retention_after_inactive_days']),
        'voucher_every': int(c['retention_voucher_every_days']), 'budget': Decimal(str(c['retention_monthly_budget'])),
    }


def month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Mes calendario en Argentina, como UTC sin zona (como se guardan las fechas)."""
    local = (now.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ) if now else local_now())
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return utc(start), utc(end)


def committed(db: Session, now: datetime | None = None) -> Decimal:
    """Lo que Trappi ya comprometió este mes: descuentos activos (por su monto) y usados (por lo que se descontó)."""
    start, end = month_window(now)
    now = now or datetime.utcnow()
    active = db.scalar(select(func.coalesce(func.sum(RetentionVoucher.amount), 0)).where(
        RetentionVoucher.created_at >= start, RetentionVoucher.created_at < end, RetentionVoucher.status == 'activo', RetentionVoucher.expires_at > now)) or 0
    used = db.scalar(select(func.coalesce(func.sum(RetentionVoucher.used_amount), 0)).where(
        RetentionVoucher.used_at >= start, RetentionVoucher.used_at < end, RetentionVoucher.status == 'usado')) or 0
    return money(Decimal(active) + Decimal(used))


def _expire(db: Session, now: datetime) -> None:
    for v in db.scalars(select(RetentionVoucher).where(RetentionVoucher.status == 'activo', RetentionVoucher.expires_at <= now)).all():
        v.status = 'vencido'


def active_voucher(db: Session, account_id: int | None, now: datetime | None = None) -> RetentionVoucher | None:
    if not account_id:
        return None
    now = now or datetime.utcnow()
    return db.scalar(select(RetentionVoucher).where(RetentionVoucher.account_id == account_id, RetentionVoucher.status == 'activo',
                                                    RetentionVoucher.expires_at > now).order_by(RetentionVoucher.expires_at))


def _delivered(db: Session, account_id: int):
    return db.scalars(select(Order).options(joinedload(Order.store), selectinload(Order.items)).where(
        Order.account_id == account_id, Order.status == OrderStatus.ENTREGADO).order_by(Order.created_at.desc())).unique().all()


def maybe_issue(db: Session, account: ClientAccount | None, now: datetime | None = None, cfg: dict | None = None) -> RetentionVoucher | None:
    """Le da un descuento si corresponde y hay presupuesto. Idempotente: nunca dos activos. No hace commit."""
    cfg = cfg or config(db)
    if not cfg['vouchers'] or account is None or not account.active or cfg['amount'] <= 0:
        return None
    now = now or datetime.utcnow()
    _expire(db, now)
    current = active_voucher(db, account.id, now)
    if current:
        return current
    last = db.scalar(select(func.max(RetentionVoucher.created_at)).where(RetentionVoucher.account_id == account.id))
    if last and (now - last).days < cfg['voucher_every']:
        return None
    delivered = _delivered(db, account.id)
    if not delivered:
        return None
    pending = db.scalar(select(func.count(Order.id)).where(Order.account_id == account.id, Order.status.not_in((OrderStatus.ENTREGADO, OrderStatus.CANCELADO))))
    if pending:
        return None  # ya tiene un pedido en curso: no hace falta
    reason = None
    ever = db.scalar(select(func.count(RetentionVoucher.id)).where(RetentionVoucher.account_id == account.id)) or 0
    if cfg['after_first'] and len(delivered) == 1 and not ever:
        reason = 'segundo_pedido'
    elif cfg['inactive_days'] and (now - delivered[0].created_at).days >= cfg['inactive_days']:
        reason = 'te_extranamos'
    if not reason:
        return None
    if committed(db, now) + cfg['amount'] > cfg['budget']:
        return None  # se llego al presupuesto del mes
    v = RetentionVoucher(account_id=account.id, reason=reason, amount=money(cfg['amount']), min_order=money(cfg['min_order']),
                         expires_at=now + timedelta(days=cfg['valid_days']), created_at=now)
    db.add(v)
    db.flush()
    return v


def grant(db: Session, account_id: int, amount: Decimal, days: int, note: str, user, min_order: Decimal = ZERO) -> RetentionVoucher:
    """Descuento manual del superadmin (cuenta para el presupuesto del mes). No hace commit."""
    v = RetentionVoucher(account_id=account_id, reason='manual', amount=money(amount), min_order=money(min_order),
                         expires_at=datetime.utcnow() + timedelta(days=days), note=(note or '')[:255], user_id=getattr(user, 'id', None))
    db.add(v)
    db.flush()
    return v


# ---------- recordatorio ----------

def _since(days: int) -> str:
    if days < 14:
        return f'Hace {days} días'
    if days < 60:
        return f'Hace {days // 7} semanas'
    return f'Hace {days // 30} meses'


def reminder(db: Session, account: ClientAccount | None, now: datetime | None = None, cfg: dict | None = None) -> dict | None:
    """'Hace 7 días pediste ... ¿Querés pedir de nuevo?' con su último pedido entregado (solo sus datos)."""
    cfg = cfg or config(db)
    if not cfg['reminders'] or account is None or not account.active or account.personalize is False:
        return None
    now = now or datetime.utcnow()
    delivered = _delivered(db, account.id)
    if not delivered:
        return None
    last = delivered[0]
    days = (now - last.created_at).days
    if days < cfg['reminder_days']:
        return None
    newer = db.scalar(select(func.count(Order.id)).where(Order.account_id == account.id, Order.created_at > last.created_at,
                                                         Order.status != OrderStatus.CANCELADO))
    if newer:
        return None
    names = [it.product_name for it in last.items][:2]
    what = ' y '.join(names) if names else 'tu pedido'
    return {'days': days, 'store_name': last.store.name, 'store_slug': last.store.slug, 'order_id': last.id, 'products': names,
            'text': f'{_since(days)} pediste {what} en {last.store.name}. ¿Querés pedir de nuevo?'}


def offer(db: Session, account: ClientAccount | None, now: datetime | None = None) -> dict:
    """Lo que se le muestra en el inicio: el recordatorio y su descuento (si tiene o le corresponde uno). Hace commit si crea uno."""
    cfg = config(db)
    out = {'reminder': reminder(db, account, now, cfg), 'voucher': None}
    v = maybe_issue(db, account, now, cfg)
    if v is not None:
        db.commit()
        out['voucher'] = voucher_json(v)
    return out


def voucher_json(v: RetentionVoucher) -> dict:
    return {'id': v.id, 'amount': float(v.amount), 'min_order': float(v.min_order), 'expires_at': v.expires_at.isoformat() + 'Z',
            'expires_text': to_local(v.expires_at).strftime('%d/%m'),
            'text': f'Tenés {fmt(v.amount)} de descuento en tu próximo pedido' + (f' desde {fmt(v.min_order)}' if v.min_order else '') + '.'}


# ---------- en el checkout ----------

def usable(db: Session, account, products: Decimal, trappi_amount: Decimal) -> dict:
    """Cuánto se puede descontar en este pedido (products = productos con el cupón del local ya restado)."""
    out = {'voucher': None, 'discount': ZERO, 'reason': None}
    if account is None or not config(db)['vouchers']:
        return out
    v = active_voucher(db, account.id)
    if v is None:
        return out
    out['voucher'] = v
    if Decimal(products) < Decimal(v.min_order):
        out['reason'] = f'Tu descuento de {fmt(v.amount)} es para pedidos desde {fmt(v.min_order)} en productos.'
        return out
    cap = min(Decimal(v.amount), max(Decimal(trappi_amount), ZERO))  # nunca mas de lo que Trappi gana en este pedido
    if cap <= 0:
        out['reason'] = 'Tu descuento no se puede usar en este pedido.'
        return out
    out['discount'] = money(cap)
    return out


def apply_to_order(db: Session, order: Order, account) -> None:
    """Aplica el descuento de Trappi (despues de plans.snapshot, antes de los puntos). No hace commit."""
    from . import plans
    b = plans.breakdown(order)
    u = usable(db, account, b['products'], b['trappi_amount'])
    if not u['discount']:
        return
    order.voucher_id, order.voucher_discount = u['voucher'].id, u['discount']
    order.total = plans.money(order.total) - u['discount']


def mark_used(db: Session, order: Order) -> None:
    if not order.voucher_id:
        return
    v = db.get(RetentionVoucher, order.voucher_id)
    if v and v.status == 'activo':
        v.status, v.order_id, v.used_amount, v.used_at = 'usado', order.id, order.voucher_discount, datetime.utcnow()


def on_cancelled(db: Session, order: Order) -> None:
    """Pedido cancelado: el descuento vuelve a estar disponible (si no vencio)."""
    if not order.voucher_id:
        return
    v = db.get(RetentionVoucher, order.voucher_id)
    if v and v.status == 'usado' and v.order_id == order.id:
        v.status = 'activo' if v.expires_at > datetime.utcnow() else 'vencido'
        v.order_id = v.used_amount = v.used_at = None


# ---------- envio (email y notificacion) ----------

def unsubscribe_token(account_id: int) -> str:
    return _signer.dumps(account_id)


def account_from_token(token: str) -> int | None:
    try:
        value = _signer.loads(token)
        return int(value)
    except (BadSignature, ValueError, TypeError):
        return None


@dataclass
class RunResult:
    candidates: int = 0
    emails: int = 0
    pushes: int = 0
    vouchers: int = 0
    skipped_budget: bool = False


def run(db: Session, base_url: str, now: datetime | None = None, send: bool = True, limit: int = 500) -> RunResult:
    """Manda recordatorios a quienes aceptaron novedades y corresponde. Con send=False solo cuenta (vista previa)."""
    from . import email, push
    cfg = config(db)
    res = RunResult()
    if not cfg['reminders']:
        return res
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=cfg['send_every'])
    accounts = db.scalars(select(ClientAccount).where(ClientAccount.active.is_(True), ClientAccount.marketing_opt_in.is_(True),
                                                      or_(ClientAccount.last_retention_at.is_(None), ClientAccount.last_retention_at < cutoff))
                          .order_by(ClientAccount.id).limit(limit)).all()
    for acct in accounts:
        r = reminder(db, acct, now, cfg)
        if not r:
            continue
        res.candidates += 1
        if not send:
            continue
        before = active_voucher(db, acct.id, now)
        v = maybe_issue(db, acct, now, cfg)
        if v is not None and before is None:
            res.vouchers += 1
        extra = f'\n\n{voucher_json(v)["text"]} Vence el {to_local(v.expires_at).strftime("%d/%m")}.' if v else ''
        link = f'{base_url}/tienda/{r["store_slug"]}'
        off = f'{base_url}/novedades/baja?t={unsubscribe_token(acct.id)}'
        text = (f'Hola{" " + acct.first_name if acct.first_name else ""}:\n\n{r["text"]}{extra}\n\nPedí acá: {link}\n\n'
                f'Te escribimos porque aceptaste recibir novedades de Trappi. Para no recibir más: {off}')
        if acct.email and email.configured():
            try:
                email.send(acct.email, '¿Pedimos de nuevo?' if not v else f'Tenés {fmt(v.amount)} de descuento en Trappi', text)
                res.emails += 1
            except email.EmailError:
                pass
        if push.notify_account(db, acct.id, '¿Pedimos de nuevo?', r['text'] + (f' {voucher_json(v)["text"]}' if v else ''), store_slug=r['store_slug']):
            res.pushes += 1
        acct.last_retention_at = now
        db.commit()
    return res


def stats(db: Session, now: datetime | None = None) -> dict:
    """Para el panel: presupuesto del mes y si los descuentos traen pedidos que dejan ganancia."""
    from . import plans
    now = now or datetime.utcnow()
    _expire(db, now)
    db.commit()
    start, end = month_window(now)
    cfg = config(db)
    issued = db.scalars(select(RetentionVoucher).where(RetentionVoucher.created_at >= start, RetentionVoucher.created_at < end)).all()
    used_orders = db.scalars(select(Order).where(Order.voucher_id.is_not(None), Order.status == OrderStatus.ENTREGADO,
                                                 Order.created_at >= start, Order.created_at < end)).all()
    cost = sum((Decimal(o.voucher_discount or 0) for o in used_orders), ZERO)
    income = sum((plans.breakdown(o)['trappi_income'] for o in used_orders), ZERO)  # ya con el descuento restado
    used = [v for v in issued if v.status == 'usado']
    return {'cfg': cfg, 'committed': committed(db, now), 'budget': cfg['budget'], 'left': max(cfg['budget'] - committed(db, now), ZERO),
            'issued': len(issued), 'used': len(used), 'expired': sum(1 for v in issued if v.status == 'vencido'),
            'active': sum(1 for v in issued if v.status == 'activo'), 'use_rate': round(len(used) / len(issued) * 100, 1) if issued else None,
            'cost': money(cost), 'orders': len(used_orders), 'gmv': money(sum((Decimal(o.total) for o in used_orders), ZERO)),
            'net': money(income), 'opted_in': db.scalar(select(func.count(ClientAccount.id)).where(ClientAccount.marketing_opt_in.is_(True))) or 0,
            'recent': db.scalars(select(RetentionVoucher).order_by(RetentionVoucher.created_at.desc()).limit(30)).all()}
