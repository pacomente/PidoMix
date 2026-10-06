"""Modelo comercial: alta manual de comercios, planes Trappi Comercio / Trappi Delivery, cambios de plan,
reparto de la plata de cada pedido, logistica por plan, abonos y permisos."""
import os
import sys
from decimal import Decimal

import pytest

STORE = (-38.7183, -62.2663)
NEAR = (-38.7200, -62.2700)
ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("commercial") / "commercial.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, engine
    from app.services import platform
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    platform.invalidate()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def admin_client():
    c = client()
    assert c.post("/admin/login", data=ADMIN, follow_redirects=False).status_code == 303
    return c


def setting(key, value):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        row = db.query(Setting).filter_by(key=key).first()
        if value is None:
            if row: db.delete(row)
        elif row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
        db.commit()
    platform.invalidate()


def create_store(c, name, plan, **extra):
    data = {"name": name, "owner_name": "Dueño " + name, "phone": "2915550000", "whatsapp": "5492915550000", "address": "Alsina 100",
            "open_time": "00:00", "close_time": "23:59", "login_email": f"{name.lower().replace(' ', '')}@test.local", "plan": plan, **extra}
    r = c.post("/admin/comercios/nuevo", data=data, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/comercios/"), r.headers.get("location")
    return int(r.headers["location"].rsplit("/", 1)[1])


def add_product(store_id, name="Pizza", price=20000):
    from app.db import SessionLocal
    from app.models import Product, Store
    with SessionLocal() as db:
        s = db.get(Store, store_id)
        s.lat, s.lng, s.delivery_enabled, s.delivery_cost = STORE[0], STORE[1], True, Decimal("2000")
        p = Product(store_id=store_id, name=name, price=Decimal(price))
        db.add(p); db.commit()
        return p.id


def order(c, product_id, method="delivery", qty=1):
    r = c.post("/api/v1/orders", json={"items": [{"product_id": product_id, "quantity": qty}], "delivery_method": method, "first_name": "Ana",
                                         "phone": "2914000000", "address": "Alsina 200", "lat": NEAR[0], "lng": NEAR[1]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def get(model, id_):
    from app.db import SessionLocal
    with SessionLocal() as db:
        obj = db.get(model, id_)
        db.expunge(obj)
        return obj


# ---------- alta comercial ----------

def test_boton_publico_abre_whatsapp_y_no_hay_registro_publico(env):
    c = client()
    setting("platform_whatsapp", None)
    home = c.get("/").text
    assert "¿Tenés un comercio?" in home and 'aria-disabled="true">Escribinos por WhatsApp' in home and "wa.me" not in home.split('id="sumate"')[1][:900]
    setting("platform_whatsapp", "5492914742731")
    home = c.get("/").text
    assert "https://wa.me/5492914742731?text=Hola%2C%20quiero%20sumar%20mi%20comercio%20a%20Trappi" in home and "data-join" in home
    setting("new_stores_open", "0")
    assert "no estamos sumando comercios" in c.get("/").text and "data-join" not in c.get("/").text
    setting("new_stores_open", None)
    # no existe registro publico: ni paginas ni POST que creen comercios sin un administrador
    for url in ["/registro", "/registrarse", "/sumate", "/admin/registro", "/admin/comercios/nuevo"]:
        r = c.get(url, follow_redirects=False)
        assert r.status_code in (303, 404), url
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        before = db.query(Store).count()
    assert c.post("/admin/comercios/nuevo", data={"name": "Pirata", "login_email": "p@x.com", "plan": "TRAPPI_DELIVERY"}, follow_redirects=False).headers["location"].startswith("/admin/login")
    assert c.post("/admin/stores", data={"name": "Pirata", "slug": "pirata"}, follow_redirects=False).headers["location"].startswith("/admin/login")
    with SessionLocal() as db:
        assert db.query(Store).count() == before


def test_alta_plan_comercio_queda_pendiente_y_se_activa(env):
    from app.models import Store, StorePlanChange, User
    from app.db import SessionLocal
    a = admin_client()
    sid = create_store(a, "La Esquina", "TRAPPI_COMERCIO")
    s = get(Store, sid)
    assert s.plan == "TRAPPI_COMERCIO" and s.monthly_fee == Decimal("10000.00") and s.commission_rate == Decimal("0.00") and s.logistics == "propia"
    assert s.account_status == "pendiente" and s.slug == "la-esquina"
    with SessionLocal() as db:
        assert db.query(User).filter_by(store_id=sid).one().email == "laesquina@test.local"
        assert db.query(StorePlanChange).filter_by(store_id=sid).count() == 1
    detail = a.get(f"/admin/comercios/{sid}").text
    assert "Se muestran una sola vez" in detail and "laesquina@test.local" in detail  # credenciales generadas, una vez
    assert "Se muestran una sola vez" not in a.get(f"/admin/comercios/{sid}").text
    # pendiente: no se publica ni recibe pedidos
    assert client().get("/tienda/la-esquina").status_code == 404
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "activo"})
    assert get(Store, sid).account_status == "pendiente"  # sin productos no se activa
    add_product(sid)
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "activo"})
    assert get(Store, sid).account_status == "activo" and client().get("/tienda/la-esquina").status_code == 200
    # suspendido: desaparece y no toma pedidos
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "suspendido"})
    assert client().get("/tienda/la-esquina").status_code == 404
    r = client().post("/api/v1/orders", json={"items": [{"product_id": add_product(sid, "Fugazza")}], "delivery_method": "retiro", "first_name": "A", "phone": "1"})
    assert r.status_code == 400
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "activo"})
    listing = a.get("/admin/comercios?f=comercio").text
    assert "La Esquina" in listing and "Trappi Comercio" in listing


