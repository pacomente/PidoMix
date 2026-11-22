"""Lo que se hace sobre un pedido desde la app: chat con el repartidor, cuenta de la mesa, peso real, reclamo, fotos y avisos.

Se separó de mobile_api.py (mismas rutas, mismo prefijo /api/v1): los helpers y servicios compartidos vienen de ahí."""
from fastapi import APIRouter

from .mobile_api import *  # noqa: F401,F403  (helpers, modelos de datos y servicios compartidos)

router = APIRouter()


# ---------- chat con el repartidor (con fotos) ----------

def _customer_order(db: Session, order_id: int, t: str) -> Order | None:
    return db.get(Order, order_id) if valid_order_token(t, order_id) else None


def _customer_photo_url(o: Order):
    tok = order_token(o.id)
    return lambda pid: f'/api/v1/orders/{o.id}/photos/{pid}?t={tok}'


@router.get('/orders/{order_id}/chat')
def order_chat(order_id: int, t: str = '', after: int = 0, db: Session = Depends(get_db)):
    o = _customer_order(db, order_id, t)
    if not o:
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    can_read, can_write = delivery_safety.chat_open(db, o)
    if not can_read:
        return JSONResponse({'ok': False, 'error': 'El chat se abre cuando un repartidor toma tu pedido.'}, status_code=404)
    return {'ok': True, 'can_write': can_write, 'me': 'customer', 'courier': o.courier.name.split()[0] if o.courier else None,
            'messages': [delivery_safety.message_json(m, _customer_photo_url(o)) for m in delivery_safety.messages(db, o, 'cliente', after)]}


class CustomerChatIn(BaseModel):
    t: str = Field('', max_length=200)
    text: str = Field('', max_length=600)


def _notify_courier_chat(o: Order, text: str) -> None:
    if o.courier is not None:
        push.notify_courier_message(o.courier, o, f'Mensaje del cliente · pedido #{o.id}', text or '📷 Te mandó una foto')


@router.post('/orders/{order_id}/chat')
def order_chat_post(order_id: int, body: CustomerChatIn, request: Request, db: Session = Depends(get_db)):
    o = _customer_order(db, order_id, body.t)
    if not o:
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    if not chat_limiter.check(f'o{o.id}:{client_ip(request)}'):
        return JSONResponse({'ok': False, 'error': 'Mandaste muchos mensajes seguidos. Esperá un poco.'}, status_code=429)
    try:
        m = delivery_safety.post(db, o, 'cliente', 'customer', body.text)
    except delivery_safety.SafetyError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=exc.status)
    db.commit()
    _notify_courier_chat(o, m.text or '')
    return {'ok': True, 'message': delivery_safety.message_json(m, _customer_photo_url(o))}


@router.post('/orders/{order_id}/chat/photo')
async def order_chat_photo(order_id: int, request: Request, t: str = Form(''), photo: UploadFile = File(...), db: Session = Depends(get_db)):
    o = _customer_order(db, order_id, t)
    if not o:
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    if not chat_limiter.check(f'o{o.id}:{client_ip(request)}'):
        return JSONResponse({'ok': False, 'error': 'Mandaste muchos mensajes seguidos. Esperá un poco.'}, status_code=429)
    raw = await photo.read(delivery_safety.MAX_UPLOAD + 1)
    try:
        if not delivery_safety.chat_open(db, o)[1]:
            raise delivery_safety.SafetyError('Este chat ya está cerrado.')
        p = delivery_safety.save_photo(db, o, raw, 'chat', 'customer')
        m = delivery_safety.post(db, o, 'cliente', 'customer', '', p.id)
    except delivery_safety.SafetyError as exc:
        db.rollback()
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=exc.status)
    db.commit()
    _notify_courier_chat(o, '')
    return {'ok': True, 'message': delivery_safety.message_json(m, _customer_photo_url(o))}


class WeightAnswerIn(BaseModel):
    t: str = Field(..., max_length=200)
    accept: bool


@router.get('/orders/{order_id}/table')
def order_table(order_id: int, t: str = '', n: int = 0, db: Session = Depends(get_db)):
    """Pedido hecho desde la mesa: la cuenta de toda la mesa (la sube la caja) y dividirla en partes iguales."""
    from ..services import table_tab
    if not valid_order_token(t, order_id):
        return JSONResponse({'error': 'No encontramos ese pedido.'}, status_code=404)
    o = db.get(Order, order_id)
    table = table_tab.table_of_order(db, o) if o else None
    if table is None:
        return JSONResponse({'error': 'Este pedido no es de una mesa.'}, status_code=404)
    return table_tab.tab_json(db, table, max(0, min(30, n)))


