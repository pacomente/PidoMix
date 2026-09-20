from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from ..db import get_db
from ..models import Banner, Category, Order, OrderStatus, Product, ProductStatus, Role, Store, StoreCategory, StoreStatus, User
from ..services.auth import current_user, hash_password, verify_password
from ..services.cloudinary_service import upload

router = APIRouter()
templates = __import__('fastapi').templating.Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


def auth(request, db):
    u = current_user(request, db)
    return u if u and u.active and u.role in (Role.SUPERADMIN, Role.STORE_ADMIN) else None


def guard(request, db):
    u = auth(request, db)
    return u if u else RedirectResponse('/admin/login', 303)


def can_manage_store(user, store_id):
    return user.role == Role.SUPERADMIN or user.store_id == store_id


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse('admin/login.html', {'request': request})


@router.post('/login')
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not u or not u.active or not verify_password(password, u.password_hash):
        return templates.TemplateResponse('admin/login.html', {'request': request, 'error': 'Credenciales inválidas'}, status_code=401)
    request.session['user_id'] = u.id
    return RedirectResponse('/admin', 303)


@router.get('/logout')
def logout(request: Request):
    request.session.clear(); return RedirectResponse('/admin/login', 303)


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
    recent = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.customer)).where(*order_filter).order_by(Order.created_at.desc()).limit(8)).all()
    return templates.TemplateResponse('admin/dashboard.html', {'request':request,'user':u,'stores':stores_count,'products':products_count,'orders':orders_count,'pending':pending,'recent':recent})


@router.get('/stores', response_class=HTMLResponse)
def store_list(request: Request, db: Session = Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stmt=select(Store).options(joinedload(Store.store_category)).order_by(Store.name)
    if u.role != Role.SUPERADMIN: stmt=stmt.where(Store.id==u.store_id)
    stores=db.scalars(stmt).all(); categories=db.scalars(select(StoreCategory).where(StoreCategory.active).order_by(StoreCategory.name)).all()
    return templates.TemplateResponse('admin/stores.html',{'request':request,'user':u,'stores':stores,'categories':categories})


@router.post('/stores')
def store_create(request:Request,name:str=Form(...),slug:str=Form(...),description:str=Form(''),phone:str=Form(''),whatsapp:str=Form(''),address:str=Form(''),store_category_id:int|None=Form(None),delivery_enabled:bool=Form(False),delivery_cost:float=Form(0),minimum_order:float=Form(0),estimated_minutes:int=Form(30),featured:bool=Form(False),logo:UploadFile|None=File(None),cover:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin/stores',303)
    logo_url=logo_pid=cover_url=cover_pid=None
    if logo and logo.filename: logo_url,logo_pid=upload(logo.file,'pidomix/stores/logos')
    if cover and cover.filename: cover_url,cover_pid=upload(cover.file,'pidomix/stores/covers')
    db.add(Store(name=name.strip(),slug=slug.strip().lower(),description=description,phone=phone,whatsapp=whatsapp,address=address,store_category_id=store_category_id,delivery_enabled=delivery_enabled,delivery_cost=delivery_cost,minimum_order=minimum_order,estimated_minutes=estimated_minutes,featured=featured,logo_url=logo_url,logo_public_id=logo_pid,cover_url=cover_url,cover_public_id=cover_pid)); db.commit()
    return RedirectResponse('/admin/stores',303)


@router.post('/stores/{store_id}/toggle')
def store_toggle(store_id:int,request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=db.get(Store,store_id)
    if not s or not can_manage_store(u,store_id): return RedirectResponse('/admin/stores',303)
    s.status = StoreStatus.INACTIVA if s.status != StoreStatus.INACTIVA else StoreStatus.ACTIVA; db.commit(); return RedirectResponse('/admin/stores',303)


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
    image_url=image_pid=None
    if file and file.filename:
        image_url,image_pid=upload(file.file,'pidomix/categories')
    db.add(Category(name=name.strip(),slug=slug.strip().lower(),description=description,image_url=image_url,image_public_id=image_pid,display_order=display_order)); db.commit(); return RedirectResponse('/admin/categories',303)


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
    url=pid=None
    if file and file.filename: url,pid=upload(file.file,'pidomix/products')
    db.add(Product(name=name.strip(),price=price,store_id=store_id,category_id=category_id,description=description,previous_price=previous_price,image_url=url,image_public_id=pid,stock=stock,featured=featured,display_order=display_order)); db.commit(); return RedirectResponse('/admin/products',303)


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
    rows=db.scalars(select(Banner).order_by(Banner.display_order,Banner.id)).all(); return templates.TemplateResponse('admin/banners.html',{'request':request,'user':u,'banners':rows})


@router.post('/banners')
def banner_create(request:Request,file:UploadFile=File(...),title:str=Form(''),subtitle:str=Form(''),button_text:str=Form(''),link:str=Form(''),display_order:int=Form(0),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    url,pid=upload(file.file,'pidomix/banners'); db.add(Banner(image_url=url,image_public_id=pid,title=title,subtitle=subtitle,button_text=button_text,link=link,display_order=display_order)); db.commit(); return RedirectResponse('/admin/banners',303)


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
    rows=db.scalars(stmt.limit(100)).all(); return templates.TemplateResponse('admin/orders.html',{'request':request,'user':u,'orders':rows,'statuses':list(OrderStatus)})


@router.post('/orders/{order_id}/status')
def order_status(order_id:int,request:Request,status:OrderStatus=Form(...),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    order=db.get(Order,order_id)
    if order and can_manage_store(u,order.store_id): order.status=status; db.commit()
    return RedirectResponse('/admin/orders',303)
