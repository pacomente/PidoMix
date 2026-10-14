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
"""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import PosSale, Product, ProductStatus, Role, Store, StoreSection, User
from ..services import pos
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
    return {'ok': True, 'token': pos.device_token(store), **me_json(db, store)}


def me_json(db: Session, store: Store) -> dict:
    shift = pos.open_shift(db, store)
    pc = pos.points_config(db)
    return {'store': {'id': store.id, 'name': store.name, 'address': store.address, 'phone': store.phone},
            'cashiers': [{'id': c.id, 'name': c.name, 'is_owner': c.is_owner} for c in pos.cashiers(db, store)],
            'shift': pos.shift_summary(db, shift) if shift else None,
            'points': {'enabled': pc['enabled'], 'per_point': float(pc['per_point']), 'days': pc['days']},
            'methods': [{'id': m, 'label': pos.METHOD_LABELS[m]} for m in pos.METHODS]}


@router.get('/me')
def me(db: Session = Depends(get_db), authorization: str = Header('')):
    try:
        return me_json(db, device(authorization, db))
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
    products = db.scalars(select(Product).where(Product.store_id == store.id, Product.deleted.is_(False), Product.status == ProductStatus.ACTIVO)
                          .order_by(Product.display_order, Product.name)).all()
    return {'sections': [{'id': s.id, 'name': s.name} for s in sections],
            'products': [{'id': p.id, 'name': p.name, 'price': float(p.price), 'barcode': p.barcode, 'section_id': p.section_id,
                          'image': cdn(p.image_url, 'thumb'), 'stock': p.stock} for p in products]}


class ShiftIn(BaseModel):
    amount: float = 0


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
        summary = pos.close_shift(db, store, cashier, body.amount)
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