class TableCallIn(BaseModel):
    t: str = Field(max_length=200)
    kind: str = Field(max_length=10)


@router.post('/orders/{order_id}/table-call')
def order_table_call(order_id: int, body: TableCallIn, db: Session = Depends(get_db)):
    """"Llamar al mozo" / "Pedir la cuenta" desde el pedido de la mesa."""
    from ..services import table_tab
    if not valid_order_token(body.t, order_id):
        return JSONResponse({'error': 'No encontramos ese pedido.'}, status_code=404)
    o = db.get(Order, order_id)
    table = table_tab.table_of_order(db, o) if o else None
    if table is None or body.kind not in table_tab.KINDS or o.status in (OrderStatus.CANCELADO,):
        return JSONResponse({'error': 'No se puede llamar desde este pedido.'}, status_code=400)
    _, new = table_tab.call(db, table, body.kind)
    db.commit()
    if new:
        table_tab.notify(db, table, body.kind)
    return {'ok': True, 'new': new}


@router.post('/orders/{order_id}/weight')
def order_weight_answer(order_id: int, body: WeightAnswerIn, db: Session = Depends(get_db)):
    """El cliente acepta (o no) el peso real cuando se pasó del margen. El total lo recalcula el servidor."""
    o = db.get(Order, order_id)
    if not o or not valid_order_token(body.t, order_id):
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    try:
        weight.customer_answer(db, o, body.accept)
    except weight.WeightError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    db.commit()
    return {'ok': True, 'order': order_json(o)}


@router.post('/orders/{order_id}/claim')
async def order_claim(order_id: int, request: Request, t: str = Form(''), reason: str = Form(''), text: str = Form(''),
                      photo: UploadFile | None = File(None), authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Reclamo del pedido (con foto opcional). Solo quien lo hizo: con su cuenta, o el pedido sin cuenta hecho desde la app
    (el link de seguimiento lo puede tener el local, asi que el token solo no alcanza para los pedidos de la web)."""
    o = db.scalar(select(Order).options(joinedload(Order.store), selectinload(Order.events)).where(Order.id == order_id)) if valid_order_token(t, order_id) else None
    acct = current_account(db, authorization)
    owner = o is not None and ((o.account_id is not None and acct is not None and acct.id == o.account_id) or (o.account_id is None and o.origin == 'app'))
    if not owner:
        if o is None or o.account_id is None:
            return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
        return JSONResponse({'ok': False, 'error': 'Ingresá con la cuenta con la que hiciste el pedido.'}, status_code=403)
    if not chat_limiter.check(f'claim{o.id}:{client_ip(request)}'):
        return JSONResponse({'ok': False, 'error': 'Probá de nuevo en unos minutos.'}, status_code=429)
    raw = await photo.read(delivery_safety.MAX_UPLOAD + 1) if photo is not None and photo.filename else None
    try:
        claims.create(db, o, reason, text, raw)
    except claims.ClaimError as exc:
        db.rollback()
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=400)
    db.commit()
    db.refresh(o)
    return {'ok': True, 'claim': claim_json(o)}


@router.get('/orders/{order_id}/photos/{photo_id}')
def order_photo(order_id: int, photo_id: int, t: str = '', db: Session = Depends(get_db)):
    """El cliente ve las fotos de su chat y la foto de prueba de su pedido (no las del chat con el local)."""
    from ..models import OrderMessage
    o = _customer_order(db, order_id, t)
    p = delivery_safety.photo_of(db, o, photo_id) if o else None
    allowed = p is not None and (photo_id == o.proof_photo_id or db.scalar(select(OrderMessage.id).where(
        OrderMessage.order_id == o.id, OrderMessage.thread == 'cliente', OrderMessage.photo_id == photo_id).limit(1)) is not None)
    if not allowed:
        return JSONResponse({'ok': False, 'error': 'Foto no encontrada.'}, status_code=404)
    return Response(p.content, media_type=p.mime, headers={'Cache-Control': 'private, max-age=3600'})


@router.post('/orders/{order_id}/push')
def order_push(order_id: int, body: PushIn, db: Session = Depends(get_db)):
    """Registra el telefono para recibir notificaciones de este pedido."""
    o = db.get(Order, order_id) if valid_order_token(body.t, order_id) else None
    if not o:
        return JSONResponse({'ok': False, 'error': 'No encontramos ese pedido.'}, status_code=404)
    ok = push.register(db, o, body.token, body.platform)
    try:
        db.commit()
    except IntegrityError:  # el mismo telefono registrado dos veces a la vez
        db.rollback()
    return {'ok': ok, 'enabled': push.enabled()}
