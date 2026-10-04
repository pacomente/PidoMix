"""Dinero de Trappi: movimientos por cuenta, caja de los repartidores, rendiciones y liquidaciones.

Nunca se mezcla la plata: cada movimiento (LedgerEntry) es de una cuenta
  merchant          (+) Trappi le debe al comercio   (-) el comercio le debe a Trappi
  courier_cash      (+) efectivo que el repartidor cobro y tiene que rendir
  courier_earnings  (+) lo que Trappi le debe al repartidor por sus viajes
Los movimientos no se borran ni se editan; cada uno tiene una clave para no duplicarse
(el mismo pedido no genera dos veces el mismo cobro aunque se reintente). Lo pendiente es la suma
de lo que todavia no se rindio o liquido.

Que genera cada pedido al entregarse (o al aprobarse el pago online):
  efectivo, reparte la flota        el repartidor queda debiendo el total (caja) y Trappi le debe al
                                    comercio su parte (productos - comision - envio a cargo del comercio)
  efectivo/transferencia al local   el comercio cobro todo: le debe a Trappi su parte (comision y,
                                    si repartio la flota, el envio)
  Mercado Pago                      el Split ya repartio la plata: queda registrado como liquidado
  flota                             Trappi le debe al repartidor su pago por el viaje
"""
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (CashRemittance, Courier, CourierPayoutAccount, CourierSettlement, LedgerEntry, MerchantSettlement, Order,
                      OrderStatus)
from . import audit, crypto, platform, plans

ZERO = Decimal('0.00')
SETTLEMENT_STATUSES = {'pending': 'Pendiente', 'processing': 'En proceso', 'paid': 'Pagada', 'failed': 'Fallida', 'cancelled': 'Cancelada'}


class FinanceError(Exception):
    pass


def money(v) -> Decimal:
    return plans.money(v)


def entry(db: Session, account: str, kind: str, amount, *, store_id=None, courier_id=None, order_id=None, description='', dedupe=None,
          settled=False, user=None) -> LedgerEntry | None:
    """Agrega un movimiento. Con dedupe, si ya existe no hace nada (idempotente). No hace commit."""
    amount = money(amount)
    if dedupe and db.scalar(select(LedgerEntry.id).where(LedgerEntry.dedupe_key == dedupe)):
        return None
    row = LedgerEntry(account=account, kind=kind, amount=amount, store_id=store_id, courier_id=courier_id, order_id=order_id,
                      description=(description or '')[:255] or None, dedupe_key=dedupe, settled=settled, user_id=getattr(user, 'id', None))
    db.add(row)
    db.flush()  # la clave unica de dedupe_key frena un duplicado concurrente (la transaccion falla y no se guarda nada a medias)
    return row


# ---------- lo que genera cada pedido ----------

def on_online_paid(db: Session, order: Order, payment) -> None:
    """Pago online aprobado: el Split ya le dio al comercio y a Trappi su parte (queda como liquidado)."""
    b = plans.breakdown(order)
    entry(db, 'merchant', 'online_split', b['merchant_amount'], store_id=order.store_id, order_id=order.id, settled=True,
          description=f'Pedido #{order.id} cobrado por Mercado Pago (Split): ya acreditado al comercio', dedupe=f'order:{order.id}:online_split')


def on_refund(db: Session, order: Order, payment, amount: Decimal) -> None:
    entry(db, 'merchant', 'refund', -money(amount), store_id=order.store_id, order_id=order.id, settled=True,
          description=f'Devolución de Mercado Pago del pedido #{order.id}', dedupe=f'order:{order.id}:refund:{money(amount)}')


