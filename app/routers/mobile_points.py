"""Puntos Trappi en el mostrador: el cliente escanea el QR de la caja del local y paga con sus puntos.

Se separó de mobile_api.py (mismas rutas, mismo prefijo /api/v1): los helpers y servicios compartidos vienen de ahí."""
from fastapi import APIRouter

from .mobile_api import *  # noqa: F401,F403  (helpers, modelos de datos y servicios compartidos)

router = APIRouter()


# ---------- escanear QR de Puntos Trappi en un local (programa Trappi Caja) ----------

def _scan_error(status: int, message: str) -> JSONResponse:
    return JSONResponse({'ok': False, 'error': message}, status_code=status)


@router.get('/points/claim/{code}')
def points_claim_info(code: str, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """QR del ticket: cuántos puntos da y de qué local (para mostrarlo antes de sumarlos)."""
    from ..models import Store
    from ..services import pos
    if not current_account(db, authorization):
        return no_session()
    c, problem = pos.claim_status(db, code)
    if not c:
        return _scan_error(404, problem)
    store = db.get(Store, c.store_id)
    return {'ok': problem is None, 'error': problem, 'code': c.code, 'points': c.points, 'store': store.name if store else '', 'expires_at': iso(c.expires_at)}


@router.post('/points/claim/{code}')
def points_claim_app(code: str, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    from ..services import pos
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    try:
        c = pos.claim(db, code, acct)
        db.commit()
    except pos.PosError as exc:
        db.rollback()
        return _scan_error(exc.status, str(exc))
    s = loyalty.summary(db, acct)
    return {'ok': True, 'points': c.points, 'balance': s['points'] if s else None}


class CounterIn(BaseModel):
    code: str = Field(..., max_length=8)


@router.post('/points/counter/{counter}/quote')
def points_counter_quote(counter: str, body: CounterIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """QR del mostrador + el código de la caja: cuánto se descuenta (el cliente lo ve antes de confirmar)."""
    from ..services import pos_points
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    try:
        store, p, q = pos_points.lookup(db, counter, body.code, acct)
    except pos_points.PointsPayError as exc:
        return _scan_error(exc.status, str(exc))
    return {'ok': True, 'store': store.name, 'amount': num(p.amount), 'points': q['points'], 'discount': num(q['discount']), 'rest': num(q['rest']),
            'balance': q['balance'], 'max_percent': q['max_pct'], 'reason': q['reason']}


@router.post('/points/counter/{counter}/confirm')
def points_counter_confirm_app(counter: str, body: CounterIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    from ..services import pos_points
    acct = current_account(db, authorization)
    if not acct:
        return no_session()
    try:
        store, p, _ = pos_points.lookup(db, counter, body.code, acct)
        pos_points.confirm(db, store, p, acct)
        db.commit()
    except pos_points.PointsPayError as exc:
        db.rollback()
        return _scan_error(exc.status, str(exc))
    s = loyalty.summary(db, acct)
    return {'ok': True, 'store': store.name, 'amount': num(p.amount), 'points': p.points, 'discount': num(p.discount),
            'rest': num(p.amount - p.discount), 'balance': s['points'] if s else None}
