"""Niveles de cliente (Bronce, Plata y Oro) arriba de los Puntos Trappi y el regalo de cumpleaños."""
import os
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("tiers") / "tiers.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ClientAccount, Setting
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        for k, v in {"loyalty_enabled": "1", "loyalty_pesos_per_point": "100", "loyalty_tier_silver_orders": "3", "loyalty_tier_gold_orders": "6",
                     "loyalty_tier_silver_bonus": "25", "loyalty_tier_gold_bonus": "50", "loyalty_birthday_points": "300"}.items():
            db.add(Setting(key=k, value=v))
        for e in ("lu@test.local", "nuevo@test.local", "web@test.local"):
            db.add(ClientAccount(email=e, first_name=e.split("@")[0].capitalize()))
        db.commit()
    from app.services import platform
    platform.invalidate()
    yield
    engine.dispose()


def account(email):
    from app.db import SessionLocal
    from app.models import ClientAccount
    with SessionLocal() as db:
        return db.query(ClientAccount).filter_by(email=email).one().id


def deliver(account_id, n=1, subtotal="10000", days_ago=1):
    """n pedidos entregados con la cuenta (suman puntos como en la vida real: con loyalty.on_delivered)."""
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Store
    from app.services import loyalty
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        ids = []
        for _ in range(n):
            o = Order(store_id=s.id, account_id=account_id, delivery_method="retiro", subtotal=Decimal(subtotal), shipping=0, total=Decimal(subtotal),
                      status=OrderStatus.ENTREGADO, created_at=datetime.utcnow() - timedelta(days=days_ago))
            db.add(o); db.flush()
            loyalty.on_delivered(db, o)
            ids.append(o.id)
        db.commit()
        return ids


def earned(order_id):
    from app.db import SessionLocal
    from app.models import LoyaltyEntry
    with SessionLocal() as db:
        return db.query(LoyaltyEntry).filter_by(dedupe_key=f"earn:{order_id}").one()


def bearer(email):
    from app.db import SessionLocal
    from app.models import ClientAccount
    from app.services import accounts
    with SessionLocal() as db:
        return {"Authorization": "Bearer " + accounts.app_token(db.query(ClientAccount).filter_by(email=email).one())}


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_niveles_y_puntos_extra(env):
    from app.db import SessionLocal
    from app.models import ClientAccount
    from app.services import loyalty
    aid = account("lu@test.local")
    # Bronce: puntos normales (10.000 / 100 = 100)
    first = deliver(aid, 3)
    assert [earned(i).points for i in first] == [100, 100, 100]
    with SessionLocal() as db:
        t = loyalty.tier_info(db, db.get(ClientAccount, aid))
        assert t["key"] == "plata" and t["orders"] == 3 and t["bonus"] == 25 and t["next"]["key"] == "oro" and t["next"]["missing"] == 3
    # el 4° pedido ya es de Plata: +25 %
    e = earned(deliver(aid)[0])
    assert e.points == 125 and "nivel Plata +25 %" in e.note
    deliver(aid, 2)  # 6 pedidos: Oro
    e = earned(deliver(aid)[0])
    assert e.points == 150 and "nivel Oro +50 %" in e.note
    with SessionLocal() as db:
        t = loyalty.tier_info(db, db.get(ClientAccount, aid))
        assert t["key"] == "oro" and t["next"] is None
    # los pedidos de hace más de un año no cuentan para el nivel
    viejo = account("nuevo@test.local")
    deliver(viejo, 5, days_ago=400)
    with SessionLocal() as db:
        assert loyalty.tier_info(db, db.get(ClientAccount, viejo))["key"] == "bronce"


