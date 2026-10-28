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


def _login_client(c, email_addr, outbox):
    import re
    c.get("/ingresar?next=/")
    c.post("/ingresar/email", data={"email": email_addr, "next": "/"}, follow_redirects=False)
    code = re.search(r"\b(\d{6})\b", outbox[-1]["text"]).group(1)
    assert c.post("/ingresar/codigo", data={"code": code}, follow_redirects=False).status_code == 303


def test_invita_a_un_amigo(env):
    from app.db import SessionLocal
    from app.models import ClientAccount, LoyaltyEntry, Order, OrderStatus, Setting, Store
    from app.services import email, finance, platform, referrals
    outbox = []
    email.set_outbox(outbox)
    try:
        with SessionLocal() as db:
            for k, v in {"loyalty_enabled": "1", "referral_enabled": "1", "referral_points_inviter": "300", "referral_points_friend": "200",
                         "referral_min_order": "5000", "referral_monthly_cap": "1"}.items():
                db.add(Setting(key=k, value=v))
            db.commit()
        platform.invalidate()
        ana = client()
        _login_client(ana, "ana-invita@test.local", outbox)
        page = ana.get("/cuenta").text
        assert "Invitá a un amigo" in page and "/invitar/" in page
        link = "/invitar/" + page.split("/invitar/")[1].split('"')[0]
        assert ana.get(link, follow_redirects=False).status_code == 303  # con cuenta no se usa
        # un amigo nuevo entra desde el link y crea su cuenta
        bea = client()
        assert "te invitó a Trappi" in bea.get(link).text and "200 Puntos Trappi" in bea.get(link).text
        _login_client(bea, "bea-amiga@test.local", outbox)
        # alguien que ya tenia cuenta no queda como invitado
        old = client()
        _login_client(old, "vieja@test.local", outbox)
        old2 = client(); old2.get(link)
        _login_client(old2, "vieja@test.local", outbox)
        assert client().get("/invitar/NOEXISTE", follow_redirects=False).status_code == 303
        with SessionLocal() as db:
            a = db.query(ClientAccount).filter_by(email="ana-invita@test.local").one()
            b = db.query(ClientAccount).filter_by(email="bea-amiga@test.local").one()
            v = db.query(ClientAccount).filter_by(email="vieja@test.local").one()
            assert b.referred_by_id == a.id and v.referred_by_id is None
            s = db.query(Store).filter_by(slug="burger-mix").one()

            def deliver_order(acct, subtotal):
                o = Order(store_id=s.id, account_id=acct.id, delivery_method="retiro", subtotal=Decimal(subtotal), shipping=0, total=Decimal(subtotal),
                          status=OrderStatus.ENTREGADO, created_at=datetime.utcnow())
                db.add(o); db.flush()
                referrals.on_delivered(db, o)
                return o
            deliver_order(b, 3000)  # chico: todavia no cuenta
            assert b.referral_rewarded_at is None
            deliver_order(b, 8000)
            deliver_order(b, 8000)  # una sola vez
            db.commit()
            pts = lambda acct: sum(e.points for e in db.query(LoyaltyEntry).filter_by(account_id=acct.id, kind="referral"))
            assert pts(b) == 200 and pts(a) == 300
            # el tope del mes: el segundo amigo cobra, quien invita no
            c2 = ClientAccount(email="caro@test.local", referred_by_id=a.id); db.add(c2); db.flush()
            deliver_order(c2, 9000); db.commit()
            assert pts(c2) == 200 and pts(a) == 300
        assert "1 amigo ya pidió" in ana.get("/cuenta").text or "amigos ya pidieron" in ana.get("/cuenta").text
    finally:
        email.set_outbox(None)
