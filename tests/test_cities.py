"""Multi-ciudad: cada cliente ve los comercios de su ciudad, la flota y las zonas trabajan por ciudad,
cada ciudad puede tener su propia configuracion y el panel filtra por ciudad."""
import os
import sys
from decimal import Decimal as D

import pytest

BAHIA = (-38.7183, -62.2663)
NEAR_BAHIA = (-38.7200, -62.2700)
PUNTA = (-38.8800, -62.0700)
NEAR_PUNTA = (-38.8810, -62.0720)
ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("cities") / "cities.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import City, Courier, Product, Store, StoreHour
    from app.services import cities, platform
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        bahia = db.query(City).one()
        assert bahia.name == "Bahía Blanca"  # el seed crea la ciudad principal
        punta = City(name="Punta Alta", slug="punta-alta", province="Buenos Aires", center_lat=PUNTA[0], center_lng=PUNTA[1], radius_km=12)
        db.add(punta); db.flush()
        burger = db.query(Store).filter_by(slug="burger-mix").one()
        burger.lat, burger.lng = BAHIA
        pizza = Store(name="Pizza Punta", slug="pizza-punta", city_id=punta.id, lat=PUNTA[0], lng=PUNTA[1], delivery_cost=D("1200"),
                      estimated_minutes=30, account_status="activo")
        db.add(pizza); db.flush()
        for wd in range(7):
            db.add(StoreHour(store_id=pizza.id, weekday=wd, open_time="00:00", close_time="23:59", closed=False))
        db.add(Product(store_id=pizza.id, name="Muzzarella Punta", price=D("9000")))
        db.add_all([Courier(name="Flota Bahía", phone="2911000001", pin_hash=hash_password("1111"), city_id=bahia.id),
                    Courier(name="Flota Punta", phone="2911000002", pin_hash=hash_password("2222"), city_id=punta.id),
                    Courier(name="Flota Libre", phone="2911000003", pin_hash=hash_password("3333"))])
        db.commit()
        ids = {"bahia": bahia.id, "punta": punta.id, "burger": burger.id, "pizza": pizza.id}
    cities.invalidate(); platform.invalidate()
    yield ids
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def admin_client():
    c = client()
    assert c.post("/admin/login", data=ADMIN, follow_redirects=False).status_code == 303
    return c


def names(stores):
    return {s["name"] for s in stores}


# ==================== clientes ====================

def test_web_shows_only_the_city_of_the_customer(env):
    c = client()
    home = c.get("/").text
    assert "Burger Mix" in home and "Pizza Punta" not in home  # sin ubicacion: la ciudad principal
    assert 'class="where-city"' in home and "Bahía Blanca" in home  # hay dos ciudades: se muestra el selector
    # marca su ubicacion en Punta Alta: pasa a ver esa ciudad
    r = c.post("/api/ubicacion", json={"lat": NEAR_PUNTA[0], "lng": NEAR_PUNTA[1], "label": "Casa"})
    assert r.json()["city"] == "punta-alta"
    home = c.get("/").text
    assert "Pizza Punta" in home and "Burger Mix" not in home
    assert "Muzzarella Punta" in c.get("/buscar?q=muzza").text
    assert "Burger Mix" not in c.get("/tiendas").text
    # elige otra ciudad a mano
    page = c.get("/ciudades").text
    assert "Punta Alta" in page and "Bahía Blanca" in page
    assert c.get("/ciudad/bahia-blanca", follow_redirects=False).status_code == 303
    home = c.get("/").text
    assert "Burger Mix" in home and "Pizza Punta" not in home
    assert c.get("/ciudad/no-existe").status_code == 404
    # el link directo a un comercio de otra ciudad sigue andando
    assert c.get("/tienda/pizza-punta").status_code == 200


