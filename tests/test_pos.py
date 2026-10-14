"""Caja (punto de venta): vincular la compu, cajeros con PIN, ventas (también sin internet), QR de Puntos Trappi,
comisión configurable, cierre de caja y panel del local."""
import os
import re
import sys
import uuid
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("pos") / "pos.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import PosCashier, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email="caja@burger.test", password_hash=hash_password("Caja-1234"), store_id=s.id))
        db.add_all([PosCashier(store_id=s.id, name="Sofi", pin_hash=hash_password("1111")),
                    PosCashier(store_id=s.id, name="Dueño", pin_hash=hash_password("9999"), is_owner=True)])
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def setting(**values):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        for k, v in values.items():
            row = db.query(Setting).filter_by(key=k).first()
            v = "1" if v is True else "0" if v is False else str(v)
            if row: row.value = v
            else: db.add(Setting(key=k, value=v))
        db.commit()
    platform.invalidate()


def linked(c):
    r = c.post("/api/pos/v1/link", json={"email": "caja@burger.test", "password": "Caja-1234"})
    assert r.status_code == 200, r.text
    return r.json()


def test_caja_completa(env):
    from app.db import SessionLocal
    from app.models import LedgerEntry, PointsClaim, PosSale, Product, Store
    c = client()
    setting(pos_enabled=False)
    assert c.post("/api/pos/v1/link", json={"email": "caja@burger.test", "password": "Caja-1234"}).status_code == 403
    setting(pos_enabled=True, loyalty_enabled=True, loyalty_pesos_per_point=100, pos_commission_percent=1.5, pos_monthly_fee=5000, pos_daily_points_cap=300)
    assert c.post("/api/pos/v1/link", json={"email": "caja@burger.test", "password": "mal"}).status_code == 401
    me = linked(c)
    dev = {"Authorization": "Bearer " + me["token"]}
    assert {x["name"] for x in me["cashiers"]} == {"Sofi", "Dueño"} and me["points"]["enabled"]
    ids = {x["name"]: x["id"] for x in me["cashiers"]}
    assert c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Sofi"], "pin": "0000"}).status_code == 401
    sofi = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Sofi"], "pin": "1111"}).json()["token"]
    owner = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Dueño"], "pin": "9999"}).json()["token"]
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    p = cat["products"][0]
    assert c.post("/api/pos/v1/shifts/open", headers={**dev, "X-Cashier": sofi}, json={"amount": 20000}).json()["opening_cash"] == 20000
    # venta: el precio lo pone el menu aunque la caja mande otro; monto libre sí lo escribe el cajero
    u1 = str(uuid.uuid4())
    sale = {"client_uuid": u1, "cashier_id": ids["Sofi"], "payment_method": "efectivo", "paid_with": 100000, "sold_at": "2026-10-14T18:00:00Z",
            "items": [{"product_id": p["id"], "quantity": 2, "unit_price": 1}, {"name": "Salsa extra", "quantity": 1, "unit_price": 500}]}
    r = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [sale]}).json()["results"][0]
    expected = p["price"] * 2 + 500
    assert r["ok"] and r["total"] == expected and r["number"] == 1
    assert r["points"] == min(int(expected // 100), 300) and r["claim"]["url"].endswith("/puntos/q/" + r["claim"]["code"])
    # la misma venta subida dos veces (se cortó internet) no se duplica
    again = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [sale]}).json()["results"][0]
    assert again["id"] == r["id"]
    # otra venta: el tope diario de puntos frena (300 por día)
    r2 = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [{**sale, "client_uuid": str(uuid.uuid4()), "payment_method": "mercadopago", "paid_with": None}]}).json()["results"][0]
    assert r2["ok"] and r["points"] + r2["points"] <= 300
    # una venta inválida no frena a las demás
    bad = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [{**sale, "client_uuid": str(uuid.uuid4()), "items": [{"product_id": 999999, "quantity": 1}]},
                                                                    {**sale, "client_uuid": str(uuid.uuid4()), "payment_method": "transferencia", "paid_with": None}]}).json()["results"]
    assert not bad[0]["ok"] and bad[1]["ok"]
    with SessionLocal() as db:
        sid = db.query(Store).filter_by(slug="burger-mix").one().id
        comm = db.query(LedgerEntry).filter_by(store_id=sid, kind="pos_commission").all()
        assert len(comm) == 3 and float(comm[0].amount) == -round(expected * 0.015, 2)
        assert db.query(LedgerEntry).filter_by(store_id=sid, kind="pos_fee").count() == 1  # una vez por mes
    # el cliente escanea el QR y suma los puntos (una sola vez)
    code = r["claim"]["code"]
    w = client()
    page = w.get(f"/puntos/q/{code}").text
    assert "Ingresá para sumarlos" in page and str(r["points"]) in page
    from app.models import ClientAccount
    from app.services import accounts
    with SessionLocal() as db:
        acct = ClientAccount(email="cliente@pos.test"); db.add(acct); db.commit(); aid = acct.id
    from app.services import pos
    with SessionLocal() as db:
        pos.claim(db, code, db.get(ClientAccount, aid)); db.commit()
        from app.services import loyalty
        assert loyalty.balance(db, aid).points == r["points"]
        with pytest.raises(pos.PosError):
            pos.claim(db, code, db.get(ClientAccount, aid))
    assert "ya se sumaron" in w.get(f"/puntos/q/{code}").text
    # anular: solo el dueño; devuelve la comisión y el QR ya no sirve
    assert c.post(f"/api/pos/v1/sales/{r2['id']}/void", headers={**dev, "X-Cashier": sofi}).status_code == 403
    v = c.post(f"/api/pos/v1/sales/{r2['id']}/void", headers={**dev, "X-Cashier": owner}).json()
    assert v["voided"]
    # cierre de caja: solo el dueño, con el efectivo contado
    assert c.post("/api/pos/v1/shifts/close", headers={**dev, "X-Cashier": sofi}, json={"amount": 0}).status_code == 403
    summary = c.post("/api/pos/v1/shifts/close", headers={**dev, "X-Cashier": owner}, json={"amount": 20000 + expected - 100}).json()
    assert summary["sales"] == 2 and summary["by_method"]["efectivo"]["total"] == expected and summary["difference"] == -100
    # desvincular desde el panel: el token de la caja deja de servir
    a = client()
    assert a.post("/admin/login", data={"email": "caja@burger.test", "password": "Caja-1234"}, follow_redirects=False).status_code == 303
    page = a.get("/admin/caja").text
    assert "Descargar Trappi Caja" in page and "Sofi" in page and "1,5 %" not in page
    tok = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert "PIN de 4 a 6" in a.post("/admin/caja/cajeros", data={"name": "Mati", "pin": "12", "csrf_token": tok}).text
    a.post("/admin/caja/desvincular", data={"csrf_token": tok})
    assert c.get("/api/pos/v1/me", headers=dev).status_code == 401
    setting(pos_commission_percent=0, pos_monthly_fee=0, loyalty_enabled=False)


