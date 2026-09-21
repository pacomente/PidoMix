from pathlib import Path
from decimal import Decimal
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from ..db import get_db
from ..models import Banner, Category, Customer, Order, OrderStatus, Product, ProductStatus, Role, Store, StoreCategory, StoreHour, StoreStatus, User
from ..services.auth import current_user, hash_password, verify_password
from ..services.cloudinary_service import delete, upload

router = APIRouter()
templates = __import__('fastapi').templating.Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


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
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not u or not u.active or not verify_password(password, u.password_hash):
        return templates.TemplateResponse('admin/login.html', {'request': request, 'error': 'Credenciales inválidas'}, status_code=401)
    request.session.clear()
    request.session['user_id'] = u.id
    return RedirectResponse('/admin', 303)


@router.get('/logout')
def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/admin/login', 303)


@router.get('', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    store_filter = [] if u.role == Role.SUPERADMIN else [Store.id == u.store_id]
    product_filter = [] if u.role == Role.SUPERADMIN else [Product.store_id == u.store_id]
    order_filter = [] if u.role == Role.SUPERADMIN else [Order.store_id == u.store_id]
    stores_count = db.scalar(select(func.count(Store.id)).where(*store_filter)) or 0
    products_count = db.scalar(select(func.count(Product.id)).where(*product_filter)) or 0
    orders_count = db.scalar(select(func.count(Order.id)).where(*order_filter)) or 0
    pending = db.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.PENDIENTE, *order_filter)) or 0
    customers_count = db.scalar(select(func.count(Customer.id))) or 0
    recent = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(*order_filter).order_by(Order.created_at.desc()).limit(8)).all()
    return templates.TemplateResponse('admin/dashboard.html', {'request':request,'user':u,'stores':stores_count,'products':products_count,'orders':orders_count,'pending':pending,'customers':customers_count,'recent':recent})