def test_app_catalog_by_city(env):
    c = client()
    cfg = c.get("/api/v1/config").json()
    assert {x["slug"] for x in cfg["cities"]} == {"bahia-blanca", "punta-alta"}
    home = c.get("/api/v1/home").json()
    assert home["city"]["slug"] == "bahia-blanca" and "Pizza Punta" not in names(home["stores"]) and len(home["cities"]) == 2
    home = c.get(f"/api/v1/home?lat={NEAR_PUNTA[0]}&lng={NEAR_PUNTA[1]}").json()
    assert home["city"]["slug"] == "punta-alta" and "Pizza Punta" in names(home["stores"]) and "Burger Mix" not in names(home["stores"])
    home = c.get(f"/api/v1/home?city=bahia-blanca&lat={NEAR_PUNTA[0]}&lng={NEAR_PUNTA[1]}").json()
    assert home["city"]["slug"] == "bahia-blanca"  # la que eligio en la app manda
    assert "Pizza Punta" in names(c.get("/api/v1/stores?city=punta-alta").json()["stores"])
    found = c.get("/api/v1/search?q=muzza&city=bahia-blanca").json()
    assert found["products"] == []
    found = c.get("/api/v1/search?q=muzza&city=punta-alta").json()
    assert [p["name"] for p in found["products"]] == ["Muzzarella Punta"]


def test_order_keeps_its_city(env):
    from app.db import SessionLocal
    from app.models import Order, Product
    c = client()
    with SessionLocal() as db:
        pid = db.query(Product).filter_by(name="Muzzarella Punta").one().id
    r = c.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "delivery", "first_name": "Ana",
                                       "phone": "2914000000", "address": "Colón 100", "lat": NEAR_PUNTA[0], "lng": NEAR_PUNTA[1]})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Order, r.json()["id"]).city_id == env["punta"]


# ==================== flota, zonas y configuracion ====================

def test_fleet_couriers_work_in_their_city(env):
    from app.db import SessionLocal
    from app.models import Courier, Order, Store
    from app.services import dispatch
    with SessionLocal() as db:
        o = Order(store_id=env["pizza"], city_id=env["punta"], delivery_method="delivery", subtotal=D("1"), total=D("1"), logistics="trappi")
        o.store = db.get(Store, env["pizza"])
        by = {c.name: c for c in db.query(Courier).all()}
        assert dispatch.allowed(o, by["Flota Punta"])
        assert not dispatch.allowed(o, by["Flota Bahía"])  # la flota de Bahía no lleva pedidos de Punta Alta
        assert dispatch.allowed(o, by["Flota Libre"])  # sin ciudad: cualquiera


def test_zones_are_per_city(env):
    from app.db import SessionLocal
    from app.models import LogisticsZone, Store
    from app.services import logistics
    with SessionLocal() as db:
        db.add(LogisticsZone(name="Bahía centro", city_id=env["bahia"], kind="radius", center_lat=BAHIA[0], center_lng=BAHIA[1], radius_km=60,
                             base_fee=D("999"), included_km=0, per_km=D("0"), min_fee=D("0"), rounding=D("0")))
        for sid in (env["burger"], env["pizza"]):
            s = db.get(Store, sid); s.logistics, s.plan = "trappi", "TRAPPI_DELIVERY"
        db.commit()
        logistics.invalidate()
        burger, pizza = db.get(Store, env["burger"]), db.get(Store, env["pizza"])
        q = logistics.delivery_quote(db, burger, {"lat": NEAR_BAHIA[0], "lng": NEAR_BAHIA[1]})
        assert q.zone_name == "Bahía centro" and q.fee_real == D("999.00")
        # Punta Alta queda dentro del radio de la zona de Bahía, pero es otra ciudad: no se usa
        q = logistics.delivery_quote(db, pizza, {"lat": NEAR_PUNTA[0], "lng": NEAR_PUNTA[1]})
        assert q.zone_name is None and q.snapshot.get("note", "").startswith("sin zonas de la flota")
        for sid in (env["burger"], env["pizza"]):
            s = db.get(Store, sid); s.logistics, s.plan = None, None
        db.commit()


