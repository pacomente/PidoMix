"""API del programa Trappi Caja (Windows). Ver services/pos.py.

  POST /link                     vincular la compu con el usuario del local (devuelve el token de la caja)
  GET  /me                       comercio, cajeros, caja abierta y reglas de puntos
  POST /cashiers/login           el cajero pone su PIN (devuelve su token, X-Cashier)
  GET  /catalog                  productos del menú (con código de barras) y secciones
  POST /shifts/open | /close     abrir la caja con el fondo / cerrarla con el efectivo contado
  GET  /shifts/current           resumen de la caja abierta
  POST /sales                    subir ventas (una o varias, también las que quedaron sin internet)
  GET  /sales                    últimas ventas
  POST /sales/{id}/void          anular (solo el dueño)
  POST /approvals                el dueño autoriza un descuento grande (devuelve una autorización que viaja con la venta)
  POST /cash-movements           retiro (lo autoriza el dueño) o ingreso de efectivo en la caja abierta
  POST /phone-orders             pedido por teléfono: entra al tablero de Comandas como un pedido aceptado
  POST /kitchen-tickets          tandas de las mesas para la cocina (también las que quedaron sin internet)
  GET  /customers?phone=         cliente frecuente (lo que compró en este local)
  POST /products/{id}/stock      agotar / volver a tener un producto (también en la app y la web)
  GET  /reports/today            resumen del día (solo el dueño)
"""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from sqlalchemy.orm import selectinload

from ..models import ModifierGroup, PosSale, Product, ProductStatus, Role, Store, StoreSection, User
from ..services import pos, pos_phone, pos_points, pos_salon
from ..services.auth import verify_password
from ..services.images import cdn
from ..services.ratelimit import PersistentRateLimiter, client_ip

router = APIRouter()
link_limiter = PersistentRateLimiter('pos-link', limit=8, window_seconds=600)
pin_limiter = PersistentRateLimiter('pos-pin', limit=8, window_seconds=600)


def err(e: pos.PosError):
    return JSONResponse({'ok': False, 'error': str(e)}, status_code=e.status)


def device(authorization: str = Header(''), db: Session = Depends(get_db)) -> Store:
    return pos.store_from_token(db, authorization.removeprefix('Bearer ').strip())


class LinkIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


@router.post('/link')
def link(body: LinkIn, request: Request, db: Session = Depends(get_db)):
    key = f'{client_ip(request)}|{body.email.strip().lower()}'
    if link_limiter.blocked(key):
        return JSONResponse({'ok': False, 'error': 'Demasiados intentos. Esperá unos minutos.'}, status_code=429)
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not u or not u.active or not verify_password(body.password, u.password_hash) or u.role == Role.SUPERADMIN or not u.store_id:
        link_limiter.hit(key)
        return JSONResponse({'ok': False, 'error': 'Email o contraseña incorrectos (tiene que ser el usuario del local).'}, status_code=401)
    store = db.get(Store, u.store_id)
    if not pos.available(db, store):
        return JSONResponse({'ok': False, 'error': 'La caja no está habilitada para tu comercio. Escribile a Trappi.'}, status_code=403)
    link_limiter.reset(key)
    data = me_json(db, store)
    db.commit()  # por si se creó el código del QR del mostrador
    return {'ok': True, 'token': pos.device_token(store), **data}


def me_json(db: Session, store: Store) -> dict:
    shift = pos.open_shift(db, store)
    pc = pos.points_config(db)
    return {'store': {'id': store.id, 'name': store.name, 'address': store.address, 'phone': store.phone},
            'cashiers': [{'id': c.id, 'name': c.name, 'is_owner': c.is_owner} for c in pos.cashiers(db, store)],
            'shift': pos.shift_summary(db, shift) if shift else None,
            'points': {'enabled': pc['enabled'], 'per_point': float(pc['per_point']), 'days': pc['days']},
            'methods': [{'id': m, 'label': pos.METHOD_LABELS[m]} for m in pos.METHODS],
            'free_discount_pct': float(pos.FREE_DISCOUNT_PCT), 'bills': list(pos.BILLS),
            'delivery': pos_phone.delivery_options(store),
            'features': pos_salon.features(store),  # lo que Trappi le habilitó: la caja oculta lo demás
            'points_pay': ({'enabled': True, 'counter_url': pos_points.counter_url(pos_points.counter_code(db, store))}
                           if pos_points.enabled(db, store) else {'enabled': False})}


