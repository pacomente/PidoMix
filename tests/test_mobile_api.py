"""API /api/v1 que usa la app movil."""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("mobile") / "mobile.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import ModifierGroup, ModifierOption, Product
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        burger = db.query(Product).filter_by(name="Hamburguesa Clásica").one()
        g = ModifierGroup(product_id=burger.id, name="Extras", max_select=2); db.add(g); db.flush()
        db.add(ModifierOption(group_id=g.id, name="Cheddar", price_extra=500)); db.commit()
    yield TestClient(app)
    engine.dispose()


def ids(api):
    from app.db import SessionLocal
    from app.models import ModifierOption, Product
    with SessionLocal() as db:
        return (db.query(Product).filter_by(name="Coca Cola").one().id, db.query(Product).filter_by(name="Hamburguesa Clásica").one().id,
                db.query(ModifierOption).filter_by(name="Cheddar").one().id)


def test_catalog(api):
    assert api.get("/api/v1/config").json()["map_center"]["lat"] < 0
    home = api.get("/api/v1/home").json()
    assert home["stores"][0]["slug"] == "burger-mix" and home["stores"][0]["emoji"] == "🍔"
    assert {"banners", "store_categories", "categories", "promos"} <= set(home)
    detail = api.get("/api/v1/stores/burger-mix").json()
    assert detail["store"]["is_open"] and sum(len(g["products"]) for g in detail["menu"]) == 2
    assert api.get("/api/v1/stores/no-existe").status_code == 404
    _, burger, cheddar = ids(api)
    product = api.get(f"/api/v1/products/{burger}").json()
    assert product["customizable"] and product["groups"][0]["options"][0]["id"] == cheddar
    assert [s["slug"] for s in api.get("/api/v1/search?q=burger").json()["stores"]] == ["burger-mix"]
    assert api.get("/api/v1/stores?sort=rapidos&delivery=true").status_code == 200
    # las fotos de Cloudinary se piden al tamaño justo y en formato liviano
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        db.get(Product, burger).image_url = "https://res.cloudinary.com/demo/image/upload/v1/pidomix/products/burger.jpg"; db.commit()
    img = api.get(f"/api/v1/products/{burger}").json()["image_url"]
    assert img == "https://res.cloudinary.com/demo/image/upload/f_auto,q_auto,c_limit,w_720/v1/pidomix/products/burger.jpg"
    page = api.get("/tienda/burger-mix").text
    assert "f_auto,q_auto,c_limit,w_720/v1/pidomix/products/burger.jpg" in page


def test_quote_and_order_flow(api):
    coca, burger, cheddar = ids(api)
    items = [{"product_id": coca, "quantity": 2}, {"product_id": burger, "modifiers": [cheddar, 999]}, {"product_id": 123456}]
    q = api.post("/api/v1/cart/quote", json={"items": items, "delivery_method": "delivery"}).json()
    assert q["subtotal"] == 2 * 2000 + 10500 and q["shipping"] == 1500 and q["total"] == 16000 and q["dropped"] == 1
    assert q["items"][1]["modifiers"] == [cheddar]  # la opcion inexistente se descarta
    assert api.post("/api/v1/cart/quote", json={"items": items, "delivery_method": "retiro"}).json()["shipping"] == 0
    bad = api.post("/api/v1/orders", json={"items": items, "delivery_method": "delivery", "first_name": "Ana", "phone": "1"})
    assert bad.status_code == 400 and "dirección" in bad.json()["error"]
    assert api.post("/api/v1/orders", json={"items": [], "delivery_method": "retiro", "first_name": "Ana", "phone": "1"}).status_code == 400
    r = api.post("/api/v1/orders", json={"items": items, "delivery_method": "delivery", "first_name": "Ana", "last_name": "Paz", "phone": "291 555", "address": "Calle 1", "notes": "Sin hielo"})
    data = r.json()
    assert r.status_code == 200 and data["ok"] and data["total"] == 16000
    order = api.get(f"/api/v1/orders/{data['id']}?t={data['token']}").json()
    assert order["status"] == "PENDIENTE" and order["steps"][0]["current"] and order["steps"][0]["at"]
    assert [s["status"] for s in order["steps"]][-2:] == ["EN_CAMINO", "ENTREGADO"] and order["items"][1]["modifiers_text"] == "Cheddar"
    assert api.get(f"/api/v1/orders/{data['id']}?t=falso").status_code == 404
    batch = api.get(f"/api/v1/orders?refs={data['id']}:{data['token']},99:malo").json()["orders"]
    assert [o["id"] for o in batch] == [data["id"]]
    # reseña: solo cuando el local lo marca entregado
    review = {"t": data["token"], "rating": 5, "comment": "Excelente"}
    assert api.post(f"/api/v1/orders/{data['id']}/review", json=review).status_code == 409
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    with SessionLocal() as db:
        db.get(Order, data["id"]).status = OrderStatus.ENTREGADO; db.commit()
    assert api.get(f"/api/v1/orders/{data['id']}?t={data['token']}").json()["can_review"]
    assert api.post(f"/api/v1/orders/{data['id']}/review", json=review).json()["ok"]
    assert api.post(f"/api/v1/orders/{data['id']}/review", json=review).status_code == 409
    assert api.get("/api/v1/stores/burger-mix").json()["reviews"][0]["author"] == "Ana P."


