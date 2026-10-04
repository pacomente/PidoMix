"""App del repartidor: ofertas estilo Uber, viaje y ganancias."""
import os
import sys
from datetime import datetime, timedelta

import pytest

STORE = (-38.7183, -62.2663)
NEAR = (-38.7200, -62.2700)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("courier") / "courier.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import Courier, Store
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        store.lat, store.lng = STORE
        other = Store(name="Otro local", slug="otro-local", lat=STORE[0], lng=STORE[1])
        db.add(other); db.flush()
        db.add_all([
            Courier(name="Lucía Propia", phone="2911111111", pin_hash=hash_password("1234"), store_id=store.id),
            Courier(name="Fede Flota", phone="2912222222", pin_hash=hash_password("5678")),
            Courier(name="Ajeno", phone="2913333333", pin_hash=hash_password("0000"), store_id=other.id),
        ])
        db.commit()
    yield TestClient(app)
    engine.dispose()


def login(c, phone, pin):
    r = c.post("/api/courier/v1/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def new_order(c):
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        coca = db.query(Product).filter_by(name="Coca Cola").one().id
    r = c.post("/api/v1/orders", json={"items": [{"product_id": coca, "quantity": 3}], "delivery_method": "delivery", "first_name": "Ana",
                                        "phone": "2914000000", "address": "Alsina 100", "lat": NEAR[0], "lng": NEAR[1]})
    assert r.status_code == 200, r.text
    return r.json()


def confirm(order_id, now=None):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    from app.services import dispatch
    from app.services.orders import set_status
    with SessionLocal() as db:
        assert set_status(db.get(Order, order_id), OrderStatus.CONFIRMADO)
        db.commit()
        dispatch.tick(db, now)


def pulse(c, h, **kw):
    r = c.post("/api/courier/v1/pulse", headers=h, json=kw)
    assert r.status_code in (200, 409), r.text
    return r.json()


def test_login_y_sesion(env):
    assert env.post("/api/courier/v1/login", json={"phone": "291 111-1111", "pin": "9999"}).status_code == 401
    h = login(env, "291 111-1111", "1234")  # el telefono se normaliza
    me = env.get("/api/courier/v1/me", headers=h).json()
    assert me["courier"]["name"] == "Lucía Propia" and me["courier"]["fleet"] == "local" and me["trip"] is None
    assert env.get("/api/courier/v1/me", headers={"Authorization": "Bearer falso"}).status_code == 401


def test_oferta_viaje_y_ganancias(env):
    from app.routers import mobile_api
    mobile_api.order_limiter._hits.clear()
    own, fleet, alien = login(env, "2911111111", "1234"), login(env, "2912222222", "5678"), login(env, "2913333333", "0000")
    for h in (own, fleet, alien):
        assert pulse(env, h, online=True, lat=NEAR[0], lng=NEAR[1])["courier"]["online"]
    order = new_order(env)
    assert pulse(env, own)["offer"] is None  # pendiente: todavia no se ofrece
    confirm(order["id"])
    # primero el repartidor propio del local; el de otro local nunca lo ve
    offer = pulse(env, own)["offer"]
    assert offer and offer["order_id"] == order["id"] and offer["own_store"] and offer["earnings"] == 1500 and offer["to_store_km"] is not None
    assert pulse(env, fleet)["offer"] is None and pulse(env, alien)["offer"] is None
    # rechaza: pasa a la flota de Trappi
    assert env.post(f"/api/courier/v1/offers/{offer['id']}/reject", headers=own).json()["offer"] is None
    offer2 = pulse(env, fleet)["offer"]
    assert offer2 and offer2["order_id"] == order["id"] and not offer2["own_store"]
    assert env.post(f"/api/courier/v1/offers/{offer['id']}/accept", headers=own).status_code == 409  # ya la rechazo
    state = env.post(f"/api/courier/v1/offers/{offer2['id']}/accept", headers=fleet).json()
    trip = state["trip"]
    assert trip["order_id"] == order["id"] and trip["stage"] == "pickup" and trip["customer"]["address"] == "Alsina 100"
    assert trip["collect"] == trip["total"] and trip["items"][0]["quantity"] == 3
    # el cliente ve quien lo lleva
    seguimiento = env.get(f"/api/v1/orders/{order['id']}?t={order['token']}").json()
    assert seguimiento["courier"] == {"name": "Fede", "vehicle": "moto"}
    # no se puede desconectar ni entregar antes de retirar
    assert env.post("/api/courier/v1/pulse", headers=fleet, json={"online": False}).status_code == 409
    assert env.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=fleet).status_code == 409
    assert env.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=own).status_code == 404  # no es su viaje
    assert env.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=fleet).json()["trip"]["stage"] == "dropoff"
    done = env.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=fleet).json()
    assert done["delivered"]["earnings"] == 1500 and done["trip"] is None
    assert done["earnings"]["today"] == 1500 and done["earnings"]["trips_today"] == 1
    hist = env.get("/api/courier/v1/earnings", headers=fleet).json()
    assert hist["week"] == 1500 and hist["trips"][0]["order_id"] == order["id"]
    assert env.get(f"/api/v1/orders/{order['id']}?t={order['token']}").json()["status"] == "ENTREGADO"


