from .db import Base, SessionLocal, engine
from .models import User, Role, StoreCategory, Store, Category, Product, StoreStatus
from .config import settings
from .services.auth import hash_password
Base.metadata.create_all(engine)
db=SessionLocal()
if not db.query(User).filter_by(email=settings.admin_email).first(): db.add(User(email=settings.admin_email,password_hash=hash_password(settings.admin_password),role=Role.SUPERADMIN))
if not db.query(StoreCategory).first(): db.add(StoreCategory(name='Restaurante',slug='restaurante'))
if not db.query(Category).first(): db.add_all([Category(name='Hamburguesas',slug='hamburguesas'),Category(name='Pizzas',slug='pizzas'),Category(name='Bebidas',slug='bebidas')])
db.commit();
if not db.query(Store).first():
    cat=db.query(StoreCategory).first(); s=Store(name='Burger Mix',slug='burger-mix',description='Comercio demo de PidoMix',whatsapp=settings.whatsapp_default_number,delivery_enabled=True,delivery_cost=1500,estimated_minutes=30,status=StoreStatus.ACTIVA,featured=True,store_category_id=cat.id); db.add(s); db.flush(); c=db.query(Category).filter_by(slug='hamburguesas').first(); db.add(Product(name='Hamburguesa Clásica',description='Carne, queso y vegetales',price=10000,store_id=s.id,category_id=c.id,featured=True)); db.commit()
db.close(); print('Seed completado')