def test_push_notifications(api, monkeypatch):
    import json
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, PushToken
    from app.routers import mobile_api
    from app.services import push
    from app.services.orders import set_status
    mobile_api.order_limiter.clear()
    coca, _, _ = ids(api)
    base = {"items": [{"product_id": coca}], "delivery_method": "retiro", "first_name": "Ana", "phone": "1"}
    data = api.post("/api/v1/orders", json={**base, "push_token": "tel-uno-123456"}).json()
    oid, tok = data["id"], data["token"]
    assert api.post(f"/api/v1/orders/{oid}/push", json={"t": "malo", "token": "tel-dos-123456"}).status_code == 404
    r = api.post(f"/api/v1/orders/{oid}/push", json={"t": tok, "token": "tel-dos-123456"}).json()
    assert r["ok"] and not r["enabled"]  # sin FIREBASE_SERVICE_ACCOUNT no se manda nada
    api.post(f"/api/v1/orders/{oid}/push", json={"t": tok, "token": "tel-dos-123456"})  # repetido: no se duplica
    with SessionLocal() as db:
        assert sorted(db.query(PushToken.token).filter_by(order_id=oid).all()) == [("tel-dos-123456",), ("tel-uno-123456",)]
        order = db.get(Order, oid)
        assert set_status(order, OrderStatus.CONFIRMADO) and not push.notify_status(db, order)
        db.commit()

    # con la cuenta de servicio configurada: cada telefono recibe el aviso y los dados de baja se borran
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    monkeypatch.setattr(push.settings, "firebase_service_account", json.dumps({"project_id": "trappi-test", "client_email": "bot@trappi-test.iam", "private_key": pem}))
    sent = []
    monkeypatch.setattr(push, "_send", lambda info, payloads: sent.extend(payloads) or ["tel-uno-123456"])

    class SyncThread:
        def __init__(self, target, args, daemon): self.run = lambda: target(*args)
        def start(self): self.run()
    monkeypatch.setattr(push.threading, "Thread", SyncThread)
    with SessionLocal() as db:
        order = db.get(Order, oid)
        assert set_status(order, OrderStatus.PREPARANDO) and push.notify_status(db, order)
    assert len(sent) == 2 and sent[0][1]["message"]["data"]["channelId"] == "seguimiento"
    msg = sent[0][1]["message"]["data"]
    assert "preparando" in msg["message"] and json.loads(msg["body"]) == {"order_id": oid, "status": "PREPARANDO"}
    with SessionLocal() as db:
        assert db.query(PushToken.token).filter_by(order_id=oid).all() == [("tel-dos-123456",)]
        order = db.get(Order, oid); order.status = OrderStatus.LISTO
        assert push.message_for(order)[0] == "¡Tu pedido está listo! 🛍"  # retiro: "pasá a retirar"
        order.status = OrderStatus.ENTREGADO; db.commit()
    assert not api.post(f"/api/v1/orders/{oid}/push", json={"t": tok, "token": "tel-tres-123456"}).json()["ok"]  # ya terminado


def test_validation_and_rate_limit(api):
    coca, _, _ = ids(api)
    assert api.post("/api/v1/cart/quote", json={"items": [{"product_id": coca, "quantity": 500}]}).status_code == 422
    assert api.post("/api/v1/orders/1/review", json={"t": "x", "rating": 9}).status_code == 422
    from app.routers import mobile_api
    mobile_api.order_limiter.clear()
    order = {"items": [{"product_id": coca}], "delivery_method": "retiro", "first_name": "Bot", "phone": "1"}
    for _ in range(mobile_api.order_limiter.limit):
        assert api.post("/api/v1/orders", json=order).status_code == 200
    assert api.post("/api/v1/orders", json=order).status_code == 429
