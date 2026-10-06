"""Paginas legales: terminos y condiciones, politica de privacidad y boton de arrepentimiento.

Los datos del titular (razon social, CUIT, domicilio, email) se cargan en el panel:
Configuracion -> Clientes y datos legales. La version (fecha) de los textos esta en accounts.TERMS_VERSION.
"""
import secrets
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import WithdrawalRequest
from ..services import accounts, audit, csrf, platform
from ..services.ratelimit import PersistentRateLimiter, client_ip
from .public import ctx, templates

router = APIRouter()
withdrawal_limiter = PersistentRateLimiter('withdrawal', limit=5, window_seconds=3600)


def legal(db: Session) -> dict:
    cfg = platform.get_all(db)
    holder = (cfg.get('legal_name') or '').strip()
    return {
        'holder': holder or 'el titular de Trappi', 'holder_set': bool(holder), 'cuit': (cfg.get('legal_cuit') or '').strip(),
        'address': (cfg.get('legal_address') or '').strip(), 'email': (cfg.get('legal_email') or '').strip(),
        'jurisdiction': (cfg.get('legal_jurisdiction') or '').strip(), 'whatsapp': (cfg.get('platform_whatsapp') or '').strip(),
        'version': date.fromisoformat(accounts.TERMS_VERSION).strftime('%d/%m/%Y'),
    }


@router.get('/terminos', response_class=HTMLResponse)
def terms(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, 'public/legal_terms.html', ctx(request, L=legal(db)))


@router.get('/privacidad', response_class=HTMLResponse)
def privacy(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, 'public/legal_privacy.html', ctx(request, L=legal(db)))


@router.get('/arrepentimiento', response_class=HTMLResponse)
def withdrawal_page(request: Request, db: Session = Depends(get_db)):
    acct = accounts.from_session(request, db)
    return templates.TemplateResponse(request, 'public/legal_withdrawal.html', ctx(request, L=legal(db), acct=acct, done=None, error=None))


@router.post('/arrepentimiento', response_class=HTMLResponse, dependencies=[Depends(csrf.protect)])
def withdrawal_send(request: Request, name: str = Form(''), email: str = Form(''), phone: str = Form(''), order_ref: str = Form(''),
                    detail: str = Form(''), db: Session = Depends(get_db)):
    acct = accounts.from_session(request, db)
    page = lambda **kw: templates.TemplateResponse(request, 'public/legal_withdrawal.html', ctx(request, L=legal(db), acct=acct, **kw))
    name, email, phone = name.strip()[:160], email.strip()[:255], ''.join(ch for ch in phone if ch.isdigit() or ch in '+ -')[:40]
    if not name or not (email or phone):
        return page(done=None, error='Completá tu nombre y un email o teléfono para responderte.')
    ip = client_ip(request)
    if not withdrawal_limiter.check(ip):
        return page(done=None, error='Mandaste muchos pedidos seguidos. Esperá un rato o escribinos por WhatsApp.')
    code = None
    while not code or db.scalar(select(WithdrawalRequest.id).where(WithdrawalRequest.code == code)):
        code = 'ARR-' + secrets.token_hex(3).upper()
    row = WithdrawalRequest(code=code, name=name, email=email or None, phone=phone or None, order_ref=order_ref.strip()[:40] or None,
                            detail=detail.strip()[:4000] or None, account_id=acct.id if acct else None)
    db.add(row)
    db.flush()
    audit.log(db, 'withdrawal.request', 'withdrawal_request', row.id, new={'code': code, 'order': row.order_ref}, ip=ip)
    db.commit()
    return page(done=code, error=None)
