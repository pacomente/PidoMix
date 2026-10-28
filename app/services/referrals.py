"""Invitá a un amigo: cada cliente tiene un link propio. Cuando un amigo crea su cuenta desde ese link y recibe
su primer pedido (de un mínimo), los dos ganan Puntos Trappi.

- Se prende en Configuración → Puntos (apagado de arranque) y solo funciona con los Puntos Trappi prendidos.
- Solo cuentas nuevas: el amigo tiene que crear la cuenta después de tocar el link (no se puede invitar a alguien que ya tenía cuenta).
- Un premio por amigo, una sola vez. Quien invita tiene un tope de premios por mes (el amigo cobra igual).
"""
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import ClientAccount, Order
from . import platform

SESSION_KEY = 'ref'
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def config(db: Session) -> dict:
    from . import loyalty
    cfg = platform.get_all(db)
    return {'enabled': bool(cfg['referral_enabled']) and loyalty.config(db)['enabled'], 'inviter': int(cfg['referral_points_inviter']),
            'friend': int(cfg['referral_points_friend']), 'min_order': cfg['referral_min_order'], 'cap': int(cfg['referral_monthly_cap'])}


def code_for(db: Session, acct: ClientAccount) -> str:
    if not acct.referral_code:
        for _ in range(10):
            code = ''.join(secrets.choice(ALPHABET) for _ in range(7))
            if not db.scalar(select(ClientAccount.id).where(ClientAccount.referral_code == code)):
                acct.referral_code = code
                db.flush()
                break
    return acct.referral_code


def inviter_by_code(db: Session, code: str) -> ClientAccount | None:
    code = ''.join(ch for ch in (code or '').upper() if ch in ALPHABET)[:12]
    acct = db.scalar(select(ClientAccount).where(ClientAccount.referral_code == code)) if code else None
    return acct if acct is not None and acct.active else None


def remember(request, db: Session, code: str) -> ClientAccount | None:
    """El link /invitar/<codigo>: se guarda en la sesion para cuando cree la cuenta."""
    inviter = inviter_by_code(db, code) if config(db)['enabled'] else None
    if inviter is not None:
        request.session[SESSION_KEY] = inviter.referral_code
    return inviter


def on_signup(request, db: Session, acct: ClientAccount) -> None:
    """Cuenta recien creada: si vino de un link de invitacion, queda anotado quien la invito."""
    code = request.session.pop(SESSION_KEY, None) if request is not None else None
    if not code or not getattr(acct, 'just_created', False) or acct.referred_by_id:
        return
    inviter = inviter_by_code(db, code)
    if inviter is not None and inviter.id != acct.id:
        acct.referred_by_id = inviter.id


def on_delivered(db: Session, order: Order) -> None:
    """Primer pedido entregado del amigo (desde el minimo): los dos ganan puntos, una sola vez."""
    from . import loyalty
    if not order.account_id:
        return
    friend = db.get(ClientAccount, order.account_id)
    if friend is None or not friend.referred_by_id or friend.referral_rewarded_at is not None:
        return
    cfg = config(db)
    if not cfg['enabled'] or float(order.subtotal or 0) < float(cfg['min_order'] or 0):
        return
    claimed = db.execute(update(ClientAccount).where(ClientAccount.id == friend.id, ClientAccount.referral_rewarded_at.is_(None))
                         .values(referral_rewarded_at=datetime.utcnow()))
    if claimed.rowcount != 1:
        return
    friend.referral_rewarded_at = friend.referral_rewarded_at or datetime.utcnow()
    months = loyalty.config(db)['months']
    expires = datetime.utcnow() + timedelta(days=30 * months) if months else None  # vencen igual que los ganados por pedidos
    loyalty._add(db, friend.id, 'referral', cfg['friend'], order_id=order.id, note='Bienvenida por invitación de un amigo',
                 expires_at=expires, dedupe=f'referral-friend:{friend.id}')
    month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    paid = db.scalar(select(func.count(ClientAccount.id)).where(ClientAccount.referred_by_id == friend.referred_by_id,
                                                               ClientAccount.referral_rewarded_at >= month, ClientAccount.id != friend.id)) or 0
    if paid < cfg['cap']:
        loyalty._add(db, friend.referred_by_id, 'referral', cfg['inviter'], order_id=order.id, note='Invitaste a un amigo',
                     expires_at=expires, dedupe=f'referral-inviter:{friend.id}')


def summary(db: Session, acct: ClientAccount) -> dict | None:
    cfg = config(db)
    if not cfg['enabled']:
        return None
    friends = db.scalar(select(func.count(ClientAccount.id)).where(ClientAccount.referred_by_id == acct.id, ClientAccount.referral_rewarded_at.is_not(None))) or 0
    waiting = db.scalar(select(func.count(ClientAccount.id)).where(ClientAccount.referred_by_id == acct.id, ClientAccount.referral_rewarded_at.is_(None))) or 0
    return {'code': code_for(db, acct), 'friends': friends, 'waiting': waiting, **cfg}
