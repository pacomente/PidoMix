"""Trappi Mandados: el cliente manda algo de una dirección a otra con la flota (sin local)."""
import os
import sys
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
HOME = (-38.7183, -62.2663)          # donde se retira
OFFICE = (-38.7100, -62.2600)        # donde se entrega (~1,1 km)
FAR = (-38.9000, -62.6000)           # fuera de la zona


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("errand") / "errand.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ClientAccount, Courier, LogisticsZone
    from app.services import accounts, logistics
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        db.add(LogisticsZone(name="Centro", kind="radius", center_lat=HOME[0], center_lng=HOME[1], radius_km=5, priority=0,
                             base_fee=Decimal("1000"), included_km=1, per_km=Decimal("400"), min_fee=Decimal("0"), rounding=Decimal("0")))
        db.add(Courier(name="Fede Flota", phone="2912222222", pin_hash=hash_password("5678")))
        acct = ClientAccount(email="ema@test.com", name="Ema", first_name="Ema")
        db.add(acct); db.commit()
        token = accounts.app_token(acct)
    logistics.invalidate()
    yield {"Authorization": f"Bearer {token}"}
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def setting(**kw):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        for k, v in kw.items():
            row = db.query(Setting).filter_by(key=k).first()
            if row: row.value = v
            else: db.add(Setting(key=k, value=v))
        db.commit()
    platform.invalidate() if hasattr(platform, "invalidate") else None


BODY = {"pickup": {"lat": HOME[0], "lng": HOME[1], "address": "Alsina 120", "note": "Timbre 3B"},
        "dropoff": {"lat": OFFICE[0], "lng": OFFICE[1], "address": "Estomba 845", "note": "Oficina 2"},
        "kind": "documentos", "size": "chico", "what": "Un sobre con papeles",
        "sender": {"name": "Ema", "phone": "291 400-1122"}, "recipient": {"name": "Laura Gómez", "phone": "291 455-1122"}}


def test_apagado_no_se_ofrece(env):
    c = client()
    assert c.get("/api/v1/config").json()["errands"] == {"enabled": False}
    assert c.get("/api/v1/errands/config", params={"lat": HOME[0], "lng": HOME[1]}).json()["enabled"] is False
    r = c.post("/api/v1/errands/quote", json={"pickup": BODY["pickup"], "dropoff": BODY["dropoff"]})
    assert r.status_code == 400 and "todavía no están disponibles" in r.json()["error"]


def test_cotiza_con_la_tarifa_de_la_flota(env):
    setting(errands_enabled="1")
    c = client()
    cfg = c.get("/api/v1/errands/config", params={"lat": HOME[0], "lng": HOME[1]}).json()
    assert cfg["enabled"] and [k["code"] for k in cfg["kinds"]][:3] == ["documentos", "llaves", "paquete"] and "prohibido" in cfg["forbidden"]
    q = c.post("/api/v1/errands/quote", json={"pickup": BODY["pickup"], "dropoff": BODY["dropoff"]}).json()
    assert q["ok"] and q["price"] >= 1000 and q["km"] > 0
    far = c.post("/api/v1/errands/quote", json={"pickup": BODY["pickup"], "dropoff": {**BODY["dropoff"], "lat": FAR[0], "lng": FAR[1]}})
    assert far.status_code == 400
    out = c.post("/api/v1/errands/quote", json={"pickup": {**BODY["pickup"], "lat": FAR[0], "lng": FAR[1]}, "dropoff": BODY["dropoff"]})
    assert out.status_code == 400 and "fuera de la zona" in out.json()["error"]


def test_pedir_un_mandado_y_que_lo_lleve_la_flota(env):
    from app.db import SessionLocal
    from app.models import Courier, Order, OrderStatus, Store
    c = client()
    assert c.post("/api/v1/errands", json=BODY).status_code == 401  # sin cuenta no
    bad = c.post("/api/v1/errands", json={**BODY, "recipient": {"name": "", "phone": ""}}, headers=env)
    assert bad.status_code == 400 and "quién lo recibe" in bad.json()["error"]
    price = c.post("/api/v1/errands/quote", json={"pickup": BODY["pickup"], "dropoff": BODY["dropoff"]}).json()["price"]
    r = c.post("/api/v1/errands", json=BODY, headers=env).json()
    assert r["ok"] and r["total"] == price
    with SessionLocal() as db:
        o = db.get(Order, r["id"])
        assert o.status == OrderStatus.LISTO and o.subtotal == 0 and o.shipping == o.total and o.delivery_pin and not o.pickup_code
        assert (o.pickup_address, o.pickup_lat) == ("Alsina 120", HOME[0]) and o.address == "Estomba 845"
        assert o.delivery_mode == "trappi" and o.platform_commission == 0 and o.store_net == 0
        hub = db.get(Store, o.store_id)
        assert hub.name == "Trappi Mandados" and hub.status.value == "INACTIVA"
    assert all(s["name"] != "Trappi Mandados" for s in c.get("/api/v1/stores").json().get("stores", []))  # no aparece como local
    # el seguimiento del cliente
    tr = c.get(f"/api/v1/orders/{r['id']}", params={"t": r["token"]}).json()
    assert tr["errand"]["kind_label"].endswith("Documentos") and tr["errand"]["pickup"]["address"] == "Alsina 120"
    assert tr["errand"]["recipient"]["name"] == "Laura Gómez"
    web = c.get(f"/pedido/{r['id']}", params={"t": r["token"]})  # el link que se le comparte a quien recibe
    assert web.status_code == 200 and "Estomba 845" in web.text
    # el repartidor cerca de donde se retira recibe la oferta, con la dirección del mandado
    h = {"Authorization": "Bearer " + c.post("/api/courier/v1/login", json={"phone": "2912222222", "pin": "5678"}).json()["token"]}
    st = c.post("/api/courier/v1/pulse", headers=h, json={"online": True, "lat": HOME[0] + 0.002, "lng": HOME[1]}).json()
    offer = st["offer"]
    assert offer["store"]["address"] == "Alsina 120" and offer["store"]["name"].startswith("Mandado")
    assert offer["errand"]["recipient"]["phone"] and offer["to_store_km"] is not None and offer["collect"] == price
    st = c.post(f"/api/courier/v1/offers/{offer['id']}/accept", headers=h).json()
    trip = st["trip"]
    assert trip["store"]["address"] == "Alsina 120" and trip["errand"]["pickup"]["name"] == "Ema" and not trip["pickup_code_required"]
    assert c.post(f"/api/courier/v1/trip/{r['id']}/pickup", headers=h, json={}).status_code == 200
    with SessionLocal() as db:
        pin = db.get(Order, r["id"]).delivery_pin
        cid = db.query(Courier).filter_by(phone="2912222222").one().id
    c.post("/api/courier/v1/pulse", headers=h, json={"lat": OFFICE[0], "lng": OFFICE[1]})
    c.post(f"/api/courier/v1/trip/{r['id']}/arrived", headers=h)
    d = c.post(f"/api/courier/v1/trip/{r['id']}/deliver", headers=h, json={"pin": pin})
    assert d.status_code == 200, d.text
    assert d.json()["delivered"]["collected"] == price  # cobró el mandado en efectivo
    with SessionLocal() as db:
        o = db.get(Order, r["id"])
        assert o.status == OrderStatus.ENTREGADO and o.courier_id == cid and o.trappi_income is not None
