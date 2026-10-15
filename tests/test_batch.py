"""Varios pedidos a la vez y seguimiento en vivo del repartidor."""
import os
import sys

import pytest

STORE = (-38.7183, -62.2663)
NEAR = (-38.7200, -62.2700)
DROP_A = (-38.7250, -62.2750)
DROP_B = (-38.7270, -62.2770)   # ~300 m de A
FAR = (-38.7600, -62.3200)      # ~6 km de A


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("batch") / "batch.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import Courier, Setting, Store
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
        db.add_all([Courier(name="Lucía Propia", phone="2911111111", pin_hash=hash_password("1234"), store_id=store.id),
                    Setting(key="delivery_pin_required", value="0")])
        db.commit()
    yield TestClient(app)
    engine.dispose()


def setting(key, value):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        row = db.query(Setting).filter_by(key=key).first()
        if row: row.value = value
        else: db.add(Setting(key=key, value=value))
        db.commit()
    platform.invalidate()


def store_batch(on):
    """Varios pedidos para los repartidores propios: lo decide el local."""
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        db.query(Store).filter_by(slug="burger-mix").update({"own_batch": on}); db.commit()


def login(c):
    r = c.post("/api/courier/v1/login", json={"phone": "2911111111", "pin": "1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def order_at(c, at, slug="burger-mix"):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Product, Store
    from app.routers import mobile_api
    from app.services import dispatch
    from app.services.orders import set_status
    mobile_api.order_limiter.clear()
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug=slug).one()
        prod = db.query(Product).filter_by(store_id=store.id).first()
        if prod is None:  # el otro local no tiene menú: le copiamos uno
            base = db.query(Product).filter_by(name="Coca Cola").one()
            prod = Product(store_id=store.id, name="Agua", price=base.price, category_id=None)
            db.add(prod); db.commit()
        pid = prod.id
    r = c.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "delivery", "first_name": "Ana",
                                         "phone": "2914000000", "address": "Alsina 100", "lat": at[0], "lng": at[1]})
    assert r.status_code == 200, r.text
    o = r.json()
    with SessionLocal() as db:
        assert set_status(db.get(Order, o["id"]), OrderStatus.CONFIRMADO)
        db.commit()
        dispatch.tick(db)
    return o


def track(c, o):
    return c.get(f"/api/v1/orders/{o['id']}?t={o['token']}").json()["tracking"]


def pulse(c, h, **kw):
    r = c.post("/api/courier/v1/pulse", headers=h, json=kw)
    assert r.status_code in (200, 409), r.text
    return r.json()


def test_suma_un_pedido_del_mismo_local_con_entrega_cerca(env):
    h = login(env)
    pulse(env, h, online=True, lat=NEAR[0], lng=NEAR[1])
    a = order_at(env, DROP_A)
    offer = pulse(env, h)["offer"]
    assert offer["order_id"] == a["id"] and offer["batch"] is False
    assert track(env, a) is None  # todavía sin repartidor
    env.post(f"/api/courier/v1/offers/{offer['id']}/accept", headers=h)
    t = track(env, a)  # el cliente ve al repartidor yendo al local y cuánto falta
    assert t["stage"] == "to_store" and t["courier"]["lat"] == round(NEAR[0], 5) and isinstance(t["eta_min"], int) and t["eta_min"] >= 1
    assert t["name"] == "Lucía" and "phone" not in t
    b = order_at(env, DROP_B)
    st = pulse(env, h)
    assert st["trip"]["order_id"] == a["id"] and st["offer"] is None  # apagado: con un viaje no le llegan más
    store_batch(True)
    from app.db import SessionLocal
    from app.services import dispatch
    with SessionLocal() as db:
        dispatch.tick(db)
    st = pulse(env, h)
    assert st["trip"]["order_id"] == a["id"] and st["offer"]["order_id"] == b["id"]
    assert st["offer"]["batch"] is True and st["offer"]["batch_count"] == 2
    st = env.post(f"/api/courier/v1/offers/{st['offer']['id']}/accept", headers=h).json()
    assert [s["order_id"] for s in st["trips"]] == [a["id"], b["id"]] and st["trip"]["order_id"] == a["id"]
    # lejos, de otro local o pasado el máximo: no se suma
    far, other, third = order_at(env, FAR), order_at(env, DROP_B, slug="otro-local"), order_at(env, DROP_A)
    assert pulse(env, h)["offer"] is None
    # retira los dos y entrega en el orden en que los aceptó
    assert env.post(f"/api/courier/v1/trip/{a['id']}/pickup", headers=h).json()["trip"]["order_id"] == b["id"]
    st = env.post(f"/api/courier/v1/trip/{b['id']}/pickup", headers=h).json()
    assert st["trip"]["order_id"] == a["id"] and st["trip"]["stage"] == "dropoff" and [s["stage"] for s in st["trips"]] == ["dropoff", "dropoff"]
    assert track(env, a)["stage"] == "to_you" and track(env, a)["courier"]
    tb = track(env, b)  # el segundo no ve dónde está (estaría viendo la casa del primero): solo que es el siguiente
    assert tb["stage"] == "other_delivery" and tb["ahead"] == 1 and tb["courier"] is None and tb["eta_min"] is None
    st = env.post(f"/api/courier/v1/trip/{a['id']}/deliver", headers=h).json()
    assert track(env, a) is None and track(env, b)["stage"] == "to_you" and track(env, b)["courier"]
    assert st["delivered"]["order_id"] == a["id"] and st["trip"]["order_id"] == b["id"] and st["trips"] == []
    st = env.post(f"/api/courier/v1/trip/{b['id']}/deliver", headers=h).json()
    assert st["trip"] is None and st["earnings"]["trips_today"] == 2
    with SessionLocal() as db:
        from app.models import Order
        for o in (far, other, third):  # siguen esperando repartidor
            db.get(Order, o["id"]).status = db.get(Order, o["id"]).status.CANCELADO
        db.commit()
    store_batch(False)


