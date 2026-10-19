"""Panel: solicitudes de comercios que se quieren sumar (/admin/solicitudes, solo superadmin).

El superadmin las revisa, contacta al dueño (WhatsApp o email) y, si avanza, "Crear el comercio" abre el alta de
Comercios y planes con los datos ya cargados. Al guardarlo, la solicitud queda aprobada con el comercio vinculado.
"""
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import SessionLocal, get_db
from ..models import MerchantApplication, Role
from ..services import audit
from ..services.ratelimit import client_ip
from .admin import guard, templates, wa_link
from .join import DELIVERY

router = APIRouter()
STATUSES = {'nueva': 'Nuevas', 'contactada': 'Contactadas', 'aprobada': 'Aprobadas', 'rechazada': 'Rechazadas'}
FROM_KEY = 'from_application'  # la solicitud que se está dando de alta en Comercios y planes
FROM_SECONDS = 2 * 3600


def pending_count() -> int:
    """Para el número al lado de "Solicitudes" en el menú."""
    try:
        with SessionLocal() as db:
            return db.scalar(select(func.count(MerchantApplication.id)).where(MerchantApplication.status == 'nueva')) or 0
    except Exception:
        return 0


templates.env.globals['applications_pending'] = pending_count


def _super(request: Request, db: Session):
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u
    return u if u.role == Role.SUPERADMIN else RedirectResponse('/admin', 303)


def contact_message(a: MerchantApplication) -> str:
    return (f'Hola {a.owner_name.split()[0]}, te escribo de Trappi. Recibimos la solicitud para sumar {a.store_name} '
            f'(trámite {a.code}). ¿Tenés unos minutos para contarte los planes y terminar el alta?')


@router.get('/solicitudes', response_class=HTMLResponse)
def applications_page(request: Request, estado: str = 'nueva', db: Session = Depends(get_db)):
    u = _super(request, db)
    if isinstance(u, RedirectResponse): return u
    estado = estado if estado in STATUSES else 'nueva'
    rows = db.scalars(select(MerchantApplication).options(joinedload(MerchantApplication.store_category), joinedload(MerchantApplication.city))
                      .where(MerchantApplication.status == estado).order_by(MerchantApplication.id.desc()).limit(200)).all()
    counts = dict(db.execute(select(MerchantApplication.status, func.count(MerchantApplication.id)).group_by(MerchantApplication.status)).all())
    return templates.TemplateResponse(request, 'admin/applications.html', {
        'user': u, 'rows': rows, 'estado': estado, 'statuses': STATUSES, 'counts': counts, 'delivery': DELIVERY,
        'wa': lambda a: wa_link(a.owner_whatsapp, contact_message(a)), 'okmsg': request.query_params.get('m')})


@router.post('/solicitudes/{app_id}')
def application_update(app_id: int, request: Request, action: str = Form(...), note: str = Form(''), db: Session = Depends(get_db)):
    u = _super(request, db)
    if isinstance(u, RedirectResponse): return u
    a = db.get(MerchantApplication, app_id)
    if not a:
        return RedirectResponse('/admin/solicitudes', 303)
    old = a.status
    a.admin_note = (note.strip()[:4000] or None) if action == 'nota' else (note.strip()[:4000] or a.admin_note)
    if action == 'contactada' and a.status in ('nueva', 'rechazada'):
        a.status = 'contactada'
    elif action == 'rechazar' and a.status != 'aprobada':
        a.status = 'rechazada'
    elif action == 'reabrir' and a.status == 'rechazada':
        a.status = 'nueva'
    elif action == 'crear' and a.status != 'aprobada':
        # abre el alta del comercio con lo que cargó en el formulario (el plan, el usuario y la contraseña los define el superadmin)
        cat = a.store_category.name if a.store_category else a.category_other
        notes = '\n'.join(x for x in [
            f'Solicitud {a.code} del {a.created_at.strftime("%d/%m/%Y")}', f'Rubro: {cat}' if cat else '', f'Vende: {a.food_types}' if a.food_types else '',
            f'Provincia: {a.province} · CP {a.postal_code}', f'Delivery: {DELIVERY.get(a.delivery, "-")}' if a.delivery else '',
            f'Horarios: {a.hours}' if a.hours else '', f'Instagram: @{a.instagram}' if a.instagram else '', f'CUIT: {a.cuit}' if a.cuit else '',
            f'Comentarios: {a.comments}' if a.comments else '', f'Nota: {a.admin_note}' if a.admin_note else ''] if x)
        request.session['commercial_form'] = {
            'name': a.store_name, 'owner_name': a.owner_name, 'phone': a.store_phone or '', 'whatsapp': a.owner_whatsapp,
            'contact_email': a.email, 'address': ', '.join(x for x in [a.address, a.address_extra, a.city_name] if x),
            'store_category_id': str(a.store_category_id or ''), 'commercial_notes': notes, 'login_email': a.email,
            'city_id': str(a.city_id or ''), 'plan': '', 'monthly_fee': '', 'commission_rate': '', 'logistics': '', 'next_due_date': '',
            'slug': '', 'open_time': '', 'close_time': ''}
        request.session[FROM_KEY] = [a.id, int(time.time())]
        db.commit()
        return RedirectResponse('/admin/comercios/nuevo', 303)
    if a.status != old or note.strip():
        a.reviewed_by, a.reviewed_at = u.id, datetime.utcnow()
        audit.log(db, f'merchant.application.{action}', 'merchant_application', a.id, user=u, old={'status': old}, new={'status': a.status},
                  reason=note.strip()[:200] or None, ip=client_ip(request))
    db.commit()
    return RedirectResponse(f'/admin/solicitudes?estado={a.status}&m=Guardado.', 303)


def link_created_store(request: Request, db: Session, store, user) -> None:
    """Llamado al crear un comercio: si venía de una solicitud, la marca aprobada con el comercio. No hace commit."""
    ref = request.session.pop(FROM_KEY, None)
    # solo si el alta se hizo poco después de tocar "Crear el comercio" (si no, sería otro comercio cargado a mano)
    app_id = ref[0] if isinstance(ref, list) and len(ref) == 2 and time.time() - ref[1] < FROM_SECONDS else None
    a = db.get(MerchantApplication, app_id) if app_id else None
    if a and a.status != 'aprobada':
        a.status, a.store_id, a.reviewed_by, a.reviewed_at = 'aprobada', store.id, user.id, datetime.utcnow()
        audit.log(db, 'merchant.application.aprobada', 'merchant_application', a.id, user=user, new={'store': store.id}, ip=client_ip(request))
