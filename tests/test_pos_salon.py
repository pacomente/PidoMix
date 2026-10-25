"""Caja 1.3: promos del mostrador, propina, cuenta dividida, mesas (comandas por tanda), llamador, cliente frecuente,
agotar desde la caja y resumen del día."""
import os
import sys
import uuid
from datetime import datetime

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("salon") / "salon.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ClientAccount, PosCashier, Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email="dueno@test.local", password_hash=hash_password("Dueno-1234"), role=Role.STORE_ADMIN, store_id=s.id, active=True))
        db.add_all([PosCashier(store_id=s.id, name="Sofi", pin_hash=hash_password("1111")),
                    PosCashier(store_id=s.id, name="Dueño", pin_hash=hash_password("9999"), is_owner=True)])
        db.add(ClientAccount(email="marta@test.local", first_name="Marta", last_name="Gómez", phone="+54 9 291 455-6677"))
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


def panel():
    c = client()
    assert c.post("/admin/login", data={"email": "dueno@test.local", "password": "Dueno-1234"}, follow_redirects=False).status_code == 303
    return c


def caja(c):
    setting(pos_enabled=True, pos_commission_percent=0, pos_monthly_fee=0)
    me = c.post("/api/pos/v1/link", json={"email": "dueno@test.local", "password": "Dueno-1234"}).json()
    dev = {"Authorization": "Bearer " + me["token"]}
    ids = {x["name"]: x["id"] for x in me["cashiers"]}
    sofi = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Sofi"], "pin": "1111"}).json()["token"]
    owner = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Dueño"], "pin": "9999"}).json()["token"]
    if not c.get("/api/pos/v1/shifts/current", headers=dev).json()["shift"]:
        c.post("/api/pos/v1/shifts/open", headers={**dev, "X-Cashier": sofi}, json={"amount": 10000})
    return dev, sofi, owner, ids


def sale(c, dev, cid, items, **extra):
    d = {"client_uuid": str(uuid.uuid4()), "cashier_id": cid, "items": items, "payment_method": "efectivo",
         "sold_at": datetime.utcnow().isoformat() + "Z", **extra}
    return c.post("/api/pos/v1/sales", headers=dev, json={"sales": [d]}).json()["results"][0]


def test_motor_de_promos():
    from decimal import Decimal
    from app.services.pos_salon import apply_promos, is_on
    monday_19 = datetime(2026, 10, 26, 19, 30)
    two4one = {"id": 1, "name": "2x1 cervezas", "kind": "nxm", "buy": 2, "pay": 1, "value": 0, "product_ids": [10], "section_ids": [], "days": "0123456", "start": "18:00", "end": "21:00"}
    combo = {"id": 2, "name": "Combo", "kind": "combo", "buy": 2, "pay": 1, "value": 12000, "product_ids": [1, 2, 3], "section_ids": [], "days": "0123456", "start": None, "end": None}
    pct = {"id": 3, "name": "20% pizzas", "kind": "percent", "buy": 2, "pay": 1, "value": 20, "product_ids": [], "section_ids": [7], "days": "1", "start": None, "end": None}
    lines = [{"product_id": 10, "section_id": None, "quantity": 3, "unit": 3500, "base": 3500},
             {"product_id": 1, "section_id": 1, "quantity": 2, "unit": 9800, "base": 9000},  # con opciones: el combo descuenta sobre el precio base
             {"product_id": 2, "section_id": 1, "quantity": 1, "unit": 3000, "base": 3000},
             {"product_id": 3, "section_id": 1, "quantity": 1, "unit": 2500, "base": 2500},
             {"product_id": 20, "section_id": 7, "quantity": 1, "unit": 11000, "base": 11000}]
    total, applied = apply_promos([two4one, combo, pct], lines, monday_19)
    got = {a["id"]: a["amount"] for a in applied}
    assert got == {1: 3500.0, 2: 2500.0}  # 3 cervezas: una gratis; un combo (9000+3000+2500-12000); el % es solo los martes
    assert total == Decimal("6000.00")
    tuesday = datetime(2026, 10, 27, 22, 0)
    total, applied = apply_promos([two4one, combo, pct], lines, tuesday)  # fuera del happy hour; martes: 20% en pizzas
    assert {a["id"]: a["amount"] for a in applied} == {2: 2500.0, 3: 2200.0}
    overnight = {**two4one, "start": "22:00", "end": "02:00"}
    assert is_on(overnight, datetime(2026, 10, 26, 1, 0)) and not is_on(overnight, datetime(2026, 10, 26, 12, 0))


