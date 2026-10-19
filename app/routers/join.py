"""Formulario "Sumá tu comercio" (/sumate): los comercios con local dejan sus datos y Trappi los contacta.

No crea el comercio ni da acceso al panel: queda una solicitud que el superadmin revisa en /admin/solicitudes,
contacta al dueño por WhatsApp o email y recién ahí da de alta el comercio (con los datos ya cargados).
"""
import re
import secrets
import unicodedata

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Category, City, MerchantApplication, StoreCategory
from ..services import audit, csrf, email, platform
from ..services.ratelimit import PersistentRateLimiter, client_ip
from .public import ctx, templates

router = APIRouter()
join_limiter = PersistentRateLimiter('merchant-join', limit=4, window_seconds=3600)

PROVINCES = ['Buenos Aires', 'Ciudad Autónoma de Buenos Aires', 'Catamarca', 'Chaco', 'Chubut', 'Córdoba', 'Corrientes', 'Entre Ríos', 'Formosa',
             'Jujuy', 'La Pampa', 'La Rioja', 'Mendoza', 'Misiones', 'Neuquén', 'Río Negro', 'Salta', 'San Juan', 'San Luis', 'Santa Cruz',
             'Santa Fe', 'Santiago del Estero', 'Tierra del Fuego', 'Tucumán']
DELIVERY = {'propio': 'Tengo mis propios repartidores', 'quiere_trappi': 'Me interesa la flota de Trappi', 'no_tiene': 'Por ahora solo retiro en el local'}
FOOD_TYPES = ['Hamburguesas', 'Pizzas', 'Empanadas', 'Lomitos y sándwiches', 'Milanesas', 'Parrilla', 'Pastas', 'Sushi', 'Comida china',
              'Comida árabe', 'Mexicana', 'Vegetariana / vegana', 'Ensaladas', 'Helados', 'Cafetería', 'Panadería', 'Pastelería y postres',
              'Rotisería', 'Bebidas', 'Kiosco / almacén']
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _plain(text: str) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFD', text or '') if unicodedata.category(ch) != 'Mn').lower().strip()


def match_city(db: Session, name: str) -> City | None:
    """La ciudad de Trappi con ese nombre (sin importar tildes ni mayúsculas), si ya operamos ahí."""
    target = _plain(name)
    return next((c for c in db.scalars(select(City)) if _plain(c.name) == target), None) if target else None


def digits(value: str) -> str:
    return ''.join(ch for ch in value or '' if ch.isdigit())


def form_options(db: Session) -> dict:
    cats = db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    foods = [c.name for c in db.scalars(select(Category).where(Category.active).order_by(Category.name))]
    return {'store_categories': cats, 'food_options': sorted(set(foods) | set(FOOD_TYPES), key=_plain), 'provinces': PROVINCES, 'delivery_options': DELIVERY}


def _notify_admin(db: Session, row: MerchantApplication) -> None:
    """Aviso por email a Trappi (si el envío de emails está configurado)."""
    to = (platform.get(db, 'legal_email') or '').strip() or settings.admin_email
    if not email.configured() or not to or to.endswith('.local'):
        return
    try:
        email.send(to, f'Nuevo comercio para sumar: {row.store_name}',
                   f'{row.owner_name} quiere sumar "{row.store_name}" ({row.city_name}, {row.province}).\n'
                   f'WhatsApp: {row.owner_whatsapp} · Email: {row.email}\n\nRevisalo en el panel: Solicitudes de comercios (trámite {row.code}).')
    except Exception:  # el aviso es opcional: la solicitud ya quedó guardada
        pass


def _page(request: Request, db: Session, **kw):
    cfg = platform.get_all(db)
    data = {'open': cfg['new_stores_open'], 'done': None, 'error': None, 'form': {}, **form_options(db), **kw}
    return templates.TemplateResponse(request, 'public/join.html', ctx(request, **data))


@router.get('/sumate', response_class=HTMLResponse)
def join_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, db)


