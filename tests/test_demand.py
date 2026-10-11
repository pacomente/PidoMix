"""Demanda y multiplicador de la flota, zonas calientes y ruta paso a paso de la app del repartidor."""
import os
import sys
from decimal import Decimal

import pytest

STORE = (-38.7183, -62.2663)
NEAR = (-38.7200, -62.2700)
FAR = (-38.7400, -62.2300)  # a unos 4 km


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("demand") / "demand.db"
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
        db.add_all([
            Courier(name="Fede Flota", phone="2912222222", pin_hash=hash_password("5678")),
            Courier(name="Lucía Propia", phone="2911111111", pin_hash=hash_password("1234"), store_id=store.id),
        ])
        db.commit()
    yield TestClient(app)
    engine.dispose()


def settings(**values):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import demand, platform
    with SessionLocal() as db:
        for k, v in values.items():
            row = db.query(Setting).filter_by(key=k).first()
            v = "1" if v is True else "0" if v is False else str(v)
            if row:
                row.value = v
            else:
                db.add(Setting(key=k, value=v))
        db.commit()
    platform.invalidate()
    demand.clear()


def login(c, phone, pin):
    r = c.post("/api/courier/v1/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def pulse(c, h, **kw):
    r = c.post("/api/courier/v1/pulse", headers=h, json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def waiting_order(status="CONFIRMADO"):
    """Un pedido de delivery confirmado, sin repartidor, que la flota puede llevar."""
    from app.db import SessionLocal
    from app.models import Customer, Order, OrderStatus, Store
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        cust = Customer(first_name="Ana", last_name="", phone="2914000000")
        db.add(cust); db.flush()
        o = Order(store_id=store.id, customer_id=cust.id, status=OrderStatus[status], delivery_method="delivery", address="Alsina 100",
                  lat=NEAR[0], lng=NEAR[1], subtotal=Decimal("6000"), shipping=Decimal("1500"), total=Decimal("7500"),
                  payment_method="efectivo", logistics="mixta")
        db.add(o); db.commit()
        return o.id


def clear_orders():
    from app.db import SessionLocal
    from app.models import DeliveryOffer, Order, OrderStatus
    with SessionLocal() as db:
        db.query(DeliveryOffer).delete()
        for o in db.query(Order).all():
            o.status, o.courier_id = OrderStatus.ENTREGADO, None
        db.commit()


def test_niveles_y_tope_del_multiplicador(env):
    from app.services import demand
    cfg = {"surge_enabled": True, "surge_mode": "auto", "surge_high_multiplier": 1.2, "surge_very_high_multiplier": 1.8,
           "surge_manual_multiplier": 1.3, "surge_max_multiplier": 1.5}
    assert demand.multiplier_for(cfg, "normal") == Decimal("1.00")
    assert demand.multiplier_for(cfg, "alta") == Decimal("1.20")
    assert demand.multiplier_for(cfg, "muy_alta") == Decimal("1.50")  # el tope manda
    assert demand.multiplier_for({**cfg, "surge_mode": "manual"}, "normal") == Decimal("1.30")
    assert demand.multiplier_for({**cfg, "surge_enabled": False}, "muy_alta") == Decimal("1.00")
    assert demand.mult_text(Decimal("1.20")) == "x1,2" and demand.mult_text(Decimal("1.50")) == "x1,5"


def test_pago_con_multiplicador(env):
    from app.services import logistics
    base = {"courier_pay_mode": "shipping", "courier_pay_value": 0, "surge_max_extra": 0}
    pay, detail = logistics.courier_payout(base, Decimal("1500"), multiplier=Decimal("1.2"))
    assert pay == Decimal("1800.00") and detail["surge"] == "300.00" and detail["before_surge"] == "1500.00"
    pay, detail = logistics.courier_payout({**base, "surge_max_extra": 200}, Decimal("1500"), multiplier=Decimal("1.5"))
    assert pay == Decimal("1700.00")  # el extra no pasa del tope en pesos
    pay, detail = logistics.courier_payout(base, Decimal("1500"), multiplier=Decimal("1"))
    assert pay == Decimal("1500.00") and "surge" not in detail


def test_demanda_zonas_y_oferta_con_multiplicador(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.services import demand
    clear_orders()
    settings(surge_enabled=True, surge_mode="auto", surge_min_orders=2, surge_high_ratio=1.5, surge_high_multiplier=1.2,
             surge_very_high_ratio=3, surge_very_high_multiplier=1.5, surge_max_multiplier=2, dispatch_auto=False)
    fleet, own = login(env, "2912222222", "5678"), login(env, "2911111111", "1234")
    st = pulse(env, fleet, online=True, lat=FAR[0], lng=FAR[1])
    assert st["demand"]["level"] == "normal" and st["demand"]["multiplier_text"] is None and st["demand"]["hotspots"] == []
    ids = [waiting_order() for _ in range(3)]
    demand.clear()
    st = pulse(env, fleet, lat=FAR[0], lng=FAR[1])
    d = st["demand"]
    # 3 pedidos esperando y 1 repartidor libre: demanda muy alta, x1,5
    assert d["level"] == "muy_alta" and d["multiplier"] == 1.5 and d["multiplier_text"] == "x1,5" and d["waiting"] == 3
    assert len(d["hotspots"]) == 1 and d["hotspots"][0]["orders"] == 3 and d["hotspots"][0]["name"] == "Burger Mix"
    assert d["suggestion"] and d["suggestion"]["orders"] == 3 and "Burger Mix" in d["suggestion"]["text"]
    # el cadete propio del local no tiene multiplicador ni zonas (lo paga el local)
    d_own = pulse(env, own, online=True, lat=NEAR[0], lng=NEAR[1])["demand"]
    assert d_own["multiplier"] == 1 and d_own["hotspots"] == [] and d_own["suggestion"] is None
    pulse(env, own, online=False)
    # la oferta a la flota lleva el multiplicador fijo, y es lo que cobra al aceptar
    settings(dispatch_auto=True)
    from app.services import dispatch
    with SessionLocal() as db:
        dispatch.tick(db)
    offer = pulse(env, fleet, lat=NEAR[0], lng=NEAR[1])["offer"]
    assert offer and offer["multiplier_text"] == "x1,5" and offer["earnings"] == 2250
    assert any(line["label"].startswith("Multiplicador x1,5") and line["amount"] == 750 for line in offer["payout"]["lines"])
    settings(surge_enabled=False)  # aunque lo apaguen despues, se respeta lo que se le ofrecio
    st = env.post(f"/api/courier/v1/offers/{offer['id']}/accept", headers=fleet).json()
    assert st["trip"]["earnings"] == 2250
    with SessionLocal() as db:
        o = db.get(Order, st["trip"]["order_id"])
        assert o.courier_pay == Decimal("2250.00") and '"multiplier": "1.50"' in o.courier_pay_breakdown
    assert st["trip"]["order_id"] in ids


class FakeDirections:
    name = "fake"

    def __init__(self):
        self.calls = []

    def route(self, a, b):
        from app.services.routing import Route
        return Route(km=1.0, minutes=3.0, source="osrm")

    def directions(self, a, b):
        from app.services.routing import parse_directions
        self.calls.append((a, b))
        return parse_directions({"distance": 1200, "duration": 240, "geometry": {"coordinates": [[a[1], a[0]], [b[1], b[0]]]},
                                 "legs": [{"steps": [
                                     {"distance": 400, "name": "Alsina", "maneuver": {"type": "depart", "location": [a[1], a[0]]}},
                                     {"distance": 800, "name": "Av. Alem", "maneuver": {"type": "turn", "modifier": "right", "location": [-62.268, -38.719]}},
                                     {"distance": 0, "name": "", "maneuver": {"type": "arrive", "location": [b[1], b[0]]}}]}]})


def test_ruta_paso_a_paso(env):
    from app.services import routing
    fake = FakeDirections()
    routing.set_provider(fake)
    try:
        fleet = login(env, "2912222222", "5678")
        r = env.get("/api/courier/v1/route", headers=fleet, params={"lat": FAR[0], "lng": FAR[1]})
        assert r.status_code == 200, r.text
        data = r.json()
        # viaje en curso sin retirar: va al local
        assert data["kind"] == "store" and data["to"] == {"lat": STORE[0], "lng": STORE[1]}
        steps = data["directions"]["steps"]
        assert [s["text"] for s in steps] == ["Salí por Alsina", "Doblá a la derecha por Av. Alem", "Llegaste a Burger Mix"]
        assert data["directions"]["km"] == 1.2 and data["directions"]["minutes"] == 4.0
        assert fake.calls[-1] == ((FAR[0], FAR[1]), STORE)
        # misma consulta: sale de la cache, no vuelve a llamar al servidor de rutas
        env.get("/api/courier/v1/route", headers=fleet, params={"lat": FAR[0], "lng": FAR[1]})
        assert len(fake.calls) == 1
        # sin proveedor: la app recibe el destino y dibuja la linea recta
        routing.set_provider(None)
        data = env.get("/api/courier/v1/route", headers=fleet, params={"lat": FAR[0], "lng": FAR[1]}).json()
        assert data["directions"] is None and data["kind"] == "store"
        # sin viaje no hay ruta de viaje
        own = login(env, "2911111111", "1234")
        assert env.get("/api/courier/v1/route", headers=own, params={"lat": 1, "lng": 1}).status_code == 404
    finally:
        routing.set_provider(None)


def test_canal_de_notificacion_segun_version(env, monkeypatch):
    """La app 1.5.0+ avisa su canal (otro sonido); a las viejas se les sigue mandando el de antes."""
    import threading
    from app.db import SessionLocal
    from app.models import Courier, Order
    from app.services import push
    sent = []
    monkeypatch.setattr(push, "_service_account", lambda: {"project_id": "x"})
    monkeypatch.setattr(push, "_send", lambda info, payloads: sent.extend(payloads) or [])
    monkeypatch.setattr(threading, "Thread", lambda target, args=(), daemon=None: type("T", (), {"start": lambda self: target(*args)})())
    fleet = login(env, "2912222222", "5678")
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.courier_id.isnot(None)).first()
    for body, channel, sound in (({"token": "tel-viejo"}, "ofertas", "trappi_viaje.wav"),
                                 ({"token": "tel-nuevo", "channel": "viajes_nuevos"}, "viajes_nuevos", "trappi_repartidor_nuevo.wav"),
                                 ({"token": "tel-raro", "channel": "cualquiera"}, "ofertas", "trappi_viaje.wav")):
        assert env.post("/api/courier/v1/push", headers=fleet, json=body).status_code == 200
        with SessionLocal() as db:
            c = db.query(Courier).filter_by(phone="2912222222").one()
            o = db.get(Order, order.id)
            assert push.notify_offer(c, o, 30, 1500)
        data = sent[-1][1]["message"]["data"]
        assert data["channelId"] == channel and data["sound"] == sound
