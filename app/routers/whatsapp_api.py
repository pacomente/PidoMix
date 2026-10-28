"""Webhook de WhatsApp Cloud (Meta) para el agente de cada local.

GET  /api/whatsapp/webhook   Meta verifica la URL con el "verify token"
POST /api/whatsapp/webhook   mensajes de los clientes: se acepta solo con la firma de Meta (X-Hub-Signature-256)
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..services import wa_agent

router = APIRouter()
log = logging.getLogger('pidomix.wa')
MAX_BODY = 512 * 1024


@router.get('/webhook')
def verify(request: Request):
    q = request.query_params
    import hmac
    if (settings.whatsapp_verify_token and q.get('hub.mode') == 'subscribe'
            and hmac.compare_digest(q.get('hub.verify_token', ''), settings.whatsapp_verify_token)):
        return PlainTextResponse(q.get('hub.challenge', ''))
    return PlainTextResponse('forbidden', status_code=403)


@router.post('/webhook')
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > MAX_BODY or not wa_agent.verify_signature(raw, request.headers.get('x-hub-signature-256')):
        return JSONResponse({'ok': False}, status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        return JSONResponse({'ok': False}, status_code=400)
    todo = wa_agent.receive(db, payload)
    if todo:
        wa_agent.reply_later(todo)
    return {'ok': True}  # Meta reintenta si no recibe 200 rapido