@router.post('/sumate', response_class=HTMLResponse, dependencies=[Depends(csrf.protect)])
async def join_send(request: Request, db: Session = Depends(get_db)):
    data = await request.form()
    f = {k: (str(data.get(k) or '')).strip() for k in ('store_name', 'store_category_id', 'category_other', 'province', 'city_name', 'postal_code',
                                                        'address', 'address_extra', 'owner_name', 'owner_whatsapp', 'email', 'store_phone',
                                                        'instagram', 'cuit', 'delivery', 'hours', 'comments', 'website', 'accept')}
    f['food_types'] = ', '.join(v.strip()[:60] for v in data.getlist('food_types') if v.strip())[:400]
    if not platform.get(db, 'new_stores_open'):
        return _page(request, db)
    if f['website']:  # campo oculto: solo lo completan los robots
        return _page(request, db, done='SOL-RECIBIDA')
    wa, mail, cp = digits(f['owner_whatsapp']), f['email'].lower(), f['postal_code'].upper().replace(' ', '')
    errors = []
    if not f['store_name']: errors.append('el nombre del local')
    if not f['store_category_id'] and not f['category_other']: errors.append('el rubro')
    if f['province'] not in PROVINCES: errors.append('la provincia')
    if len(f['city_name']) < 2: errors.append('la ciudad')
    if not re.fullmatch(r'\d{4}|[A-Z]\d{4}[A-Z]{3}', cp): errors.append('el código postal (4 números, ej. 8000)')
    if len(f['address']) < 4: errors.append('la dirección del local')
    if not f['owner_name']: errors.append('tu nombre')
    if len(wa) < 10: errors.append('tu WhatsApp con código de área (ej. 291 455 6677)')
    if not EMAIL_RE.match(mail): errors.append('un email válido')
    if f['accept'] != '1': errors.append('aceptar que te contactemos')
    if errors:
        return _page(request, db, form=f, error='Revisá: ' + ', '.join(errors) + '.')
    ip = client_ip(request)
    if not join_limiter.check(ip):
        return _page(request, db, form=f, error='Mandaste varias solicitudes seguidas. Esperá un rato o escribinos por WhatsApp.')
    # misma persona y mismo local todavía sin revisar: no se duplica, se le devuelve el mismo trámite
    dup = db.scalar(select(MerchantApplication).where(MerchantApplication.status.in_(('nueva', 'contactada')),
                                                      MerchantApplication.owner_whatsapp == wa, MerchantApplication.store_name == f['store_name'][:160]))
    if dup:
        return _page(request, db, done=dup.code)
    cat = db.get(StoreCategory, int(f['store_category_id'])) if f['store_category_id'].isdigit() else None
    code = None
    while not code or db.scalar(select(MerchantApplication.id).where(MerchantApplication.code == code)):
        code = 'SOL-' + secrets.token_hex(3).upper()
    city = match_city(db, f['city_name'])
    row = MerchantApplication(
        code=code, store_name=f['store_name'][:160], store_category_id=cat.id if cat else None,
        category_other=None if cat else f['category_other'][:100] or None, food_types=f['food_types'] or None,
        province=f['province'], city_name=f['city_name'][:120], city_id=city.id if city else None, postal_code=cp[:10],
        address=f['address'][:255], address_extra=f['address_extra'][:120] or None, owner_name=f['owner_name'][:160], owner_whatsapp=wa[:40],
        email=mail[:255], store_phone=digits(f['store_phone'])[:40] or None, instagram=f['instagram'].lstrip('@')[:120] or None,
        cuit=''.join(ch for ch in f['cuit'] if ch.isdigit() or ch == '-')[:20] or None,
        delivery=f['delivery'] if f['delivery'] in DELIVERY else None, hours=f['hours'][:200] or None, comments=f['comments'][:2000] or None)
    db.add(row)
    db.flush()
    audit.log(db, 'merchant.application', 'merchant_application', row.id, new={'code': code, 'store': row.store_name, 'city': row.city_name}, ip=ip)
    db.commit()
    _notify_admin(db, row)
    return _page(request, db, done=code)