def test_ya_retiro_no_se_le_suma_y_la_oferta_vieja_no_se_acepta(env):
    from app.db import SessionLocal
    from app.models import DeliveryOffer
    from app.services import dispatch
    h = login(env)
    pulse(env, h, online=True, lat=NEAR[0], lng=NEAR[1])
    a = order_at(env, DROP_A)
    offer = pulse(env, h)["offer"]
    env.post(f"/api/courier/v1/offers/{offer['id']}/accept", headers=h)
    store_batch(True)
    b = order_at(env, DROP_B)
    extra = pulse(env, h)["offer"]
    assert extra and extra["order_id"] == b["id"]
    env.post(f"/api/courier/v1/trip/{a['id']}/pickup", headers=h)  # salió: ya no se le puede sumar
    r = env.post(f"/api/courier/v1/offers/{extra['id']}/accept", headers=h)
    assert r.status_code == 409 and "terminá el viaje" in r.json()["error"]
    with SessionLocal() as db:
        db.query(DeliveryOffer).filter_by(order_id=b["id"], status="pending").update({"status": "rejected"}); db.commit()
        dispatch.tick(db)
    assert pulse(env, h)["offer"] is None
    # si la app deja de reportar la ubicación, no se muestra una vieja
    from datetime import datetime, timedelta
    from app.models import Courier
    with SessionLocal() as db:
        db.query(Courier).filter_by(phone="2911111111").update({"location_at": datetime.utcnow() - timedelta(minutes=10)}); db.commit()
    t = track(env, a)
    assert t["stage"] == "to_you" and t["courier"] is None
    pulse(env, h, lat=NEAR[0], lng=NEAR[1])
    env.post(f"/api/courier/v1/trip/{a['id']}/deliver", headers=h)
    store_batch(False)


def panel(store_slug, email):
    """Un usuario del local (no superadmin) con su propia sesión del panel."""
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import Store, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug=store_slug).one()
        if not db.query(User).filter_by(email=email).first():
            db.add(User(email=email, password_hash=hash_password("Local-1234"), store_id=s.id)); db.commit()
    c = TestClient(app)
    assert c.post("/admin/login", data={"email": email, "password": "Local-1234"}, follow_redirects=False).status_code == 303
    return c


def test_el_local_prende_varios_pedidos_para_sus_repartidores_y_los_ve_en_vivo(env):
    from app.db import SessionLocal
    from app.models import Store
    setting("dispatch_batch", "0")  # el panel general apagado: decide el local
    local = panel("burger-mix", "dueno@burger.test")
    page = local.get("/admin/repartidores").text
    assert "En vivo" in page and "Varios pedidos a la vez" in page
    r = local.post("/admin/repartidores/varios", data={"own_batch": "1", "own_batch_max": "9", "own_batch_km": "2"}, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        assert (s.own_batch, s.own_batch_max, s.own_batch_km) == (True, 3, 2.0)  # el máximo se limita a 3
    h = login(env)
    pulse(env, h, online=True, lat=NEAR[0], lng=NEAR[1])
    a = order_at(env, DROP_A)
    env.post(f"/api/courier/v1/offers/{pulse(env, h)['offer']['id']}/accept", headers=h)
    b = order_at(env, DROP_B)
    extra = pulse(env, h)["offer"]
    assert extra and extra["order_id"] == b["id"] and extra["batch"]
    env.post(f"/api/courier/v1/offers/{extra['id']}/accept", headers=h)
    live = local.get("/admin/repartidores/mapa.json").json()
    me = next(c for c in live["couriers"] if c["name"] == "Lucía Propia")
    assert [t["order_id"] for t in me["trips"]] == [a["id"], b["id"]] and live["store"]["name"] == "Burger Mix"
    # otro local no ve a los repartidores de este
    assert panel("otro-local", "dueno@otro.test").get("/admin/repartidores/mapa.json").json()["couriers"] == []
    # lo apaga: no se suman más (los que ya lleva siguen)
    local.post("/admin/repartidores/varios", data={"own_batch_max": "2", "own_batch_km": "1.5"})
    c3 = order_at(env, DROP_A)
    assert pulse(env, h)["offer"] is None
    for o in (a, b):
        env.post(f"/api/courier/v1/trip/{o['id']}/pickup", headers=h)
    for o in (a, b):
        env.post(f"/api/courier/v1/trip/{o['id']}/deliver", headers=h)
    with SessionLocal() as db:
        from app.models import Order, OrderStatus
        db.get(Order, c3["id"]).status = OrderStatus.CANCELADO; db.commit()


def test_la_flota_de_trappi_sigue_el_panel_general(env):
    from app.db import SessionLocal
    from app.models import Courier, Order
    from app.services import dispatch
    a = order_at(env, DROP_A)
    with SessionLocal() as db:
        o = db.get(Order, a["id"])
        fleet = Courier(name="Flota", phone="2919999999", pin_hash="x")
        own = db.query(Courier).filter_by(phone="2911111111").one()
        store_batch(True); setting("dispatch_batch", "0")
        db.expire_all()
        assert dispatch.batch_rules(db, o, fleet)[0] is False and dispatch.batch_rules(db, o, own)[0] is True
        setting("dispatch_batch", "1"); store_batch(False)
        db.expire_all()
        assert dispatch.batch_rules(db, o, fleet)[0] is True and dispatch.batch_rules(db, o, own)[0] is False
        setting("dispatch_batch", "0")
        o.status = o.status.CANCELADO; db.commit()