def on_delivered(db: Session, order: Order) -> None:
    """Al entregarse: caja del repartidor, saldo del comercio y pago del viaje. Idempotente."""
    if order.status != OrderStatus.ENTREGADO:
        return
    b = plans.breakdown(order)
    courier = order.courier
    fleet_courier = courier is not None and courier.store_id is None
    total = money(order.total)
    if order.payment_method in ('mercadopago',):
        pass  # ya repartido por el Split (on_online_paid)
    elif order.paid_by == 'repartidor' and fleet_courier:
        # el cadete de Trappi cobro todo: lo rinde a Trappi, y Trappi le debe al comercio su parte
        if entry(db, 'courier_cash', 'cash_collected', total, courier_id=courier.id, order_id=order.id,
                 description=f'Efectivo cobrado del pedido #{order.id}', dedupe=f'order:{order.id}:cash'):
            order.cash_pending = total
        entry(db, 'merchant', 'cash_sale', b['merchant_amount'], store_id=order.store_id, order_id=order.id,
              description=f'Pedido #{order.id} cobrado en efectivo por la flota: {money(b["total"])} - comisión {b["commission"]}'
                          + (f' - envío a cargo {b["fee_merchant"]}' if b['fee_merchant'] else ''), dedupe=f'order:{order.id}:merchant')
    else:
        # lo cobro el comercio (mostrador, cadete propio o transferencia): le debe a Trappi su parte
        owed = b['trappi_amount']
        if owed > 0:
            entry(db, 'merchant', 'commission_due', -owed, store_id=order.store_id, order_id=order.id,
                  description=f'Pedido #{order.id}: comisión {b["commission"]}' + (f' + envío de la flota {b["fee_customer"] + b["fee_merchant"]}' if b['fleet'] else ''),
                  dedupe=f'order:{order.id}:merchant')
    if fleet_courier and order.courier_pay is not None:
        entry(db, 'courier_earnings', 'trip', order.courier_pay, courier_id=courier.id, order_id=order.id,
              description=f'Viaje del pedido #{order.id}', dedupe=f'order:{order.id}:payout')


# ---------- saldos ----------

def _sum(db: Session, account: str, *conds) -> Decimal:
    return money(db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.account == account, *conds)))


def courier_cash_pending(db: Session, courier_id: int) -> Decimal:
    return _sum(db, 'courier_cash', LedgerEntry.courier_id == courier_id, LedgerEntry.settled.is_(False))


def cash_limit(db: Session, courier: Courier) -> Decimal:
    return money(courier.cash_limit) if courier.cash_limit is not None else money(platform.get_all(db)['courier_cash_limit'])


def courier_box(db: Session, courier: Courier) -> dict:
    """"Mi caja" del repartidor (solo lectura)."""
    collected = _sum(db, 'courier_cash', LedgerEntry.courier_id == courier.id, LedgerEntry.kind == 'cash_collected')
    remitted = money(db.scalar(select(func.coalesce(func.sum(CashRemittance.received), 0)).where(CashRemittance.courier_id == courier.id)))
    differences = money(db.scalar(select(func.coalesce(func.sum(CashRemittance.difference), 0)).where(CashRemittance.courier_id == courier.id)))
    pending = courier_cash_pending(db, courier.id)
    limit = cash_limit(db, courier)
    earnings_pending = _sum(db, 'courier_earnings', LedgerEntry.courier_id == courier.id, LedgerEntry.settled.is_(False), LedgerEntry.courier_settlement_id.is_(None))
    paid = money(db.scalar(select(func.coalesce(func.sum(CourierSettlement.total), 0)).where(CourierSettlement.courier_id == courier.id, CourierSettlement.status == 'paid')))
    return {'collected': collected, 'remitted': remitted, 'pending': pending, 'limit': limit, 'available': max(ZERO, limit - pending),
            'differences': differences, 'blocked': cash_blocked(db, courier), 'earnings_pending': earnings_pending, 'earnings_paid': paid,
            'cash_orders_enabled': courier.cash_orders_enabled, 'online_orders_enabled': courier.online_orders_enabled}


def can_take_cash(db: Session, courier: Courier, amount: Decimal) -> bool:
    """Puede tomar un pedido que va a cobrar en efectivo (solo la flota de Trappi tiene limite)."""
    if courier.store_id is not None:
        return True
    if not courier.cash_orders_enabled:
        return False
    return courier_cash_pending(db, courier.id) + money(amount) <= cash_limit(db, courier)


def cash_blocked(db: Session, courier: Courier) -> bool:
    """Ya no puede tomar pedidos en efectivo: llego al limite (o se los apagaron). Se destraba al rendir."""
    if courier.store_id is not None:
        return False
    return not courier.cash_orders_enabled or courier_cash_pending(db, courier.id) >= cash_limit(db, courier)


def can_take_online(db: Session, courier: Courier) -> bool:
    if courier.store_id is not None:
        return True
    if not courier.online_orders_enabled:
        return False
    if not platform.get_all(db)['cash_block_allows_online'] and cash_blocked(db, courier):
        return False
    return True