def test_economia_plan_comercio_y_cadetes_propios(env):
    from app.db import SessionLocal
    from app.models import Courier, Order, Store
    from app.services import dispatch, plans
    from app.services.auth import hash_password
    a = admin_client()
    sid = create_store(a, "Pizzeria Uno", "TRAPPI_COMERCIO")
    pid = add_product(sid, price=20000)
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "activo"})
    oid = order(client(), pid)
    o = get(Order, oid)
    assert o.plan == "TRAPPI_COMERCIO" and o.commission_rate == Decimal("0.00") and o.logistics == "propia"
    assert o.subtotal == Decimal("20000.00") and o.shipping == Decimal("2000.00") and o.total == Decimal("22000.00")
    assert o.platform_commission == Decimal("0.00") and o.store_net == Decimal("22000.00") and o.trappi_income == Decimal("0.00")
    with SessionLocal() as db:
        own = Courier(name="Propio", phone="2917000001", pin_hash=hash_password("1111"), store_id=sid)
        fleet = Courier(name="Flota", phone="2917000002", pin_hash=hash_password("2222"))
        db.add_all([own, fleet]); db.commit()
        o = db.get(Order, oid)
        assert dispatch.allowed(o, own) and not dispatch.allowed(o, fleet)  # plan Comercio: solo cadetes propios
        o.status = __import__("app.models", fromlist=["OrderStatus"]).OrderStatus.CONFIRMADO
        with pytest.raises(dispatch.DispatchError):
            dispatch.assign_manual(db, o, fleet)
        dispatch.assign_manual(db, o, own); db.commit()
        o = db.get(Order, oid)
        assert o.store_net == Decimal("22000.00") and o.trappi_income == Decimal("0.00")  # el envio es del comercio
        b = plans.breakdown(o)
        assert b["products"] == Decimal("20000.00") and b["shipping"] == Decimal("2000.00") and not b["fleet"]


