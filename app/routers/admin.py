from pathlib import Path
import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session, joinedload, selectinload
from ..db import get_db
from ..models import Banner, Category, Coupon, Customer, ModifierGroup, ModifierOption, Order, OrderItem, OrderStatus, Product, ProductStatus, Review, Role, Store, StoreCategory, StoreHour, StoreSection, StoreStatus, User
from ..services.auth import current_user, hash_password, verify_password
from ..services.cloudinary_service import delete, upload
from ..services.ratelimit import RateLimiter
from ..services.store_hours import is_open, local_day_start_utc, local_now, to_local

router = APIRouter()
login_limiter = RateLimiter(limit=5, window_seconds=300)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}

STATUS_TONE = {
    'ACTIVA': 'good', 'ACTIVO': 'good', 'ENTREGADO': 'good', 'LISTO': 'good',
    'INACTIVA': 'neutral', 'INACTIVO': 'neutral',
    'CERRADA': 'bad', 'CANCELADO': 'bad', 'SIN_STOCK': 'warn',
    'PENDIENTE': 'warn', 'CONFIRMADO': 'accent', 'PREPARANDO': 'accent', 'EN_CAMINO': 'accent',
}


def _human_label(value: str) -> str:
    return str(value).replace('_', ' ').capitalize()


FLOW = [OrderStatus.PENDIENTE, OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO, OrderStatus.ENTREGADO]
ADVANCE_LABEL = {'CONFIRMADO': 'Confirmar pedido', 'PREPARANDO': 'Empezar a preparar', 'LISTO': 'Marcar listo', 'EN_CAMINO': 'Enviar con repartidor', 'ENTREGADO': 'Marcar entregado'}


def advance(order):
    """Siguiente estado del pedido y texto del boton (el retiro en local salta 'En camino')."""
    seq = [x for x in FLOW if not (x == OrderStatus.EN_CAMINO and order.delivery_method == 'retiro')]
    if order.status not in seq: return None
    i = seq.index(order.status)
    if i + 1 >= len(seq): return None
    nxt = seq[i + 1]
    return nxt.value, ADVANCE_LABEL[nxt.value]


def wa_link(phone):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return f'https://wa.me/{digits}' if digits else ''


templates.env.globals['advance'] = advance
templates.env.globals['wa_link'] = wa_link
templates.env.globals['store_is_open'] = is_open
templates.env.filters['tone'] = lambda v: STATUS_TONE.get(str(v), 'neutral')
templates.env.filters['human'] = _human_label


def auth(request, db):
    u = current_user(request, db)
    return u if u and u.active and u.role in (Role.SUPERADMIN, Role.STORE_ADMIN) else None


def guard(request, db):
    u = auth(request, db)
    return u if u else RedirectResponse('/admin/login', 303)


def can_manage_store(user, store_id):
    return user.role == Role.SUPERADMIN or user.store_id == store_id


def image_upload(file: UploadFile | None, folder: str):
    if not file or not file.filename:
        return None, None
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError('Formato de imagen no permitido.')
    content = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError('La imagen supera el máximo de 5 MB.')
    return upload(content, folder)


def safe_slug(value: str) -> str:
    return '-'.join(value.strip().lower().split())


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse('admin/login.html', {'request': request})


@router.post('/login')
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    ip = (request.headers.get('x-forwarded-for') or (request.client.host if request.client else '')).split(',')[0].strip()
    key = f'{ip}|{email.strip().lower()}'
    if login_limiter.blocked(key):
        return templates.TemplateResponse('admin/login.html', {'request': request, 'error': 'Demasiados intentos. Esperá unos minutos e intentá de nuevo.'}, status_code=429)
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not u or not u.active or not verify_password(password, u.password_hash):
        login_limiter.hit(key)
        return templates.TemplateResponse('admin/login.html', {'request': request, 'error': 'Email o contraseña incorrectos.'}, status_code=401)
    login_limiter.reset(key)
    request.session.clear()
    request.session['user_id'] = u.id
    return RedirectResponse('/admin', 303)