def test_city_settings_override_the_general_ones(env):
    from app.db import SessionLocal
    from app.models import Courier
    from app.services import finance, platform
    a = admin_client()
    page = a.get(f"/admin/ciudades/{env['punta']}").text
    assert "Configuración de Punta Alta" in page and 'name="inherit_courier_cash_limit"' in page
    # Punta Alta: limite de efectivo propio; lo demas como la general
    form = {f"inherit_{k}": "1" for k in platform.CITY_KEYS if k != "courier_cash_limit"}
    form["courier_cash_limit"] = "12000"
    r = a.post(f"/admin/ciudades/{env['punta']}/configuracion", data=form, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        by = {c.name: c for c in db.query(Courier).all()}
        assert finance.cash_limit(db, by["Flota Punta"]) == D("12000.00")
        assert finance.cash_limit(db, by["Flota Bahía"]) == D("50000.00")  # la general
        assert platform.for_city(db, env["punta"])["courier_cash_limit"] == 12000
        assert platform.get_all(db)["courier_cash_limit"] == 50000
    # volver a la general
    form = {f"inherit_{k}": "1" for k in platform.CITY_KEYS}
    a.post(f"/admin/ciudades/{env['punta']}/configuracion", data=form)
    with SessionLocal() as db:
        assert platform.for_city(db, env["punta"])["courier_cash_limit"] == 50000


# ==================== panel ====================

def test_admin_cities_crud_and_filter(env):
    from app.db import SessionLocal
    from app.models import City, Store
    a = admin_client()
    assert "Punta Alta" in a.get("/admin/ciudades").text
    r = a.post("/admin/ciudades", data={"name": "Monte Hermoso", "province": "Buenos Aires", "center_lat": "-38.99", "center_lng": "-61.29", "radius_km": "10"},
               follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        mh = db.query(City).filter_by(slug="monte-hermoso").one()
        assert mh.active is False  # se crea oculta
    assert "Monte Hermoso" not in client().get("/ciudades").text  # los clientes todavia no la ven
    bad = a.post("/admin/ciudades", data={"name": "X", "center_lat": "abc", "center_lng": "1"}, follow_redirects=True)
    assert "Marcá el centro" in bad.text
    # filtro del panel: solo Punta Alta
    a.post("/admin/filtro-ciudad", data={"city": str(env["punta"]), "back": "/admin/comercios"})
    page = a.get("/admin/comercios").text
    assert "Pizza Punta" in page and "Burger Mix" not in page
    page = a.get("/admin/repartidores").text
    assert "Flota Punta" in page and "Flota Bahía" not in page
    a.post("/admin/filtro-ciudad", data={"city": ""})
    page = a.get("/admin/comercios").text
    assert "Pizza Punta" in page and "Burger Mix" in page
    # mover un comercio de ciudad
    a.post(f"/admin/comercios/{env['pizza']}/ciudad", data={"city": str(mh.id)})
    with SessionLocal() as db:
        assert db.get(Store, env["pizza"]).city_id == mh.id
    a.post(f"/admin/comercios/{env['pizza']}/ciudad", data={"city": str(env["punta"])})


@pytest.mark.parametrize("path", ["/admin/ciudades", "/admin/ciudades/{punta}", "/admin/logistica/zonas?city={punta}", "/admin/comercios/nuevo",
                                  "/admin/finanzas", "/admin/logistica", "/admin/logistica/rentabilidad", "/admin"])
def test_admin_pages_render_with_cities(env, path):
    r = admin_client().get(path.format(**env))
    assert r.status_code == 200, r.text[:300]


def test_store_admin_cannot_manage_cities(env):
    from app.db import SessionLocal
    from app.models import Role, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        db.add(User(email="pizza@test.local", password_hash=hash_password("Pizza-123!"), role=Role.STORE_ADMIN, store_id=env["pizza"]))
        db.commit()
    c = client()
    c.post("/admin/login", data={"email": "pizza@test.local", "password": "Pizza-123!"})
    assert c.get("/admin/ciudades", follow_redirects=False).status_code == 303
    assert c.post(f"/admin/comercios/{env['pizza']}/ciudad", data={"city": str(env["bahia"])}, follow_redirects=False).status_code == 303
    from app.models import Store
    with SessionLocal() as db:
        assert db.get(Store, env["pizza"]).city_id == env["punta"]