def merchant_balance(db: Session, store_id: int) -> dict:
    pending = _sum(db, 'merchant', LedgerEntry.store_id == store_id, LedgerEntry.settled.is_(False))
    in_settlement = _sum(db, 'merchant', LedgerEntry.store_id == store_id, LedgerEntry.settled.is_(False), LedgerEntry.merchant_settlement_id.is_not(None))
    settled = _sum(db, 'merchant', LedgerEntry.store_id == store_id, LedgerEntry.settled.is_(True), LedgerEntry.kind != 'online_split')
    cash_sales = _sum(db, 'merchant', LedgerEntry.store_id == store_id, LedgerEntry.settled.is_(False), LedgerEntry.kind == 'cash_sale')
    # "ventas en efectivo pendientes" en bruto (lo que cobro la flota) y su comision
    rows = db.execute(select(Order.total, Order.platform_commission).join(LedgerEntry, LedgerEntry.order_id == Order.id).where(
        LedgerEntry.account == 'merchant', LedgerEntry.store_id == store_id, LedgerEntry.kind == 'cash_sale', LedgerEntry.settled.is_(False))).all()
    gross = money(sum((Decimal(t or 0) for t, _ in rows), Decimal('0')))
    commission = money(sum((Decimal(c or 0) for _, c in rows), Decimal('0')))
    return {'pending': pending, 'in_settlement': in_settlement, 'unassigned': pending - in_settlement, 'settled': settled,
            'cash_sales_gross': gross, 'cash_sales_commission': commission, 'cash_sales_net': cash_sales}


def movements(db: Session, account: str, *, store_id=None, courier_id=None, limit=200):
    q = select(LedgerEntry).where(LedgerEntry.account == account)
    if store_id is not None:
        q = q.where(LedgerEntry.store_id == store_id)
    if courier_id is not None:
        q = q.where(LedgerEntry.courier_id == courier_id)
    return db.scalars(q.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).limit(limit)).all()


# ---------- ajustes ----------

def adjust(db: Session, account: str, amount, reason: str, *, store_id=None, courier_id=None, user=None, ip=None) -> LedgerEntry:
    if not (reason or '').strip():
        raise FinanceError('Todo ajuste necesita un motivo.')
    if account not in ('merchant', 'courier_cash', 'courier_earnings') or (account == 'merchant') != (store_id is not None):
        raise FinanceError('Cuenta no válida.')
    amount = money(amount)
    if amount == 0:
        raise FinanceError('El ajuste no puede ser 0.')
    row = entry(db, account, 'adjustment', amount, store_id=store_id, courier_id=courier_id, description=reason.strip(), user=user)
    audit.log(db, 'ledger.adjustment', account, store_id or courier_id, user=user, amount_new=amount, reason=reason, ip=ip)
    return row


# ---------- rendiciones de efectivo ----------

def create_remittance(db: Session, courier: Courier, received, *, order_ids: list[int] | None = None, receipt='', notes='', user=None, ip=None) -> CashRemittance:
    """Registra la rendicion: lo esperado sale de la caja pendiente (o de los pedidos elegidos). No hace commit."""
    received = money(received)
    if received < 0:
        raise FinanceError('El importe recibido no puede ser negativo.')
    q = select(LedgerEntry).where(LedgerEntry.account == 'courier_cash', LedgerEntry.courier_id == courier.id, LedgerEntry.settled.is_(False))
    if order_ids:
        q = q.where(LedgerEntry.order_id.in_(order_ids))
    rows = db.scalars(q.with_for_update()).all()
    if not rows:
        raise FinanceError('Este repartidor no tiene efectivo pendiente de rendir' + (' en esos pedidos.' if order_ids else '.'))
    expected = money(sum((r.amount for r in rows), Decimal('0')))
    rem = CashRemittance(courier_id=courier.id, expected=expected, received=received, difference=received - expected,
                         order_ids=json.dumps(sorted({r.order_id for r in rows if r.order_id})), receipt=(receipt or '').strip()[:1000] or None,
                         notes=(notes or '').strip() or None, user_id=getattr(user, 'id', None))
    db.add(rem)
    db.flush()
    for r in rows:
        r.settled, r.remittance_id = True, rem.id
        if r.order_id:
            o = db.get(Order, r.order_id)
            if o:
                o.cash_pending = ZERO
    if rem.difference != 0:
        # faltante: sigue debiendolo / sobrante: queda a favor del repartidor
        entry(db, 'courier_cash', 'remittance_difference', -rem.difference, courier_id=courier.id,
              description=f'Diferencia de la rendición #{rem.id}', dedupe=f'remittance:{rem.id}:difference', user=user)
    audit.log(db, 'remittance.create', 'courier', courier.id, user=user, amount_old=expected, amount_new=received, reason=notes, ip=ip,
              new={'remittance': rem.id, 'orders': json.loads(rem.order_ids)})
    return rem