def test_plan_delivery_comision_configurable_y_flota(env):
    from app.db import SessionLocal
    from app.models import Courier, Order, OrderStatus, Store
    from app.services import dispatch
    from app.services.auth import hash_password
    setting("plan_delivery_commission", "12,5")
    a = admin_client()
    sid = create_store(a, "Sushi Dos", "TRAPPI_DELIVERY")
    s = get(Store, sid)
    assert s.monthly_fee == Decimal("0.00") and s.commission_rate == Decimal("12.50") and s.logistics == "trappi"
    pid = add_product(sid, price=20000)
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "activo"})
    oid = order(client(), pid)
    o = get(Order, oid)
    assert o.platform_commission == Decimal("2500.00") and o.store_net == Decimal("17500.00")  # 12,5 % de 20.000; el envio no es del comercio
    assert o.trappi_income == Decimal("2500.00")  # el envio queda para el cadete hasta que se asigne
    with SessionLocal() as db:
        fleet = db.query(Courier).filter_by(phone="2917000002").one()
        own = Courier(name="Propio Sushi", phone="2917000003", pin_hash=hash_password("3333"), store_id=sid)
        db.add(own); db.commit()
        o = db.get(Order, oid)
        assert dispatch.allowed(o, fleet) and not dispatch.allowed(o, own)
        o.status = OrderStatus.CONFIRMADO
        dispatch.assign_manual(db, o, fleet); db.commit()
        o = db.get(Order, oid)
        # la flota cobra el envio (2.000) y le paga al cadete con la regla configurada (por defecto, el envio entero)
        assert o.courier_pay == Decimal("2000.00") and o.trappi_income == Decimal("2500.00") and o.store_net == Decimal("17500.00")
    setting("courier_pay_mode", "fixed"); setting("courier_pay_value", "1500")
    with SessionLocal() as db:
        o = db.get(Order, oid)
        dispatch.unassign(db, o); db.commit()  # la sesion no hace autoflush
        dispatch.assign_manual(db, o, db.query(Courier).filter_by(phone="2917000002").one()); db.commit()
        o = db.get(Order, oid)
        assert o.courier_pay == Decimal("1500.00") and o.trappi_income == Decimal("3000.00")  # comision 2.500 + 500 de margen del envio
    setting("courier_pay_mode", None); setting("courier_pay_value", None)
    # retiro: sin cadete ni envio, la comision igual se cobra sobre los productos
    rid = order(client(), pid, method="retiro")
    r = get(Order, rid)
    assert r.shipping == 0 and r.platform_commission == Decimal("2500.00") and r.store_net == Decimal("17500.00")
    with SessionLocal() as db:
        assert not dispatch.needs_courier(db.get(Order, rid))
    setting("plan_delivery_commission", None)


def test_cambio_de_plan_con_historial_y_pedidos_viejos_intactos(env):
    from app.db import SessionLocal
    from app.models import Order, Store, StorePlanChange
    a = admin_client()
    sid = create_store(a, "Cambia Plan", "TRAPPI_DELIVERY", commission_rate="10")
    pid = add_product(sid, price=10000)
    a.post(f"/admin/comercios/{sid}/estado", data={"status": "activo"})
    first = order(client(), pid)
    assert get(Order, first).platform_commission == Decimal("1000.00")
    # B -> A: pasa a pagar el abono y usar sus cadetes
    a.post(f"/admin/comercios/{sid}/plan", data={"plan": "TRAPPI_COMERCIO", "note": "usa sus cadetes"})
    s = get(Store, sid)
    assert s.plan == "TRAPPI_COMERCIO" and s.commission_rate == 0 and s.monthly_fee == Decimal("10000.00") and s.logistics == "propia"
    second = order(client(), pid)
    assert get(Order, second).platform_commission == 0 and get(Order, second).plan == "TRAPPI_COMERCIO"
    old = get(Order, first)
    assert old.plan == "TRAPPI_DELIVERY" and old.commission_rate == Decimal("10.00") and old.platform_commission == Decimal("1000.00")
    # A -> B con una comision acordada distinta
    a.post(f"/admin/comercios/{sid}/plan", data={"plan": "TRAPPI_DELIVERY", "commission_rate": "8", "monthly_fee": "0", "logistics": "trappi"})
    assert get(Store, sid).commission_rate == Decimal("8.00")
    with SessionLocal() as db:
        hist = db.query(StorePlanChange).filter_by(store_id=sid).order_by(StorePlanChange.id).all()
        assert [(h.from_plan, h.to_plan) for h in hist] == [(None, "TRAPPI_DELIVERY"), ("TRAPPI_DELIVERY", "TRAPPI_COMERCIO"), ("TRAPPI_COMERCIO", "TRAPPI_DELIVERY")]
        assert hist[1].note == "usa sus cadetes" and all(h.user_id for h in hist)
    assert get(Order, second).platform_commission == 0  # el pedido hecho con el plan Comercio no cambia
    assert "Historial de plan" in a.get(f"/admin/comercios/{sid}").text
    # valores invalidos: no se guardan
    a.post(f"/admin/comercios/{sid}/plan", data={"plan": "TRAPPI_DELIVERY", "commission_rate": "150"})
    a.post(f"/admin/comercios/{sid}/plan", data={"plan": "GRATIS"})
    assert get(Store, sid).commission_rate == Decimal("8.00") and get(Store, sid).plan == "TRAPPI_DELIVERY"


