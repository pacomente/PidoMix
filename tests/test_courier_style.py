"""Repartidor 1.9: elige su personaje y color en el mapa; el cliente lo ve en el seguimiento."""
import os
import sys
from datetime import datetime
from decimal import Decimal

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("cstyle") / "cstyle.db"
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
        s = db.query(Store).filter_by(slug="burger-mix").one()
        s.lat, s.lng = -38.7183, -62.2663
        db.add(Courier(name="Lucas Gómez", phone="2915550000", pin_hash=hash_password("1234"), store_id=s.id))
        db.commit()
    yield TestClient(app)
    engine.dispose()


def login(c):
    r = c.post("/api/courier/v1/login", json={"phone": "2915550000", "pin": "1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def orders(n, status, courier=True):
    from app.db import SessionLocal
    from app.models import Courier, Order, Store
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        cid = db.query(Courier).filter_by(phone="2915550000").one().id
        ids = []
        for _ in range(n):
            o = Order(store_id=s.id, courier_id=cid if courier else None, delivery_method="delivery", subtotal=Decimal("5000"), shipping=0,
                      total=Decimal("5000"), status=status, address="Alsina 100", lat=-38.72, lng=-62.27)
            db.add(o); db.flush(); ids.append(o.id)
        db.commit()
        return ids


def test_elige_personaje_y_color(env):
    from app.models import OrderStatus
    c = env
    assert c.get("/api/courier/v1/style").status_code == 401
    h = login(c)
    cat = c.get("/api/courier/v1/style", headers=h).json()
    assert cat["avatar"] is None and cat["color"] == "violeta" and cat["delivered"] == 0
    av = {a["key"]: a for a in cat["avatars"]}
    assert av["gato"]["emoji"] == "🐱" and not av["gato"]["locked"] and av["unicornio"]["locked"] and av["unicornio"]["unlock"] == 100
    assert c.get("/api/courier/v1/me", headers=h).json()["courier"]["style"] == {"avatar": None, "color": None}

    r = c.post("/api/courier/v1/style", headers=h, json={"avatar": "gato", "color": "rosa"})
    assert r.status_code == 200 and r.json()["style"] == {"avatar": "🐱", "color": "#FF6FB5"}
    assert c.get("/api/courier/v1/me", headers=h).json()["courier"]["style"] == {"avatar": "🐱", "color": "#FF6FB5"}
    # no existe, o todavía bloqueado: no cambia nada
    assert c.post("/api/courier/v1/style", headers=h, json={"avatar": "dinosaurio"}).status_code == 400
    assert c.post("/api/courier/v1/style", headers=h, json={"avatar": "gato", "color": "#000000"}).status_code == 400
    r = c.post("/api/courier/v1/style", headers=h, json={"avatar": "cohete", "color": "menta"})
    assert r.status_code == 400 and "25 entregas" in r.json()["error"]
    assert c.get("/api/courier/v1/style", headers=h).json()["avatar"] == "gato"
    # con 25 entregas se desbloquea el cohete
    orders(25, OrderStatus.ENTREGADO)
    assert c.post("/api/courier/v1/style", headers=h, json={"avatar": "cohete", "color": "menta"}).json()["style"] == {"avatar": "🚀", "color": "#2EE59D"}
    # vacío: vuelve al punto de siempre
    assert c.post("/api/courier/v1/style", headers=h, json={"avatar": ""}).json()["style"] == {"avatar": None, "color": None}


def test_el_cliente_ve_el_personaje(env):
    from app.db import SessionLocal
    from app.models import Courier, Order, OrderStatus
    from app.services import tracking
    c = env
    h = login(c)
    c.post("/api/courier/v1/style", headers=h, json={"avatar": "gato", "color": "rosa"})
    oid = orders(1, OrderStatus.EN_CAMINO)[0]
    with SessionLocal() as db:
        cour = db.query(Courier).filter_by(phone="2915550000").one()
        cour.lat, cour.lng, cour.location_at = -38.719, -62.268, datetime.utcnow()
        db.commit()
        tr = tracking.for_order(db, db.get(Order, oid))
    assert tr["avatar"] == "🐱" and tr["color"] == "#FF6FB5" and tr["vehicle"] == "moto"
    from app.routers.public import order_token
    page = c.get(f"/pedido/{oid}?t={order_token(oid)}").text
    assert "tr.avatar" in page
