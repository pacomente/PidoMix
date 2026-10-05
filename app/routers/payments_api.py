"""Avisos de Mercado Pago (webhooks) y el link de pago de un pedido.

POST /api/payments/mercadopago/webhook   lo llama Mercado Pago. Se valida la firma, se descarta si ya
                                         se proceso y se consulta el pago a la API antes de tocar nada.
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import mercadopago

router = APIRouter()
logger = logging.getLogger('trappi.mercadopago')


@router.post('/mercadopago/webhook')
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    query = dict(request.query_params)
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not mercadopago.verify_signature(headers, query):
        logger.warning('Webhook de Mercado Pago con firma inválida')
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
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)
    return {'ok': True, 'result': result}
