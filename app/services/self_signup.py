"""Alta de comercios por su cuenta, con la aprobación de Trappi.

1. El comercio completa /sumate con una contraseña. Si su ciudad ya es de Trappi, en el momento se crean su local
   (pendiente: no aparece en la app ni recibe pedidos) y su usuario del panel, y entra directo.
2. En su panel carga logo, horarios, ubicación y menú (también desde una planilla) y toca "Ya está listo".
3. El superadmin lo revisa en Solicitudes (con lo que falta marcado) y toca "Aprobar y publicar": recién ahí se ve.

El plan y la comisión salen de la configuración comercial de la ciudad (el superadmin los puede cambiar en la ficha
del comercio antes de publicar). Una ciudad donde Trappi todavía no está sigue el camino de siempre (solo la solicitud).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MerchantApplication, Product, ProductStatus, Role, Store, StoreHour, User
from . import plans, platform
from .auth import hash_password

MIN_PASSWORD = 8


class SignupError(Exception):
    pass


def enabled(db: Session) -> bool:
    return bool(platform.get(db, 'stores_self_signup'))


def password_problem(password: str, email: str = '') -> str | None:
    if len(password) < MIN_PASSWORD:
        return f'La contraseña tiene que tener {MIN_PASSWORD} caracteres o más.'
    if password.lower() in (email.lower(), email.split('@')[0].lower()) or len(set(password)) < 4:
        return 'Elegí una contraseña más difícil de adivinar.'
    return None


def _slug(db: Session, name: str) -> str:
    base = unicodedata.normalize('NFD', name.lower())
    base = re.sub(r'[^a-z0-9]+', '-', ''.join(ch for ch in base if unicodedata.category(ch) != 'Mn')).strip('-')[:60] or 'local'
    slug, n = base, 2
    while db.scalar(select(Store.id).where(Store.slug == slug)):
        slug, n = f'{base}-{n}', n + 1
    return slug


def create(db: Session, app: MerchantApplication, password: str) -> tuple[Store, User]:
    """Crea el local pendiente y el usuario del dueño a partir de la solicitud. No hace commit."""
    if app.city_id is None:
        raise SignupError('Todavía no estamos en tu ciudad.')
    if db.scalar(select(User.id).where(func.lower(User.email) == app.email.lower())):
        raise SignupError('Ese email ya tiene una cuenta en Trappi. Entrá a tu panel o usá otro email.')
    problem = password_problem(password, app.email)
    if problem:
        raise SignupError(problem)
    plan = plans.DELIVERY if app.delivery == 'trappi' else plans.COMERCIO
    base = plans.defaults(db, plan, app.city_id)
    cat = app.store_category.name if app.store_category else app.category_other
    store = Store(name=app.store_name[:160], slug=_slug(db, app.store_name), phone=app.store_phone or None, whatsapp=app.owner_whatsapp,
                  address=', '.join(x for x in [app.address, app.address_extra] if x)[:255], store_category_id=app.store_category_id,
                  owner_name=app.owner_name, contact_email=app.email, city_id=app.city_id, account_status='pendiente',
                  delivery_enabled=app.delivery != 'no_tiene',
                  commercial_notes='\n'.join(x for x in [f'Se dio de alta solo desde /sumate (trámite {app.code}).', f'Rubro: {cat}' if cat else '',
                                                         f'Vende: {app.food_types}' if app.food_types else '', f'Horarios: {app.hours}' if app.hours else '',
                                                         f'Instagram: @{app.instagram}' if app.instagram else '', f'CUIT: {app.cuit}' if app.cuit else '',
                                                         f'Comentarios: {app.comments}' if app.comments else ''] if x))
    db.add(store)
    db.flush()
    plans.set_plan(db, store, plan, base['monthly_fee'], base['commission_rate'], base['logistics'], None, note='Alta del comercio por su cuenta')
    user = User(email=app.email.lower(), password_hash=hash_password(password), role=Role.STORE_ADMIN, store_id=store.id, active=True)
    db.add(user)
    app.store_id = store.id
    db.flush()
    return store, user


def checklist(db: Session, store: Store) -> list[dict]:
    """Lo que tiene que estar antes de publicar (para el dueño y para el superadmin)."""
    products = db.scalar(select(func.count(Product.id)).where(Product.store_id == store.id, Product.deleted.is_(False),
                                                               Product.status == ProductStatus.ACTIVO)) or 0
    hours = db.scalar(select(func.count(StoreHour.id)).where(StoreHour.store_id == store.id)) or 0
    return [
        {'key': 'menu', 'ok': products >= 3, 'text': f'Menú cargado ({products} productos)' if products else 'Cargá tu menú (al menos 3 productos)',
         'href': '/admin/menu/importar', 'cta': 'Cargar desde planilla'},
        {'key': 'hours', 'ok': hours > 0, 'text': 'Horarios cargados' if hours else 'Cargá tus horarios', 'href': '/admin/stores#horarios', 'cta': 'Cargar'},
        {'key': 'location', 'ok': store.lat is not None and store.lng is not None, 'text': 'Ubicación en el mapa' if store.lat is not None else 'Marcá el local en el mapa',
         'href': '/admin/stores', 'cta': 'Marcar'},
        {'key': 'logo', 'ok': bool(store.logo_url), 'text': 'Logo' if store.logo_url else 'Subí el logo de tu local', 'href': '/admin/stores', 'cta': 'Subir'},
    ]


def application_of(db: Session, store: Store) -> MerchantApplication | None:
    return db.scalar(select(MerchantApplication).where(MerchantApplication.store_id == store.id).order_by(MerchantApplication.id.desc()))


def mark_ready(db: Session, store: Store) -> MerchantApplication | None:
    """El dueño avisa que terminó: la solicitud pasa a "Listos para revisar". No hace commit."""
    app = application_of(db, store)
    if app is None or app.status in ('aprobada', 'rechazada') or store.account_status != 'pendiente':
        return None
    missing = [c['text'] for c in checklist(db, store) if not c['ok'] and c['key'] in ('menu', 'hours', 'location')]
    if missing:
        raise SignupError('Antes de pedir la revisión: ' + ', '.join(m[0].lower() + m[1:] for m in missing) + '.')
    app.status = 'lista'
    return app


def publish(db: Session, app: MerchantApplication, user) -> Store:
    """El superadmin aprueba: el local queda activo y visible. No hace commit."""
    store = db.get(Store, app.store_id) if app.store_id else None
    if store is None:
        raise SignupError('Esta solicitud no tiene un local creado.')
    plans.set_status(store, 'activo')
    app.status, app.reviewed_by, app.reviewed_at = 'aprobada', user.id, datetime.utcnow()
    return store


def reject(db: Session, app: MerchantApplication, user) -> None:
    """El superadmin la rechaza: el local queda desactivado y su usuario sin acceso. No hace commit."""
    store = db.get(Store, app.store_id) if app.store_id else None
    if store is not None and store.account_status != 'activo':
        plans.set_status(store, 'desactivado')
        for u in db.scalars(select(User).where(User.store_id == store.id)):
            u.active = False
    app.status, app.reviewed_by, app.reviewed_at = 'rechazada', user.id, datetime.utcnow()
