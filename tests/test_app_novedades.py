"""App de clientes 1.16: tarjeta de sellos, invitá a un amigo, reclamos con foto y ver el plato en 3D (API /api/v1)."""
import io
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("appnov") / "appnov.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ClientAccount, Setting, Store
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        s.stamps_goal, s.stamps_reward_type, s.stamps_reward_value = 5, "percent", Decimal("20")
        for k, v in {"loyalty_enabled": "1", "referral_enabled": "1", "referral_points_inviter": "300", "referral_points_friend": "200",
                     "referral_min_order": "5000"}.items():
            db.add(Setting(key=k, value=v))
        db.add(ClientAccount(email="marta-app@test.local", first_name="Marta"))
        db.add(ClientAccount(email="otro-app@test.local", first_name="Otro"))
        db.commit()
    from app.services import platform
    platform.invalidate()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def bearer(email):
    from app.db import SessionLocal
    from app.models import ClientAccount
    from app.services import accounts
    with SessionLocal() as db:
        return {"Authorization": "Bearer " + accounts.app_token(db.query(ClientAccount).filter_by(email=email).one())}


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(out, "JPEG")
    return out.getvalue()


def delivered_order(email=None, origin="app", hours_ago=1):
    from app.db import SessionLocal
    from app.models import ClientAccount, Order, OrderEvent, OrderStatus, Store
    from app.routers.public import order_token
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        acct = db.query(ClientAccount).filter_by(email=email).one() if email else None
        o = Order(store_id=s.id, account_id=acct.id if acct else None, origin=origin, delivery_method="retiro", subtotal=Decimal("10000"),
                  shipping=0, total=Decimal("10000"), status=OrderStatus.ENTREGADO, created_at=datetime.utcnow() - timedelta(hours=hours_ago))
        db.add(o); db.flush()
        db.add(OrderEvent(order_id=o.id, status="ENTREGADO", created_at=datetime.utcnow() - timedelta(hours=hours_ago)))
        db.commit()
        return o.id, order_token(o.id)