# ---------- liquidaciones ----------

def create_merchant_settlement(db: Session, store_id: int, *, user=None, ip=None, method='transferencia', notes='') -> MerchantSettlement | None:
    """Junta todo lo pendiente del comercio en una liquidacion. None si no hay nada. No hace commit."""
    rows = db.scalars(select(LedgerEntry).where(LedgerEntry.account == 'merchant', LedgerEntry.store_id == store_id, LedgerEntry.settled.is_(False),
                                                LedgerEntry.merchant_settlement_id.is_(None)).with_for_update()).all()
    if not rows:
        return None
    total = money(sum((r.amount for r in rows), Decimal('0')))
    st = MerchantSettlement(store_id=store_id, total=total, entries_count=len(rows), method=method, notes=(notes or '').strip() or None, user_id=getattr(user, 'id', None))
    db.add(st)
    db.flush()
    for r in rows:
        r.merchant_settlement_id = st.id
    audit.log(db, 'settlement.merchant.create', 'merchant_settlement', st.id, user=user, amount_new=total, ip=ip, new={'store': store_id, 'entries': len(rows)})
    return st


def generate_merchant_settlements(db: Session, *, user=None, ip=None) -> list[MerchantSettlement]:
    """Liquidaciones automaticas: una por cada comercio con saldo pendiente. No hace commit."""
    ids = db.scalars(select(LedgerEntry.store_id).where(LedgerEntry.account == 'merchant', LedgerEntry.settled.is_(False),
                                                       LedgerEntry.merchant_settlement_id.is_(None)).distinct()).all()
    out = []
    for sid in ids:
        st = create_merchant_settlement(db, sid, user=user, ip=ip, notes='Generada automáticamente')
        if st and st.total != 0:
            out.append(st)
        elif st:
            st.status = 'paid'  # saldo cero: se cierra sola
            st.paid_at = datetime.utcnow()
            for r in db.scalars(select(LedgerEntry).where(LedgerEntry.merchant_settlement_id == st.id)):
                r.settled = True
    return out


def create_courier_settlement(db: Session, courier: Courier, *, bonuses=0, adjustments=0, notes='', user=None, ip=None) -> CourierSettlement:
    rows = db.scalars(select(LedgerEntry).where(LedgerEntry.account == 'courier_earnings', LedgerEntry.courier_id == courier.id, LedgerEntry.settled.is_(False),
                                                LedgerEntry.courier_settlement_id.is_(None)).with_for_update()).all()
    bonuses, adjustments = money(bonuses), money(adjustments)
    if not rows and not bonuses and not adjustments:
        raise FinanceError('Este repartidor no tiene ganancias pendientes.')
    earnings = money(sum((r.amount for r in rows), Decimal('0')))
    account = payout_account(db, courier.id)
    st = CourierSettlement(courier_id=courier.id, earnings=earnings, bonuses=bonuses, adjustments=adjustments, total=earnings + bonuses + adjustments,
                           entries_count=len(rows), method='transferencia', notes=(notes or '').strip() or None, user_id=getattr(user, 'id', None),
                           payout_account_id=account.id if account else None, account_masked=masked_account(account) if account else None)
    db.add(st)
    db.flush()
    for r in rows:
        r.courier_settlement_id = st.id
    for kind, value in (('bonus', bonuses), ('adjustment', adjustments)):
        if value:
            row = entry(db, 'courier_earnings', kind, value, courier_id=courier.id, description=f'{kind} de la liquidación #{st.id}',
                        dedupe=f'courier_settlement:{st.id}:{kind}', user=user)
            if row:
                row.courier_settlement_id = st.id
    audit.log(db, 'settlement.courier.create', 'courier_settlement', st.id, user=user, amount_new=st.total, ip=ip,
              new={'courier': courier.id, 'earnings': str(earnings), 'bonuses': str(bonuses), 'adjustments': str(adjustments)})
    return st


