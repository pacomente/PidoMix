"""Para los clientes: reclamos con foto, "Invitá a un amigo" e instalar Trappi desde la web."""
import io
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-cli@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("cli") / "cli.db"
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


def guest_order(c):
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        pid = db.query(Product).filter_by(name="Hamburguesa Clásica").one().id
    c.post("/api/cart/add", json={"product_id": pid, "quantity": 1})
    r = c.post("/checkout", data={"first_name": "Ana", "last_name": "Paz", "phone": "2914001122", "delivery_method": "retiro", "payment_method": "efectivo"},
               follow_redirects=False)
    loc = r.headers["location"]
    return int(loc.split("/pedido/")[1].split("?")[0]), loc.split("t=")[1]


def deliver(oid, hours_ago=1):
    from app.db import SessionLocal
    from app.models import Order, OrderEvent, OrderStatus
    with SessionLocal() as db:
        o = db.get(Order, oid)
        o.status = OrderStatus.ENTREGADO
        db.add(OrderEvent(order_id=oid, status="ENTREGADO", created_at=datetime.utcnow() - timedelta(hours=hours_ago)))
        db.commit()


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(out, "JPEG")
    return out.getvalue()


def test_reclamo_con_foto_y_resolucion(env, monkeypatch):
    from app.services import owner_alerts
    pushed = []
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: pushed.append(data))
    c = client()
    oid, t = guest_order(c)
    assert "¿Tuviste un problema" not in c.get(f"/pedido/{oid}?t={t}").text  # todavia no se entrego
    deliver(oid)
    page = c.get(f"/pedido/{oid}?t={t}").text
    assert "¿Tuviste un problema con tu pedido?" in page
    # con el link pero desde otro navegador (por ejemplo el local) no se puede reclamar
    assert "¿Tuviste un problema" not in client().get(f"/pedido/{oid}?t={t}").text
    assert client().post(f"/pedido/{oid}/reclamo", data={"t": t, "reason": "falta"}).status_code == 404
    assert "Elegí qué pasó" in c.post(f"/pedido/{oid}/reclamo", data={"t": t, "reason": "inventado"}).text
    r = c.post(f"/pedido/{oid}/reclamo", data={"t": t, "reason": "falta", "text": "Faltaron las papas"},
               files={"photo": ("foto.jpg", jpeg(), "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 303
    assert pushed[-1]["title"] == f"⚠️ Reclamo en el pedido #{oid}"
    assert "Lo estamos revisando" in c.get(f"/pedido/{oid}?t={t}").text
    c.post(f"/pedido/{oid}/reclamo", data={"t": t, "reason": "frio"})  # uno por pedido
    from app.db import SessionLocal
    from app.models import Coupon, OrderClaim, OrderPhoto
    with SessionLocal() as db:
        claim = db.query(OrderClaim).filter_by(order_id=oid).one()
        assert claim.reason == "falta" and db.get(OrderPhoto, claim.photo_id).kind == "reclamo"
        cid, photo = claim.id, claim.photo_id
    owner = login(OWNER)
    page = owner.get("/admin/reclamos").text
    assert f"#{oid}" in page and "Faltaron las papas" in page and "Puntos Trappi" not in page  # el local no da puntos
    assert owner.get(f"/admin/orders/{oid}/photos/{photo}").status_code == 200  # el local ve la foto del reclamo
    owner.post(f"/admin/reclamos/{cid}/responder", data={"note": "Se nos pasaron, perdón"})
    assert "Elegí cómo lo resolvés" in owner.post(f"/admin/reclamos/{cid}/resolver", data={"resolution": "puntos", "points": "500", "answer": "x"}).text
    # el pedido fue sin cuenta: no se puede dar un descuento personal
    assert "pidió sin cuenta" in owner.post(f"/admin/reclamos/{cid}/resolver", data={"resolution": "cupon", "amount": "3000", "answer": "Perdón"}).text
    admin = login(ADMIN)
    assert "Puntos Trappi" in admin.get("/admin/reclamos").text and "Se nos pasaron" in admin.get("/admin/reclamos").text
    admin.post(f"/admin/reclamos/{cid}/resolver", data={"resolution": "nada", "answer": "Hablamos con el local para que no vuelva a pasar."})
    with SessionLocal() as db:
        cl = db.get(OrderClaim, cid)
        assert cl.status == "rechazado" and cl.resolved_at is not None
    assert "Hablamos con el local para que no vuelva a pasar." in c.get(f"/pedido/{oid}?t={t}").text
    # pasadas las 48 h ya no se reclama desde la web
    oid2, t2 = guest_order(c)
    deliver(oid2, hours_ago=50)
    assert "¿Tuviste un problema" not in c.get(f"/pedido/{oid2}?t={t2}").text


def test_reclamo_con_cuenta_cupon_del_local(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import ClientAccount, Coupon, Order, OrderClaim, OrderStatus, Store
    from app.services import claims, owner_alerts
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: None)
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        acct = ClientAccount(email="reclama@test.local"); db.add(acct); db.flush()
        o = Order(store_id=s.id, account_id=acct.id, delivery_method="retiro", subtotal=Decimal("10000"), shipping=0, total=Decimal("10000"),
                  status=OrderStatus.ENTREGADO, created_at=datetime.utcnow())
        db.add(o); db.flush()
        from app.models import OrderEvent
        db.add(OrderEvent(order_id=o.id, status="ENTREGADO", created_at=datetime.utcnow())); db.flush()
        cl = claims.create(db, o, "frio", "Llegó frío")
        db.commit()
        cid, aid, sid = cl.id, acct.id, s.id
    owner = login(OWNER)
    assert "no más que el total" in owner.post(f"/admin/reclamos/{cid}/resolver", data={"resolution": "cupon", "amount": "99999", "answer": "Perdón"}).text
    owner.post(f"/admin/reclamos/{cid}/resolver", data={"resolution": "cupon", "amount": "2500", "answer": "Perdón, te dejamos $2.500 para la próxima."})
    with SessionLocal() as db:
        cl = db.get(OrderClaim, cid)
        cp = db.get(Coupon, cl.coupon_id)
        assert cl.status == "resuelto" and cp.account_id == aid and cp.store_id == sid and cp.discount_value == Decimal("2500") and cp.max_uses == 1