def test_oferta_vence_y_pasa_al_siguiente(env):
    from app.db import SessionLocal
    from app.services import dispatch
    own, fleet = login(env, "2911111111", "1234"), login(env, "2912222222", "5678")
    pulse(env, own, online=True, lat=NEAR[0], lng=NEAR[1]); pulse(env, fleet, online=True, lat=NEAR[0], lng=NEAR[1])
    order = new_order(env)
    confirm(order["id"])
    assert pulse(env, own)["offer"]["order_id"] == order["id"]
    with SessionLocal() as db:
        dispatch.tick(db, datetime.utcnow() + timedelta(seconds=dispatch.offer_seconds(db) + 1))
    assert pulse(env, own)["offer"] is None and pulse(env, fleet)["offer"]["order_id"] == order["id"]
    # el local lo asigna a mano: la oferta pendiente se cancela
    from app.models import Courier, Order
    with SessionLocal() as db:
        o, lucia, ajeno = db.get(Order, order["id"]), db.query(Courier).filter_by(phone="2911111111").one(), db.query(Courier).filter_by(phone="2913333333").one()
        with pytest.raises(dispatch.DispatchError):
            dispatch.assign_manual(db, o, ajeno)  # es de otro local
        dispatch.assign_manual(db, o, lucia); db.commit()
        dispatch.tick(db)
    assert pulse(env, fleet)["offer"] is None
    assert pulse(env, own)["trip"]["order_id"] == order["id"]
    # lo libera antes de retirarlo: se le ofrece al otro (a ella no se le vuelve a ofrecer)
    assert env.post(f"/api/courier/v1/trip/{order['id']}/release", headers=own).json()["trip"] is None
    with SessionLocal() as db:
        assert db.get(Order, order["id"]).courier_id is None
        dispatch.tick(db, datetime.utcnow() + timedelta(minutes=4))
    assert pulse(env, own)["offer"] is None
    assert pulse(env, fleet)["offer"]["order_id"] == order["id"]


def test_desconectado_o_sin_ubicacion_no_recibe(env):
    from app.db import SessionLocal
    from app.models import Courier
    from app.services import dispatch
    with SessionLocal() as db:
        db.query(Courier).update({"online": False}); db.commit()
        assert dispatch.available(db) == []
        db.query(Courier).update({"online": True, "location_at": datetime.utcnow() - timedelta(minutes=10)}); db.commit()
        assert dispatch.available(db) == []  # la ubicacion es vieja


def test_panel_repartidores_y_asignacion_en_comandas(env):
    import re
    from app.db import SessionLocal
    from app.models import Courier, Order
    from app.routers import mobile_api
    mobile_api.order_limiter._hits.clear()
    env.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    r = env.post("/admin/repartidores", data={"name": "Nico Nuevo", "phone": "291 444-4444", "vehicle": "bici", "store_id": ""}, follow_redirects=True)
    pin = re.search(r'letter-spacing:\.15em">(\d{4})<', r.text).group(1)
    assert "Nico Nuevo" in r.text and "Desconectado" in r.text
    assert "letter-spacing:.15em" not in env.get("/admin/repartidores").text  # el PIN se muestra una sola vez
    assert env.post("/admin/repartidores", data={"name": "Otro", "phone": "2914444444"}, follow_redirects=True).text.count("Ya hay un repartidor") == 1
    h = login(env, "2914444444", pin)
    # un pedido confirmado aparece en comandas con el selector de repartidores
    order = new_order(env)
    confirm(order["id"])
    board = env.get("/admin/comandas/board").text
    assert f'/admin/orders/{order["id"]}/courier' in board and "Asignar a…" in board
    with SessionLocal() as db:
        nico = db.query(Courier).filter_by(phone="2914444444").one().id
    r = env.post(f"/admin/orders/{order['id']}/courier", data={"courier_id": str(nico)}, headers={"X-Requested-With": "fetch"})
    assert r.json() == {"ok": True, "error": None}
    assert "Nico Nuevo</b> · va a retirar" in env.get("/admin/comandas/board").text
    assert env.get("/api/courier/v1/me", headers=h).json()["trip"]["order_id"] == order["id"]
    # nuevo PIN: la sesion anterior se cierra
    env.post(f"/admin/repartidores/{nico}/pin")
    assert env.get("/api/courier/v1/me", headers=h).status_code == 401
    with SessionLocal() as db:
        assert db.get(Order, order["id"]).courier_id == nico


def test_reglas_configurables_ganancia_y_ofertas_apagadas(env):
    from decimal import Decimal
    from app.db import SessionLocal
    from app.models import Order, Setting
    from app.routers import mobile_api
    from app.services import platform
    mobile_api.order_limiter._hits.clear()
    with SessionLocal() as db:
        db.add_all([Setting(key="courier_pay_mode", value="fixed"), Setting(key="courier_pay_value", value="2000"), Setting(key="dispatch_auto", value="0")])
        db.commit()
    platform.invalidate()
    own = login(env, "2911111111", "1234")
    pulse(env, own, online=True, lat=NEAR[0], lng=NEAR[1])
    order = new_order(env)
    confirm(order["id"])
    assert pulse(env, own)["offer"] is None  # ofertas automaticas apagadas: lo asigna el local
    with SessionLocal() as db:
        db.query(Setting).filter_by(key="dispatch_auto").update({"value": "1"}); db.commit()
    platform.invalidate()
    offer = pulse(env, own)["offer"]
    assert offer and offer["earnings"] == 2000  # monto fijo configurado, no el envio
    env.post(f"/api/courier/v1/offers/{offer['id']}/accept", headers=own)
    with SessionLocal() as db:
        assert db.get(Order, order["id"]).courier_pay == Decimal("2000.00")
        db.query(Setting).filter(Setting.key.in_(["courier_pay_mode", "courier_pay_value"])).delete(); db.commit()
    platform.invalidate()
    env.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=own)
    done = env.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=own).json()
    assert done["delivered"]["earnings"] == 2000  # queda lo que se le ofrecio aunque despues cambie la regla
