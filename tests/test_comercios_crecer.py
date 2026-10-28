"""Herramientas para que el comercio crezca: link para compartir, tarjeta de sellos y resumen semanal por mail."""
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-crece@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("crece") / "crece.db"
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
    return TestClient(app)


def login(who):
    c = client()
    assert c.post("/admin/login", data=who, follow_redirects=False).status_code == 303
    return c


def test_link_para_compartir_con_vista_previa(env):
    c = client()
    r = c.get("/tienda/burger-mix/compartir.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
    assert c.get("/tienda/no-existe/compartir.png").status_code == 404
    page = c.get("/tienda/burger-mix").text
    assert 'property="og:image" content="http://testserver/tienda/burger-mix/compartir.png"' in page
    assert 'name="twitter:card" content="summary_large_image"' in page and 'property="og:url" content="http://testserver/tienda/burger-mix"' in page
    home = login(OWNER).get("/admin").text
    assert "Compartí tu local" in home and "https://wa.me/?text=" in home and "/tienda/burger-mix/compartir.png" in home


def _order(db, store, acct, subtotal, status=None, coupon=None):
    from app.models import Order, OrderStatus
    o = Order(store_id=store.id, account_id=acct.id if acct else None, delivery_method="retiro", subtotal=Decimal(subtotal), shipping=0,
              total=Decimal(subtotal), status=status or OrderStatus.ENTREGADO, coupon_id=coupon.id if coupon else None, created_at=datetime.utcnow())
    db.add(o); db.flush()
    return o


def test_tarjeta_de_sellos_del_local(env):
    from app.db import SessionLocal
    from app.models import ClientAccount, Coupon, Store
    from app.services import finance, stamps
    from app.services.checkout import find_coupon, resolve_coupon
    owner = login(OWNER)
    assert "Tarjeta de sellos" in owner.get("/admin/coupons").text
    assert owner.post("/admin/coupons/sellos", data={"on": "1", "goal": "7", "reward_type": "percent", "reward_value": "20"}, follow_redirects=False).headers["location"].endswith("error=stamps")
    assert owner.post("/admin/coupons/sellos", data={"on": "1", "goal": "5", "reward_type": "percent", "reward_value": "150"}, follow_redirects=False).headers["location"].endswith("error=stamps")
    assert owner.post("/admin/coupons/sellos", data={"on": "1", "goal": "5", "reward_type": "percent", "reward_value": "20", "min_order": "5000"},
                      follow_redirects=False).headers["location"].endswith("ok=stamps")
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        marta = ClientAccount(email="marta-sellos@test.local", first_name="Marta"); otra = ClientAccount(email="otra-sellos@test.local")
        db.add_all([marta, otra]); db.flush()
        assert s.stamps_goal == 5 and stamps.info(s)["reward"] == "20 % de descuento"
        # un pedido chico no suma; el mismo pedido no suma dos veces; sin cuenta no suma
        o = _order(db, s, marta, 3000); stamps.on_delivered(db, o)
        assert stamps.progress(db, s, marta)["stamps"] == 0
        o = _order(db, s, marta, 8000); finance.on_delivered(db, o)  # el mismo camino que al entregar de verdad
        stamps.on_delivered(db, o)
        assert stamps.progress(db, s, marta)["stamps"] == 1
        assert stamps.on_delivered(db, _order(db, s, None, 8000)) is None
        prize = None
        for _ in range(4):
            prize = stamps.on_delivered(db, _order(db, s, marta, 8000)) or prize
        db.commit()
        p = stamps.progress(db, s, marta)
        assert prize is not None and p["stamps"] == 0 and len(p["rewards"]) == 1 and prize.account_id == marta.id and prize.max_uses == 1
        # el premio se aplica solo para Marta, nunca para otra cuenta (ni con el codigo)
        c, d, _, auto = resolve_coupon(db, s.id, "", Decimal("10000"), marta)
        assert c.id == prize.id and d == Decimal("2000") and auto
        c, d, _, _ = resolve_coupon(db, s.id, "", Decimal("10000"), otra)
        assert c is None or c.id != prize.id
        assert find_coupon(db, s.id, prize.code, Decimal("10000"), otra)[0] is None
        assert "premio personal" in find_coupon(db, s.id, prize.code, Decimal("10000"), otra)[1]
        # canjearlo no suma sello; si ese pedido se cancela, el premio vuelve
        from app.models import OrderStatus
        from app.services.orders import set_status
        prize.uses_count = 1
        o = _order(db, s, marta, 10000, status=OrderStatus.PENDIENTE, coupon=prize)
        db.refresh(o)
        assert stamps.on_delivered(db, o) is None and stamps.progress(db, s, marta)["stamps"] == 0
        assert set_status(o, OrderStatus.CANCELADO)
        db.commit()
        assert db.get(Coupon, prize.id).uses_count == 0
        prize_code = prize.code
    # el local no ve los premios personales entre sus cupones, pero si el resumen
    page = owner.get("/admin/coupons").text
    assert prize_code not in page and "premios ganados: <b>1</b>" in page
    assert "Juntá 5 sellos: 20 % de descuento" in client().get("/tienda/burger-mix").text
    owner.post("/admin/coupons/sellos", data={"on": "0"})
    assert "Juntá 5 sellos" not in client().get("/tienda/burger-mix").text


def test_resumen_semanal_por_mail(env):
    from app.db import SessionLocal
    from app.models import Order, OrderItem, OrderStatus, Product, Review, Store
    from app.services import email, weekly_report
    from app.services.store_hours import local_now
    outbox = []
    email.set_outbox(outbox)
    try:
        now = local_now()
        monday = (now - timedelta(days=now.weekday())).replace(hour=10, minute=0, second=0, microsecond=0)  # este lunes a las 10
        with SessionLocal() as db:
            s = db.query(Store).filter_by(slug="burger-mix").one()
            sid = s.id
            last_week = datetime.utcnow() - timedelta(days=now.weekday() + 4)  # el jueves de la semana pasada
            for total in (10000, 12000):
                o = Order(store_id=sid, delivery_method="retiro", subtotal=Decimal(total), shipping=0, total=Decimal(total), status=OrderStatus.ENTREGADO, created_at=last_week)
                db.add(o); db.flush()
                pid = db.query(Product).filter_by(name="Hamburguesa Clásica").one().id
                db.add(OrderItem(order_id=o.id, product_id=pid, product_name="Hamburguesa Clásica", quantity=2, unit_price=Decimal(total / 2)))
            db.add(Review(order_id=o.id, store_id=sid, rating=2, comment="Llegó frío", created_at=last_week))
            db.commit()
        with SessionLocal() as db:
            assert weekly_report.run(db, monday.replace(hour=8)) == 0  # antes de las 9 no sale
            assert weekly_report.run(db, monday - timedelta(days=1)) == 0  # solo los lunes
            assert weekly_report.run(db, monday) == 1
            assert weekly_report.run(db, monday) == 0  # una vez por semana
        m = outbox[-1]
        assert m["to"] == OWNER["email"] and m["subject"].startswith("Tu semana en Trappi:")
        assert "Hamburguesa Clásica (4)" in m["text"] and "1 o 2 estrellas sin responder" in m["text"] and "/resumen-semanal/baja?t=" in m["text"]
        link = m["text"].split("/resumen-semanal/baja?t=")[1].split()[0]
        assert "no va a recibir más el resumen semanal" in client().get(f"/resumen-semanal/baja?t={link}").text
        assert client().get("/resumen-semanal/baja?t=falso").status_code == 404
        with SessionLocal() as db:
            assert db.get(Store, sid).weekly_report is False
    finally:
        email.set_outbox(None)