@router.get('/me')
def me(db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        data = me_json(db, device(authorization, db))
        db.commit()
        return data
    except pos.PosError as e:
        return err(e)


class PinIn(BaseModel):
    cashier_id: int
    pin: str = Field(max_length=12)


@router.post('/cashiers/login')
def cashier_login(body: PinIn, db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        store = device(authorization, db)
    except pos.PosError as e:
        return err(e)
    key = f'{store.id}|{body.cashier_id}'
    if pin_limiter.blocked(key):
        return JSONResponse({'ok': False, 'error': 'Demasiados intentos con ese cajero. Esperá unos minutos.'}, status_code=429)
    from ..models import PosCashier
    c = db.get(PosCashier, body.cashier_id)
    if not c or c.store_id != store.id or not c.active or not verify_password(body.pin, c.pin_hash):
        pin_limiter.hit(key)
        return JSONResponse({'ok': False, 'error': 'PIN incorrecto.'}, status_code=401)
    pin_limiter.reset(key)
    return {'ok': True, 'token': pos.cashier_token(c), 'cashier': {'id': c.id, 'name': c.name, 'is_owner': c.is_owner}}


def _both(db: Session, authorization: str, x_cashier: str | None):
    store = device(authorization, db)
    return store, pos.cashier_from_token(db, store, x_cashier)


@router.get('/catalog')
def catalog(db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        store = device(authorization, db)
    except pos.PosError as e:
        return err(e)
    sections = db.scalars(select(StoreSection).where(StoreSection.store_id == store.id, StoreSection.active.is_(True)).order_by(StoreSection.display_order)).all()
    products = db.scalars(select(Product).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options))
                          .where(Product.store_id == store.id, Product.deleted.is_(False), Product.status == ProductStatus.ACTIVO)
                          .order_by(Product.display_order, Product.name)).all()
    ids = {p.id for p in products}
    return {'sections': [{'id': s.id, 'name': s.name} for s in sections],
            'products': [{'id': p.id, 'name': p.name, 'price': float(p.price), 'barcode': p.barcode, 'section_id': p.section_id,
                          'image': cdn(p.image_url, 'thumb'), 'stock': p.stock,
                          # las mismas opciones del menú online (gustos, tamaño, extras): las agotadas no se ofrecen
                          'groups': [{'id': g.id, 'name': g.name, 'required': g.required, 'min': g.min_select, 'max': g.max_select,
                                      'options': [{'id': o.id, 'name': o.name, 'price': float(o.price_extra)} for o in g.options if o.active]}
                                     for g in sorted(p.modifier_groups, key=lambda g: (g.display_order, g.id)) if any(o.active for o in g.options)]}
                         for p in products],
            'favorites': [pid for pid in pos.favorites(db, store) if pid in ids][:pos.FAVORITES],
            'promos': [pos_salon.promo_json(p) for p in pos_salon.store_promos(db, store.id)] if pos_salon.has(store, 'promos') else [],
            'tables': [pos_salon.table_json(t) for t in pos_salon.tables(db, store.id)] if pos_salon.has(store, 'tables') else []}


class ShiftIn(BaseModel):
    amount: float = 0
    bills: dict | None = None  # arqueo al cerrar: {"20000": 3, "1000": 7, "monedas": 350}


@router.post('/shifts/open')
def shift_open(body: ShiftIn, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        s = pos.start_shift(db, store, cashier, body.amount)
        db.commit()
        return pos.shift_summary(db, s)
    except pos.PosError as e:
        db.rollback(); return err(e)


@router.post('/shifts/close')
def shift_close(body: ShiftIn, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        if not cashier.is_owner:
            raise pos.PosError('Solo el dueño puede cerrar la caja.', 403)
        summary = pos.close_shift(db, store, cashier, body.amount, bills=body.bills)
        db.commit()
        return summary
    except pos.PosError as e:
        db.rollback(); return err(e)


@router.get('/shifts/current')
def shift_current(db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        store = device(authorization, db)
    except pos.PosError as e:
        return err(e)
    s = pos.open_shift(db, store)
    return {'shift': pos.shift_summary(db, s) if s else None}


class SalesIn(BaseModel):
    sales: list[dict] = Field(max_length=200)


@router.post('/sales')
def upload_sales(body: SalesIn, db: Session = Depends(get_db), authorization: str = Header('')):
    """Cada venta se guarda por separado: si una tiene un problema, las demás se suben igual."""
    try:
        store = device(authorization, db)
    except pos.PosError as e:
        return err(e)
    results = []
    for data in body.sales:
        try:
            sale = pos.record_sale(db, store, data)
            db.commit()
            results.append({'ok': True, **pos.sale_json(db, sale)})
        except pos.PosError as e:
            db.rollback()
            results.append({'ok': False, 'client_uuid': data.get('client_uuid'), 'error': str(e)})
    return {'results': results}


@router.get('/sales')
def recent_sales(limit: int = 30, db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        store = device(authorization, db)
    except pos.PosError as e:
        return err(e)
    rows = db.scalars(select(PosSale).where(PosSale.store_id == store.id).order_by(PosSale.id.desc()).limit(min(max(limit, 1), 100))).all()
    return {'sales': [pos.sale_json(db, s) for s in rows]}


@router.post('/sales/{sale_id}/void')
def void(sale_id: int, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        sale = pos.void_sale(db, store, sale_id, cashier)
        db.commit()
        return pos.sale_json(db, sale)
    except pos.PosError as e:
        db.rollback(); return err(e)


# ---------- pagar con Puntos Trappi (el cliente escanea el QR del mostrador) ----------

class PointsPayIn(BaseModel):
    amount: float


def perr(e: pos_points.PointsPayError):
    return JSONResponse({'ok': False, 'error': str(e)}, status_code=e.status)


@router.post('/points-payments')
def points_pay_create(body: PointsPayIn, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        p = pos_points.create(db, store, cashier, body.amount)
        data = pos_points.status_json(db, p)
        data['counter_url'] = pos_points.counter_url(store.pos_counter_code)
        db.commit()
        return data
    except pos.PosError as e:
        db.rollback(); return err(e)
    except pos_points.PointsPayError as e:
        db.rollback(); return perr(e)


@router.get('/points-payments/{payment_id}')
def points_pay_status(payment_id: int, db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        store = device(authorization, db)
        p = pos_points.get(db, store, payment_id)
        db.commit()
        return pos_points.status_json(db, p)
    except pos.PosError as e:
        return err(e)
    except pos_points.PointsPayError as e:
        return perr(e)


@router.post('/points-payments/{payment_id}/cancel')
def points_pay_cancel(payment_id: int, db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        store = device(authorization, db)
        p = pos_points.cancel(db, store, payment_id)
        db.commit()
        return pos_points.status_json(db, p)
    except pos.PosError as e:
        db.rollback(); return err(e)
    except pos_points.PointsPayError as e:
        db.rollback(); return perr(e)


# ---------- gastronomía: autorizaciones del dueño, retiros e ingresos, pedidos por teléfono ----------

class ApprovalIn(BaseModel):
    kind: str = Field(max_length=20)
    amount: float


@router.post('/approvals')
def approval(body: ApprovalIn, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    """X-Cashier es el del dueño que puso su PIN en la caja."""
    try:
        store, owner = _both(db, authorization, x_cashier)
        return {'ok': True, 'approval': pos.approval_token(store, owner, body.kind, body.amount), 'owner': owner.name}
    except pos.PosError as e:
        return err(e)


class MovementIn(BaseModel):
    client_uuid: str = Field(max_length=40)
    kind: str = Field(max_length=10)
    amount: float
    reason: str = Field('', max_length=200)


@router.post('/cash-movements')
def cash_movement(body: MovementIn, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    """Un retiro se manda con el X-Cashier del dueño que lo autorizó."""
    try:
        store, cashier = _both(db, authorization, x_cashier)
        pos.add_movement(db, store, cashier, body.model_dump())
        db.commit()
        s = pos.open_shift(db, store)
        return {'ok': True, 'shift': pos.shift_summary(db, s) if s else None}
    except pos.PosError as e:
        db.rollback(); return err(e)


class PhoneOrderIn(BaseModel):
    client_uuid: str = Field(max_length=40)
    items: list[dict] = Field(max_length=80)
    first_name: str = Field(max_length=100)
    phone: str = Field(max_length=40)
    delivery_method: str = Field(max_length=10)
    address: str = Field('', max_length=255)
    reference: str = Field('', max_length=255)
    notes: str = Field('', max_length=500)
    zone_id: int | None = None
    payment_method: str = Field('efectivo', max_length=20)
    cash_with: float | None = None


@router.post('/phone-orders')
def phone_order(body: PhoneOrderIn, request: Request, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        order = pos_phone.create(db, store, cashier, body.model_dump())
        db.commit()
    except pos.PosError as e:
        db.rollback(); return err(e)
    from .admin import wa_link
    from .public import order_token, public_base
    track = f'{public_base(request)}/pedido/{order.id}?t={order_token(order.id)}'
    text = (f'¡Hola {order.customer.first_name}! Recibimos tu pedido #{order.id} en {store.name}. '
            f'Total ${pos.money(order.total):,.0f}'.replace(',', '.') + f'. Seguilo acá: {track}')
    return {'ok': True, 'id': order.id, 'total': float(order.total), 'shipping': float(order.shipping), 'subtotal': float(order.subtotal),
            'track_url': track, 'whatsapp_url': wa_link(order.customer.phone, text) or None}


# ---------- salón: comandas por tanda, cliente frecuente, agotar y resumen ----------

class KitchenIn(BaseModel):
    tickets: list[dict] = Field(max_length=100)


@router.post('/kitchen-tickets')
def kitchen_tickets(body: KitchenIn, db: Session = Depends(get_db), authorization: str = Header('')):
    """Cada tanda se guarda por separado (como las ventas): si una tiene un problema, las demás entran igual."""
    try:
        store = device(authorization, db)
    except pos.PosError as e:
        return err(e)
    results = []
    for data in body.tickets:
        try:
            t = pos_salon.record_kitchen(db, store, data)
            db.commit()
            results.append({'ok': True, 'client_uuid': t.client_uuid, 'id': t.id})
        except pos.PosError as e:
            db.rollback()
            results.append({'ok': False, 'client_uuid': data.get('client_uuid'), 'error': str(e)})
    return {'results': results}


@router.get('/customers')
def customer(phone: str = '', db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, _ = _both(db, authorization, x_cashier)
        found = pos_salon.find_customer(db, store, phone)
    except pos.PosError as e:
        return err(e)
    if not found:
        return JSONResponse({'ok': False, 'error': 'No hay ningún cliente con cuenta Trappi con ese teléfono.'}, status_code=404)
    return {'ok': True, 'customer': found}


class StockIn(BaseModel):
    action: str = Field(max_length=10)


@router.post('/products/{product_id}/stock')
def product_stock(product_id: int, body: StockIn, db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        p = pos_salon.set_stock(db, store, product_id, body.action)
        from ..services import audit
        audit.log(db, f'product.stock.pos.{body.action}', 'product', p.id, new={'stock': p.stock}, reason=f'Desde la caja · {cashier.name}')
        db.commit()
        return {'ok': True, 'id': p.id, 'stock': p.stock, 'out_until': p.out_until.isoformat() + 'Z' if p.out_until else None}
    except pos.PosError as e:
        db.rollback(); return err(e)


@router.get('/reports/today')
def report_today(db: Session = Depends(get_db), authorization: str = Header(''), x_cashier: str | None = Header(None)):
    try:
        store, cashier = _both(db, authorization, x_cashier)
        pos_salon.require(store, 'report')
        if not cashier.is_owner:
            raise pos.PosError('El resumen del día lo ve el dueño.', 403)
    except pos.PosError as e:
        return err(e)
    data = pos_salon.day_report(db, store)
    s = pos.open_shift(db, store)
    return {'ok': True, **data, 'shift': pos.shift_summary(db, s) if s else None}
