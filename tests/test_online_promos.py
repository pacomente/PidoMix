"""Promos de la caja (2x1, happy hour) marcadas "también en la app": el servidor las aplica a los pedidos online."""
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("promo") / "promo.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import PosPromo, Product, Store
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        s.pos_features = json.dumps(["promos"])
        ipa = Product(name="IPA pinta", price=Decimal("4000"), store_id=s.id)
        db.add(ipa); db.flush()
        db.add(PosPromo(store_id=s.id, name="2x1 en pintas", kind="nxm", buy=2, pay=1, product_ids=json.dumps([ipa.id]), days="0123456", online=True))
        db.add(PosPromo(store_id=s.id, name="Solo mostrador", kind="percent", value=50, product_ids=json.dumps([ipa.id]), days="0123456", online=False))
        db.commit()
    yield
    engine.dispose()


def ids():
    from app.db import SessionLocal
    from app.models import Product, Store
    with SessionLocal() as db:
        return db.query(Store).filter_by(slug="burger-mix").one().id, db.query(Product).filter_by(name="IPA pinta").one().id


def test_el_2x1_online_se_calcula_en_el_servidor(env):
    from app.db import SessionLocal
    from app.services.cart import price_lines
    _, ipa = ids()
    with SessionLocal() as db:
        cart = price_lines(db, [{"product_id": ipa, "quantity": 3, "modifiers": []}])
    assert cart["subtotal"] == Decimal("12000")
    assert cart["promo_discount"] == Decimal("4000")  # 3 pintas: una gratis (la promo solo de mostrador no entra)
    assert [p["name"] for p in cart["promos"]] == ["2x1 en pintas"]


def test_la_cotizacion_de_la_app_y_el_pedido_llevan_la_promo(env):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.models import Order
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    sid, ipa = ids()
    c = TestClient(app)
    q = c.post("/api/v1/cart/quote", json={"items": [{"product_id": ipa, "quantity": 2, "modifiers": []}], "delivery_method": "retiro"}).json()
    assert q["promo_discount"] == 4000 and q["discount"] == 4000 and q["total"] == 4000
    assert q["promos"] == [{"name": "2x1 en pintas", "amount": 4000.0}]
    store = c.get("/api/v1/stores/burger-mix").json()
    assert any(p["label"] == "2×1" and p["on"] and ipa in p["product_ids"] for p in store["promos"])
    assert all(p["name"] != "Solo mostrador" for p in store["promos"])
    r = c.post("/api/v1/orders", json={"items": [{"product_id": ipa, "quantity": 2, "modifiers": []}], "delivery_method": "retiro",
                                        "payment_method": "efectivo", "first_name": "Ana", "last_name": "Test", "phone": "2914000000"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        o = db.get(Order, r.json()["id"])
        assert o.subtotal == Decimal("8000") and o.promo_discount == Decimal("4000") and o.discount == Decimal("4000") and o.total == Decimal("4000")
        assert o.promo_text == "2x1 en pintas"


def test_happy_hour_con_horario(env):
    from app.db import SessionLocal
    from app.models import PosPromo, Store
    from app.services import online_promos
    sid, ipa = ids()
    with SessionLocal() as db:
        db.query(PosPromo).filter_by(name="2x1 en pintas").update({"start": "18:00", "end": "21:00"})
        db.commit()
        s = db.get(Store, sid)
        # 19:30 hora de Argentina = 22:30 UTC: vale y termina a las 21 (00:00 UTC)
        at = datetime(2026, 11, 17, 22, 30)
        b = [x for x in online_promos.badges(db, s, now=at) if x["name"] == "2x1 en pintas"][0]
        assert b["on"] and b["ends_at"] == datetime(2026, 11, 18, 0, 0)
        # 15:00 (18:00 UTC): todavía no empezó, pero se avisa desde qué hora
        b = [x for x in online_promos.badges(db, s, now=datetime(2026, 11, 17, 18, 0)) if x["name"] == "2x1 en pintas"][0]
        assert not b["on"] and b["start"] == "18:00" and b["ends_at"] is None
        # 22:00 (01:00 UTC del día siguiente): ya terminó, no se muestra
        assert not [x for x in online_promos.badges(db, s, now=datetime(2026, 11, 18, 1, 0)) if x["name"] == "2x1 en pintas"]
        db.query(PosPromo).filter_by(name="2x1 en pintas").update({"start": None, "end": None})
        db.commit()
