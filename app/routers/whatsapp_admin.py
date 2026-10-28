"""Panel: agente de WhatsApp del local.

- Superadmin: lo habilita comercio por comercio (sin eso el local no ve nada) y puede probarlo con el numero de prueba de Trappi.
- Local habilitado: conecta su numero con Meta (sin pasar claves), prende o pausa el agente, ve las charlas,
  toma una charla (el agente se calla) o se la devuelve, y elige que avisos le llegan al celular.
"""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..csp import with_meta_signup
from ..models import Order, Role, Store, WaConversation, WaMessage
from ..services import audit, wa_agent
from ..services.forms import form_int
from ..services.ratelimit import client_ip
from .admin import guard, templates

router = APIRouter()
MAX_OWNER_TEXT = 2000


def _store(request: Request, db: Session, u) -> Store | None:
    if u.role == Role.SUPERADMIN:
        sid = form_int(request.query_params.get('store'))
        return db.get(Store, sid) if sid else None
    s = db.get(Store, u.store_id) if u.store_id else None
    return s if s is not None and s.wa_enabled else None  # sin habilitar, el local no ve nada


def _back(u, s, msg='') -> RedirectResponse:
    q = [f'store={s.id}'] if u.role == Role.SUPERADMIN and s else []
    if msg:
        q.append(f'ok={msg}')
    return RedirectResponse('/admin/whatsapp' + ('?' + '&'.join(q) if q else ''), 303)


def _guarded(request: Request, db: Session):
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u, None
    s = _store(request, db, u)
    if s is None:
        return RedirectResponse('/admin/whatsapp' if u.role == Role.SUPERADMIN else '/admin', 303), None
    return u, s


def _conv(db: Session, s: Store, conv_id: int) -> WaConversation | None:
    c = db.get(WaConversation, conv_id)
    return c if c is not None and c.store_id == s.id else None


def conv_json(db: Session, c: WaConversation, after: int = 0) -> dict:
    msgs = db.scalars(select(WaMessage).where(WaMessage.conversation_id == c.id, WaMessage.id > after).order_by(WaMessage.id.desc()).limit(80)).all()
    order = db.scalar(select(Order).where(Order.wa_conversation_id == c.id).order_by(Order.id.desc()).limit(1))
    return {'id': c.id, 'name': c.name or 'Cliente', 'phone': c.wa_id, 'mode': c.mode, 'needs': c.needs, 'needs_note': c.needs_note,
            'window': wa_agent.window_open(c),
            'order': {'id': order.id, 'total': float(order.total), 'status': order.status.value,
                      'scheduled': order.scheduled_for.isoformat() + 'Z' if order.scheduled_for else None} if order else None,
            'messages': [{'id': m.id, 'author': m.author, 'text': m.text, 'status': m.status, 'at': m.created_at.isoformat() + 'Z'} for m in reversed(msgs)]}