@router.get('/stores', response_class=HTMLResponse)
def store_list(request: Request, db: Session = Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stmt=select(Store).options(joinedload(Store.store_category), joinedload(Store.hours)).order_by(Store.name)
    if u.role != Role.SUPERADMIN: stmt=stmt.where(Store.id==u.store_id)
    stores=db.scalars(stmt).unique().all()
    categories=db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse('admin/stores.html',{'request':request,'user':u,'stores':stores,'categories':categories})


@router.post('/stores')
def store_create(request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),phone:str=Form(''),whatsapp:str=Form(''),address:str=Form(''),store_category_id:int|None=Form(None),delivery_enabled:bool=Form(False),delivery_cost:float=Form(0),minimum_order:float=Form(0),estimated_minutes:int=Form(30),featured:bool=Form(False),logo:UploadFile|None=File(None),cover:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin/stores',303)
    slug=safe_slug(slug)
    if db.scalar(select(Store).where(Store.slug == slug)):
        return RedirectResponse('/admin/stores?error=slug',303)
    try:
        logo_url=logo_pid=image_url=image_pid=None
        cover_url=cover_pid=None
        if logo and logo.filename: logo_url,logo_pid=image_upload(logo,'pidomix/stores/logos')
        if cover and cover.filename: cover_url,cover_pid=image_upload(cover,'pidomix/stores/covers')
        db.add(Store(name=name.strip(),slug=slug,description=description.strip(),phone=phone.strip(),whatsapp=whatsapp.strip(),address=address.strip(),store_category_id=store_category_id,delivery_enabled=delivery_enabled,delivery_cost=max(0,delivery_cost),minimum_order=max(0,minimum_order),estimated_minutes=max(1,estimated_minutes),featured=featured,logo_url=logo_url,logo_public_id=logo_pid,cover_url=cover_url,cover_public_id=cover_pid))
        db.commit()
    except (ValueError, RuntimeError):
        db.rollback()
        return RedirectResponse('/admin/stores?error=image',303)
    return RedirectResponse('/admin/stores',303)


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


@router.post('/stores/{store_id}/toggle')
def store_toggle(store_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=db.get(Store,store_id)
    if not s or not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    s.status = StoreStatus.INACTIVA if s.status != StoreStatus.INACTIVA else StoreStatus.ACTIVA
    db.commit(); return RedirectResponse('/admin/stores',303)


@router.post('/stores/{store_id}/hours')
def store_hours(store_id:int,request:Request,db:Session=Depends(get_db), monday_open:str=Form('09:00'),monday_close:str=Form('21:00'),tuesday_open:str=Form('09:00'),tuesday_close:str=Form('21:00'),wednesday_open:str=Form('09:00'),wednesday_close:str=Form('21:00'),thursday_open:str=Form('09:00'),thursday_close:str=Form('21:00'),friday_open:str=Form('09:00'),friday_close:str=Form('21:00'),saturday_open:str=Form('09:00'),saturday_close:str=Form('21:00'),sunday_open:str=Form('09:00'),sunday_close:str=Form('21:00')):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    store=db.get(Store,store_id)
    if not store: return RedirectResponse('/admin/stores',303)
    values=[(monday_open,monday_close),(tuesday_open,tuesday_close),(wednesday_open,wednesday_close),(thursday_open,thursday_close),(friday_open,friday_close),(saturday_open,saturday_close),(sunday_open,sunday_close)]
    for weekday,(op,cl) in enumerate(values):
        hour=db.scalar(select(StoreHour).where(StoreHour.store_id==store_id,StoreHour.weekday==weekday))
        if not hour:
            hour=StoreHour(store_id=store_id,weekday=weekday); db.add(hour)
        hour.open_time=op; hour.close_time=cl; hour.closed=False
    db.commit(); return RedirectResponse('/admin/stores',303)


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
    rows=db.scalars(select(Category).order_by(Category.display_order,Category.name)).all()
    return templates.TemplateResponse('admin/categories.html',{'request':request,'user':u,'categories':rows})


@router.post('/categories')
def category_create(request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
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
    c=db.get(Category,category_id)
    if c: c.active=not c.active; db.commit()
    return RedirectResponse('/admin/categories',303)


@router.get('/products', response_class=HTMLResponse)
def products(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stores_stmt=select(Store).order_by(Store.name)
    product_stmt=select(Product).options(joinedload(Product.store),joinedload(Product.category)).order_by(Product.store_id,Product.display_order,Product.name)
    if u.role != Role.SUPERADMIN:
        stores_stmt=stores_stmt.where(Store.id==u.store_id); product_stmt=product_stmt.where(Product.store_id==u.store_id)
    stores=db.scalars(stores_stmt).all(); rows=db.scalars(product_stmt).all(); cats=db.scalars(select(Category).where(Category.active).order_by(Category.name)).all()
    return templates.TemplateResponse('admin/products.html',{'request':request,'user':u,'products':rows,'stores':stores,'categories':cats})


@router.post('/products')
def product_create(request:Request,name:str=Form(...),price:float=Form(...),store_id:int=Form(...),category_id:int|None=Form(None),description:str=Form(''),previous_price:float|None=Form(None),stock:int|None=Form(None),featured:bool=Form(False),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if not can_manage_store(u,store_id): return RedirectResponse('/admin/products',303)
    try:
        url=pid=None
        if file and file.filename: url,pid=image_upload(file,'pidomix/products')
        db.add(Product(name=name.strip(),price=max(0,price),store_id=store_id,category_id=category_id,description=description.strip(),previous_price=previous_price, image_url=url,image_public_id=pid,stock=stock,featured=featured,display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/products?error=image',303)
    return RedirectResponse('/admin/products',303)


@router.post('/products/{product_id}/edit')
def product_edit(product_id:int,request:Request,name:str=Form(...),price:float=Form(...),store_id:int=Form(...),category_id:int|None=Form(None),description:str=Form(''),previous_price:float|None=Form(None),stock:int|None=Form(None),featured:bool=Form(False),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    p=db.get(Product,product_id)
    if not p or not can_manage_store(u,p.store_id) or not can_manage_store(u,store_id): return RedirectResponse('/admin/products',303)
    try:
        p.name=name.strip(); p.price=max(0,price); p.store_id=store_id; p.category_id=category_id; p.description=description.strip(); p.previous_price=previous_price; p.stock=stock; p.featured=featured; p.display_order=display_order
        if file and file.filename:
            url,pid=image_upload(file,'pidomix/products')
            if p.image_public_id: delete(p.image_public_id)
            p.image_url,p.image_public_id=url,pid
        db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/products?error=image',303)
    return RedirectResponse('/admin/products',303)


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
    rows=db.scalars(select(Banner).order_by(Banner.display_order,Banner.id)).all()
    return templates.TemplateResponse('admin/banners.html',{'request':request,'user':u,'banners':rows})


@router.post('/banners')
def banner_create(request:Request,file:UploadFile=File(...),title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:int=Form(0),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    try:
        url,pid=image_upload(file,'pidomix/banners'); db.add(Banner(image_url=url,image_public_id=pid,title=title.strip(),subtitle=subtitle.strip(),button_text=button_text.strip(),link=link.strip(),display_order=display_order)); db.commit()
    except (ValueError, RuntimeError): db.rollback(); return RedirectResponse('/admin/banners?error=image',303)
    return RedirectResponse('/admin/banners',303)


@router.post('/banners/{banner_id}/edit')
def banner_edit(banner_id:int,request:Request,title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:int=Form(0),file:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
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
    b=db.get(Banner,banner_id)
    if b: b.active=not b.active; db.commit()
    return RedirectResponse('/admin/banners',303)


@router.get('/orders', response_class=HTMLResponse)
def orders(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stmt=select(Order).options(joinedload(Order.store),joinedload(Order.customer)).order_by(Order.created_at.desc())
    if u.role != Role.SUPERADMIN: stmt=stmt.where(Order.store_id==u.store_id)
    rows=db.scalars(stmt).all()
    return templates.TemplateResponse('admin/orders.html',{'request':request,'user':u,'orders':rows,'statuses':list(OrderStatus)})


@router.post('/orders/{order_id}/status')
def order_status(order_id:int,request:Request,status:OrderStatus=Form(...),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    order=db.get(Order,order_id)
    if order and can_manage_store(u,order.store_id): order.status=status; db.commit()
    return RedirectResponse('/admin/orders',303)


@router.get('/customers', response_class=HTMLResponse)
def customers(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    rows=db.scalars(select(Customer).order_by(Customer.created_at.desc())).all()
    return templates.TemplateResponse('admin/customers.html',{'request':request,'user':u,'customers':rows})


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