def set_settlement_status(db: Session, st, status: str, *, receipt='', notes='', user=None, ip=None) -> None:
    """pending -> processing -> paid | failed | cancelled. Pagada o cancelada ya no cambia. No hace commit."""
    if status not in SETTLEMENT_STATUSES:
        raise FinanceError('Estado no válido.')
    if st.status in ('paid', 'cancelled'):
        raise FinanceError('Esa liquidación ya está cerrada.')
    old = st.status
    st.status = status
    if receipt:
        st.receipt = receipt.strip()[:1000]
    if notes:
        st.notes = ((st.notes + '\n') if st.notes else '') + notes.strip()
    field = 'merchant_settlement_id' if isinstance(st, MerchantSettlement) else 'courier_settlement_id'
    rows = db.scalars(select(LedgerEntry).where(getattr(LedgerEntry, field) == st.id)).all()
    if status == 'paid':
        st.paid_at = datetime.utcnow()
        for r in rows:
            r.settled = True
    elif status in ('failed', 'cancelled'):
        for r in rows:  # vuelven a quedar pendientes para otra liquidacion
            if r.kind in ('bonus', 'adjustment') and isinstance(st, CourierSettlement):
                r.settled = True  # el bono/ajuste de esta liquidacion se anula con un contra-asiento
                entry(db, 'courier_earnings', 'reversal', -r.amount, courier_id=r.courier_id, settled=True,
                      description=f'Anulación de {r.kind} de la liquidación #{st.id}', dedupe=f'reversal:{r.id}')
            else:
                setattr(r, field, None)
    audit.log(db, f'settlement.{status}', type(st).__tablename__, st.id, user=user, old=old, new=status, amount_new=st.total, reason=notes, ip=ip)


# ---------- datos de cobro del repartidor ----------

def payout_account(db: Session, courier_id: int) -> CourierPayoutAccount | None:
    return db.scalar(select(CourierPayoutAccount).where(CourierPayoutAccount.courier_id == courier_id, CourierPayoutAccount.current.is_(True))
                     .order_by(CourierPayoutAccount.id.desc()))


def masked_account(acct: CourierPayoutAccount | None) -> str:
    if not acct:
        return ''
    kind = 'CVU' if acct.cvu_enc else ('CBU' if acct.cbu_enc else 'Alias')
    tail = f'•••• {acct.last4}' if acct.last4 else (acct.alias or '')
    return f'{kind} {tail} · {acct.holder}'.strip()


def _digits(value: str) -> str:
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def save_payout_account(db: Session, courier: Courier, *, holder: str, provider='', cbu='', cvu='', alias='', account_type='', verification='pendiente',
                        user=None, ip=None, reason='') -> CourierPayoutAccount:
    """Nueva version de los datos de cobro (la anterior queda en el historial). No hace commit."""
    cbu, cvu = _digits(cbu), _digits(cvu)
    for label, value in (('CBU', cbu), ('CVU', cvu)):
        if value and len(value) != 22:
            raise FinanceError(f'El {label} tiene que tener 22 números.')
    if not (holder or '').strip():
        raise FinanceError('Poné el titular de la cuenta.')
    if not (cbu or cvu or (alias or '').strip()):
        raise FinanceError('Cargá un CBU, un CVU o un alias.')
    if verification not in ('pendiente', 'verificado', 'rechazado'):
        verification = 'pendiente'
    old = payout_account(db, courier.id)
    if old:
        old.current = False
    acct = CourierPayoutAccount(courier_id=courier.id, holder=holder.strip()[:160], provider=(provider or '').strip()[:80] or None,
                                cbu_enc=crypto.encrypt(cbu), cvu_enc=crypto.encrypt(cvu), last4=(cvu or cbu)[-4:] or None,
                                alias=(alias or '').strip()[:60] or None, account_type=(account_type or '').strip()[:30] or None,
                                verification=verification, current=True, user_id=getattr(user, 'id', None))
    db.add(acct)
    db.flush()
    audit.log(db, 'payout_account.update', 'courier', courier.id, user=user, old=masked_account(old) if old else None, new=masked_account(acct), reason=reason, ip=ip)
    return acct
