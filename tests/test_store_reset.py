"""Reiniciar un comercio (solo superadmin) y eliminar productos (el propio local)."""
import os
import sys
from decimal import Decimal

import pytest

NEAR = (-38.7200, -62.2700)
ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("reset") / "reset.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, engine
    from app.services import platform
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    platform.invalidate()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def login(email, password):
    c = client()
    assert c.post("/admin/login", data={"email": email, "password": password}, follow_redirects=False).status_code == 303
    return c


def owner_of(slug, email):
    from app.db import SessionLocal
    from app.models import Store, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug=slug).one()
        if not db.query(User).filter_by(email=email).first():
            db.add(User(email=email, password_hash=hash_password("Dueno-1234"), store_id=s.id)); db.commit()
        return s.id, login(email, "Dueno-1234")


def place_order(product_id):
    r = client().post("/api/v1/orders", json={"items": [{"product_id": product_id, "quantity": 1}], "delivery_method": "retiro",
                                              "first_name": "Ana", "phone": "2914000000"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def other_store():
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="otro-local").first()
        if not s:
            s = Store(name="Otro Local", slug="otro-local"); db.add(s); db.commit()
        return s.id


def test_el_local_elimina_sus_productos(env):
    from app.db import SessionLocal
    from app.models import Product, Store
    sid, owner = owner_of("burger-mix", "dueno@burger.test")
    with SessionLocal() as db:
        fresh = Product(store_id=sid, name="Nunca vendido", price=Decimal("100")); sold = Product(store_id=sid, name="Ya vendido", price=Decimal("200"))
        foreign = Product(store_id=other_store(), name="De otro", price=Decimal("300"))
        db.add_all([fresh, sold, foreign]); db.commit()
        fresh_id, sold_id, foreign_id = fresh.id, sold.id, foreign.id
    oid = place_order(sold_id)
    # nunca vendido: se borra del todo
    r = owner.post(f"/admin/products/{fresh_id}/delete", follow_redirects=False)
    assert r.headers["location"] == "/admin/products?ok=product_deleted"
    # vendido: queda oculto para los pedidos viejos
    owner.post(f"/admin/products/{sold_id}/delete")
    # de otro local: no lo puede tocar
    owner.post(f"/admin/products/{foreign_id}/delete")
    with SessionLocal() as db:
        assert db.get(Product, fresh_id) is None
        p = db.get(Product, sold_id)
        assert p.deleted and p.status.value == "INACTIVO"
        assert not db.get(Product, foreign_id).deleted
    page = owner.get("/admin/products").text
    assert "Ya vendido" not in page and "Nunca vendido" not in page
    assert "Ya vendido" not in client().get("/tienda/burger-mix").text
    # el pedido viejo lo sigue mostrando
    assert "Ya vendido" in owner.get(f"/admin/orders/{oid}").text
    # editar o reactivar un eliminado no hace nada
    owner.post(f"/admin/products/{sold_id}/toggle")
    with SessionLocal() as db:
        assert db.get(Product, sold_id).status.value == "INACTIVO"


def test_reiniciar_comercio_borra_ventas_y_comisiones(env):
    from app.db import SessionLocal
    from app.models import (AuditLog, Courier, Coupon, LedgerEntry, MerchantSettlement, Order, OrderStatus, Payment, Product, Review,
                            Store, SubscriptionPayment)
    from app.services import finance
    sid, owner = owner_of("burger-mix", "dueno@burger.test")
    with SessionLocal() as db:
        s = db.get(Store, sid)
        product = db.query(Product).filter_by(store_id=sid, deleted=False).first().id
        other = db.query(Product).filter_by(name="De otro").one().store_id
    o1, o2 = place_order(product), place_order(product)
    with SessionLocal() as db:
        first = db.get(Order, o1)
        copy = Order(store_id=other, total=Decimal("100"), subtotal=Decimal("100"), shipping=Decimal("0"), status=OrderStatus.ENTREGADO,
                     **{k: getattr(first, k) for k in ("delivery_method", "payment_method") if hasattr(first, k)})
        db.add(copy); db.commit()
        keep = copy.id
    with SessionLocal() as db:
        courier = Courier(name="Flota Uno", phone="2917999001", pin_hash="x"); db.add(courier); db.flush()
        for o in db.query(Order).filter_by(store_id=sid):
            o.status = OrderStatus.ENTREGADO
        db.add(Review(order_id=o1, store_id=sid, rating=5, comment="Muy rico"))
        db.add(Payment(order_id=o2, amount=Decimal("1000"), status="approved"))
        db.add(SubscriptionPayment(store_id=sid, period="2026-09", amount=Decimal("5000"), status="pagado"))
        db.add(Coupon(store_id=sid, code="RESET10", discount_value=Decimal("10"), uses_count=7))
        s = db.get(Store, sid); s.rating_avg, s.rating_count = Decimal("5"), 1
        finance.entry(db, "merchant", "commission_due", -500, store_id=sid, order_id=o1)
        finance.entry(db, "merchant", "cash_sale", 300, store_id=sid, order_id=o2)
        finance.entry(db, "merchant", "commission_due", -100, store_id=other, order_id=keep)
        finance.entry(db, "courier_cash", "cash_collected", 1750, courier_id=courier.id, order_id=o2, description="Efectivo")
        finance.entry(db, "courier_earnings", "trip", 900, courier_id=courier.id, order_id=o2)
        db.commit()
        courier_id = courier.id
        finance.create_merchant_settlement(db, sid); db.commit()
        cash_before = finance.courier_cash_pending(db, courier_id)

    # el comercio no se puede reiniciar solo
    assert owner.post(f"/admin/comercios/{sid}/reiniciar", data={"confirm_name": "Burger Mix"}, follow_redirects=False).headers["location"] == "/admin/mi-plan"
    a = login(**ADMIN)
    page = a.get(f"/admin/comercios/{sid}/reiniciar").text
    assert "No se puede deshacer" in page and "saldo con Trappi" in page and "sin rendir" in page
    # nombre equivocado: no borra nada
    a.post(f"/admin/comercios/{sid}/reiniciar", data={"confirm_name": "otro"})
    with SessionLocal() as db:
        assert db.query(Order).filter_by(store_id=sid).count() >= 2
    with SessionLocal() as db:
        name = db.get(Store, sid).name
    r = a.post(f"/admin/comercios/{sid}/reiniciar", data={"confirm_name": f"  {name.upper()} ", "reason": "datos de prueba"}, follow_redirects=False)
    assert r.headers["location"] == f"/admin/comercios/{sid}"
    with SessionLocal() as db:
        assert db.query(Order).filter_by(store_id=sid).count() == 0
        assert db.query(Review).filter_by(store_id=sid).count() == 0
        assert db.query(Payment).filter(Payment.order_id.in_([o1, o2])).count() == 0
        assert db.query(LedgerEntry).filter_by(account="merchant", store_id=sid).count() == 0
        assert db.query(MerchantSettlement).filter_by(store_id=sid).count() == 0
        assert db.query(SubscriptionPayment).filter_by(store_id=sid).count() == 1  # sin marcar, los abonos quedan
        s = db.get(Store, sid)
        assert s.rating_count == 0 and s.rating_avg == 0
        assert db.query(Coupon).filter_by(code="RESET10").one().uses_count == 0
        assert db.query(Product).filter_by(name="Ya vendido").count() == 0  # el eliminado ya no tiene pedidos
        assert db.query(Product).filter_by(store_id=sid, deleted=False).count() > 0
        # la plata del cadete sigue igual
        assert finance.courier_cash_pending(db, courier_id) == cash_before
        moved = db.query(LedgerEntry).filter_by(courier_id=courier_id, kind="trip").filter(LedgerEntry.description.like(f"#{o2} %")).one()
        assert moved.order_id is None and moved.amount == Decimal("900")
        # el otro comercio no se toca
        assert db.get(Order, keep) is not None
        assert db.query(LedgerEntry).filter_by(account="merchant", store_id=other).count() == 1
        log = db.query(AuditLog).filter_by(action="store.reset", entity_id=str(sid)).one()
        assert log.reason == "datos de prueba" and log.user_id is not None
    assert finance_balance_zero(sid)
    # reiniciar de nuevo, ahora con los abonos
    a.post(f"/admin/comercios/{sid}/reiniciar", data={"confirm_name": name, "subscriptions": "1"})
    with SessionLocal() as db:
        assert db.query(SubscriptionPayment).filter_by(store_id=sid).count() == 0


def finance_balance_zero(sid):
    from app.db import SessionLocal
    from app.services import finance
    with SessionLocal() as db:
        b = finance.merchant_balance(db, sid)
        return b["pending"] == 0 and b["in_settlement"] == 0 and b["paid_to_trappi"] == 0


def test_no_se_reinicia_con_pedidos_en_curso(env):
    from app.db import SessionLocal
    from app.models import Order, Product, Store
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        sid, name = s.id, s.name
        product = db.query(Product).filter_by(store_id=sid, deleted=False).first().id
    oid = place_order(product)
    a = login(**ADMIN)
    assert "pedidos en curso" in a.get(f"/admin/comercios/{sid}/reiniciar").text
    a.post(f"/admin/comercios/{sid}/reiniciar", data={"confirm_name": name})
    with SessionLocal() as db:
        assert db.get(Order, oid) is not None
