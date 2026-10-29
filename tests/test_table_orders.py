"""Pedí desde tu mesa: QR por mesa, el pedido entra con la mesa (sin envío ni horario) y con la comisión propia de la mesa."""
import os
import sys
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-mesa@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("mesa") / "mesa.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=mix.id, active=True))
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def login(who):
    c = client()
    assert c.post("/admin/login", data=who, follow_redirects=False).status_code == 303
    return c


def _ids():
    from app.db import SessionLocal
    from app.models import Product, Store
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        return s.id, db.query(Product).filter_by(name="Hamburguesa Clásica").one().id


def _codes(sid):
    from app.db import SessionLocal
    from app.models import PosTable
    with SessionLocal() as db:
        return {t.name: t.qr_code for t in db.query(PosTable).filter_by(store_id=sid, active=True)}


def _order(c, pid, **extra):
    c.post("/api/cart/add", json={"product_id": pid, "quantity": 2})
    data = {"first_name": "Ana", "last_name": "Paz", "phone": "2914001122", "delivery_method": "mesa", "payment_method": "efectivo"}
    data.update(extra)
    return c.post("/checkout", data=data, follow_redirects=False)


def test_qr_de_mesa_y_pedido_con_comision_de_mesa(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.services import plans
    sid, pid = _ids()
    admin, owner = login(ADMIN), login(OWNER)
    admin.post(f"/admin/caja/funciones?store={sid}", data={"f_tables": "1"})
    owner.post("/admin/caja/mesas", data={"from": "1", "to": "4", "area": "Salón"})
    owner.post("/admin/caja/mesas", data={"name": "Barra 1", "area": "Barra"})
    # sin "Pedí desde tu mesa" habilitado no hay QR de mesas
    assert "Imprimir QR de las mesas" not in owner.get("/admin/caja/salon").text
    assert owner.get("/admin/caja/mesas/qr", follow_redirects=False).headers["location"] == "/admin/caja"

    admin.post(f"/admin/caja/funciones?store={sid}", data={"f_tables": "1", "f_table_orders": "1"})
    assert "Imprimir QR de las mesas" in owner.get("/admin/caja/salon").text
    sheet = owner.get("/admin/caja/mesas/qr").text
    codes = _codes(sid)
    assert len(codes) == 5 and all(codes.values()) and len(set(codes.values())) == 5
    assert "Mesa 3" in sheet and "Barra 1" in sheet and sheet.count("<svg") == 5
    assert owner.get("/admin/caja/mesas/qr").text.count("<svg") == 5 and _codes(sid) == codes  # no cambian al volver a abrir

    # el cliente escanea la mesa 3
    c = client()
    assert c.get("/mesa/no-existe").status_code == 404
    r = c.get(f"/mesa/{codes['3']}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tienda/burger-mix"
    menu = c.get("/tienda/burger-mix").text
    assert "Estás en la <b>Mesa 3</b>" in menu and "No estoy en el local" in menu
    page = (c.post("/api/cart/add", json={"product_id": pid, "quantity": 2}), c.get("/checkout").text)[1]
    assert 'name="delivery_method" value="mesa"' in page and "Mesa 3" in page and 'name="address"' not in page
    # aunque manden direccion u horario, va a la mesa (comision general de la mesa: 3 %)
    r = _order(c, pid, address="Calle falsa 123", scheduled_for="2030-01-01T12:00")
    assert r.status_code == 303 and "/pedido/" in r.headers["location"], r.text[:500]
    oid = int(r.headers["location"].split("/pedido/")[1].split("?")[0])
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.table_name == "Mesa 3" and o.origin == "mesa" and o.delivery_method == "retiro"
        assert o.address == "" and o.scheduled_for is None and o.shipping == 0
        assert o.commission_rate == Decimal("3.00")
        assert o.platform_commission == plans.money(o.subtotal * Decimal("0.03"))
        assert "pedido desde la mesa" in plans.read_snapshot(o)["commission"]["source"]
    track = c.get(r.headers["location"]).text
    assert "🍽 Mesa 3" in track and "Te lo llevan a la Mesa 3" in track
    # el local lo ve con la mesa (tablero de comandas y pedidos)
    assert "🍽 Mesa 3" in owner.get("/admin/orders").text
    assert "Mesa 3" in owner.get(f"/admin/orders/{oid}").text

    # Trappi le pone otra comision de mesa a este local
    admin.post(f"/admin/caja/plan?store={sid}", data={"enabled": "default", "table_percent": "1.5"})
    r = _order(c, pid)
    oid2 = int(r.headers["location"].split("/pedido/")[1].split("?")[0])
    with SessionLocal() as db:
        o2 = db.get(Order, oid2)
        assert o2.commission_rate == Decimal("1.50") and o2.platform_commission == plans.money(o2.subtotal * Decimal("0.015"))
        assert db.get(Order, oid).commission_rate == Decimal("3.00")  # el pedido viejo no cambia

    # "No estoy en el local": vuelve al pedido normal (con la comisión de siempre)
    assert c.post("/mesa/salir", follow_redirects=False).headers["location"] == "/tienda/burger-mix"
    assert "Estás en la" not in c.get("/tienda/burger-mix").text
    r = _order(c, pid)
    assert r.status_code == 400 and "Tu mesa ya no está activa" in r.text


def test_mesa_de_otro_local_o_qr_cambiado(env):
    from app.db import SessionLocal
    from app.models import Order, PosTable
    sid, pid = _ids()
    owner = login(OWNER)
    codes = _codes(sid)
    c = client()
    c.get(f"/mesa/{codes['1']}")
    # el QR se cambia: el viejo deja de andar, el que ya estaba sentado sigue (la mesa es la misma)
    with SessionLocal() as db:
        tid = db.query(PosTable).filter_by(store_id=sid, name="1").one().id
    owner.post(f"/admin/caja/mesas/{tid}/qr-nuevo")
    assert _codes(sid)["1"] != codes["1"]
    assert client().get(f"/mesa/{codes['1']}").status_code == 404
    # si la mesa se borra, ya no se puede pedir para esa mesa
    owner.post(f"/admin/caja/mesas/{tid}", data={"action": "delete"})
    r = _order(c, pid)
    assert r.status_code == 400 and "Tu mesa ya no está activa" in r.text
    # si Trappi apaga la funcion, los QR dejan de andar
    admin = login(ADMIN)
    admin.post(f"/admin/caja/funciones?store={sid}", data={"f_tables": "1"})
    assert client().get(f"/mesa/{_codes(sid)['2']}").status_code == 404
    with SessionLocal() as db:
        assert db.query(Order).filter(Order.table_name == "Mesa 1").count() == 0
