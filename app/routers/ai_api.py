"""Trappi AI por HTTP.

  POST /api/v1/ai/chat   app: el carrito viaja en el pedido (como en /cart/quote) y vuelve actualizado
  POST /api/ai/chat      web: el carrito es el de la sesion del navegador

El asistente solo puede usar las herramientas de app/ai/client_tools.py: nada de acceso directo a la base.
"""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..ai import assistant, providers
from ..ai.tools import ToolContext
from ..db import get_db
from ..services import accounts, cities, csrf, platform
from ..services.cart import get_cart, price_lines, save_cart
from ..services.geo import parse_location
from ..services.ratelimit import PersistentRateLimiter, client_ip
from .mobile_api import CartLine, city_for, loc_from, num, require_app_enabled

router = APIRouter()


def ai_status(db: Session) -> dict:
    cfg = platform.get_all(db)
    return {'available': bool(cfg.get('ai_enabled')) and providers.configured(), 'welcome': cfg.get('ai_welcome') or ''}


def _limit(db: Session, request: Request, account) -> JSONResponse | None:
    limit = int(platform.get_all(db).get('ai_messages_per_hour') or 30)
    key = f'a{account.id}' if account else f'ip:{client_ip(request)}'
    if not PersistentRateLimiter('ai', limit=limit, window_seconds=3600).check(key):
        return JSONResponse({'ok': False, 'error': 'Llegaste al límite de mensajes del asistente por ahora. Probá de nuevo en un rato.'}, status_code=429)
    return None


def _unavailable() -> JSONResponse:
    return JSONResponse({'ok': False, 'error': 'El asistente no está disponible en este momento.'}, status_code=503)


def app_cart(db: Session, lines: list[dict], loc) -> list[dict]:
    """Lineas del carrito con lo que la app guarda (nombre, precio, comercio)."""
    cart = price_lines(db, lines, loc, precise=False)
    return [{'product_id': it['product'].id, 'quantity': it['quantity'], 'modifiers': [o.id for o in it['modifiers']], 'name': it['product'].name,
             'unit_price': num(it['unit_price']), 'modifiers_text': it['modifiers_text'] or None,
             'store_slug': it['product'].store.slug, 'store_name': it['product'].store.name} for it in cart['items']]


class ChatIn(BaseModel):
    message: str = Field('', max_length=2000)
    state: str | None = Field(None, max_length=200_000)
    items: list[CartLine] = Field(default_factory=list, max_length=60)
    lat: float | None = None
    lng: float | None = None
    city: str | None = Field(None, max_length=140)


@router.post('/v1/ai/chat', dependencies=[Depends(require_app_enabled)])
def app_chat(body: ChatIn, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    if not ai_status(db)['available']:
        return _unavailable()
    account = accounts.from_bearer(db, authorization)
    if (blocked := _limit(db, request, account)) is not None:
        return blocked
    loc = loc_from(body.lat, body.lng)
    here = city_for(db, body.city, loc)
    ctx = ToolContext(db=db, account=account, loc=loc, city_id=here.id if here else None, cart=[line.model_dump() for line in body.items])
    result = assistant.chat(ctx, body.message, body.state)
    if result['cart_changed']:
        result['cart'] = app_cart(db, result['cart'] or [], loc)
    return result


class WebChatIn(BaseModel):
    message: str = Field('', max_length=2000)
    state: str | None = Field(None, max_length=200_000)


@router.post('/ai/chat')
def web_chat(body: WebChatIn, request: Request, db: Session = Depends(get_db)):
    if not csrf.same_origin(request):
        return JSONResponse({'ok': False, 'error': 'Envío no permitido.'}, status_code=403)
    if not ai_status(db)['available']:
        return _unavailable()
    account = accounts.from_session(request, db)
    if (blocked := _limit(db, request, account)) is not None:
        return blocked
    loc = parse_location(request.session.get('loc') or {})
    here = cities.for_request(request, db)
    ctx = ToolContext(db=db, account=account, loc=loc, city_id=here.id if here else None, cart=list(get_cart(request)))
    result = assistant.chat(ctx, body.message, body.state)
    if result['cart_changed']:
        save_cart(request, result['cart'] or [])
        result['cart_count'] = sum(int(x.get('quantity', 0)) for x in result['cart'] or [])
    result.pop('cart', None)
    return result
