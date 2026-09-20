from .db import Base, SessionLocal, engine
from .models import User, Role, StoreCategory, Store, Category, Product, StoreStatus
from .config import settings
from .services.auth import hash_password

Base.metadata.create_all(engine)
db=SessionLocal()
try:
    admin=db.query(User).filter_by(email=settings.admin_email).first()
    if not admin:
        db.add(User(email=settings.admin_email.lower(),password_hash=hash_password(settings.admin_password),role=Role.SUPERADMIN))
    cat=db.query(StoreCategory).first()
    if not cat:
        cat=StoreCategory(name='Restaurante',slug='restaurante'); db.add(cat); db.flush()
    for name,slug in [('Hamburguesas','hamburguesas'),('Pizzas','pizzas'),('Bebidas','bebidas'),('Postres','postres')]:
        if not db.query(Category).filter_by(slug=slug).first(): db.add(Category(name=name,slug=slug))
    db.commit()
    if not db.query(Store).first():
        s=Store(name='Burger Mix',slug='burger-mix',description='Comercio demo de PidoMix',whatsapp=settings.whatsapp_default_number,delivery_enabled=True,delivery_cost=1500,minimum_order=0,estimated_minutes=30,status=StoreStatus.ACTIVA,featured=True,store_category_id=cat.id)
        db.add(s); db.flush(); h=db.query(Category).filter_by(slug='hamburguesas').first(); b=db.query(Category).filter_by(slug='bebidas').first()
        db.add_all([Product(name='Hamburguesa Clásica',description='Carne, queso y vegetales',price=10000,store_id=s.id,category_id=h.id,featured=True),Product(name='Coca Cola',description='Bebida 500 ml',price=2000,store_id=s.id,category_id=b.id)])
        db.commit()
finally: db.close()
print('Seed completado')
