"""La cuenta de la mesa: la caja la sube, el cliente la ve desde el QR (web) o desde su pedido (app) y llama al mozo."""
import json
import os
import sys
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-tab@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("tab") / "tab.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import PosTable, Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        mix.pos_features = json.dumps(["tables", "table_orders"])
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=mix.id, active=True))
        db.add(PosTable(store_id=mix.id, name="7", qr_code="mesasiete7"))
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def table_id():
    from app.db import SessionLocal
    from app.models import PosTable
    with SessionLocal() as db:
        return db.query(PosTable).filter_by(qr_code="mesasiete7").one().id


def pos_client():
    from app.db import SessionLocal
    from app.models import Setting
    with SessionLocal() as db:  # la caja habilitada (sin costo) para poder vincularla
        for k, v in {"pos_enabled": "1", "pos_commission_percent": "0", "pos_monthly_fee": "0"}.items():
            row = db.query(Setting).filter_by(key=k).first()
            if row: row.value = v
            else: db.add(Setting(key=k, value=v))
        db.commit()
    c = client()
    token = c.post("/api/pos/v1/link", json=OWNER).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


TAB = {"items": [{"name": "IPA Patagonia", "quantity": 2, "unit_price": 4200, "total": 8400},
                 {"name": "Picada para 4", "quantity": 1, "unit_price": 17900, "total": 17900, "modifiers_text": "Sin aceitunas"}],
       "subtotal": 26300, "promo_discount": 4200, "total": 22100, "opened_at": "2026-11-17T21:00:00"}


def test_la_caja_sube_la_cuenta_y_el_cliente_la_ve_desde_el_qr(env):
    tid = table_id()
    pos = pos_client()
    r = pos.post("/api/pos/v1/table-tabs", json={"tabs": [{"table_id": tid, **TAB}, {"table_id": 999999, **TAB}]})
    assert r.json() == {"ok": True, "saved": 1}  # la mesa de otro local no se guarda
    c = client()
    assert c.get("/mesa/mesasiete7", follow_redirects=False).status_code == 303
    page = c.get("/mesa/cuenta?n=4").text
    assert "Mesa 7" in page and "IPA Patagonia" in page and "Sin aceitunas" in page
    assert "$22.100" in page and "$5.525 cada uno" in page  # 22.100 / 4
    # sin haber escaneado el QR no se ve ninguna cuenta
    assert "Picada" not in client().get("/mesa/cuenta").text


def test_llamar_al_mozo_y_la_caja_lo_ve(env):
    from app.services import csrf  # noqa: F401  (el formulario lleva el token de la sesión)
    tid = table_id()
    c = client()
    c.get("/mesa/mesasiete7")
    page = c.get("/mesa/cuenta").text
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    r = c.post("/mesa/llamar", data={"kind": "mozo", "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/mesa/cuenta?ok=mozo"
    c.post("/mesa/llamar", data={"kind": "mozo", "csrf_token": token})  # repetido: no se duplica
    pos = pos_client()
    calls = pos.get("/api/pos/v1/table-calls").json()["calls"]
    assert [(x["table_id"], x["kind"]) for x in calls] == [(tid, "mozo")]
    assert pos.post(f"/api/pos/v1/table-calls/{calls[0]['id']}/seen").json() == {"ok": True}
    assert pos.get("/api/pos/v1/table-calls").json()["calls"] == []


def test_desde_el_pedido_de_la_app_y_la_mesa_que_se_cierra(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Store
    from app.routers.public import order_token
    tid = table_id()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        o = Order(store_id=s.id, origin="mesa", delivery_method="retiro", table_name="Mesa 7", subtotal=Decimal(8400), shipping=0, total=Decimal(8400),
                  status=OrderStatus.CONFIRMADO, payment_method="efectivo")
        db.add(o); db.commit()
        oid = o.id
    c, t = client(), order_token(oid)
    tab = c.get(f"/api/v1/orders/{oid}/table?t={t}&n=2").json()
    assert tab["table"] == "Mesa 7" and tab["total"] == 22100 and tab["split"] == {"people": 2, "each": 11050}
    assert c.get(f"/api/v1/orders/{oid}/table?t=malo").status_code == 404
    assert c.post(f"/api/v1/orders/{oid}/table-call", json={"t": t, "kind": "cuenta"}).json() == {"ok": True, "new": True}
    assert c.get(f"/api/v1/orders/{oid}/table?t={t}").json()["calls"] == ["cuenta"]
    assert c.post(f"/api/v1/orders/{oid}/table-call", json={"t": t, "kind": "propina"}).status_code == 400
    # la caja cobró la mesa: manda la cuenta vacía y el cliente ya no la ve
    pos_client().post("/api/pos/v1/table-tabs", json={"tabs": [{"table_id": tid, "items": []}]})
    assert c.get(f"/api/v1/orders/{oid}/table?t={t}").json()["items"] == []