def test_funciones_apagadas_hasta_que_trappi_las_habilita(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import pos_salon
    c = client()
    dev, sofi, owner, ids = caja(c)
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        sid, code = s.id, pos_salon.screen_code(db, s, new=True)
        db.commit()
    me = c.get("/api/pos/v1/me", headers=dev).json()
    assert not any(me["features"].values())  # todo arranca apagado
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    assert cat.get("tables", []) == [] and cat.get("promos", []) == []
    pid = cat["products"][0]["id"]
    assert c.post(f"/api/pos/v1/products/{pid}/stock", headers={**dev, "X-Cashier": sofi}, json={"action": "out"}).status_code == 403
    assert c.get("/api/pos/v1/customers?phone=2914556677", headers={**dev, "X-Cashier": sofi}).status_code == 403
    assert c.get("/api/pos/v1/reports/today", headers={**dev, "X-Cashier": owner}).status_code == 403
    assert c.get(f"/llamador/{code}").status_code == 404
    # el dueño no se las puede prender solo
    p = panel()
    p.post(f"/admin/caja/funciones?store={sid}", data={"f_tables": "1"}, follow_redirects=False)
    assert not any(c.get("/api/pos/v1/me", headers=dev).json()["features"].values())
    # el superadmin sí, comercio por comercio
    a = client()
    assert a.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False).status_code == 303
    assert "Funciones de la caja" in a.get(f"/admin/caja?store={sid}").text
    r = a.post(f"/admin/caja/funciones?store={sid}", data={"f_tables": "1", "f_report": "on"}, follow_redirects=False)
    assert r.status_code == 303 and "features" in r.headers["location"]
    f = c.get("/api/pos/v1/me", headers=dev).json()["features"]
    assert f["tables"] and f["report"] and not f["stock"]
    assert c.get("/api/pos/v1/reports/today", headers={**dev, "X-Cashier": owner}).status_code == 200
    a.post(f"/admin/caja/funciones?store={sid}", data={f"f_{k}": "1" for k in pos_salon.FEATURES}, follow_redirects=False)
    assert all(c.get("/api/pos/v1/me", headers=dev).json()["features"].values())
    assert c.get(f"/llamador/{code}").status_code == 200


