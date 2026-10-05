"""Create the minimum PidoMix initial data.

Schema creation belongs exclusively to Alembic. This module only inserts/reuses
seed data and is safe to execute more than once.
"""

from sqlalchemy import func

from .config import settings
from .db import SessionLocal
from .models import Category, City, Product, Role, Store, StoreCategory, StoreStatus, User
from .services.auth import hash_password


ADMIN_EMAIL = settings.admin_email.strip().lower()


def run_seed() -> None:
    if settings.is_production and settings.admin_password == "change-me":
        raise RuntimeError(
            "ADMIN_PASSWORD debe configurarse en Render antes de ejecutar el seed en producción."
        )
    if not ADMIN_EMAIL:
        raise RuntimeError("ADMIN_EMAIL no puede estar vacío.")
    if not settings.admin_password:
        raise RuntimeError("ADMIN_PASSWORD no puede estar vacío.")

    db = SessionLocal()
    try:
        # Admin: case-insensitive lookup prevents duplicate attempts such as
        # Admin@Pidomix.com vs admin@pidomix.com.
        admin = (
            db.query(User)
            .filter(func.lower(User.email) == ADMIN_EMAIL)
            .first()
        )
        if not admin:
            admin = User(
                email=ADMIN_EMAIL,
                password_hash=hash_password(settings.admin_password),
                role=Role.SUPERADMIN,
                active=True,
            )
            db.add(admin)

        # Store category: reuse the canonical demo category if it already exists.
        store_category = (
            db.query(StoreCategory)
            .filter(
                (StoreCategory.slug == "restaurante")
                | (StoreCategory.name == "Restaurante")
            )
            .first()
        )
        if not store_category:
            store_category = StoreCategory(name="Restaurante", slug="restaurante")
            db.add(store_category)
            db.flush()

        # Global product categories are keyed by slug.
        category_specs = [
            ("Hamburguesas", "hamburguesas"),
            ("Pizzas", "pizzas"),
            ("Bebidas", "bebidas"),
            ("Postres", "postres"),
        ]
        categories: dict[str, Category] = {}
        for name, slug in category_specs:
            category = db.query(Category).filter_by(slug=slug).first()
            if not category:
                category = Category(name=name, slug=slug, active=True)
                db.add(category)
                db.flush()
            categories[slug] = category

        # Ciudad principal (multi-ciudad): si todavia no hay ninguna, la del centro del mapa.
        city = db.query(City).order_by(City.display_order, City.id).first()
        if not city:
            try:
                lat, lng = (float(x) for x in settings.map_default_center.split(","))
            except ValueError:
                lat, lng = -38.7183, -62.2663
            bahia = abs(lat + 38.72) < 0.3 and abs(lng + 62.27) < 0.3
            city = City(name="Bahía Blanca" if bahia else "Ciudad principal", slug="bahia-blanca" if bahia else "principal",
                        province="Buenos Aires" if bahia else None, center_lat=lat, center_lng=lng, radius_km=25.0)
            db.add(city)
            db.flush()

        # Demo store: lookup by stable slug instead of "first store" so existing
        # real stores are never modified just because the seed runs again.
        store = db.query(Store).filter_by(slug="burger-mix").first()
        if not store:
            store = Store(
                name="Burger Mix",
                slug="burger-mix",
                description="Comercio demo de Trappi",
                whatsapp=settings.whatsapp_default_number,
                delivery_enabled=True,
                delivery_cost=1500,
                minimum_order=0,
                estimated_minutes=30,
                status=StoreStatus.ACTIVA,
                featured=True,
                store_category_id=store_category.id,
                city_id=city.id,
            )
            db.add(store)
            db.flush()
        elif store.store_category_id is None:
            store.store_category_id = store_category.id

        # Demo products: stable identity is (store, product name). Existing
        # products are reused; missing demo products are added.
        product_specs = [
            (
                "Hamburguesa Clásica",
                "Carne, queso y vegetales",
                10000,
                "hamburguesas",
            ),
            ("Coca Cola", "Bebida 500 ml", 2000, "bebidas"),
        ]
        for name, description, price, category_slug in product_specs:
            product = (
                db.query(Product)
                .filter(Product.store_id == store.id, Product.name == name)
                .first()
            )
            if not product:
                db.add(
                    Product(
                        name=name,
                        description=description,
                        price=price,
                        store_id=store.id,
                        category_id=categories[category_slug].id,
                        featured=True if category_slug == "hamburguesas" else False,
                    )
                )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
    print("Seed completado")