@router.get('/whatsapp', response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store(request, db, u)
    if s is None and u.role != Role.SUPERADMIN:
        return RedirectResponse('/admin', 303)
    ctx = {'user': u, 's': s, 'error': request.session.pop('wa_error', None), 'alert_names': wa_agent.ALERTS,
           'webhook_ready': wa_agent.webhook_ready(), 'signup_ready': wa_agent.signup_ready(), 'test_ready': wa_agent.test_number_ready(),
           'meta_app_id': settings.meta_app_id, 'signup_config_id': settings.whatsapp_signup_config_id}
    if u.role == Role.SUPERADMIN and s is None:
        stores = db.scalars(select(Store).order_by(Store.wa_enabled.desc(), Store.name)).all()
        chats = dict(db.execute(select(WaConversation.store_id, func.count(WaConversation.id)).group_by(WaConversation.store_id)).all())
        ctx.update(stores=stores, chats=chats, connected=wa_agent.connected)
    elif s is not None:
        convs = db.scalars(select(WaConversation).where(WaConversation.store_id == s.id).order_by(WaConversation.last_at.desc()).limit(60)).all()
        last = {}
        if convs:
            for m in db.scalars(select(WaMessage).where(WaMessage.id.in_(
                    select(func.max(WaMessage.id)).where(WaMessage.conversation_id.in_([c.id for c in convs])).group_by(WaMessage.conversation_id)))):
                last[m.conversation_id] = m
        orders = dict(db.execute(select(Order.wa_conversation_id, func.max(Order.id)).where(
            Order.wa_conversation_id.in_([c.id for c in convs] or [0])).group_by(Order.wa_conversation_id)).all())
        sel = _conv(db, s, form_int(request.query_params.get('c')) or 0) or (convs[0] if convs else None)
        ctx.update(convs=convs, last=last, orders=orders, sel=sel, sel_json=conv_json(db, sel) if sel else None,
                   connected=wa_agent.connected(s), alerts=wa_agent.alerts(s), store_q=f'?store={s.id}' if u.role == Role.SUPERADMIN else '')
    response = templates.TemplateResponse(request, 'admin/whatsapp.html', ctx)
    return with_meta_signup(response)


@router.post('/whatsapp/habilitar')
def enable(request: Request, on: str = Form(''), db: Session = Depends(get_db)):
    """Solo superadmin: el comercio tiene (o no) el agente de WhatsApp."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    s = _store(request, db, u)
    if s is None: return RedirectResponse('/admin/whatsapp', 303)
    old, s.wa_enabled = s.wa_enabled, on == '1'
    audit.log(db, 'whatsapp.enable', 'store', s.id, user=u, old={'enabled': old}, new={'enabled': s.wa_enabled}, ip=client_ip(request))
    db.commit()
    return RedirectResponse('/admin/whatsapp' + (f'?ok=enabled' if request.query_params.get('back') == 'list' else f'?store={s.id}&ok=enabled'), 303)


@router.post('/whatsapp/prueba')
def test_number(request: Request, db: Session = Depends(get_db)):
    """Solo superadmin: el local usa el numero de prueba de Trappi (para probar antes de que el local conecte el suyo)."""
    u, s = _guarded(request, db)
    if s is None: return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    if not wa_agent.test_number_ready():
        request.session['wa_error'] = 'Falta el número de prueba: WHATSAPP_CLOUD_TOKEN y WHATSAPP_CLOUD_PHONE_ID en Render.'
        return _back(u, s)
    wa_agent.connect_test_number(db, s)
    audit.log(db, 'whatsapp.test_number', 'store', s.id, user=u, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'connected')


@router.post('/whatsapp/conectar')
async def connect(request: Request, db: Session = Depends(get_db)):
    """Vuelta del registro de Meta (en la misma pagina): el codigo se cambia por el token del lado del servidor."""
    u, s = _guarded(request, db)
    if s is None: return JSONResponse({'ok': False, 'error': 'Sin permiso.'}, status_code=403)
    f = await request.form()
    try:
        wa_agent.connect(db, s, str(f.get('code') or ''), str(f.get('waba_id') or ''), str(f.get('phone_id') or ''))
    except wa_agent.ConnectError as exc:
        db.rollback()
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    audit.log(db, 'whatsapp.connect', 'store', s.id, user=u, new={'number': s.wa_number}, ip=client_ip(request))
    db.commit()
    return {'ok': True, 'number': s.wa_number}


@router.post('/whatsapp/desconectar')
def disconnect(request: Request, db: Session = Depends(get_db)):
    u, s = _guarded(request, db)
    if s is None: return u
    wa_agent.disconnect(s)
    audit.log(db, 'whatsapp.disconnect', 'store', s.id, user=u, ip=client_ip(request))
    db.commit()
    return _back(u, s, 'disconnected')


@router.post('/whatsapp/agente')
def agent_switch(request: Request, on: str = Form(''), db: Session = Depends(get_db)):
    u, s = _guarded(request, db)
    if s is None: return u
    s.wa_agent_on = on == '1'
    db.commit()
    return _back(u, s, 'agent')


@router.post('/whatsapp/avisos')
async def alerts(request: Request, db: Session = Depends(get_db)):
    u, s = _guarded(request, db)
    if s is None: return u
    f = await request.form()
    s.wa_alerts = json.dumps({'off': [k for k in wa_agent.ALERTS if f.get(f'a_{k}') not in ('1', 'on')]})
    db.commit()
    return _back(u, s, 'alerts')


@router.get('/whatsapp/c/{conv_id}')
def conversation(conv_id: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    u, s = _guarded(request, db)
    c = _conv(db, s, conv_id) if s is not None else None
    if c is None: return JSONResponse({'ok': False}, status_code=404)
    return {'ok': True, **conv_json(db, c, after)}


@router.post('/whatsapp/c/{conv_id}/{action}')
async def conversation_action(conv_id: int, action: str, request: Request, db: Session = Depends(get_db)):
    """tomar: el dueño atiende (el agente se calla) · devolver: vuelve el agente · enviar: el dueño escribe."""
    u, s = _guarded(request, db)
    c = _conv(db, s, conv_id) if s is not None else None
    if c is None or action not in ('tomar', 'devolver', 'enviar'):
        return JSONResponse({'ok': False, 'error': 'Charla no encontrada.'}, status_code=404)
    if action == 'tomar':
        wa_agent.take(db, c)
    elif action == 'devolver':
        wa_agent.release(db, c)
    else:
        text = str((await request.form()).get('text') or '').strip()[:MAX_OWNER_TEXT]
        if not text:
            return JSONResponse({'ok': False, 'error': 'Escribí un mensaje.'}, status_code=400)
        if not wa_agent.window_open(c):
            return JSONResponse({'ok': False, 'error': 'Pasaron más de 24 h desde el último mensaje del cliente: WhatsApp no deja escribirle hasta que vuelva a escribir.'}, status_code=400)
        wa_agent.take(db, c)  # si el dueño contesta, la charla es suya
        msg = wa_agent.send(db, c, text, author='owner')
        if msg.status != 'sent':
            db.commit()
            return JSONResponse({'ok': False, 'error': 'WhatsApp no aceptó el mensaje. Probá de nuevo.'}, status_code=502)
        c.needs = c.needs_note = None
    db.commit()
    return {'ok': True, **conv_json(db, c)}
