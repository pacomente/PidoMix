"""Panel: reclamos de los clientes. El local ve los de sus pedidos, contesta o da un cupón suyo;
Trappi ve todos y los resuelve (puntos, cupón del local o reintegro por Mercado Pago desde el pedido)."""
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Order, OrderClaim, Role
from ..services import audit, claims
from ..services.forms import form_float, form_int
from ..services.ratelimit import client_ip
from .admin import guard, templates

router = APIRouter()


def _claim(db: Session, u, claim_id: int) -> OrderClaim | None:
    c = db.scalar(select(OrderClaim).options(joinedload(OrderClaim.order).joinedload(Order.store)).where(OrderClaim.id == claim_id))
    if c is None or (u.role != Role.SUPERADMIN and c.store_id != u.store_id):
        return None
    return c


@router.get('/reclamos', response_class=HTMLResponse)
def claims_page(request: Request, ver: str = 'abiertos', db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN and not u.store_id: return RedirectResponse('/admin', 303)
    q = select(OrderClaim).options(joinedload(OrderClaim.order).joinedload(Order.store)).order_by(OrderClaim.created_at.desc()).limit(100)
    if u.role != Role.SUPERADMIN:
        q = q.where(OrderClaim.store_id == u.store_id)
    if ver != 'todos':
        q = q.where(OrderClaim.status == 'abierto')
    return templates.TemplateResponse(request, 'admin/claims.html', {
        'user': u, 'rows': db.scalars(q).unique().all(), 'ver': ver, 'reasons': claims.REASONS, 'resolutions': claims.RESOLUTIONS,
        'error': request.session.pop('claim_error', None), 'ok': request.query_params.get('ok')})


@router.post('/reclamos/{claim_id}/responder')
def claim_reply(claim_id: int, request: Request, note: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    c = _claim(db, u, claim_id)
    if c is None: return RedirectResponse('/admin/reclamos', 303)
    try:
        claims.store_reply(db, c, note)
    except claims.ClaimError as exc:
        request.session['claim_error'] = str(exc)
        return RedirectResponse('/admin/reclamos', 303)
    db.commit()
    return RedirectResponse('/admin/reclamos?ok=reply', 303)


@router.post('/reclamos/{claim_id}/resolver')
def claim_resolve(claim_id: int, request: Request, resolution: str = Form(''), answer: str = Form(''), points: str = Form(''), amount: str = Form(''),
                  db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    c = _claim(db, u, claim_id)
    if c is None: return RedirectResponse('/admin/reclamos', 303)
    try:
        claims.resolve(db, c, u, resolution, answer, points=form_int(points, 0) or 0, amount=Decimal(str(form_float(amount, 0) or 0)),
                       superadmin=u.role == Role.SUPERADMIN)
    except claims.ClaimError as exc:
        db.rollback()
        request.session['claim_error'] = str(exc)
        return RedirectResponse('/admin/reclamos', 303)
    audit.log(db, 'claim.resolve', 'order_claim', c.id, user=u, new={'resolution': resolution, 'points': c.points, 'coupon': c.coupon_id}, ip=client_ip(request))
    db.commit()
    return RedirectResponse('/admin/reclamos?ok=resolved', 303)
