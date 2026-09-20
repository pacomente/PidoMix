from decimal import Decimal
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload
from ..db import get_db
from ..models import Banner, Category, Customer, Order, OrderItem, Product, Store, StoreStatus
from ..services.whatsapp import build_message, whatsapp_url

router=APIRouter()

def ctx(request, **kwargs): return {"request":request, **kwargs}

@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session=Depends(get_db)):
    banners=db.scalars(select(Banner).where(Banner.active).order_by(Banner.display_order)).all()
    cats=db.scalars(select(Category).where(Category.active).order_by(Category.name)).all()
    stores=db.scalars(select(Store).where(Store.status==StoreStatus.ACTIVA).order_by(Store.featured.desc(), Store.name)).all()
    return templates.TemplateResponse("public/home.html", ctx(request,banners=banners,categories=cats,stores=stores))

templates=__import__('fastapi').templating.Jinja2Templates(directory=str(__import__('pathlib').Path(__file__).resolve().parents[1]/'templates'))

@router.get("/tiendas", response_class=HTMLResponse)
def stores(request: Request, q: str|None=None, delivery: bool|None=None, db: Session=Depends(get_db)):
    stmt=select(Store).where(Store.status==StoreStatus.ACTIVA)
    if q: stmt=stmt.where(Store.name.ilike(f"%{q}%"))
    if delivery is True: stmt=stmt.where(Store.delivery_enabled.is_(True))
    return templates.TemplateResponse("public/stores.html", ctx(request,stores=db.scalars(stmt.order_by(Store.featured.desc(),Store.name)).all(),q=q))

@router.get("/tienda/{slug}", response_class=HTMLResponse)
def store(slug: str, request: Request, db: Session=Depends(get_db)):
    s=db.scalar(select(Store).options(joinedload(Store.products)).where(Store.slug==slug, Store.status!=StoreStatus.INACTIVA))
    if not s: return HTMLResponse("Tienda no encontrada",404)
    cats=db.scalars(select(Category).where(Category.active)).all()
    return templates.TemplateResponse("public/store.html", ctx(request,store=s,categories=cats))

@router.get("/categoria/{slug}", response_class=HTMLResponse)
def category(slug: str, request: Request, db: Session=Depends(get_db)):
    cat=db.scalar(select(Category).where(Category.slug==slug))
    if not cat: return HTMLResponse("Categoría no encontrada",404)
    products=db.scalars(select(Product).where(Product.category_id==cat.id, Product.status.name=='ACTIVO')).all()
    return templates.TemplateResponse("public/category.html", ctx(request,category=cat,products=products))

@router.get("/checkout", response_class=HTMLResponse)
def checkout(request: Request): return templates.TemplateResponse("public/checkout.html",ctx(request))

@router.post("/checkout")
def checkout_post(request: Request, db: Session=Depends(get_db), first_name: str=Form(...), last_name: str=Form(...), phone: str=Form(...), address: str=Form(""), reference: str=Form(""), delivery_method: str=Form(...), notes: str=Form("")):
    cart=request.session.get("cart",[])
    if not cart: return RedirectResponse("/",303)
    product_ids=[x['product_id'] for x in cart]
    products=db.scalars(select(Product).where(Product.id.in_(product_ids))).all(); by_id={p.id:p for p in products}
    store=by_id[product_ids[0]].store
    items=[]; subtotal=Decimal('0')
    for line in cart:
        p=by_id.get(line['product_id']); qty=int(line['quantity'])
        if not p: continue
        items.append({'product_id':p.id,'name':p.name,'unit_price':Decimal(p.price),'quantity':qty}); subtotal += Decimal(p.price)*qty
    shipping=Decimal(store.delivery_cost or 0) if delivery_method=='delivery' and store.delivery_enabled else Decimal('0')
    total=subtotal+shipping
    customer=Customer(first_name=first_name,last_name=last_name,phone=phone,address=address,reference=reference); db.add(customer); db.flush()
    order=Order(store_id=store.id,customer_id=customer.id,delivery_method=delivery_method,address=address,reference=reference,notes=notes,subtotal=subtotal,shipping=shipping,total=total); db.add(order); db.flush()
    for x in items: db.add(OrderItem(order_id=order.id,product_id=x['product_id'],product_name=x['name'],unit_price=x['unit_price'],quantity=x['quantity']))
    message=build_message(store,{'first_name':first_name,'last_name':last_name,'phone':phone,'address':address,'reference':reference},items,subtotal,shipping,total,delivery_method)
    order.whatsapp_url=whatsapp_url(store.whatsapp, message) if store.whatsapp else whatsapp_url('',message)
    db.commit(); request.session['cart']=[]
    return RedirectResponse(order.whatsapp_url,303)