def test_cumpleanos_una_vez_y_con_espera(env):
    from app.db import SessionLocal
    from app.models import ClientAccount, LoyaltyEntry
    from app.services import loyalty
    from app.services.store_hours import to_local
    aid = account("nuevo@test.local")
    now = datetime.utcnow()
    month = to_local(now).month
    with SessionLocal() as db:
        a = db.get(ClientAccount, aid)
        assert loyalty.set_birthday(a, 31, 2) == "Esa fecha no existe."
        assert loyalty.set_birthday(a, 29, 2) is None  # bisiesto: vale
        assert "ya está cargado" in loyalty.set_birthday(a, 10, month)
        a.birth_day, a.birth_month, a.birth_set_at = 10, month, now  # recién cargado en su mes: todavía no hay regalo
        assert loyalty.birthday_gift(db, a) == 0
        a.birth_set_at = now - timedelta(days=40)
        assert loyalty.birthday_gift(db, a) == 300  # Bronce
        assert loyalty.birthday_gift(db, a) == 0  # una vez por año
        db.commit()
        assert db.query(LoyaltyEntry).filter_by(account_id=aid, kind="gift").count() == 1
        # otro mes: nada
        b = db.get(ClientAccount, account("web@test.local"))
        b.birth_day, b.birth_month, b.birth_set_at = 5, (month % 12) + 1, now - timedelta(days=90)
        assert loyalty.birthday_gift(db, b) == 0
    # Oro: el regalo lleva su extra (+50 %)
    oro = account("lu@test.local")
    with SessionLocal() as db:
        a = db.get(ClientAccount, oro)
        a.birth_day, a.birth_month, a.birth_set_at = 1, month, now - timedelta(days=60)
        assert loyalty.birthday_gift(db, a) == 450
        db.commit()


def test_cuenta_web_y_app(env, monkeypatch):
    from app.services import email
    outbox = []
    email.set_outbox(outbox)
    c = client()
    c.get("/ingresar?next=/")
    c.post("/ingresar/email", data={"email": "web@test.local", "next": "/"}, follow_redirects=False)
    code = re.search(r"\b(\d{6})\b", outbox[-1]["text"]).group(1)
    assert c.post("/ingresar/codigo", data={"code": code}, follow_redirects=False).status_code == 303
    page = c.get("/cuenta").text
    assert "Tu nivel" in page and "Bronce" in page and "para 🥈 Plata" in page
    # ya tiene cumpleaños (lo cargó el test anterior): no se puede cambiar
    from app.db import SessionLocal
    from app.models import ClientAccount
    with SessionLocal() as db:
        a = db.get(ClientAccount, account("web@test.local"))
        a.birth_day = a.birth_month = a.birth_set_at = None
        db.commit()
    assert "¿Cuándo es tu cumpleaños?" in c.get("/cuenta").text
    token = c.get("/cuenta").text.split('name="csrf_token" value="')[1].split('"')[0]
    c.post("/cuenta/cumple", data={"csrf_token": token, "day": "14", "month": "7"})
    page = c.get("/cuenta").text
    assert "14 de julio" in page and "¿Cuándo es tu cumpleaños?" not in page
    c.post("/cuenta/cumple", data={"csrf_token": token, "day": "1", "month": "1"}, follow_redirects=False)
    assert "ya está cargado" in c.get("/cuenta").text and "14 de julio" in c.get("/cuenta").text

    # la app
    api = client()
    h = bearer("lu@test.local")
    pts = api.get("/api/v1/me/points", headers=h).json()
    assert pts["tier"]["key"] == "oro" and pts["tier"]["bonus"] == 50 and pts["birthday"]["day"] == 1
    assert api.post("/api/v1/me/birthday", headers=h, json={"day": 3, "month": 3}).status_code == 400  # ya tenía
    h2 = bearer("nuevo@test.local")
    with SessionLocal() as db:
        a = db.get(ClientAccount, account("nuevo@test.local"))
        a.birth_day = a.birth_month = a.birth_set_at = None
        db.commit()
    r = api.post("/api/v1/me/birthday", headers=h2, json={"day": 3, "month": 3})
    assert r.status_code == 200 and r.json()["birthday"] == {"day": 3, "month": 3}


def test_trappi_corrige_el_cumple(env):
    from app.db import SessionLocal
    from app.models import AuditLog, ClientAccount
    aid = account("web@test.local")
    admin = client()
    assert admin.post("/admin/login", data=ADMIN, follow_redirects=False).status_code == 303
    page = admin.get(f"/admin/customers/accounts/{aid}").text
    assert "Nivel <b>Bronce</b>" in page and "Corregir cumpleaños" in page
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    admin.post(f"/admin/customers/accounts/{aid}/cumple", data={"csrf_token": token, "day": "15", "month": "7", "reason": ""})
    with SessionLocal() as db:
        assert db.get(ClientAccount, aid).birth_day == 14  # sin motivo no cambia
    admin.post(f"/admin/customers/accounts/{aid}/cumple", data={"csrf_token": token, "day": "15", "month": "7", "reason": "Lo cargó mal"})
    with SessionLocal() as db:
        a = db.get(ClientAccount, aid)
        assert (a.birth_day, a.birth_month) == (15, 7) and a.birth_set_at is not None
        assert db.query(AuditLog).filter_by(action="client.birthday").count() == 1
