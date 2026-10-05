"""Mercado Pago Marketplace (Argentina): cada comercio conecta su cuenta por OAuth y cobra con su token;
Trappi se lleva su parte con marketplace_fee (Split 1:1).

Flujo de un pedido pagado online:
  1. checkout -> pedido PENDIENTE con payment_status=pending
  2. create_preference() con el token del comercio y marketplace_fee = parte de Trappi -> link de pago
  3. el cliente paga en Mercado Pago
  4. Mercado Pago avisa (webhook) -> se valida la firma x-signature, se descarta si ya se proceso
     (PaymentEvent) y se CONSULTA el pago a la API (nunca se confia en el cuerpo del aviso)
  5. si esta aprobado y coincide (pedido, importe, moneda, cuenta) -> pedido pagado; recien ahi el
     local lo puede aceptar y se ofrece a los repartidores

Credenciales: variables de entorno MERCADOPAGO_* (ver config.py y README). Sandbox o produccion con
MERCADOPAGO_ENVIRONMENT. Los tokens de los comercios se guardan cifrados (services/crypto.py).
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import MercadoPagoAccount, Order, OrderStatus, Payment, PaymentEvent, Store
from . import audit, crypto, payments as order_payments, plans, platform

logger = logging.getLogger('trappi.mercadopago')
TIMEOUT = 15.0
STATUS_MAP = {'approved': 'approved', 'authorized': 'pending', 'pending': 'pending', 'in_process': 'pending', 'in_mediation': 'pending',
              'rejected': 'rejected', 'cancelled': 'cancelled', 'refunded': 'refunded', 'charged_back': 'charged_back'}
FINAL_BAD = {'rejected', 'cancelled', 'expired'}

_transport: httpx.BaseTransport | None = None  # los tests ponen uno falso; en produccion, la red


class MPError(Exception):
    pass


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _request(method: str, path: str, token: str | None = None, *, json_body=None, form=None, params=None, idempotency: str | None = None) -> dict:
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if idempotency:
        headers['X-Idempotency-Key'] = idempotency
    url = settings.mercadopago_api_url.rstrip('/') + path
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport) as client:
            resp = client.request(method, url, json=json_body, data=form, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise MPError(f'No se pudo conectar con Mercado Pago: {exc}') from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        message = data.get('message') or data.get('error') or f'HTTP {resp.status_code}'
        raise MPError(f'Mercado Pago respondió: {message}')
    return data


# ---------- disponibilidad ----------

def configured() -> bool:
    return settings.mercadopago_configured


def account_for(db: Session, store_id: int) -> MercadoPagoAccount | None:
    return db.scalar(select(MercadoPagoAccount).where(MercadoPagoAccount.store_id == store_id))


def available_for(db: Session, store: Store) -> bool:
    """Se puede ofrecer Mercado Pago en el checkout de este comercio."""
    if not configured() or not platform.get_all(db)['mp_enabled']:
        return False
    acct = account_for(db, store.id)
    return bool(acct and acct.status == 'connected' and acct.access_token_enc)


# ---------- OAuth ----------

def _state_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt='trappi-mp-oauth')


def authorization_url(store_id: int, user_id: int) -> str:
    state = _state_signer().dumps({'s': store_id, 'u': user_id})
    query = urlencode({'client_id': settings.mercadopago_client_id, 'response_type': 'code', 'platform_id': 'mp',
                       'state': state, 'redirect_uri': settings.mercadopago_redirect_uri})
    return f'{settings.mercadopago_auth_url}?{query}'


def read_state(state: str) -> dict | None:
    try:
        return _state_signer().loads(state, max_age=900)
    except (BadSignature, SignatureExpired):
        return None


def _save_tokens(acct: MercadoPagoAccount, data: dict) -> None:
    acct.access_token_enc = crypto.encrypt(data.get('access_token'))
    if data.get('refresh_token'):
        acct.refresh_token_enc = crypto.encrypt(data['refresh_token'])
    acct.public_key = data.get('public_key') or acct.public_key
    acct.live_mode = bool(data.get('live_mode'))
    expires = int(data.get('expires_in') or 0)
    acct.expires_at = datetime.utcnow() + timedelta(seconds=expires) if expires else None
    acct.status, acct.last_error, acct.last_sync_at = 'connected', None, datetime.utcnow()


def connect(db: Session, store: Store, code: str, user=None, ip: str | None = None) -> MercadoPagoAccount:
    """Cambia el codigo de autorizacion por los tokens del comercio. No hace commit."""
    form = {'client_id': settings.mercadopago_client_id, 'client_secret': settings.mercadopago_client_secret,
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': settings.mercadopago_redirect_uri}
    if settings.mercadopago_sandbox:
        form['test_token'] = 'true'
    data = _request('POST', '/oauth/token', form=form)
    if not data.get('access_token') or not data.get('user_id'):
        raise MPError('Mercado Pago no devolvió las credenciales del comercio.')
    acct = account_for(db, store.id) or MercadoPagoAccount(store_id=store.id, mp_user_id=str(data['user_id']))
    previous = acct.mp_user_id if acct.id else None
    acct.mp_user_id = str(data['user_id'])
    acct.connected_at = datetime.utcnow()
    _save_tokens(acct, data)
    try:
        me = _request('GET', '/users/me', crypto.decrypt(acct.access_token_enc))
        acct.nickname = (me.get('nickname') or me.get('email') or '')[:120] or None
    except MPError:
        pass
    db.add(acct)
    audit.log(db, 'mercadopago.connect', 'store', store.id, user=user, old=previous, new=acct.mp_user_id, ip=ip)
    return acct


def disconnect(db: Session, acct: MercadoPagoAccount, user=None, ip: str | None = None) -> None:
    acct.access_token_enc = acct.refresh_token_enc = None
    acct.status = 'disconnected'
    audit.log(db, 'mercadopago.disconnect', 'store', acct.store_id, user=user, old=acct.mp_user_id, ip=ip)


def seller_token(db: Session, acct: MercadoPagoAccount) -> str:
    """Token del comercio (lo renueva si esta por vencer)."""
    if not acct or acct.status != 'connected' or not acct.access_token_enc:
        raise MPError('El comercio no tiene Mercado Pago conectado.')
    if acct.expires_at and acct.expires_at - datetime.utcnow() < timedelta(days=7) and acct.refresh_token_enc:
        try:
            data = _request('POST', '/oauth/token', form={'client_id': settings.mercadopago_client_id, 'client_secret': settings.mercadopago_client_secret,
                                                          'grant_type': 'refresh_token', 'refresh_token': crypto.decrypt(acct.refresh_token_enc)})
            _save_tokens(acct, data)
        except MPError as exc:
            acct.last_error = str(exc)[:255]
            if acct.expires_at <= datetime.utcnow():
                acct.status = 'error'
                raise
    token = crypto.decrypt(acct.access_token_enc)
    if not token:
        acct.status = 'error'
        raise MPError('No se pudo leer el token del comercio (¿cambió la clave de cifrado?). Hay que volver a conectarlo.')
    return token


# ---------- cobro de un pedido ----------

def split_amounts(order: Order) -> tuple[Decimal, Decimal]:
    """(marketplace_fee para Trappi, importe para el comercio), del snapshot del pedido."""
    b = plans.breakdown(order)
    total = plans.money(order.total)
    fee = min(max(b['trappi_amount'], Decimal('0.00')), total)
    return fee, total - fee


def create_preference(db: Session, order: Order, base_url: str, return_url: str) -> Payment:
    """Crea (o reusa) el link de pago del pedido con el token del comercio y el fee de Trappi. No hace commit."""
    if not order_payments.awaiting_online(order):
        raise MPError('Este pedido no espera un pago online.')
    current = db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.status == 'pending', Payment.preference_id.is_not(None)).order_by(Payment.id.desc()))
    if current and current.checkout_url and (not current.expires_at or current.expires_at > datetime.utcnow() + timedelta(minutes=2)):
        return current
    acct = account_for(db, order.store_id)
    token = seller_token(db, acct)
    fee, seller = split_amounts(order)
    minutes = platform.get_all(db)['online_payment_minutes']
    expires = datetime.utcnow() + timedelta(minutes=minutes)
    base = base_url.rstrip('/')
    body = {
        'items': [{'id': f'order-{order.id}', 'title': f'Pedido #{order.id} · {order.store.name}'[:250], 'quantity': 1,
                   'currency_id': 'ARS', 'unit_price': float(plans.money(order.total))}],
        'external_reference': f'trappi-order-{order.id}',
        'metadata': {'order_id': order.id},
        'notification_url': f'{base}/api/payments/mercadopago/webhook?source_news=webhooks',
        'back_urls': {'success': return_url, 'pending': return_url, 'failure': return_url},
        'auto_return': 'approved',
        'expires': True,
        'expiration_date_to': expires.strftime('%Y-%m-%dT%H:%M:%S.000-00:00'),
        'statement_descriptor': 'TRAPPI',
    }
    if fee > 0:
        body['marketplace_fee'] = float(fee)  # parte de Trappi; sin comision (Trappi Comercio) el 100 % es del comercio
    if order.customer and order.customer.first_name:
        body['payer'] = {'name': order.customer.first_name[:60], 'surname': (order.customer.last_name or '')[:60]}
    attempt = (db.scalar(select(Payment.id).where(Payment.order_id == order.id).order_by(Payment.id.desc())) or 0) + 1
    data = _request('POST', '/checkout/preferences', token, json_body=body, idempotency=f'trappi-pref-{order.id}-{attempt}')
    url = (data.get('sandbox_init_point') if settings.mercadopago_sandbox else data.get('init_point')) or data.get('init_point')
    if not data.get('id') or not url:
        raise MPError('Mercado Pago no devolvió el link de pago.')
    payment = Payment(order_id=order.id, provider='mercadopago', preference_id=str(data['id']), checkout_url=url, status='pending',
                      amount=plans.money(order.total), marketplace_fee=fee, seller_amount=seller, live_mode=not settings.mercadopago_sandbox, expires_at=expires)
    db.add(payment)
    return payment


# ---------- avisos (webhooks) ----------

def verify_signature(headers, query) -> bool:
    """Valida x-signature (HMAC-SHA256 con la clave secreta de Webhooks). Sin clave: solo se acepta en sandbox."""
    secret = settings.mercadopago_webhook_secret
    if not secret:
        return settings.mercadopago_sandbox
    raw = headers.get('x-signature') or ''
    parts = dict(p.strip().split('=', 1) for p in raw.split(',') if '=' in p)
    ts, v1 = parts.get('ts'), parts.get('v1')
    if not ts or not v1:
        return False
    data_id = str(query.get('data.id') or query.get('id') or '')
    if data_id.isalnum():
        data_id = data_id.lower()
    manifest = ''
    if data_id:
        manifest += f'id:{data_id};'
    if headers.get('x-request-id'):
        manifest += f"request-id:{headers.get('x-request-id')};"
    manifest += f'ts:{ts};'
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def handle_notification(db: Session, payload: dict, query, headers) -> str:
    """Procesa un aviso ya validado. Idempotente: el mismo evento se procesa una sola vez."""
    topic = payload.get('type') or payload.get('topic') or query.get('type') or query.get('topic') or ''
    resource = str((payload.get('data') or {}).get('id') or query.get('data.id') or query.get('id') or '')
    if topic != 'payment' or not resource:
        return 'ignorado'
    key = f"payment:{resource}:{payload.get('action') or ''}:{headers.get('x-request-id') or payload.get('id') or ''}"[:160]
    event = PaymentEvent(provider='mercadopago', event_key=key, topic=topic, resource_id=resource, payload=json.dumps(payload)[:5000])
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return 'duplicado'
    try:
        result = sync_payment(db, resource, collector_id=str(payload.get('user_id') or ''))
    except MPError as exc:
        db.rollback()
        logger.warning('Webhook de Mercado Pago sin procesar: %s', exc)
        raise
    event.result = result[:255]
    db.commit()
    return result


def _fees(data: dict) -> tuple[Decimal | None, Decimal | None]:
    processing = app_fee = None
    for f in data.get('fee_details') or []:
        amount = plans.money(f.get('amount'))
        if f.get('type') == 'mercadopago_fee':
            processing = (processing or Decimal('0')) + amount
        elif f.get('type') == 'application_fee':
            app_fee = (app_fee or Decimal('0')) + amount
    return processing, app_fee


def sync_payment(db: Session, mp_payment_id: str, collector_id: str = '') -> str:
    """Consulta el pago a Mercado Pago y actualiza el pedido. No confia en nada de lo que llega en el aviso."""
    from . import finance
    accounts = []
    known = db.scalar(select(Payment).where(Payment.provider == 'mercadopago', Payment.provider_payment_id == str(mp_payment_id)))
    if known:
        acct = account_for(db, known.order.store_id)
        accounts = [acct] if acct else []
    if not accounts and collector_id:
        accounts = list(db.scalars(select(MercadoPagoAccount).where(MercadoPagoAccount.mp_user_id == collector_id, MercadoPagoAccount.status == 'connected')))
    if not accounts:
        accounts = list(db.scalars(select(MercadoPagoAccount).where(MercadoPagoAccount.status == 'connected')))
    data, acct = None, None
    for candidate in accounts:
        try:
            data = _request('GET', f'/v1/payments/{mp_payment_id}', seller_token(db, candidate))
            acct = candidate
            break
        except MPError:
            continue
    if data is None:
        raise MPError(f'No se pudo consultar el pago {mp_payment_id} en Mercado Pago.')
    ref = str(data.get('external_reference') or '')
    if not ref.startswith('trappi-order-') or not ref.removeprefix('trappi-order-').isdigit():
        return 'ignorado: no es un pedido de Trappi'
    order = db.get(Order, int(ref.removeprefix('trappi-order-')))
    if not order or order.store_id != acct.store_id:
        return 'rechazado: el pedido no corresponde a esa cuenta'
    collector = str(data.get('collector_id') or (data.get('collector') or {}).get('id') or '')
    if collector and collector != acct.mp_user_id:
        return 'rechazado: cobró otra cuenta'
    if (data.get('currency_id') or 'ARS') != 'ARS' or abs(plans.money(data.get('transaction_amount')) - plans.money(order.total)) > Decimal('0.01'):
        audit.log(db, 'payment.mismatch', 'order', order.id, old=str(order.total), new=str(data.get('transaction_amount')), reason='importe o moneda distintos')
        db.flush()
        return 'rechazado: el importe no coincide'
    payment = db.scalar(select(Payment).where(Payment.provider == 'mercadopago', Payment.provider_payment_id == str(data['id'])))
    if payment is None:
        payment = db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.provider_payment_id.is_(None)).order_by(Payment.id.desc()))
        if payment is None:
            fee, seller = split_amounts(order)
            payment = Payment(order_id=order.id, provider='mercadopago', amount=plans.money(order.total), marketplace_fee=fee, seller_amount=seller)
            db.add(payment)
        payment.provider_payment_id = str(data['id'])
    status = STATUS_MAP.get(data.get('status'), 'pending')
    refunded = plans.money(data.get('transaction_amount_refunded'))
    if status == 'approved' and refunded > 0:
        status = 'partially_refunded'
    if status == 'cancelled' and (data.get('status_detail') or '') == 'expired':
        status = 'expired'
    processing, app_fee = _fees(data)
    previous = payment.status
    now = datetime.utcnow()
    payment.status, payment.external_status = status, f"{data.get('status')}/{data.get('status_detail') or ''}"[:60]
    payment.payment_method = (data.get('payment_method_id') or data.get('payment_type_id') or '')[:40] or None
    payment.live_mode = bool(data.get('live_mode'))
    payment.processing_fee = processing
    if app_fee is not None:
        payment.marketplace_fee = app_fee
        payment.seller_amount = plans.money(order.total) - app_fee
    payment.refunded_amount = refunded
    acct.last_sync_at = now
    if status == 'approved' and previous != 'approved':
        payment.approved_at = payment.approved_at or now
    if status in FINAL_BAD and previous != status:
        payment.rejected_at = now
    if status in ('refunded', 'partially_refunded', 'charged_back'):
        payment.refunded_at = payment.refunded_at or now
    # ---- el pedido ----
    order.payment_processing_fee = processing
    if status in ('approved', 'partially_refunded') and not order_payments.is_paid(order):
        order_payments.mark_paid(order, 'online', now)
        order.payment_status = 'approved'
        finance.on_online_paid(db, order, payment)
    elif status in ('refunded', 'charged_back', 'partially_refunded') and previous != status:
        order.payment_status = status
        finance.on_refund(db, order, payment, refunded or plans.money(order.total))
    elif status in FINAL_BAD and not order_payments.is_paid(order):
        order.payment_status = status
        if status in ('expired', 'cancelled') and order.status == OrderStatus.PENDIENTE:
            order.status = OrderStatus.CANCELADO
            from .orders import record
            record(order, OrderStatus.CANCELADO)
    elif status == 'pending' and not order_payments.is_paid(order):
        order.payment_status = 'pending'
    db.flush()
    return f'{previous}->{status}'


def refund(db: Session, payment: Payment, amount: Decimal | None = None, user=None, reason: str = '', ip: str | None = None) -> str:
    """Devuelve el pago (total o parcial) en Mercado Pago y sincroniza. No hace commit."""
    if payment.status not in ('approved', 'partially_refunded') or not payment.provider_payment_id:
        raise MPError('Solo se pueden devolver pagos aprobados.')
    acct = account_for(db, payment.order.store_id)
    body = {'amount': float(amount)} if amount is not None else {}
    _request('POST', f'/v1/payments/{payment.provider_payment_id}/refunds', seller_token(db, acct), json_body=body,
             idempotency=f'trappi-refund-{payment.id}-{amount or "total"}-{payment.refunded_amount}')
    audit.log(db, 'payment.refund', 'payment', payment.id, user=user, amount_old=payment.amount, amount_new=amount if amount is not None else payment.amount,
              reason=reason, ip=ip)
    return sync_payment(db, payment.provider_payment_id)


def reconcile(db: Session, order: Order) -> str | None:
    """Busca en Mercado Pago pagos de este pedido (por si se perdio un aviso)."""
    acct = account_for(db, order.store_id)
    if not acct or acct.status != 'connected':
        return None
    data = _request('GET', '/v1/payments/search', seller_token(db, acct), params={'external_reference': f'trappi-order-{order.id}', 'sort': 'date_created', 'criteria': 'desc'})
    results = data.get('results') or []
    return sync_payment(db, str(results[0]['id'])) if results else None


def expire_stale(db: Session, now: datetime | None = None) -> int:
    """Cancela los pedidos online que no se pagaron a tiempo (antes, pregunta a Mercado Pago). Hace commit."""
    now = now or datetime.utcnow()
    stale = db.scalars(select(Payment).where(Payment.status == 'pending', Payment.expires_at.is_not(None), Payment.expires_at < now)).all()
    done = 0
    for payment in stale:
        order = payment.order
        try:
            if reconcile(db, order) and order_payments.is_paid(order):
                continue
        except MPError:
            continue  # sin respuesta de Mercado Pago no se cancela nada
        if payment.status == 'pending':
            payment.status, payment.rejected_at = 'expired', now
        if order_payments.awaiting_online(order) and order.status == OrderStatus.PENDIENTE:
            from .orders import record
            order.payment_status = 'expired'
            order.status = OrderStatus.CANCELADO
            record(order, OrderStatus.CANCELADO)
            done += 1
    # pedidos online que nunca abrieron el link de pago (no tienen Payment): mismo plazo
    limit = now - timedelta(minutes=platform.get_all(db)['online_payment_minutes'])
    for order in db.scalars(select(Order).where(Order.payment_method.in_(order_payments.ONLINE), Order.paid_at.is_(None),
                                                Order.status == OrderStatus.PENDIENTE, Order.created_at < limit)):
        if db.scalar(select(Payment.id).where(Payment.order_id == order.id).limit(1)):
            continue  # tiene link de pago: lo resuelve el bloque de arriba cuando vence
        from .orders import record
        order.payment_status = 'expired'
        order.status = OrderStatus.CANCELADO
        record(order, OrderStatus.CANCELADO)
        done += 1
    db.commit()
    return done


_last_sweep = {'at': None}


def expire_stale_throttled(db: Session, every_seconds: int = 60) -> int:
    """expire_stale como mucho una vez por minuto (lo llama comandas, que consulta cada 10 s). Nunca rompe la pantalla."""
    now = datetime.utcnow()
    if _last_sweep['at'] and (now - _last_sweep['at']).total_seconds() < every_seconds:
        return 0
    _last_sweep['at'] = now
    try:
        return expire_stale(db, now)
    except Exception:  # noqa: BLE001 - un error de Mercado Pago o de la base no puede frenar comandas
        db.rollback()
        logger.exception('No se pudieron vencer los pagos online pendientes')
        return 0


# ---------- diagnostico (pantalla /admin/pagos/diagnostico) ----------

def _tail(value: str) -> str:
    return f'…{value[-4:]}' if len(value) > 4 else '(muy corto)'


def diagnose(db: Session, base_url: str) -> list[dict]:
    """Cada pieza de la configuracion con su estado. Nunca muestra secretos: solo si estan y sus ultimos 4."""
    expected = base_url.rstrip('/') + '/admin/pagos/mercadopago/callback'
    env = settings.mercadopago_environment.lower()
    out = []

    def check(name, ok, detail, fix=''):
        out.append({'name': name, 'state': 'ok' if ok is True else ('warn' if ok is None else 'bad'), 'detail': detail, 'fix': fix})

    cid, secret = settings.mercadopago_client_id, settings.mercadopago_client_secret
    check('MERCADOPAGO_CLIENT_ID', bool(cid) and cid.isdigit(), f'cargado ({_tail(cid)})' if cid else 'falta',
          '' if not cid or cid.isdigit() else 'Tiene que ser el número "Client ID" / "App ID" de la aplicación (solo números), no la Public Key ni el Access Token.')
    check('MERCADOPAGO_CLIENT_SECRET', bool(secret), f'cargado ({_tail(secret)})' if secret else 'falta',
          '' if secret else 'Es el "Client Secret" de la aplicación (Credenciales de producción).')
    uri = settings.mercadopago_redirect_uri
    if not uri:
        check('MERCADOPAGO_REDIRECT_URI', False, 'falta', f'Cargá exactamente: {expected}')
    elif uri.rstrip('/') != expected:
        check('MERCADOPAGO_REDIRECT_URI', False, uri, f'No coincide con este sitio. Tiene que ser exactamente: {expected} (y la misma en la aplicación de Mercado Pago).')
    else:
        check('MERCADOPAGO_REDIRECT_URI', True, uri, 'Tiene que estar cargada igual en Mercado Pago Developers → tu aplicación → Redirect URL.')
    check('MERCADOPAGO_ENVIRONMENT', env in ('sandbox', 'production'), env or 'vacío',
          '' if env in ('sandbox', 'production') else 'Tiene que ser sandbox o production.')
    wh = settings.mercadopago_webhook_secret
    check('MERCADOPAGO_WEBHOOK_SECRET', True if wh else (None if settings.mercadopago_sandbox else False), 'cargada' if wh else 'falta',
          '' if wh else ('En sandbox se aceptan avisos sin firma; en producción se rechazan.' if settings.mercadopago_sandbox else
                         'Sin la clave de Webhooks, en producción se rechazan los avisos de pago.'))
    pub = settings.public_base_url
    check('PUBLIC_BASE_URL', (True if pub.startswith('https://') else False) if pub else None, pub or f'no cargada (se usa {base_url})',
          '' if pub.startswith('https://') else f'Recomendado: {base_url}')
    ks = crypto.key_status()
    check('FIELD_ENCRYPTION_KEY', True if ks == 'fernet' else None,
          {'fernet': 'clave válida', 'derived': 'cargada (no es una clave Fernet: se deriva una de ese texto)', 'secret_key': 'no cargada (se deriva de SECRET_KEY)'}[ks],
          '' if ks == 'fernet' else 'Funciona igual. No la cambies después: si cambia hay que volver a conectar las cuentas.')
    check('Pago online prendido', bool(platform.get_all(db)['mp_enabled']), 'sí' if platform.get_all(db)['mp_enabled'] else 'apagado en Configuración',
          '' if platform.get_all(db)['mp_enabled'] else 'Prendelo en Configuración → Pagos.')
    return out


def test_credentials() -> tuple[bool, str]:
    """Le pide a Mercado Pago un token de la aplicacion con CLIENT_ID + CLIENT_SECRET (no cobra ni guarda nada)."""
    if not settings.mercadopago_client_id or not settings.mercadopago_client_secret:
        return False, 'Faltan MERCADOPAGO_CLIENT_ID o MERCADOPAGO_CLIENT_SECRET.'
    try:
        data = _request('POST', '/oauth/token', form={'client_id': settings.mercadopago_client_id, 'client_secret': settings.mercadopago_client_secret,
                                                      'grant_type': 'client_credentials'})
    except MPError as exc:
        return False, f'{exc}. Revisá que CLIENT_ID y CLIENT_SECRET sean de la misma aplicación.'
    if not data.get('access_token'):
        return False, 'Mercado Pago no devolvió un token para esas credenciales.'
    return True, 'Mercado Pago aceptó CLIENT_ID y CLIENT_SECRET' + (f" (aplicación de la cuenta {data['user_id']})." if data.get('user_id') else '.')
