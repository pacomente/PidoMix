"""Actualización de la web: envío gratis desde un monto (solo cadetería propia), «Pedí de nuevo»,
«¿Le sumás algo?», «Lo más pedido» y los filtros rápidos de comercios."""
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-web@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("webupd") / "webupd.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ModifierGroup, ModifierOption, Product, Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        s.delivery_cost = Decimal("1500")
        burger = db.query(Product).filter_by(name="Hamburguesa Clásica").one()
        g = ModifierGroup(product_id=burger.id, name="Extras", min_select=0, max_select=3)
        db.add(g); db.flush()
        db.add_all([ModifierOption(group_id=g.id, name="Cheddar", price_extra=Decimal("800")),
                    ModifierOption(group_id=g.id, name="Panceta", price_extra=Decimal("900"))])
        db.add(Product(name="Papas grandes", description="Con cheddar", price=Decimal("3200"), store_id=s.id, category_id=burger.category_id))
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=s.id, active=True))
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def ids():
    from app.db import SessionLocal
    from app.models import ModifierOption, Product, Store
    with SessionLocal() as db:
        return {"store": db.query(Store).filter_by(slug="burger-mix").one().id,
                "burger": db.query(Product).filter_by(name="Hamburguesa Clásica").one().id,
                "coca": db.query(Product).filter_by(name="Coca Cola").one().id,
                "papas": db.query(Product).filter_by(name="Papas grandes").one().id,
                "cheddar": db.query(ModifierOption).filter_by(name="Cheddar").one().id}


def set_store(**kw):
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        for k, v in kw.items():
            setattr(s, k, v)
        db.commit()


def checkout(c, **extra):
    data = {"first_name": "Ana", "last_name": "Paz", "phone": "2914001122", "delivery_method": "delivery", "address": "Alsina 100", "payment_method": "efectivo"}
    data.update(extra)
    r = c.post("/checkout", data=data, follow_redirects=False)
    assert r.status_code == 303 and "/pedido/" in r.headers["location"], r.text[:400]
    return int(r.headers["location"].split("/pedido/")[1].split("?")[0])


def delivered(oid):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    with SessionLocal() as db:
        db.get(Order, oid).status = OrderStatus.ENTREGADO
        db.commit()


def test_envio_gratis_solo_con_cadeteria_propia(env):
    from app.db import SessionLocal
    from app.models import Order
    i = ids()
    c = client()
    # con la flota de Trappi (o sin definir) no hay envío gratis aunque el campo tenga un valor
    for logistics in (None, "trappi", "mixta"):
        set_store(logistics=logistics, free_shipping_from=Decimal("10000"))
        c.post("/api/cart/clear")
        cart = c.post("/api/cart/add", json={"product_id": i["coca"], "quantity": 6}).json()
        assert cart["free_shipping"] is None and cart["shipping"] == 1500 and cart["subtotal"] == 12000, logistics
        assert "Envío gratis desde" not in c.get("/tienda/burger-mix").text

    # cadetería propia: debajo del monto se cobra el envío y se muestra cuánto falta
    set_store(logistics="propia")
    c.post("/api/cart/clear")
    cart = c.post("/api/cart/add", json={"product_id": i["coca"], "quantity": 3}).json()
    assert cart["shipping"] == 1500 and cart["free_shipping"] == {"from": 10000.0, "missing": 4000.0}
    assert "Envío gratis desde $10.000" in c.get("/tienda/burger-mix").text
    page = c.get("/checkout").text
    assert "Te faltan <b>$4.000</b> para el envío gratis" in page
    oid = checkout(c)
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.shipping == Decimal("1500") and o.delivery_fee_customer == Decimal("1500") and o.delivery_fee_merchant == Decimal("0")

    # llegando al monto: envío gratis, lo pone el local
    c.post("/api/cart/add", json={"product_id": i["coca"], "quantity": 5})
    cart = c.get("/api/cart").json()
    assert cart["subtotal"] == 10000 and cart["shipping"] == 0 and cart["free_shipping"]["missing"] == 0
    assert "¡Tenés envío gratis!" in c.get("/checkout").text
    oid = checkout(c)
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.shipping == 0 and o.total == Decimal("10000")
        assert o.delivery_fee_customer == 0 and o.delivery_fee_merchant == Decimal("1500")
    # para retirar no cambia nada (no hay envío)
    c.post("/api/cart/add", json={"product_id": i["coca"], "quantity": 5})
    oid = checkout(c, delivery_method="retiro")
    with SessionLocal() as db:
        assert db.get(Order, oid).shipping == 0