def test_abonos_mensuales(env):
    from app.db import SessionLocal
    from app.models import SubscriptionPayment
    a = admin_client()
    sid = create_store(a, "Abona", "TRAPPI_COMERCIO", monthly_fee="12.000")
    a.post(f"/admin/comercios/{sid}/abonos", data={"period": "2026-10", "status": "pendiente"})
    a.post(f"/admin/comercios/{sid}/abonos", data={"period": "2026-10", "status": "pagado"})  # repetido: no se duplica
    a.post(f"/admin/comercios/{sid}/abonos", data={"period": "octubre", "status": "pagado"})  # invalido
    with SessionLocal() as db:
        rows = db.query(SubscriptionPayment).filter_by(store_id=sid).all()
        assert len(rows) == 1 and rows[0].amount == Decimal("12000.00") and rows[0].status == "pendiente"
        pid = rows[0].id
    a.post(f"/admin/comercios/{sid}/abonos/{pid}")
    p = get(SubscriptionPayment, pid)
    assert p.status == "pagado" and p.paid_at is not None
    assert "$12.000" in a.get("/admin/comercios").text


def test_el_comercio_ve_su_plan_pero_no_lo_puede_cambiar(env):
    from app.db import SessionLocal
    from app.models import Store, User
    from app.services.auth import hash_password
    a = admin_client()
    sid = create_store(a, "Mi Local", "TRAPPI_DELIVERY", commission_rate="10")
    with SessionLocal() as db:
        db.add(User(email="dueno@mi-local.test", password_hash=hash_password("Dueno-1234"), store_id=sid)); db.commit()
    setting("platform_whatsapp", "5492914742731")
    owner = client()
    assert owner.post("/admin/login", data={"email": "dueno@mi-local.test", "password": "Dueno-1234"}, follow_redirects=False).status_code == 303
    page = owner.get("/admin/mi-plan").text
    assert "Trappi Delivery" in page and "10&nbsp;%" in page and "Solicitar cambio de plan" in page and "wa.me/5492914742731?text=" in page
    # nada de lo comercial se puede tocar desde el panel del comercio
    for url, data in [(f"/admin/comercios/{sid}/plan", {"plan": "TRAPPI_DELIVERY", "commission_rate": "0"}),
                      (f"/admin/comercios/{sid}/estado", {"status": "activo"}),
                      (f"/admin/comercios/{sid}/abonos", {"period": "2026-11", "status": "pagado"}),
                      ("/admin/comercios/nuevo", {"name": "Otro", "login_email": "otro@x.com", "plan": "TRAPPI_COMERCIO"})]:
        r = owner.post(url, data=data, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/admin/mi-plan", url
    assert owner.get("/admin/comercios", follow_redirects=False).headers["location"] == "/admin/mi-plan"
    # editar su tienda no cambia el plan aunque mande los campos
    store = get(Store, sid)
    owner.post(f"/admin/stores/{sid}/edit", data={"name": store.name, "slug": store.slug, "plan": "TRAPPI_COMERCIO", "commission_rate": "0",
                                                 "monthly_fee": "0", "account_status": "activo"})
    s = get(Store, sid)
    assert s.plan == "TRAPPI_DELIVERY" and s.commission_rate == Decimal("10.00") and s.account_status == "pendiente"
    setting("platform_whatsapp", None)


def test_comercio_existente_sin_plan_sigue_igual(env):
    """El comercio de antes de los planes: sin comision, cadetes propios y flota, y visible."""
    from app.db import SessionLocal
    from app.models import Courier, Order, Product, Store
    from app.services import dispatch
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        assert s.plan is None and s.account_status == "activo"
        coca = db.query(Product).filter_by(name="Coca Cola").one().id
    assert client().get("/tienda/burger-mix").status_code == 200
    oid = order(client(), coca, qty=2)
    o = get(Order, oid)
    assert o.plan is None and o.platform_commission == 0 and o.logistics is None
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert dispatch.allowed(o, db.query(Courier).filter_by(phone="2917000002").one())  # la flota sigue disponible
    assert "Sin plan" in admin_client().get("/admin/comercios?f=sin_plan").text