def test_promo_propina_cliente_y_cuenta_dividida(env):
    from app.db import SessionLocal
    from app.models import LoyaltyEntry, PosPromo, PosSale, Product, Store
    c = client()
    dev, sofi, owner, ids = caja(c)
    setting(loyalty_enabled=True, loyalty_pesos_per_point=100, pos_daily_points_cap=0)
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        p = db.query(Product).filter_by(store_id=s.id, name="Coca Cola").first() or db.query(Product).filter_by(store_id=s.id).first()
        pid, price = p.id, float(p.price)
        db.add(PosPromo(store_id=s.id, name="2x1 de la casa", kind="nxm", buy=2, pay=1, product_ids=f"[{pid}]"))
        db.commit()
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    assert any(x["name"] == "2x1 de la casa" for x in cat["promos"])
    # cliente frecuente por teléfono (con o sin 9, espacios o guiones)
    r = c.get("/api/pos/v1/customers", params={"phone": "291 4556677"}, headers={**dev, "X-Cashier": sofi}).json()
    assert r["ok"] and r["customer"]["name"] == "Marta G." and r["customer"]["purchases"] == 0
    assert c.get("/api/pos/v1/customers", params={"phone": "1111"}, headers={**dev, "X-Cashier": sofi}).status_code == 400
    assert c.get("/api/pos/v1/customers", params={"phone": "2915550000"}, headers={**dev, "X-Cashier": sofi}).status_code == 404
    acct = r["customer"]["id"]
    # 2 unidades con 2x1, propina en efectivo, puntos directo a la cuenta
    r = sale(c, dev, ids["Sofi"], [{"product_id": pid, "quantity": 2}], tip=500, account_id=acct, paid_with=price + 500)
    assert r["ok"], r
    assert r["promo_discount"] == price and r["total"] == price and r["tip"] == 500 and r["promos"][0]["name"] == "2x1 de la casa"
    assert r["claim"] and r["claim"]["claimed"]  # sin escanear el QR
    with SessionLocal() as db:
        assert db.query(LoyaltyEntry).filter_by(account_id=acct, kind="earn").count() == 1
    shift = c.get("/api/pos/v1/shifts/current", headers=dev).json()["shift"]
    assert shift["tips"] >= 500 and shift["tips_cash"] >= 500 and shift["promos"] >= price
    again = c.get("/api/pos/v1/customers", params={"phone": "2914556677"}, headers={**dev, "X-Cashier": sofi}).json()["customer"]
    assert again["purchases"] == 1 and again["last_items"][0]["product_id"] == pid
    # cuenta dividida en partes iguales: el mismo medio se repite
    r = sale(c, dev, ids["Sofi"], [{"product_id": pid, "quantity": 1}], payment_method="mixto", table_name="Mesa 8",
             payments=[{"method": "efectivo", "amount": price / 2}, {"method": "efectivo", "amount": price / 2}])
    assert r["ok"] and len(r["payments"]) == 2 and r["table_name"] == "Mesa 8"


def test_mesas_comandas_y_llamador(env):
    c = client()
    dev, sofi, owner, ids = caja(c)
    p = panel()
    # el plano se arma en el panel
    assert p.post("/admin/caja/mesas", data={"from": "1", "to": "8", "area": "Salón", "seats": "4", "shape": "square"}, follow_redirects=False).status_code == 303
    assert p.post("/admin/caja/mesas", data={"name": "Barra 1", "area": "Barra", "seats": "1", "shape": "round"}, follow_redirects=False).status_code == 303
    tables = c.get("/api/pos/v1/catalog", headers=dev).json()["tables"]
    assert len(tables) == 9 and {t["area"] for t in tables} == {"Salón", "Barra"}
    salon = [(t["col"], t["row"]) for t in tables if t["area"] == "Salón"]
    assert len(set(salon)) == 8 and (6, 0) not in salon and (0, 1) in salon  # cada una en su lugar, de a 6 por fila
    page = p.get("/admin/caja/salon").text
    assert "Mesas del salón" in page and "Barra 1" in page
    # una tanda de la mesa va a la cocina (también si llega dos veces)
    t = {"client_uuid": str(uuid.uuid4()), "label": "Mesa 3 · Lucas", "cashier_id": ids["Sofi"], "sent_at": datetime.utcnow().isoformat() + "Z",
         "items": [{"name": "Hamburguesa Clásica", "quantity": 2, "modifiers_text": "Jugosa", "note": "sin cebolla"}]}
    for _ in range(2):
        r = c.post("/api/pos/v1/kitchen-tickets", headers=dev, json={"tickets": [t]}).json()["results"][0]
        assert r["ok"]
    bad = c.post("/api/pos/v1/kitchen-tickets", headers=dev, json={"tickets": [{**t, "client_uuid": str(uuid.uuid4()), "items": []}]}).json()["results"][0]
    assert not bad["ok"]
    board = p.get("/admin/comandas/board").text
    assert board.count("Mesa 3 · Lucas") == 1 and "sin cebolla" in board and "Listo para llevar" in board
    assert p.post(f"/admin/comandas/mesa/{r['id']}", data={"status": "listo"}).json()["ok"]
    assert "Ya está en la mesa" in p.get("/admin/comandas/board").text
    # llamador: ventas del mostrador con número o nombre (las de comer acá y las mesas no)
    caja_page = p.get("/admin/caja").text
    assert "/llamador/" in caja_page
    code = caja_page.split("/llamador/")[1].split('"')[0]
    v = sale(c, dev, ids["Sofi"], [{"product_id": c.get("/api/pos/v1/catalog", headers=dev).json()["products"][0]["id"], "quantity": 1}],
             call_number=31, customer_name="Juan Pérez", service="llevar", kitchen=True)
    d = client().get(f"/llamador/{code}/data").json()
    assert {"key": f"s{v['id']}", "number": "31", "name": "Juan"} in d["preparing"] and d["ready"] == []
    assert p.post(f"/admin/comandas/caja/{v['id']}", data={"status": "listo"}).json()["ok"]
    d = client().get(f"/llamador/{code}/data").json()
    assert d["ready"][0]["number"] == "31" and not any(x["key"] == f"s{v['id']}" for x in d["preparing"])
    assert "Mesa 3" not in str(d)
    assert "Llamador" in client().get(f"/llamador/{code}").text
    assert client().get("/llamador/no-existe/data").status_code == 404
    # cambiar el link deja de mostrar el viejo
    assert p.post("/admin/caja/llamador/nuevo", follow_redirects=False).status_code == 303
    assert client().get(f"/llamador/{code}/data").status_code == 404