def test_condiciones_por_comercio(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import pos
    setting(pos_enabled=False)
    a = client()
    assert a.post("/admin/login", data=ADMIN, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        sid = db.query(Store).filter_by(slug="burger-mix").one().id
    page = a.get(f"/admin/caja?store={sid}").text
    tok = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    a.post(f"/admin/caja/plan?store={sid}", data={"enabled": "on", "percent": "2", "fee": "", "csrf_token": tok})
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert pos.available(db, s) and pos.commission(db, s) == (Decimal("2.00"), Decimal("0.00"))


def test_pagar_con_puntos_en_el_mostrador(env):
    """QR fijo del local + código de la caja: el cliente confirma, se descuentan sus puntos y la venta sale con el descuento."""
    from app.db import SessionLocal
    from app.models import ClientAccount, LedgerEntry, PointsPayment, Store
    from app.services import accounts, loyalty
    setting(pos_enabled=True, loyalty_enabled=True, loyalty_pesos_per_point=100, loyalty_point_value=1, loyalty_min_redeem=100,
            loyalty_max_percent=50, pos_points_trappi_percent=40, pos_daily_points_cap=0)
    c = client()
    me = linked(c)
    dev = {"Authorization": "Bearer " + me["token"]}
    assert me["points_pay"]["enabled"] and "/puntos/local/" in me["points_pay"]["counter_url"]
    counter = me["points_pay"]["counter_url"].rsplit("/", 1)[1]
    ids = {x["name"]: x["id"] for x in me["cashiers"]}
    sofi = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Sofi"], "pin": "1111"}).json()["token"]
    owner = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Dueño"], "pin": "9999"}).json()["token"]
    cash = {**dev, "X-Cashier": sofi}
    p = c.get("/api/pos/v1/catalog", headers=dev).json()["products"][0]
    total = p["price"] * 3
    with SessionLocal() as db:
        acct = ClientAccount(email="puntos@pos.test", first_name="Juana"); db.add(acct); db.commit(); aid = acct.id
        loyalty._add(db, aid, "adjust", 800, note="regalo"); db.commit()
        token = accounts.app_token(db.get(ClientAccount, aid))
    app_h = {"Authorization": "Bearer " + token}
    # la caja pide el pago con el total y recibe un código de 4 números
    req = c.post("/api/pos/v1/points-payments", headers=cash, json={"amount": total}).json()
    assert len(req["code"]) == 4 and req["status"] == "pending"
    # código equivocado: no encuentra nada (y cuenta como intento)
    wrong = "0000" if req["code"] != "0000" else "1111"
    assert c.post(f"/api/v1/points/counter/{counter}/quote", headers=app_h, json={"code": wrong}).status_code == 404
    # el cliente ve cuánto se descuenta antes de confirmar: tope 50 % del ticket y su saldo
    q = c.post(f"/api/v1/points/counter/{counter}/quote", headers=app_h, json={"code": req["code"]}).json()
    expected = min(800, int(total * 0.5))
    assert q["ok"] and q["points"] == expected and q["discount"] == expected and q["rest"] == total - expected
    ok = c.post(f"/api/v1/points/counter/{counter}/confirm", headers=app_h, json={"code": req["code"]}).json()
    assert ok["ok"] and ok["balance"] == 800 - expected
    # el mismo código no se puede usar dos veces
    assert c.post(f"/api/v1/points/counter/{counter}/confirm", headers=app_h, json={"code": req["code"]}).status_code == 404
    st = c.get(f"/api/pos/v1/points-payments/{req['id']}", headers=dev).json()
    assert st["status"] == "confirmed" and st["customer"] == "Juana" and st["discount"] == expected
    # si el ticket cambió, la venta no usa los puntos
    base = {"cashier_id": ids["Sofi"], "payment_method": "efectivo", "items": [{"product_id": p["id"], "quantity": 3}], "points_payment_id": req["id"]}
    bad = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [{**base, "client_uuid": str(uuid.uuid4()), "items": [{"product_id": p["id"], "quantity": 2}]}]}).json()["results"][0]
    assert not bad["ok"] and "cambió" in bad["error"]
    sale = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [{**base, "client_uuid": str(uuid.uuid4()), "paid_with": total}]}).json()["results"][0]
    assert sale["ok"] and sale["total"] == total - expected and sale["points_discount"] == expected
    with SessionLocal() as db:
        sid = db.query(Store).filter_by(slug="burger-mix").one().id
        part = db.query(LedgerEntry).filter_by(store_id=sid, kind="pos_points").one()
        assert float(part.amount) == round(expected * 0.4, 2)  # lo que pone Trappi se le acredita al local
        assert db.get(PointsPayment, req["id"]).status == "used"
    # no se puede usar el mismo pago en otra venta
    again = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [{**base, "client_uuid": str(uuid.uuid4())}]}).json()["results"][0]
    assert not again["ok"]
    # anular la venta: vuelven los puntos y se saca la parte de Trappi
    c.post(f"/api/pos/v1/sales/{sale['id']}/void", headers={**dev, "X-Cashier": owner})
    with SessionLocal() as db:
        assert loyalty.balance(db, aid).points == 800 + sale["points"] * 0  # el QR de la venta anulada no se sumó
        assert sum(float(e.amount) for e in db.query(LedgerEntry).filter_by(store_id=sid, kind="pos_points")) == 0
    # cancelar desde la caja después de confirmar: también vuelven
    req2 = c.post("/api/pos/v1/points-payments", headers=cash, json={"amount": total}).json()
    assert c.post(f"/api/v1/points/counter/{counter}/confirm", headers=app_h, json={"code": req2["code"]}).json()["ok"]
    assert c.post(f"/api/pos/v1/points-payments/{req2['id']}/cancel", headers=dev).json()["status"] == "cancelled"
    with SessionLocal() as db:
        assert loyalty.balance(db, aid).points == 800
    # la web: sin cuenta pide ingresar; con el QR de otro lado, avisa
    w = client()
    assert "Ingresá para usar tus puntos" in w.get(f"/puntos/local/{counter}").text
    assert w.get("/puntos/local/noexiste").status_code == 404
    # el panel muestra el QR para imprimir
    a = client()
    a.post("/admin/login", data={"email": "caja@burger.test", "password": "Caja-1234"})
    assert "Imprimir QR del mostrador" in a.get("/admin/caja").text
    poster = a.get("/admin/caja/qr-mostrador").text
    assert "<svg" in poster and counter in poster
    setting(loyalty_enabled=False, pos_points_trappi_percent=0)
