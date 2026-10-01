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


def _delivered_order(first_name="Lucía", last_name="gómez"):
    from app.db import SessionLocal
    from app.models import Customer, Order, OrderStatus
    from app.routers.public import order_token
    with SessionLocal() as db:
        order = Order(store_id=1, customer=Customer(first_name=first_name, last_name=last_name, phone="1"), delivery_method="retiro", subtotal=1000, shipping=0, total=1000, status=OrderStatus.ENTREGADO)
        db.add(order); db.commit()
        return order.id, order_token(order.id)


def _store():
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        s = db.get(Store, 1)
        return float(s.rating_avg), s.rating_count


def test_review_flow(client):
    from app.db import SessionLocal
    from app.models import Review
    oid, t = _delivered_order()
    assert client.post(f"/pedido/{oid}/review", data={"t": t, "rating": 9}).status_code == 200  # fuera de rango: se ignora
    assert _store()[1] == 0
    client.post(f"/pedido/{oid}/review", data={"t": t, "rating": 4, "comment": "  Muy rico <script>x</script> "})
    client.post(f"/pedido/{oid}/review", data={"t": t, "rating": 1})  # doble envio: no pisa ni duplica
    assert _store() == (4.0, 1)
    oid2, t2 = _delivered_order("Pedro", "")
    client.post(f"/pedido/{oid2}/review", data={"t": t2, "rating": 1})
    assert _store() == (2.5, 2)

    html = client.get("/tienda/burger-mix").text
    assert 'id="opiniones"' in html and "Lucía G." in html and "&lt;script&gt;" in html and "<script>x" not in html
    page = client.get("/tienda/burger-mix/opiniones").text
    assert "Pedro" in page and "2.5" in page
    assert "Calificar" not in client.get("/mis-pedidos").text  # pedidos de esta sesion no entregados

    with SessionLocal() as db:
        rid = db.query(Review).filter_by(order_id=oid2).one().id
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    assert "Sin responder (2)" in client.get("/admin/reviews").text
    client.post(f"/admin/reviews/{rid}/reply", data={"reply": "Perdón, lo vamos a mejorar"})
    assert "Sin responder (1)" in client.get("/admin/reviews").text
    assert "Respuesta del local" in client.get("/tienda/burger-mix/opiniones").text
    for f in ["sin_respuesta", "con_comentario", "negativas", "ocultas"]:
        assert client.get(f"/admin/reviews?filter={f}").status_code == 200
    client.post(f"/admin/reviews/{rid}/hide")  # moderada: deja de contar en el promedio
    assert _store() == (4.0, 1)
    assert "Pedro" not in client.get("/tienda/burger-mix/opiniones").text
    client.post(f"/admin/reviews/{rid}/hide")
    assert _store() == (2.5, 2)


def test_store_admin_can_reply_but_not_hide(client):
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import Review, Role, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        db.add(User(email="local@test.local", password_hash=hash_password("Local-123!"), role=Role.STORE_ADMIN, store_id=1)); db.commit()
        rid = db.query(Review).filter(Review.hidden.is_(False)).first().id
    owner = TestClient(app)
    owner.post("/admin/login", data={"email": "local@test.local", "password": "Local-123!"})
    assert "Ocultar (moderar)" not in owner.get("/admin/reviews").text
    owner.post(f"/admin/reviews/{rid}/hide")
    owner.post(f"/admin/reviews/{rid}/reply", data={"reply": "¡Gracias!"})
    with SessionLocal() as db:
        r = db.get(Review, rid)
        assert r.hidden is False and r.reply == "¡Gracias!"
