from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..models import Banner, Category, Order, Product, Role, Store, StoreCategory, StoreStatus, User
from ..services.auth import current_user, hash_password, verify_password
from ..services.cloudinary_service import upload

router=APIRouter()
templates=__import__('fastapi').templating.Jinja2Templates(directory=str(Path(__file__).resolve().parents[1]/'templates'))

def auth(request,db):
    u=current_user(request,db); return u if u and u.active and u.role in (Role.SUPERADMIN,Role.STORE_ADMIN) else None

def guard(request,db):
    u=auth(request,db)
    if not u: return RedirectResponse('/admin/login',303)
    return u

@router.get('/login',response_class=HTMLResponse)
def login_page(request: Request): return templates.TemplateResponse('admin/login.html',{'request':request})
@router.post('/login')
def login(request: Request,email:str=Form(...),password:str=Form(...),db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==email))
    if not u or not verify_password(password,u.password_hash): return templates.TemplateResponse('admin/login.html',{'request':request,'error':'Credenciales inválidas'},status_code=401)
    request.session['user_id']=u.id; return RedirectResponse('/admin',303)
@router.get('/logout')
def logout(request: Request): request.session.clear(); return RedirectResponse('/admin/login',303)

@router.get('',response_class=HTMLResponse)
def dashboard(request: Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    data={'request':request,'user':u,'stores':db.scalar(select(func.count(Store.id))) or 0,'products':db.scalar(select(func.count(Product.id))) or 0,'orders':db.scalar(select(func.count(Order.id))) or 0,'categories':db.scalar(select(func.count(Category.id))) or 0}
    return templates.TemplateResponse('admin/dashboard.html',data)

@router.get('/stores',response_class=HTMLResponse)
def store_list(request:Request,db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    stores=db.scalars(select(Store).order_by(Store.name)).all(); return templates.TemplateResponse('admin/stores.html',{'request':request,'user':u,'stores':stores})

@router.post('/stores')
def store_create(request:Request,name:str=Form(...),slug:str=Form(...),whatsapp:str=Form(''),delivery_enabled:bool=Form(False),delivery_cost:float=Form(0),minimum_order:float=Form(0),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    s=Store(name=name,slug=slug,whatsapp=whatsapp,delivery_enabled=delivery_enabled,delivery_cost=delivery_cost,minimum_order=minimum_order); db.add(s); db.commit(); return RedirectResponse('/admin/stores',303)

@router.post('/products')
def product_create(request:Request,name:str=Form(...),price:float=Form(...),store_id:int=Form(...),description:str=Form(''),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    db.add(Product(name=name,price=price,store_id=store_id,description=description)); db.commit(); return RedirectResponse('/admin',303)

@router.post('/banners/upload')
async def banner_upload(request:Request,file:UploadFile=File(...),title:str=Form(''),db:Session=Depends(get_db)):
    u=guard(request,db)
    if isinstance(u,RedirectResponse): return u
    url,pid=upload(file.file,'pidomix/banners'); db.add(Banner(image_url=url,image_public_id=pid,title=title)); db.commit(); return RedirectResponse('/admin',303)
