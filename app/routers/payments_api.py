"""Avisos de Mercado Pago (webhooks) y el link de pago de un pedido.

POST /api/payments/mercadopago/webhook   lo llama Mercado Pago. Se valida la firma, se descarta si ya
                                         se proceso y se consulta el pago a la API antes de tocar nada.
"""
import json
import logging
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import mercadopago

router = APIRouter()
logger = logging.getLogger('trappi.mercadopago')
# ultimos avisos recibidos (en memoria, para la pantalla de diagnostico): incluye los rechazados
recent: deque = deque(maxlen=20)


def _note(status: int, result: str, query) -> None:
    recent.appendleft({'at': datetime.utcnow(), 'status': status, 'result': result[:200], 'id': str(query.get('data.id') or query.get('id') or '')[:40]})


@router.post('/mercadopago/webhook')
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    query = dict(request.query_params)
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not mercadopago.verify_signature(headers, query):
        logger.warning('Webhook de Mercado Pago con firma inválida')
        _note(401, 'firma inválida (revisá MERCADOPAGO_WEBHOOK_SECRET)', query)
        return JSONResponse({'ok': False, 'error': 'firma inválida'}, status_code=401)
    try:
        payload = json.loads(await request.body() or b'{}')
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = mercadopago.handle_notification(db, payload, query, headers)
    except mercadopago.MPError as exc:
        # 500: Mercado Pago reintenta el aviso mas tarde
        _note(500, str(exc), query)
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)
    _note(200, result, query)
    return {'ok': True, 'result': result}