def test_tarjeta_de_sellos_en_la_app(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.services import stamps
    c = client()
    data = c.get("/api/v1/stores/burger-mix").json()
    assert data["stamp_card"] == {"goal": 5, "reward": "20 % de descuento", "min_order": 0.0, "mine": None}
    ids = [delivered_order("marta-app@test.local")[0] for _ in range(2)]
    with SessionLocal() as db:  # Marta ya tiene dos pedidos entregados con sello
        for oid in ids:
            stamps.on_delivered(db, db.get(Order, oid))
        db.commit()
    mine = c.get("/api/v1/stores/burger-mix", headers=bearer("marta-app@test.local")).json()["stamp_card"]["mine"]
    assert mine == {"stamps": 2, "missing": 3, "rewards": 0}
    cards = c.get("/api/v1/me/stamps", headers=bearer("marta-app@test.local")).json()["cards"]
    assert len(cards) == 1 and cards[0]["store"]["slug"] == "burger-mix" and cards[0]["stamps"] == 2 and cards[0]["goal"] == 5
    assert c.get("/api/v1/me/stamps").status_code == 401


def test_invita_a_un_amigo_desde_la_app(env):
    c = client()
    assert c.get("/api/v1/me/invite").status_code == 401
    inv = c.get("/api/v1/me/invite", headers=bearer("marta-app@test.local")).json()
    assert inv["enabled"] and len(inv["code"]) == 7 and inv["link"].endswith("/invitar/" + inv["code"])
    assert inv["friend_points"] == 200 and inv["inviter_points"] == 300 and inv["friends"] == 0
    assert "200 Puntos Trappi" in inv["share_text"] and "$5.000 o más" in inv["share_text"] and inv["link"] in inv["share_text"]
    # el mismo codigo siempre
    assert c.get("/api/v1/me/invite", headers=bearer("marta-app@test.local")).json()["code"] == inv["code"]


def test_reclamo_con_foto_desde_la_app(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import OrderClaim, OrderPhoto
    from app.services import owner_alerts
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: None)
    c = client()
    oid, t = delivered_order("marta-app@test.local")
    order = c.get(f"/api/v1/orders/{oid}?t={t}").json()
    assert order["claim"]["can_claim"] and {"key": "falta", "label": "Faltó algo"} in order["claim"]["reasons"]
    # con el token pero sin la cuenta del pedido (por ejemplo el local, que tiene el link): no
    assert c.post(f"/api/v1/orders/{oid}/claim", data={"t": t, "reason": "falta"}).status_code == 403
    assert c.post(f"/api/v1/orders/{oid}/claim", data={"t": t, "reason": "falta"}, headers=bearer("otro-app@test.local")).status_code == 403
    assert c.post(f"/api/v1/orders/{oid}/claim", data={"t": "malo", "reason": "falta"}, headers=bearer("marta-app@test.local")).status_code == 404
    r = c.post(f"/api/v1/orders/{oid}/claim", data={"t": t, "reason": "inventado"}, headers=bearer("marta-app@test.local"))
    assert r.status_code == 400 and "Elegí qué pasó" in r.json()["error"]
    r = c.post(f"/api/v1/orders/{oid}/claim", data={"t": t, "reason": "falta", "text": "Faltaron las papas"},
               files={"photo": ("foto.jpg", jpeg(), "image/jpeg")}, headers=bearer("marta-app@test.local"))
    assert r.status_code == 200 and r.json()["claim"]["status"] == "abierto" and r.json()["claim"]["reason"] == "Faltó algo"
    with SessionLocal() as db:
        cl = db.query(OrderClaim).filter_by(order_id=oid).one()
        assert db.get(OrderPhoto, cl.photo_id).kind == "reclamo"
    assert c.get(f"/api/v1/orders/{oid}?t={t}").json()["claim"]["can_claim"] is False
    r = c.post(f"/api/v1/orders/{oid}/claim", data={"t": t, "reason": "frio"}, headers=bearer("marta-app@test.local"))
    assert r.status_code == 400 and "Ya nos contaste" in r.json()["error"]
    # pedido sin cuenta hecho desde la app: alcanza con el token; uno de la web, no (el link lo puede tener el local)
    oid2, t2 = delivered_order(None, origin="app")
    assert c.post(f"/api/v1/orders/{oid2}/claim", data={"t": t2, "reason": "frio"}).status_code == 200
    oid3, t3 = delivered_order(None, origin="web")
    assert c.post(f"/api/v1/orders/{oid3}/claim", data={"t": t3, "reason": "frio"}).status_code == 404
    # pasadas las 48 h no se ofrece ni se acepta
    oid4, t4 = delivered_order("marta-app@test.local", hours_ago=50)
    assert c.get(f"/api/v1/orders/{oid4}?t={t4}").json()["claim"] is None
    assert c.post(f"/api/v1/orders/{oid4}/claim", data={"t": t4, "reason": "frio"}, headers=bearer("marta-app@test.local")).status_code == 400


def test_plato_en_3d_desde_la_app(env):
    from app.db import SessionLocal
    from app.models import Product, Store
    c = client()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        p = db.query(Product).filter_by(store_id=s.id).order_by(Product.id).first()
        p.model_url = "https://res.cloudinary.com/demo/raw/upload/v1/pidomix/models/p1.glb"
        db.commit()
        pid, sid = p.id, s.id

    def path():
        menu = c.get("/api/v1/stores/burger-mix").json()["menu"]
        return {x["id"]: x["model_3d_path"] for sec in menu for x in sec["products"]}[pid]
    assert path() is None  # el local no tiene el 3D habilitado
    assert c.get(f"/plato/{pid}/3d").status_code == 404
    with SessionLocal() as db:
        db.get(Store, sid).ar_enabled = True
        db.commit()
    assert path() == f"/plato/{pid}/3d"
    page = c.get(f"/plato/{pid}/3d")
    assert page.status_code == 200 and "<model-viewer" in page.text and "p1.glb" in page.text and "Ver en tu mesa" in page.text
    assert "'wasm-unsafe-eval'" in page.headers["content-security-policy"]
    with SessionLocal() as db:
        db.get(Product, pid).model_visible = False
        db.commit()
    assert path() is None and c.get(f"/plato/{pid}/3d").status_code == 404