def test_agotar_resumen_y_promos_en_el_panel(env):
    from app.db import SessionLocal
    from app.models import PosPromo, Product
    c = client()
    dev, sofi, owner, ids = caja(c)
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    pid = cat["products"][0]["id"]
    r = c.post(f"/api/pos/v1/products/{pid}/stock", headers={**dev, "X-Cashier": sofi}, json={"action": "out"}).json()
    assert r["ok"] and r["stock"] == 0
    with SessionLocal() as db:
        assert db.get(Product, pid).stock == 0  # también deja de venderse en la app y la web
    r = c.post(f"/api/pos/v1/products/{pid}/stock", headers={**dev, "X-Cashier": sofi}, json={"action": "tomorrow"}).json()
    assert r["out_until"]
    r = c.post(f"/api/pos/v1/products/{pid}/stock", headers={**dev, "X-Cashier": sofi}, json={"action": "back"}).json()
    assert r["stock"] != 0 and r["out_until"] is None
    assert c.post("/api/pos/v1/products/999999/stock", headers={**dev, "X-Cashier": sofi}, json={"action": "out"}).status_code == 404
    # resumen del día: solo el dueño
    assert c.get("/api/pos/v1/reports/today", headers={**dev, "X-Cashier": sofi}).status_code == 403
    rep = c.get("/api/pos/v1/reports/today", headers={**dev, "X-Cashier": owner}).json()
    assert rep["ok"] and rep["count"] >= 1 and rep["counter"] > 0 and rep["by_hour"] and rep["top"] and rep["shift"]
    # promos desde el panel (con validaciones)
    p = panel()
    assert p.post("/admin/caja/promos", data={"name": "Mal", "kind": "nxm", "buy": "2", "pay": "2", "products": [str(pid)], "day0": "on"}, follow_redirects=False).status_code == 303
    assert "M tiene que ser menor" in p.get("/admin/caja/salon").text
    data = {"name": "Happy hour", "kind": "percent", "value": "15", "products": [str(pid)], "start": "18:00", "end": "21:00", **{f"day{d}": "on" for d in range(5)}}
    assert p.post("/admin/caja/promos", data=data, follow_redirects=False).status_code == 303
    combo = {"name": "Combo de prueba", "kind": "combo", "value": "5000", f"qty_{pid}": "2", "day0": "on"}
    assert p.post("/admin/caja/promos", data=combo, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        hh = db.query(PosPromo).filter_by(name="Happy hour").one()
        assert hh.days == "01234" and hh.start == "18:00" and float(hh.value) == 15
        assert db.query(PosPromo).filter_by(name="Combo de prueba").one().product_ids == f"[{pid}, {pid}]"
        hid = hh.id
    assert p.post(f"/admin/caja/promos/{hid}", data={"action": ""}, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.get(PosPromo, hid).active is False
