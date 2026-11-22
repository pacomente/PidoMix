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


def test_se_arma_el_local_solo_y_el_superadmin_lo_publica(env):
    """Con contraseña y en una ciudad de Trappi: local oculto + usuario al instante; carga su menú; lo publica el superadmin."""
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import MerchantApplication, Product, Store, StoreHour, User
    from app.routers import join
    join.join_limiter.clear()
    owner = TestClient(app)
    data = {**GOOD, "store_name": "Lomitería La Esquina", "email": "esquina@gmail.com", "owner_whatsapp": "291 400-9988"}
    page = owner.get("/sumate").text
    assert "Tu acceso al panel" in page and "Crear mi local" in page
    weak = owner.post("/sumate", data={**data, "password": "123", "password2": "123", "csrf_token": csrf(owner)})
    assert "8 caracteres" in weak.text
    diff = owner.post("/sumate", data={**data, "password": "Esquina-2026!", "password2": "otra-cosa1", "csrf_token": csrf(owner)})
    assert "iguales" in diff.text
    r = owner.post("/sumate", data={**data, "password": "Esquina-2026!", "password2": "Esquina-2026!", "csrf_token": csrf(owner)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin?bienvenido=1"  # entra directo a su panel
    with SessionLocal() as db:
        app_row = db.query(MerchantApplication).filter_by(email="esquina@gmail.com").one()
        store = db.get(Store, app_row.store_id)
        assert store.account_status == "pendiente" and store.plan and app_row.status == "nueva"
        assert db.query(User).filter_by(email="esquina@gmail.com").one().store_id == store.id
        sid, slug, aid = store.id, store.slug, app_row.id
    assert owner.get(f"/tienda/{slug}").status_code == 404 and "Lomitería La Esquina" not in owner.get("/").text  # oculto hasta publicarlo
    dash = owner.get("/admin?bienvenido=1").text
    assert "Bienvenido a Trappi" in dash and "Cargá tu menú" in dash and "Ya está listo" in dash
    # todavía le falta: no puede pedir la revisión
    assert "Antes de pedir la revisión" in owner.post("/admin/mi-local/listo").text  # el aviso se ve al volver al inicio
    with SessionLocal() as db:
        for i in range(3):
            db.add(Product(store_id=sid, name=f"Lomito {i}", price=5000 + i))
        db.add(StoreHour(store_id=sid, weekday=0, open_time="19:00", close_time="23:59", closed=False))
        s = db.get(Store, sid); s.lat, s.lng = -38.72, -62.27
        db.commit()
    owner.post("/admin/mi-local/listo")
    assert "Lo estamos revisando" in owner.get("/admin").text
    # el superadmin lo ve en "Listos para revisar" y lo publica
    admin = TestClient(app)
    assert admin.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False).status_code == 303
    lista = admin.get("/admin/solicitudes?estado=lista").text
    assert "Lomitería La Esquina" in lista and "Aprobar y publicar" in lista and "nos avisó que está listo" in lista
    assert admin.post(f"/admin/solicitudes/{aid}", data={"action": "publicar"}, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.get(Store, sid).account_status == "activo" and db.get(MerchantApplication, aid).status == "aprobada"
    # un email que ya tiene cuenta no puede armar otro local
    join.join_limiter.clear()
    again = owner.post("/sumate", data={**data, "store_name": "Otro", "password": "Esquina-2026!", "password2": "Esquina-2026!", "csrf_token": csrf(owner)})
    assert "ya tiene una cuenta" in again.text


def test_ciudad_nueva_sigue_siendo_solicitud(env):
    from app.db import SessionLocal
    from app.models import MerchantApplication
    from app.routers import join
    join.join_limiter.clear()
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.post("/sumate", data={**GOOD, "store_name": "Pizzas Neuquén", "city_name": "Neuquén", "email": "nqn@gmail.com", "owner_whatsapp": "299 400-1111",
                                "password": "Neuquen-2026!", "password2": "Neuquen-2026!", "csrf_token": csrf(c)})
    assert re.search(r"SOL-[0-9A-F]{6}", r.text)  # sin ciudad de Trappi: solo la solicitud, sin local
    with SessionLocal() as db:
        assert db.query(MerchantApplication).filter_by(email="nqn@gmail.com").one().store_id is None


def test_rechazar_un_local_armado_solo(env):
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import MerchantApplication, Store, User
    from app.routers import join
    join.join_limiter.clear()
    c = TestClient(app)
    c.post("/sumate", data={**GOOD, "store_name": "Local Trucho", "email": "trucho@gmail.com", "owner_whatsapp": "291 411-2233",
                            "password": "Trucho-2026!", "password2": "Trucho-2026!", "csrf_token": csrf(c)})
    with SessionLocal() as db:
        a = db.query(MerchantApplication).filter_by(email="trucho@gmail.com").one()
        aid, sid = a.id, a.store_id
    admin = TestClient(app)
    admin.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    admin.post(f"/admin/solicitudes/{aid}", data={"action": "rechazar"})
    with SessionLocal() as db:
        assert db.get(Store, sid).account_status == "desactivado" and db.query(User).filter_by(email="trucho@gmail.com").one().active is False
    assert c.get("/admin", follow_redirects=False).status_code == 303  # sin acceso al panel
