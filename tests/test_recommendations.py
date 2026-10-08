"""Recomendado para vos: aprende de los pedidos de cada cliente, nunca usa datos de otros y se puede apagar."""
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("reco") / "reco.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, engine
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    # un segundo local para ver que mezcla gustos y comercios
    from app.db import SessionLocal
    from app.models import Category, Product, Store, StoreStatus
    with SessionLocal() as db:
        burger = db.query(Store).filter_by(slug="burger-mix").one()
        pizzas = db.query(Category).filter_by(slug="pizzas").one()
        pz = Store(name="Pizzería La Esquina", slug="pizzeria-la-esquina", delivery_enabled=True, delivery_cost=0, minimum_order=0, estimated_minutes=35,
                   status=StoreStatus.ACTIVA, store_category_id=burger.store_category_id, city_id=burger.city_id)
        db.add(pz); db.flush()
        for name, price, prev in (("Fugazzeta", 10500, None), ("Muzzarella grande", 9800, 11500), ("Docena de empanadas", 14000, None)):
            db.add(Product(name=name, price=price, previous_price=prev, store_id=pz.id, category_id=pizzas.id))
        db.commit()
    yield
    engine.dispose()


def make_account(db, email):
    from app.models import ClientAccount
    a = ClientAccount(email=email, name=email.split("@")[0])
    db.add(a); db.flush()
    return a


def make_order(db, acct, product_names, days_ago=1, hour_utc=23, status="ENTREGADO"):
    from app.models import Order, OrderItem, OrderStatus, Product
    products = [db.query(Product).filter_by(name=n).one() for n in product_names]
    when = (datetime.utcnow() - timedelta(days=days_ago)).replace(hour=hour_utc, minute=0)
    total = sum(p.price for p in products)
    o = Order(store_id=products[0].store_id, account_id=acct.id, delivery_method="retiro", subtotal=total, shipping=Decimal("0"), total=total,
              status=OrderStatus[status], created_at=when)
    db.add(o); db.flush()
    for p in products:
        db.add(OrderItem(order_id=o.id, product_id=p.id, product_name=p.name, unit_price=p.price, quantity=1))
    db.flush()
    return o


def test_sin_cuenta_o_sin_pedidos_no_hay_recomendaciones(env):
    from app.db import SessionLocal
    from app.services import recommendations
    with SessionLocal() as db:
        assert recommendations.recommend(db, None) == []
        assert recommendations.recommend(db, make_account(db, "nueva@test.com")) == []


def test_aprende_de_sus_pedidos(env):
    from app.db import SessionLocal
    from app.models import Review
    from app.services import recommendations
    with SessionLocal() as db:
        ana = make_account(db, "ana@test.com")
        for d in (3, 10, 20):
            make_order(db, ana, ["Fugazzeta"], days_ago=d)
        picks = recommendations.recommend(db, ana)
        names = [x.product.name for x in picks]
        assert names[0] == "Fugazzeta"  # lo que más repite va primero
        assert picks[0].reason == "Lo pediste 3 veces"
        assert all(x.reason for x in picks)
        # otros productos del mismo local, con un motivo real
        assert any(x.product.name == "Muzzarella grande" and x.reason.startswith(("Porque pediste en", "Te gusta", "Lo que solés")) for x in picks)
        # un cliente nuevo no ve nada de Ana
        assert recommendations.recommend(db, make_account(db, "otro@test.com")) == []
        # los cancelados no cuentan
        beto = make_account(db, "beto@test.com")
        make_order(db, beto, ["Coca Cola"], status="CANCELADO")
        assert recommendations.recommend(db, beto) == []
        # si calificó mal al local, no se lo volvemos a ofrecer
        o = make_order(db, beto, ["Hamburguesa Clásica"])
        db.add(Review(order_id=o.id, store_id=o.store_id, rating=1))
        db.flush()
        assert all(x.product.store_id != o.store_id for x in recommendations.recommend(db, beto))
        # apagado desde la cuenta: no se calcula nada
        ana.personalize = False
        assert recommendations.recommend(db, ana) == []
        db.rollback()


def test_api_web_y_trappi_ai(env):
    from fastapi.testclient import TestClient
    from app.ai.client_tools import recomendados_para_mi
    from app.ai.tools import ToolContext
    from app.db import SessionLocal
    from app.main import app
    from app.services import accounts
    with SessionLocal() as db:
        caro = make_account(db, "caro@test.com")
        make_order(db, caro, ["Fugazzeta", "Docena de empanadas"], days_ago=2)
        make_order(db, caro, ["Fugazzeta"], days_ago=9)
        db.commit()
        token, cid = accounts.app_token(caro), caro.id
    c = TestClient(app)
    assert c.get("/api/v1/recommendations").json() == {"enabled": False, "title": "Recomendado para vos", "items": []}
    auth = {"Authorization": f"Bearer {token}"}
    r = c.get("/api/v1/recommendations", headers=auth).json()
    assert r["enabled"] and r["items"][0]["name"] == "Fugazzeta" and r["items"][0]["reason"] == "Lo pediste 2 veces"
    assert r["items"][0]["store"]["slug"] == "pizzeria-la-esquina"
    # se apaga y se prende desde la app
    assert c.put("/api/v1/me", json={"personalize": False}, headers=auth).json()["account"]["personalize"] is False
    assert c.get("/api/v1/recommendations", headers=auth).json() == {"enabled": False, "title": "Recomendado para vos", "items": []}
    assert c.put("/api/v1/me", json={"personalize": True}, headers=auth).json()["account"]["personalize"] is True
    # Trappi AI usa el mismo motor y devuelve el motivo
    with SessionLocal() as db:
        from app.models import ClientAccount
        ctx = ToolContext(db=db, account=db.get(ClientAccount, cid))
        out = recomendados_para_mi(ctx, limite=3)
        assert out["productos"][0]["nombre"] == "Fugazzeta" and out["productos"][0]["motivo"] == "Lo pediste 2 veces"
        assert ctx.cards and ctx.cards[0]["type"] == "product"
    # web: sin sesion no hay seccion
    assert "Recomendado para vos" not in c.get("/").text


def test_web_inicio_y_cuenta(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import ClientAccount
    from app.services import accounts
    with SessionLocal() as db:
        acct = db.query(ClientAccount).filter_by(email="caro@test.com").one()
        db.expunge(acct)
    monkeypatch.setattr(accounts, "from_session", lambda request, db: db.get(ClientAccount, acct.id))
    c = TestClient(app)
    home = c.get("/").text
    assert "Recomendado para vos" in home and "Lo pediste 2 veces" in home and 'class="why"' in home
    page = c.get("/cuenta").text
    assert 'action="/cuenta/recomendaciones"' in page and "Apagar recomendaciones" in page
    r = c.post("/cuenta/recomendaciones", data={"personalize": "0"}, follow_redirects=False)
    assert r.status_code == 303
    assert "Recomendado para vos" not in c.get("/").text and "Prender recomendaciones" in c.get("/cuenta").text
    c.post("/cuenta/recomendaciones", data={"personalize": "1"}, follow_redirects=False)
    assert "Recomendado para vos" in c.get("/").text
    assert "Recomendado para vos" in c.get("/privacidad").text