@router.get('/account', response_class=HTMLResponse)
def account(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    return templates.TemplateResponse('admin/account.html', {'request': request, 'user': u})


@router.post('/account/password')
def account_password(request: Request, current: str = Form(...), new: str = Form(...), confirm: str = Form(...), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not verify_password(current, u.password_hash): return RedirectResponse('/admin/account?error=pw_current', 303)
    if len(new) < 8 or new != confirm: return RedirectResponse('/admin/account?error=pw_new', 303)
    u.password_hash = hash_password(new); db.commit()
    return RedirectResponse('/admin/account?ok=password', 303)


@router.get('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/admin/login', 303)


@router.get('', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    is_super = u.role == Role.SUPERADMIN
    of = [] if is_super else [Order.store_id == u.store_id]
    valid = Order.status != OrderStatus.CANCELADO
    today, month = local_day_start_utc(), local_day_start_utc(local_now().day - 1)
    def count(*where): return db.scalar(select(func.count(Order.id)).where(*where, *of)) or 0
    def revenue(*where): return db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(*where, *of)) or 0
    month_orders, month_revenue = count(Order.created_at >= month, valid), revenue(Order.created_at >= month, valid)
    stats = {
        'today_orders': count(Order.created_at >= today, valid), 'today_revenue': revenue(Order.created_at >= today, valid),
        'pending': count(Order.status == OrderStatus.PENDIENTE), 'in_progress': count(Order.status.in_([OrderStatus.CONFIRMADO, OrderStatus.PREPARANDO, OrderStatus.LISTO, OrderStatus.EN_CAMINO])),
        'month_revenue': month_revenue, 'avg_ticket': (Decimal(month_revenue) / month_orders) if month_orders else 0,
        'products': db.scalar(select(func.count(Product.id)).where(*([] if is_super else [Product.store_id == u.store_id]))) or 0,
        'stores': db.scalar(select(func.count(Store.id))) or 0 if is_super else 1,
        'customers': (db.scalar(select(func.count(Customer.id))) or 0) if is_super else (db.scalar(select(func.count(func.distinct(Order.customer_id))).where(*of)) or 0),
    }
    top = db.execute(select(OrderItem.product_name, func.sum(OrderItem.quantity).label('qty'), func.sum(OrderItem.quantity * OrderItem.unit_price).label('amount')).join(Order, Order.id == OrderItem.order_id).where(Order.created_at >= month, valid, *of).group_by(OrderItem.product_name).order_by(desc('qty')).limit(5)).all()
    recent = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(*of).order_by(Order.created_at.desc()).limit(6)).all()
    my_store = db.scalar(select(Store).options(joinedload(Store.hours)).where(Store.id == u.store_id)) if not is_super and u.store_id else None
    return templates.TemplateResponse('admin/dashboard.html', {'request': request, 'user': u, 's': stats, 'top': top, 'recent': recent, 'my_store': my_store})


@router.get('/stores', response_class=HTMLResponse)
def store_list(request: Request, db: Session = Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stmt=select(Store).options(joinedload(Store.store_category), joinedload(Store.hours), joinedload(Store.admins)).order_by(Store.name)
    if u.role != Role.SUPERADMIN: stmt=stmt.where(Store.id==u.store_id)
    stores=db.scalars(stmt).unique().all()
    categories=db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse('admin/stores.html',{'request':request,'user':u,'stores':stores,'categories':categories})


@router.post('/stores')
def store_create(request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),phone:str=Form(''),whatsapp:str=Form(''),address:str=Form(''),store_category_id:int|None=Form(None),delivery_enabled:bool=Form(False),delivery_cost:float=Form(0),minimum_order:float=Form(0),estimated_minutes:int=Form(30),featured:bool=Form(False),owner_email:str=Form(''),owner_password:str=Form(''),logo:UploadFile|None=File(None),cover:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin/stores',303)
    slug=safe_slug(slug)
    owner_email=owner_email.strip().lower()
    if not owner_email or len(owner_password)<8 or db.scalar(select(User).where(User.email==owner_email)):
        return RedirectResponse('/admin/stores?error=owner',303)
    if db.scalar(select(Store).where(Store.slug == slug)):
        return RedirectResponse('/admin/stores?error=slug',303)
    try:
        logo_url=logo_pid=image_url=image_pid=None
        cover_url=cover_pid=None
        if logo and logo.filename: logo_url,logo_pid=image_upload(logo,'pidomix/stores/logos')
        if cover and cover.filename: cover_url,cover_pid=image_upload(cover,'pidomix/stores/covers')
        store=Store(name=name.strip(),slug=slug,description=description.strip(),phone=phone.strip(),whatsapp=whatsapp.strip(),address=address.strip(),store_category_id=store_category_id,delivery_enabled=delivery_enabled,delivery_cost=max(0,delivery_cost),minimum_order=max(0,minimum_order),estimated_minutes=max(1,estimated_minutes),featured=featured,logo_url=logo_url,logo_public_id=logo_pid,cover_url=cover_url,cover_public_id=cover_pid)
        db.add(store); db.flush()
        db.add(User(email=owner_email,password_hash=hash_password(owner_password),role=Role.STORE_ADMIN,store_id=store.id))
        db.commit()
    except (ValueError, RuntimeError):
        db.rollback()
        return RedirectResponse('/admin/stores?error=image',303)
    return RedirectResponse('/admin/stores?ok=store_created',303)


@router.post('/stores/{store_id}/edit')
def store_edit(store_id:int,request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),phone:str=Form(''),whatsapp:str=Form(''),address:str=Form(''),store_category_id:int|None=Form(None),delivery_enabled:bool=Form(False),delivery_cost:float=Form(0),minimum_order:float=Form(0),estimated_minutes:int=Form(30),featured:bool=Form(False),logo:UploadFile|None=File(None),cover:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=db.get(Store,store_id)
    if not s or not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    slug=safe_slug(slug)
    duplicate=db.scalar(select(Store).where(Store.slug==slug, Store.id!=store_id))
    if duplicate: return RedirectResponse('/admin/stores?error=slug',303)
    try:
        s.name=name.strip(); s.slug=slug; s.description=description.strip(); s.phone=phone.strip(); s.whatsapp=whatsapp.strip(); s.address=address.strip(); s.store_category_id=store_category_id
        s.delivery_enabled=delivery_enabled; s.delivery_cost=max(0,delivery_cost); s.minimum_order=max(0,minimum_order); s.estimated_minutes=max(1,estimated_minutes); s.featured=featured
        if logo and logo.filename:
            new_url,new_pid=image_upload(logo,'pidomix/stores/logos')
            if s.logo_public_id: delete(s.logo_public_id)
            s.logo_url,s.logo_public_id=new_url,new_pid
        if cover and cover.filename:
            new_url,new_pid=image_upload(cover,'pidomix/stores/covers')
            if s.cover_public_id: delete(s.cover_public_id)
            s.cover_url,s.cover_public_id=new_url,new_pid
        db.commit()
    except (ValueError, RuntimeError):
        db.rollback(); return RedirectResponse('/admin/stores?error=image',303)
    return RedirectResponse('/admin/stores',303)


@router.post('/stores/{store_id}/owner')
def store_owner_create(store_id:int,request:Request,owner_email:str=Form(...),owner_password:str=Form(...),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN or not db.get(Store,store_id): return RedirectResponse('/admin/stores',303)
    owner_email=owner_email.strip().lower()
    if not owner_email or len(owner_password)<8 or db.scalar(select(User).where(User.email==owner_email)):
        return RedirectResponse('/admin/stores?error=owner',303)
    db.add(User(email=owner_email,password_hash=hash_password(owner_password),role=Role.STORE_ADMIN,store_id=store_id)); db.commit()
    return RedirectResponse('/admin/stores?ok=owner_created',303)


@router.post('/stores/{store_id}/toggle')
def store_toggle(store_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=db.get(Store,store_id)
    if not s or not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    s.status = StoreStatus.INACTIVA if s.status != StoreStatus.INACTIVA else StoreStatus.ACTIVA
    db.commit(); return RedirectResponse('/admin/stores',303)


@router.post('/stores/{store_id}/hours')
async def store_hours(store_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not can_manage_store(u, store_id) or not db.get(Store, store_id): return RedirectResponse('/admin/stores', 303)
    form = await request.form()
    for weekday in range(7):
        op, cl = (form.get(f'd{weekday}_open') or '09:00'), (form.get(f'd{weekday}_close') or '21:00')
        hour = db.scalar(select(StoreHour).where(StoreHour.store_id == store_id, StoreHour.weekday == weekday))
        if not hour:
            hour = StoreHour(store_id=store_id, weekday=weekday); db.add(hour)
        hour.open_time, hour.close_time, hour.closed = op[:5], cl[:5], form.get(f'd{weekday}_closed') is not None
    db.commit()
    return RedirectResponse('/admin/stores?ok=hours', 303)


@router.post('/stores/{store_id}/open-close')
def store_open_close(store_id: int, request: Request, back: str = Form('/admin'), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.get(Store, store_id)
    if s and can_manage_store(u, store_id) and s.status != StoreStatus.INACTIVA:
        s.status = StoreStatus.CERRADA if s.status == StoreStatus.ACTIVA else StoreStatus.ACTIVA; db.commit()
    return RedirectResponse(back if back.startswith('/admin') else '/admin', 303)


@router.get('/store-categories', response_class=HTMLResponse)
def store_categories(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(StoreCategory).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse('admin/store_categories.html',{'request':request,'user':u,'categories':rows})


@router.post('/store-categories')
def store_category_create(request:Request,name:str=Form(...),slug:str=Form(...),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    slug=safe_slug(slug)
    if not db.scalar(select(StoreCategory).where((StoreCategory.slug==slug)|(StoreCategory.name==name.strip()))):
        db.add(StoreCategory(name=name.strip(),slug=slug)); db.commit()
    return RedirectResponse('/admin/store-categories',303)


@router.post('/store-categories/{category_id}/toggle')
def store_category_toggle(category_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    c=db.get(StoreCategory,category_id)
    if c and u.role==Role.SUPERADMIN: c.active=not c.active; db.commit()
    return RedirectResponse('/admin/store-categories',303)


@router.get('/categories', response_class=HTMLResponse)
def categories(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(Category).order_by(Category.display_order,Category.name)).all()
    return templates.TemplateResponse('admin/categories.html',{'request':request,'user':u,'categories':rows})


@router.post('/categories')
def category_create(request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    slug=safe_slug(slug)
    if db.scalar(select(Category).where((Category.slug==slug)|(Category.name==name.strip()))): return RedirectResponse('/admin/categories?error=duplicate',303)
    try:
        image_url=image_pid=None
        if file and file.filename: image_url,image_pid=image_upload(file,'pidomix/categories')
        db.add(Category(name=name.strip(),slug=slug,description=description.strip(),image_url=image_url,image_public_id=image_pid,display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/categories?error=image',303)
    return RedirectResponse('/admin/categories',303)


@router.post('/categories/{category_id}/edit')
def category_edit(category_id:int,request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    c=db.get(Category,category_id)
    if not c: return RedirectResponse('/admin/categories',303)
    slug=safe_slug(slug)
    if db.scalar(select(Category).where(Category.slug==slug,Category.id!=category_id)): return RedirectResponse('/admin/categories?error=duplicate',303)
    try:
        c.name=name.strip(); c.slug=slug; c.description=description.strip(); c.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/categories')
            if c.image_public_id: delete(c.image_public_id)
            c.image_url,c.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/categories?error=image',303)
    return RedirectResponse('/admin/categories',303)


@router.post('/categories/{category_id}/toggle')
def category_toggle(category_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    c=db.get(Category,category_id)
    if c: c.active=not c.active; db.commit()
    return RedirectResponse('/admin/categories',303)


@router.get('/products', response_class=HTMLResponse)
def products(request:Request,q:str='',db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stores_stmt=select(Store).order_by(Store.name)
    product_stmt=select(Product).options(joinedload(Product.store),joinedload(Product.category)).order_by(Product.store_id,Product.display_order,Product.name)
    if u.role != Role.SUPERADMIN:
        stores_stmt=stores_stmt.where(Store.id==u.store_id); product_stmt=product_stmt.where(Product.store_id==u.store_id)
    if q.strip(): product_stmt=product_stmt.where(Product.name.ilike(f'%{q.strip()}%'))
    stores=db.scalars(stores_stmt).all(); rows=db.scalars(product_stmt).all(); cats=db.scalars(select(Category).where(Category.active).order_by(Category.name)).all()
    sections=db.scalars(select(StoreSection).where(StoreSection.store_id==u.store_id,StoreSection.active).order_by(StoreSection.display_order)).all() if u.role != Role.SUPERADMIN and u.store_id else []
    return templates.TemplateResponse('admin/products.html',{'request':request,'user':u,'products':rows,'stores':stores,'categories':cats,'sections':sections,'q':q})


@router.post('/products')
def product_create(request:Request,name:str=Form(...),price:float=Form(...),store_id:int=Form(...),category_id:int|None=Form(None),section_id:int|None=Form(None),description:str=Form(''),previous_price:float|None=Form(None),stock:int|None=Form(None),featured:bool=Form(False),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if not can_manage_store(u,store_id): return RedirectResponse('/admin/products',303)
    try:
        url=pid=None
        if file and file.filename: url,pid=image_upload(file,'pidomix/products')
        db.add(Product(name=name.strip(),price=max(0,price),store_id=store_id,category_id=category_id,section_id=section_id,description=description.strip(),previous_price=previous_price, image_url=url,image_public_id=pid,stock=stock,featured=featured,display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/products?error=image',303)
    return RedirectResponse('/admin/products',303)


@router.post('/products/{product_id}/edit')
def product_edit(product_id:int,request:Request,name:str=Form(...),price:float=Form(...),store_id:int=Form(...),category_id:int|None=Form(None),section_id:int|None=Form(None),description:str=Form(''),previous_price:float|None=Form(None),stock:int|None=Form(None),featured:bool=Form(False),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    p=db.get(Product,product_id)
    if not p or not can_manage_store(u,p.store_id) or not can_manage_store(u,store_id): return RedirectResponse('/admin/products',303)
    try:
        p.name=name.strip(); p.price=max(0,price); p.store_id=store_id; p.category_id=category_id; p.section_id=section_id; p.description=description.strip(); p.previous_price=previous_price; p.stock=stock; p.featured=featured; p.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/products')
            if p.image_public_id: delete(p.image_public_id)
            p.image_url,p.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/products?error=image',303)
    return RedirectResponse('/admin/products',303)


@router.post('/products/{product_id}/duplicate')
def product_duplicate(product_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.get(Product, product_id)
    if p and can_manage_store(u, p.store_id):
        db.add(Product(name=f'{p.name} (copia)'[:180], description=p.description, price=p.price, previous_price=p.previous_price, status=ProductStatus.INACTIVO, stock=p.stock, featured=False, display_order=p.display_order, store_id=p.store_id, category_id=p.category_id)); db.commit()
    return RedirectResponse('/admin/products?ok=duplicated', 303)


@router.post('/products/bulk-price')
def products_bulk_price(request: Request, store_id: int = Form(...), percent: float = Form(...), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if not can_manage_store(u, store_id) or not -50 <= percent <= 100 or percent == 0: return RedirectResponse('/admin/products?error=percent', 303)
    factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
    for p in db.scalars(select(Product).where(Product.store_id == store_id)):
        p.price = (Decimal(p.price) * factor).quantize(Decimal('0.01'))
    db.commit()
    return RedirectResponse('/admin/products?ok=prices', 303)


@router.post('/products/{product_id}/toggle')
def product_toggle(product_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    p=db.get(Product,product_id)
    if p and can_manage_store(u,p.store_id): p.status=ProductStatus.INACTIVO if p.status==ProductStatus.ACTIVO else ProductStatus.ACTIVO; db.commit()
    return RedirectResponse('/admin/products',303)


@router.get('/banners', response_class=HTMLResponse)
def banners(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(Banner).order_by(Banner.display_order,Banner.id)).all()
    return templates.TemplateResponse('admin/banners.html',{'request':request,'user':u,'banners':rows})


@router.post('/banners')
def banner_create(request:Request,file:UploadFile=File(...),title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:int=Form(0),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    try:
        url,pid=image_upload(file,'pidomix/banners'); db.add(Banner(image_url=url,image_public_id=pid,title=title.strip(),subtitle=subtitle.strip(),button_text=button_text.strip(),link=link.strip(),display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/banners?error=image',303)
    return RedirectResponse('/admin/banners',303)


@router.post('/banners/{banner_id}/edit')
def banner_edit(banner_id:int,request:Request,title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    b=db.get(Banner,banner_id)
    if not b: return RedirectResponse('/admin/banners',303)
    try:
        b.title=title.strip(); b.subtitle=subtitle.strip(); b.button_text=button_text.strip(); b.link=link.strip(); b.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/banners')
            if b.image_public_id: delete(b.image_public_id)
            b.image_url,b.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/banners?error=image',303)
    return RedirectResponse('/admin/banners',303)


@router.post('/banners/{banner_id}/toggle')
def banner_toggle(banner_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    b=db.get(Banner,banner_id)
    if b: b.active=not b.active; db.commit()
    return RedirectResponse('/admin/banners',303)


def _order_scope(u):
    return [] if u.role == Role.SUPERADMIN else [Order.store_id == u.store_id]


@router.get('/orders', response_class=HTMLResponse)
def orders(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    base = select(Order).options(joinedload(Order.store), joinedload(Order.customer), joinedload(Order.items)).where(*_order_scope(u))
    done = (OrderStatus.ENTREGADO, OrderStatus.CANCELADO)
    active = db.scalars(base.where(Order.status.not_in(done)).order_by(Order.created_at)).unique().all()
    history = db.scalars(base.where(Order.status.in_(done)).order_by(Order.created_at.desc()).limit(30)).unique().all()
    columns = [(st, [o for o in active if o.status == st]) for st in FLOW[:-1]]
    return templates.TemplateResponse('admin/orders.html', {'request': request, 'user': u, 'columns': columns, 'history': history, 'statuses': list(OrderStatus), 'to_local': to_local})


@router.get('/orders/pending')
def orders_pending(request: Request, db: Session = Depends(get_db)):
    u = auth(request, db)
    if not u: return JSONResponse({'error': 'auth'}, status_code=401)
    where = _order_scope(u)
    pending = db.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.PENDIENTE, *where)) or 0
    latest = db.scalar(select(func.max(Order.id)).where(*where)) or 0
    return {'pending': pending, 'latest': latest}


@router.get('/orders/{order_id}', response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    o = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer), joinedload(Order.items)).where(Order.id == order_id)).unique().first()
    if not o or not can_manage_store(u, o.store_id): return RedirectResponse('/admin/orders', 303)
    return templates.TemplateResponse('admin/order_detail.html', {'request': request, 'user': u, 'o': o, 'statuses': list(OrderStatus), 'to_local': to_local})


@router.post('/orders/{order_id}/status')
def order_status(order_id: int, request: Request, status: OrderStatus = Form(...), back: str = Form('/admin/orders'), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    order = db.get(Order, order_id)
    if order and can_manage_store(u, order.store_id): order.status = status; db.commit()
    return RedirectResponse(back if back.startswith('/admin') else '/admin/orders', 303)


def _csv_safe(v):
    v = '' if v is None else str(v)
    return "'" + v if v[:1] in ('=', '+', '-', '@') else v


@router.get('/reports/export.csv')
def reports_export(request: Request, days: int = 30, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    days = days if days in (7, 14, 30, 90) else 30
    rows = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(Order.created_at >= local_day_start_utc(days - 1), *_order_scope(u)).order_by(Order.created_at.desc())).unique().all()
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(['Pedido', 'Fecha', 'Tienda', 'Cliente', 'Telefono', 'Entrega', 'Direccion', 'Subtotal', 'Envio', 'Total', 'Estado'])
    for o in rows:
        c = o.customer
        w.writerow([o.id, to_local(o.created_at).strftime('%Y-%m-%d %H:%M'), o.store.name, _csv_safe(f'{c.first_name} {c.last_name}') if c else '', _csv_safe(c.phone) if c else '', o.delivery_method, _csv_safe(o.address), o.subtotal, o.shipping, o.total, o.status.value])
    return Response('\ufeff' + buf.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=trappi-pedidos-{days}d.csv'})


@router.get('/reports', response_class=HTMLResponse)
def reports(request: Request, days: int = 14, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    days = days if days in (7, 14, 30) else 14
    since = local_day_start_utc(days - 1)
    rows = db.execute(select(Order.created_at, Order.total, Order.delivery_method, Order.status).where(Order.created_at >= since, *_order_scope(u))).all()
    by_day = {}
    for i in range(days):
        d = (local_now() - timedelta(days=days - 1 - i)).date(); by_day[d] = [0, Decimal(0)]
    delivery = pickup = cancelled = 0
    for created, total, method, status in rows:
        if status == OrderStatus.CANCELADO: cancelled += 1; continue
        slot = by_day.get(to_local(created).date())
        if slot: slot[0] += 1; slot[1] += Decimal(total)
        if method == 'delivery': delivery += 1
        else: pickup += 1
    peak = max((v[1] for v in by_day.values()), default=0) or 1
    series = [{'label': d.strftime('%d/%m'), 'orders': v[0], 'revenue': v[1], 'pct': int(v[1] * 100 / peak)} for d, v in by_day.items()]
    total_orders, total_revenue = sum(x['orders'] for x in series), sum((x['revenue'] for x in series), Decimal(0))
    top = db.execute(select(OrderItem.product_name, func.sum(OrderItem.quantity).label('qty'), func.sum(OrderItem.quantity * OrderItem.unit_price).label('amount')).join(Order, Order.id == OrderItem.order_id).where(Order.created_at >= since, Order.status != OrderStatus.CANCELADO, *_order_scope(u)).group_by(OrderItem.product_name).order_by(desc('qty')).limit(8)).all()
    return templates.TemplateResponse('admin/reports.html', {'request': request, 'user': u, 'days': days, 'series': series, 'total_orders': total_orders, 'total_revenue': total_revenue, 'avg': (total_revenue / total_orders) if total_orders else 0, 'delivery': delivery, 'pickup': pickup, 'cancelled': cancelled, 'top': top})


def _coupon_scope(u):
    return [] if u.role == Role.SUPERADMIN else [Coupon.store_id == u.store_id]


@router.get('/sections', response_class=HTMLResponse)
def sections(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN and not u.store_id: return RedirectResponse('/admin', 303)
    store_id = u.store_id if u.role != Role.SUPERADMIN else request.query_params.get('store_id', type=int)
    stores = db.scalars(select(Store).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    rows = db.scalars(select(StoreSection).where(StoreSection.store_id == store_id).order_by(StoreSection.display_order)).all() if store_id else []
    return templates.TemplateResponse('admin/sections.html', {'request': request, 'user': u, 'sections': rows, 'stores': stores, 'store_id': store_id})


@router.post('/sections')
def section_create(request: Request, name: str = Form(...), display_order: int = Form(0), store_id: int | None = Form(None), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    target = store_id if u.role == Role.SUPERADMIN else u.store_id
    if not target or not can_manage_store(u, target): return RedirectResponse('/admin/sections', 303)
    db.add(StoreSection(store_id=target, name=name.strip(), display_order=display_order)); db.commit()
    return RedirectResponse(f'/admin/sections?store_id={target}&ok=1', 303)


@router.post('/sections/{section_id}/toggle')
def section_toggle(section_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    sec = db.get(StoreSection, section_id)
    if sec and can_manage_store(u, sec.store_id): sec.active = not sec.active; db.commit()
    return RedirectResponse(f'/admin/sections?store_id={sec.store_id}' if sec else '/admin/sections', 303)


@router.get('/products/{product_id}/modifiers', response_class=HTMLResponse)
def product_modifiers_page(product_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.scalar(select(Product).options(selectinload(Product.modifier_groups).selectinload(ModifierGroup.options)).where(Product.id == product_id))
    if not p or not can_manage_store(u, p.store_id): return RedirectResponse('/admin/products', 303)
    return templates.TemplateResponse('admin/modifiers.html', {'request': request, 'user': u, 'p': p})


@router.post('/products/{product_id}/modifiers')
def modifier_group_create(product_id: int, request: Request, name: str = Form(...), required: bool = Form(False), max_select: int = Form(1), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.get(Product, product_id)
    if not p or not can_manage_store(u, p.store_id): return RedirectResponse('/admin/products', 303)
    db.add(ModifierGroup(product_id=product_id, name=name.strip(), required=required, min_select=1 if required else 0, max_select=max(1, max_select))); db.commit()
    return RedirectResponse(f'/admin/products/{product_id}/modifiers', 303)


@router.post('/modifier-groups/{group_id}/delete')
def modifier_group_delete(group_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    g = db.get(ModifierGroup, group_id)
    if g and can_manage_store(u, g.product.store_id):
        pid = g.product_id; db.delete(g); db.commit()
        return RedirectResponse(f'/admin/products/{pid}/modifiers', 303)
    return RedirectResponse('/admin/products', 303)


@router.post('/modifier-groups/{group_id}/options')
def modifier_option_create(group_id: int, request: Request, name: str = Form(...), price_extra: float = Form(0), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    g = db.get(ModifierGroup, group_id)
    if not g or not can_manage_store(u, g.product.store_id): return RedirectResponse('/admin/products', 303)
    db.add(ModifierOption(group_id=group_id, name=name.strip(), price_extra=max(0, price_extra))); db.commit()
    return RedirectResponse(f'/admin/products/{g.product_id}/modifiers', 303)


@router.post('/modifier-options/{option_id}/toggle')
def modifier_option_toggle(option_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    o = db.get(ModifierOption, option_id)
    if o and can_manage_store(u, o.group.product.store_id):
        o.active = not o.active; db.commit()
        return RedirectResponse(f'/admin/products/{o.group.product_id}/modifiers', 303)
    return RedirectResponse('/admin/products', 303)


@router.get('/coupons', response_class=HTMLResponse)
def coupons(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    stores = db.scalars(select(Store).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    rows = db.scalars(select(Coupon).options(joinedload(Coupon.store)).where(*_coupon_scope(u)).order_by(Coupon.active.desc(), Coupon.created_at.desc())).all()
    return templates.TemplateResponse('admin/coupons.html', {'request': request, 'user': u, 'coupons': rows, 'stores': stores})


@router.post('/coupons')
def coupon_create(request: Request, code: str = Form(...), discount_type: str = Form('percent'), discount_value: float = Form(...), min_order: float = Form(0), max_uses: int | None = Form(None), expires_at: str = Form(''), store_id: int | None = Form(None), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    target_store = store_id if u.role == Role.SUPERADMIN else u.store_id
    if not target_store or not can_manage_store(u, target_store): return RedirectResponse('/admin/coupons?error=owner', 303)
    code = code.strip().upper()
    if not code or db.scalar(select(Coupon).where(Coupon.store_id == target_store, func.upper(Coupon.code) == code)):
        return RedirectResponse('/admin/coupons?error=duplicate', 303)
    exp = datetime.fromisoformat(expires_at) if expires_at else None
    db.add(Coupon(store_id=target_store, code=code, discount_type='fixed' if discount_type == 'fixed' else 'percent', discount_value=max(0, discount_value), min_order=max(0, min_order), max_uses=max_uses if max_uses and max_uses > 0 else None, expires_at=exp))
    db.commit()
    return RedirectResponse('/admin/coupons?ok=1', 303)


@router.post('/coupons/{coupon_id}/toggle')
def coupon_toggle(coupon_id: int, request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Coupon, coupon_id)
    if c and can_manage_store(u, c.store_id): c.active = not c.active; db.commit()
    return RedirectResponse('/admin/coupons', 303)


@router.get('/reviews', response_class=HTMLResponse)
def reviews_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    where = [] if u.role == Role.SUPERADMIN else [Review.store_id == u.store_id]
    rows = db.scalars(select(Review).options(joinedload(Review.store), joinedload(Review.order)).where(*where).order_by(Review.created_at.desc()).limit(80)).all()
    return templates.TemplateResponse('admin/reviews.html', {'request': request, 'user': u, 'reviews': rows})


@router.get('/customers', response_class=HTMLResponse)
def customers(request:Request,q:str='',db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    spent = func.coalesce(func.sum(case((Order.status != OrderStatus.CANCELADO, Order.total), else_=0)), 0)
    stmt = select(Customer, func.count(Order.id), spent, func.max(Order.created_at)).join(Order, Order.customer_id == Customer.id)
    if u.role != Role.SUPERADMIN: stmt = stmt.where(Order.store_id == u.store_id)
    if q.strip():
        term = f'%{q.strip()}%'
        stmt = stmt.where((Customer.first_name.ilike(term)) | (Customer.last_name.ilike(term)) | (Customer.phone.ilike(term)))
    rows = db.execute(stmt.group_by(Customer.id).order_by(func.max(Order.created_at).desc()).limit(300)).all()
    return templates.TemplateResponse('admin/customers.html',{'request':request,'user':u,'rows':rows,'q':q,'to_local':to_local})


@router.get('/users', response_class=HTMLResponse)
def users(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    rows=db.scalars(select(User).options(joinedload(User.store)).order_by(User.email)).all()
    stores=db.scalars(select(Store).order_by(Store.name)).all()
    return templates.TemplateResponse('admin/users.html',{'request':request,'user':u,'users':rows,'stores':stores,'roles':[Role.STORE_ADMIN,Role.REPARTIDOR,Role.CLIENTE]})


@router.post('/users')
def user_create(request:Request,email:str=Form(...),password:str=Form(...),role:Role=Form(Role.STORE_ADMIN),store_id:int|None=Form(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin',303)
    email=email.strip().lower()
    if db.scalar(select(User).where(User.email==email)) or len(password)<8: return RedirectResponse('/admin/users?error=invalid',303)
    db.add(User(email=email,password_hash=hash_password(password),role=role,store_id=store_id if role==Role.STORE_ADMIN else None)); db.commit()
    return RedirectResponse('/admin/users',303)


@router.post('/users/{user_id}/toggle')
def user_toggle(user_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    target=db.get(User,user_id)
    if target and u.role==Role.SUPERADMIN and target.id != u.id: target.active=not target.active; db.commit()
    return RedirectResponse('/admin/users',303)