def test_el_local_carga_el_envio_gratis(env):
    from app.db import SessionLocal
    from app.models import Store
    i = ids()
    owner = client()
    assert owner.post("/admin/login", data=OWNER, follow_redirects=False).status_code == 303
    set_store(logistics="trappi", free_shipping_from=None)
    page = owner.get("/admin/stores").text
    assert "disponible para los locales que reparten con su propia cadetería" in page and 'name="free_shipping_from"' not in page
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    form = {"csrf_token": token, "name": "Burger Mix", "slug": "burger-mix", "delivery_enabled": "on", "delivery_cost": "1500", "minimum_order": "0", "estimated_minutes": "30"}
    owner.post(f"/admin/stores/{i['store']}/edit", data={**form, "free_shipping_from": "15000"})
    with SessionLocal() as db:
        assert db.get(Store, i["store"]).free_shipping_from is None  # con la flota de Trappi no se puede
    set_store(logistics="propia")
    assert 'name="free_shipping_from"' in owner.get("/admin/stores").text
    owner.post(f"/admin/stores/{i['store']}/edit", data={**form, "free_shipping_from": "15000"})
    with SessionLocal() as db:
        assert db.get(Store, i["store"]).free_shipping_from == Decimal("15000")
    owner.post(f"/admin/stores/{i['store']}/edit", data={**form, "free_shipping_from": ""})
    with SessionLocal() as db:
        assert db.get(Store, i["store"]).free_shipping_from is None


def test_pedi_de_nuevo_con_las_mismas_opciones(env):
    from app.db import SessionLocal
    from app.models import Product
    from app.routers.public import order_token
    i = ids()
    set_store(logistics=None, free_shipping_from=None)
    c = client()
    assert "Pedí de nuevo" not in c.get("/").text
    c.post("/api/cart/clear")
    c.post("/api/cart/add", json={"product_id": i["burger"], "quantity": 2, "modifiers": [i["cheddar"]]})
    c.post("/api/cart/add", json={"product_id": i["papas"], "quantity": 1})
    oid = checkout(c)
    assert "Pedí de nuevo" not in c.get("/").text  # todavía no se entregó
    delivered(oid)
    home = c.get("/").text
    assert "Pedí de nuevo" in home and "2× Hamburguesa Clásica" in home and f'action="/pedido/{oid}/repetir"' in home
    assert "Pedí de nuevo" not in client().get("/").text  # otro navegador no lo ve

    r = c.post(f"/pedido/{oid}/repetir", data={"t": order_token(oid)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/checkout"
    cart = c.get("/api/cart").json()
    burger = next(x for x in cart["items"] if x["product_id"] == i["burger"])
    assert burger["quantity"] == 2 and burger["modifiers_text"] == "Cheddar" and burger["price"] == 10800
    assert cart["subtotal"] == 2 * 10800 + 3200
    # token equivocado: nada
    assert client().post(f"/pedido/{oid}/repetir", data={"t": "malo"}, follow_redirects=False).status_code == 404
    # si un producto ya no se vende, carga el resto y avisa
    with SessionLocal() as db:
        from app.models import ProductStatus
        db.get(Product, i["papas"]).status = ProductStatus.INACTIVO
        db.commit()
    r = c.post(f"/pedido/{oid}/repetir", data={"t": order_token(oid)}, follow_redirects=False)
    assert r.headers["location"] == "/checkout?faltan=1"
    assert "1 producto no está disponible" in c.get("/checkout?faltan=1").text
    assert [x["product_id"] for x in c.get("/api/cart").json()["items"]] == [i["burger"]]
    with SessionLocal() as db:
        db.get(Product, i["papas"]).status = ProductStatus.ACTIVO
        db.commit()


def test_le_sumas_algo_y_lo_mas_pedido(env):
    from app.db import SessionLocal
    from app.models import Order, OrderItem, OrderStatus, Store
    i = ids()
    c = client()
    c.post("/api/cart/clear")
    cart = c.post("/api/cart/add", json={"product_id": i["burger"], "quantity": 1}).json()
    sug = [x["id"] for x in cart["suggestions"]]
    assert i["burger"] not in sug and set(sug) <= {i["coca"], i["papas"]} and sug
    # lo más pedido: con pedidos entregados de los últimos 60 días
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        for _ in range(3):
            o = Order(store_id=s.id, delivery_method="retiro", subtotal=Decimal("6000"), shipping=0, total=Decimal("6000"), status=OrderStatus.ENTREGADO,
                      created_at=datetime.utcnow() - timedelta(days=2))
            db.add(o); db.flush()
            db.add(OrderItem(order_id=o.id, product_id=i["coca"], product_name="Coca Cola", unit_price=Decimal("2000"), quantity=3))
        db.commit()
    page = c.get("/tienda/burger-mix").text
    assert 'id="lo-mas-pedido"' in page and page.index('id="lo-mas-pedido"') < page.index("Coca Cola")
    cart = c.get("/api/cart").json()
    # primero lo que se pide junto con la hamburguesa (papas, del pedido anterior) y después lo más vendido
    assert [x["id"] for x in cart["suggestions"]] == [i["papas"], i["coca"]]


def test_filtros_rapidos_de_comercios(env):
    c = client()
    home = c.get("/").text
    for href in ("/tiendas?sort=rapidos", "/tiendas?promos=true", "/tiendas?gratis=true", "/tiendas?sort=puntuados"):
        assert href in home
        assert c.get(href).status_code == 200
    set_store(logistics="propia", free_shipping_from=Decimal("10000"))
    assert "Burger Mix" in c.get("/tiendas?gratis=true").text
    set_store(logistics="trappi")
    assert "Burger Mix" not in c.get("/tiendas?gratis=true").text
    assert "Burger Mix" not in c.get("/tiendas?promos=true").text  # sin productos en oferta
