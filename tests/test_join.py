"""Formulario "Sumá tu comercio" (/sumate) y solicitudes en el panel del superadmin."""
import os
import re
import sys
from urllib.parse import unquote_plus

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("join") / "join.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import City
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        if not db.query(City).filter_by(name="Bahía Blanca").first():
            db.add(City(name="Bahía Blanca", slug="bahia-blanca", province="Buenos Aires", center_lat=-38.7, center_lng=-62.27))
        db.commit()
    from app.routers import join
    join.join_limiter.clear()
    yield TestClient(app)
    engine.dispose()


def csrf(c):
    page = c.get("/sumate").text
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


GOOD = {"store_name": "Pizzería Don Pepe", "store_category_id": "", "category_other": "Pizzería", "food_types": ["Pizzas", "Empanadas"],
        "province": "Buenos Aires", "city_name": "bahia blanca", "postal_code": "8000", "address": "Alsina 123", "address_extra": "Local 2",
        "owner_name": "José Pérez", "owner_whatsapp": "291 455-6677", "email": "Pepe@Gmail.com", "store_phone": "", "instagram": "@donpepe",
        "cuit": "", "delivery": "propio", "hours": "Mar a dom 19 a 24", "comments": "Tenemos 2 motos", "accept": "1", "website": ""}


def send(c, **over):
    data = {**GOOD, **over, "csrf_token": csrf(c)}
    return c.post("/sumate", data=data)


def test_form_validates_and_saves(env):
    c = env
    page = c.get("/sumate")
    assert page.status_code == 200 and "Sumá tu comercio" in page.text and "Tierra del Fuego" in page.text
    r = send(c, owner_whatsapp="123", email="no-es-mail", postal_code="80", accept="")
    assert "WhatsApp" in r.text and "email válido" in r.text and "código postal" in r.text and "aceptar" in r.text
    assert 'value="Pizzería Don Pepe"' in r.text  # no se pierde lo que cargó
    r = send(c)
    code = re.search(r"(SOL-[0-9A-F]{6})", r.text).group(1)
    from app.db import SessionLocal
    from app.models import MerchantApplication
    with SessionLocal() as db:
        a = db.query(MerchantApplication).filter_by(code=code).one()
        assert a.status == "nueva" and a.owner_whatsapp == "2914556677" and a.email == "pepe@gmail.com" and a.instagram == "donpepe"
        assert a.food_types == "Pizzas, Empanadas" and a.city is not None and a.city.name == "Bahía Blanca"
    # la misma solicitud otra vez: no se duplica
    assert code in send(c).text
    with SessionLocal() as db:
        assert db.query(MerchantApplication).count() == 1


def test_honeypot_and_csrf(env):
    c = env
    from app.db import SessionLocal
    from app.models import MerchantApplication
    with SessionLocal() as db:
        before = db.query(MerchantApplication).count()
    send(c, website="http://spam", store_name="Spam SA", owner_whatsapp="2910000000")
    assert c.post("/sumate", data={**GOOD, "store_name": "Sin token"}, headers={"x-no-csrf": "1"}).status_code in (400, 403)
    with SessionLocal() as db:
        assert db.query(MerchantApplication).count() == before


def test_closed_signup(env):
    c = env
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        db.add(Setting(key="new_stores_open", value="0")); db.commit()
    platform.invalidate()
    assert "no estamos sumando" in c.get("/sumate").text
    with SessionLocal() as db:
        db.query(Setting).filter_by(key="new_stores_open").delete(); db.commit()
    platform.invalidate()


def test_admin_reviews_and_creates_store(env):
    from fastapi.testclient import TestClient
    from app.main import app
    sa = TestClient(app)
    sa.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    page = sa.get("/admin/solicitudes").text
    assert "Pizzería Don Pepe" in page and "wa.me/5492914556677" in page and "Ciudad de Trappi: Bahía Blanca" in page
    assert "Solicitudes de comercios" in sa.get("/admin").text
    from app.db import SessionLocal
    from app.models import MerchantApplication, Store
    with SessionLocal() as db:
        aid = db.query(MerchantApplication).first().id
    r = sa.post(f"/admin/solicitudes/{aid}", data={"action": "contactada", "note": "Hablamos el lunes"}, follow_redirects=False)
    assert "estado=contactada" in r.headers["location"]
    # crear: el alta del comercio aparece con los datos cargados
    r = sa.post(f"/admin/solicitudes/{aid}", data={"action": "crear", "note": ""}, follow_redirects=False)
    assert r.headers["location"] == "/admin/comercios/nuevo"
    form = sa.get("/admin/comercios/nuevo").text
    assert 'value="Pizzería Don Pepe"' in form and 'value="pepe@gmail.com"' in form and "Alsina 123, Local 2, bahia blanca" in form
    with SessionLocal() as db:
        from app.models import City
        cid = db.query(City).filter_by(name="Bahía Blanca").one().id
    r = sa.post("/admin/comercios/nuevo", data={"name": "Pizzería Don Pepe", "login_email": "pepe@gmail.com", "login_password": "Pepe-12345",
                                                "plan": "TRAPPI_COMERCIO", "city_id": str(cid), "whatsapp": "2914556677"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    with SessionLocal() as db:
        a = db.get(MerchantApplication, aid)
        store = db.query(Store).filter_by(name="Pizzería Don Pepe").one()
        assert a.status == "aprobada" and a.store_id == store.id and store.account_status == "pendiente"
    assert "Pizzería Don Pepe" in sa.get("/admin/solicitudes?estado=aprobada").text


def test_store_admin_cannot_see_applications(env):
    from fastapi.testclient import TestClient
    from app.main import app
    shop = TestClient(app)
    shop.post("/admin/login", data={"email": "pepe@gmail.com", "password": "Pepe-12345"})
    r = shop.get("/admin/solicitudes", follow_redirects=False)
    assert r.status_code == 303 and unquote_plus(r.headers["location"]) == "/admin"
    assert shop.post("/admin/solicitudes/1", data={"action": "rechazar"}, follow_redirects=False).headers["location"] == "/admin"


def test_choice_values_fit_their_columns(env):
    """PostgreSQL rechaza textos más largos que la columna (SQLite no): cada opción tiene que entrar."""
    from app.models import MerchantApplication, Ride, RideCompany, RideOffer
    from app.routers.join import DELIVERY
    from app.services import rides
    col = lambda model, name: model.__table__.c[name].type.length
    assert all(len(k) <= col(MerchantApplication, "delivery") for k in DELIVERY)
    assert all(len(k) <= col(MerchantApplication, "status") for k in ("nueva", "contactada", "aprobada", "rechazada"))
    assert all(len(k) <= col(Ride, "status") for k in rides.STATUS_LABEL)
    assert all(len(k) <= col(Ride, "cancelled_by") for k in ("pasajero", "conductor", "empresa", "sistema"))
    assert all(len(k) <= col(Ride, "vehicle") for k in rides.VEHICLES)
    assert all(len(k) <= col(RideCompany, "plan") for k in rides.PLANS)
    assert all(len(k) <= col(RideOffer, "status") for k in ("pending", "accepted", "rejected", "expired", "cancelled"))


def test_every_delivery_option_saves(env):
    from app.routers import join
    from app.routers.join import DELIVERY
    for i, k in enumerate(DELIVERY):
        join.join_limiter.clear()
        r = send(env, delivery=k, store_name=f"Local {k}", owner_whatsapp=f"29145500{i:02d}")
        assert "SOL-" in r.text, k
