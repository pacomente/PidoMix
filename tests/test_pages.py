"""Smoke test de punta a punta: levanta la app sobre SQLite, carga datos demo y
recorre las paginas publicas, el carrito, el checkout y el panel admin."""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("pages") / "pages.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]

    from fastapi.testclient import TestClient
    from app.db import Base, SessionLocal, engine
    from app import seed
    from app.main import app
    from app.models import ModifierGroup, ModifierOption, Product

    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        burger = db.query(Product).filter_by(name="Hamburguesa Clásica").one()
        group = ModifierGroup(product_id=burger.id, name="Extras <b>", max_select=2)
        db.add(group); db.flush()
        db.add(ModifierOption(group_id=group.id, name="Cheddar", price_extra=500))
        db.commit()
    yield TestClient(app)
    engine.dispose()


def test_public_pages(client):
    for url in ["/", "/tiendas", "/tiendas?sort=rapidos", "/tienda/burger-mix", "/categoria/hamburguesas", "/buscar?q=coca", "/favoritos", "/mis-pedidos", "/checkout", "/robots.txt", "/sitemap.xml", "/health"]:
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code)
    assert client.get("/tienda/no-existe").status_code == 404


def test_store_menu_groups_products(client):
    html = client.get("/tienda/burger-mix").text
    assert "Hamburguesa Clásica" in html and "Coca Cola" in html
    assert 'id="cat-' in html


def test_cart_and_checkout(client):
    from app.db import SessionLocal
    from app.models import ModifierOption, Product
    with SessionLocal() as db:
        coca = db.query(Product).filter_by(name="Coca Cola").one().id
        burger = db.query(Product).filter_by(name="Hamburguesa Clásica").one().id
        cheddar = db.query(ModifierOption).filter_by(name="Cheddar").one().id
    r = client.post("/api/cart/add", json={"product_id": coca, "quantity": 2})
    assert r.status_code == 200 and r.json()["count"] == 2
    r = client.post("/api/cart/add", json={"product_id": burger, "modifiers": [cheddar]})
    data = r.json()
    assert data["count"] == 3 and data["subtotal"] == 2 * 2000 + 10500
    r = client.post("/checkout", data={"first_name": "Ana", "last_name": "Paz", "phone": "123", "delivery_method": "retiro"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pedido/")
    assert client.get(r.headers["location"]).status_code == 200
    assert client.get("/mis-pedidos").status_code == 200
    assert client.get("/api/cart").json()["count"] == 0


def test_admin_pages(client):
    r = client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False)
    assert r.status_code == 303
    for url in ["/admin", "/admin/stores", "/admin/products", "/admin/orders", "/admin/orders/pending", "/admin/reports", "/admin/customers", "/admin/users", "/admin/coupons", "/admin/reviews", "/admin/categories", "/admin/banners", "/admin/settings", "/admin/sections", "/admin/reports/export.csv"]:
        r = client.get(url, follow_redirects=False)
        assert r.status_code == 200, (url, r.status_code)
    r = client.post("/admin/stores/1/hours", data={"d0_open": "10:00", "d0_close": "22:00"}, follow_redirects=False)
    assert r.status_code == 303


def test_static_assets_are_compressed_and_cached(client):
    r = client.get("/static/css/trappi.css?v=1", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert "max-age" in r.headers.get("cache-control", "")


def test_bulk_price_update(client):
    from decimal import Decimal
    from app.db import SessionLocal
    from app.models import Product
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    r = client.post("/admin/products/bulk-price", data={"store_id": 1, "percent": 10}, follow_redirects=False)
    assert r.status_code == 303 and "ok=prices" in r.headers["location"]
    with SessionLocal() as db:
        assert db.query(Product).filter_by(name="Coca Cola").one().price == Decimal("2200.00")


def test_login_limit_ignores_spoofed_forwarded_for(client):
    from app.routers import admin
    for i in range(admin.account_limiter.limit):
        r = client.post("/admin/login", data={"email": "victima@test.local", "password": "mala"}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 401
    r = client.post("/admin/login", data={"email": "victima@test.local", "password": "mala"}, headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 429
