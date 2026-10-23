"""Caja para gastronomía: opciones y aclaraciones, comanda en el tablero de cocina, número para llamar, pago mixto,
descuentos que autoriza el dueño, retiros e ingresos con arqueo por billetes, favoritos y pedidos por teléfono."""
import json
import os
import sys
import uuid

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("gastro") / "gastro.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ModifierGroup, ModifierOption, PosCashier, Product, Role, Store, User
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
        burger = db.query(Product).filter_by(store_id=s.id, name="Hamburguesa Clásica").one()
        g = ModifierGroup(product_id=burger.id, name="Punto", required=True, min_select=1, max_select=1)
        x = ModifierGroup(product_id=burger.id, name="Extras", max_select=3, display_order=1)
        g.options = [ModifierOption(name="Jugosa"), ModifierOption(name="Bien cocida", display_order=1)]
        x.options = [ModifierOption(name="Cheddar", price_extra=800), ModifierOption(name="Panceta", price_extra=1200, active=False)]
        db.add_all([g, x])
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


def caja(c):
    """(headers de la compu, token de Sofi, token del dueño, ids de cajeros)"""
    setting(pos_enabled=True, pos_commission_percent=0, pos_monthly_fee=0)
    from app.db import SessionLocal
    from app.models import User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="dueno@test.local").one()
        u.password_hash = hash_password("Dueno-1234")
        db.commit()
    r = c.post("/api/pos/v1/link", json={"email": "dueno@test.local", "password": "Dueno-1234"})
    assert r.status_code == 200, r.text
    me = r.json()
    dev = {"Authorization": "Bearer " + me["token"]}
    ids = {x["name"]: x["id"] for x in me["cashiers"]}
    sofi = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Sofi"], "pin": "1111"}).json()["token"]
    owner = c.post("/api/pos/v1/cashiers/login", headers=dev, json={"cashier_id": ids["Dueño"], "pin": "9999"}).json()["token"]
    if not c.get("/api/pos/v1/shifts/current", headers=dev).json()["shift"]:
        assert c.post("/api/pos/v1/shifts/open", headers={**dev, "X-Cashier": sofi}, json={"amount": 10000}).status_code == 200
    return me, dev, sofi, owner, ids


def sale(c, dev, cashier_id, items, **extra):
    data = {"client_uuid": str(uuid.uuid4()), "cashier_id": cashier_id, "items": items, "payment_method": "efectivo",
            "sold_at": "2030-01-01T00:00:00Z", **extra}
    data["sold_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    r = c.post("/api/pos/v1/sales", headers=dev, json={"sales": [data]}).json()["results"][0]
    return r


def panel():
    c = client()
    assert c.post("/admin/login", data={"email": "dueno@test.local", "password": "Dueno-1234"}, follow_redirects=False).status_code == 303
    return c


def test_opciones_aclaracion_y_comanda_en_cocina(env):
    c = client()
    me, dev, sofi, owner, ids = caja(c)
    assert me["delivery"]["enabled"] and me["free_discount_pct"] == 10
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    burger = next(p for p in cat["products"] if p["name"] == "Hamburguesa Clásica")
    groups = {g["name"]: g for g in burger["groups"]}
    assert groups["Punto"]["required"] and [o["name"] for o in groups["Extras"]["options"]] == ["Cheddar"]  # la agotada no se ofrece
    jugosa = groups["Punto"]["options"][0]["id"]
    cheddar = groups["Extras"]["options"][0]["id"]
    other = next(p for p in cat["products"] if p["id"] != burger["id"])
    # una opción de otro producto no se acepta
    bad = sale(c, dev, ids["Sofi"], [{"product_id": other["id"], "quantity": 1, "modifiers": [cheddar]}])
    assert not bad["ok"] and "opción" in bad["error"]
    r = sale(c, dev, ids["Sofi"], [{"product_id": burger["id"], "quantity": 2, "modifiers": [jugosa, cheddar], "note": "  sin   cebolla  "}],
             call_number=23, customer_name="Juan", service="llevar", kitchen=True)
    assert r["ok"], r
    line = r["items"][0]
    assert line["unit_price"] == burger["price"] + 800 and line["total"] == (burger["price"] + 800) * 2  # el precio lo pone el servidor
    assert line["modifiers_text"] == "Jugosa, Cheddar" and line["note"] == "sin cebolla"
    assert r["call_number"] == 23 and r["customer_name"] == "Juan" and r["kitchen"] == "cocina"
    # aparece en el tablero de Comandas, en la cocina, con la aclaración
    p = panel()
    board = p.get("/admin/comandas/board").text
    assert "Pedido 23 · Juan" in board and "sin cebolla" in board and "🛍 Llevar" in board and "Listo para entregar" in board
    assert p.post(f"/admin/comandas/caja/{r['id']}", data={"status": "listo"}, headers={"X-Requested-With": "fetch"}).json()["ok"]
    assert "🙌 Entregado" in p.get("/admin/comandas/board").text
    assert p.post(f"/admin/comandas/caja/{r['id']}", data={"status": "entregado"}).json()["ok"]
    assert "Pedido 23 · Juan" not in p.get("/admin/comandas/board").text
    # anulada: sale del tablero
    r2 = sale(c, dev, ids["Sofi"], [{"product_id": other["id"], "quantity": 1}], call_number=24, kitchen=True)
    assert "Pedido 24" in p.get("/admin/comandas/board").text
    assert c.post(f"/api/pos/v1/sales/{r2['id']}/void", headers={**dev, "X-Cashier": owner}).status_code == 200
    assert "Pedido 24" not in p.get("/admin/comandas/board").text
    # sin el tilde de cocina no va al tablero
    r3 = sale(c, dev, ids["Sofi"], [{"product_id": other["id"], "quantity": 1}], call_number=25)
    assert r3["kitchen"] is None and "Pedido 25" not in p.get("/admin/comandas/board").text
    # favoritos: lo que más se vende en el mostrador primero
    assert c.get("/api/pos/v1/catalog", headers=dev).json()["favorites"][0] == burger["id"]
    # otro local no puede tocar la venta desde su tablero
    assert p.post("/admin/comandas/caja/999999", data={"status": "listo"}).status_code == 404


def test_pago_mixto_y_descuentos_autorizados(env):
    from app.db import SessionLocal
    from app.models import AuditLog, PosSale
    c = client()
    me, dev, sofi, owner, ids = caja(c)
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    p = next(x for x in cat["products"] if not x["groups"])
    before = c.get("/api/pos/v1/shifts/current", headers=dev).json()["shift"]
    total = p["price"] * 2
    r = sale(c, dev, ids["Sofi"], [{"product_id": p["id"], "quantity": 2}], payment_method="mixto",
             payments=[{"method": "efectivo", "amount": total - 1000}, {"method": "mercadopago", "amount": 1000}], paid_with=total)
    assert r["ok"] and r["payment_method"] == "mixto"
    assert {x["method"]: x["amount"] for x in r["payments"]} == {"efectivo": total - 1000, "mercadopago": 1000}
    after = c.get("/api/pos/v1/shifts/current", headers=dev).json()["shift"]
    assert after["by_method"]["mercadopago"]["total"] == before["by_method"]["mercadopago"]["total"] + 1000
    assert after["expected_cash"] == before["expected_cash"] + total - 1000  # solo la parte en efectivo va al cajón
    # si no suma justo (precio cambiado mientras estaba sin internet), la diferencia va al efectivo: la venta no se pierde
    r = sale(c, dev, ids["Sofi"], [{"product_id": p["id"], "quantity": 1}], payment_method="mixto",
             payments=[{"method": "efectivo", "amount": 1}, {"method": "transferencia", "amount": 500}])
    assert r["ok"] and sum(x["amount"] for x in r["payments"]) == p["price"]
    bad = sale(c, dev, ids["Sofi"], [{"product_id": p["id"], "quantity": 1}], payment_method="mixto", payments=[{"method": "efectivo", "amount": 1}])
    assert not bad["ok"]
    # descuento grande de una cajera sin el dueño: la venta entra (ya se hizo) pero queda marcada
    big = round(p["price"] * 0.5, 2)
    r = sale(c, dev, ids["Sofi"], [{"product_id": p["id"], "quantity": 1}], discount=big)
    assert r["ok"]
    with SessionLocal() as db:
        assert db.get(PosSale, r["id"]).approved_by is None
        assert db.query(AuditLog).filter_by(action="pos.discount.unapproved", entity_id=str(r["id"])).count() == 1
    # con la autorización del dueño (su PIN): queda quién autorizó
    assert c.post("/api/pos/v1/approvals", headers={**dev, "X-Cashier": sofi}, json={"kind": "discount", "amount": big}).status_code == 403
    ok = c.post("/api/pos/v1/approvals", headers={**dev, "X-Cashier": owner}, json={"kind": "discount", "amount": big}).json()
    r = sale(c, dev, ids["Sofi"], [{"product_id": p["id"], "quantity": 1}], discount=big, approval=ok["approval"])
    with SessionLocal() as db:
        assert db.get(PosSale, r["id"]).approved_by == ids["Dueño"]
    # la autorización no sirve para un descuento más grande
    r = sale(c, dev, ids["Sofi"], [{"product_id": p["id"], "quantity": 1}], discount=big + 100, approval=ok["approval"])
    with SessionLocal() as db:
        assert db.get(PosSale, r["id"]).approved_by is None


def test_retiros_ingresos_y_arqueo(env):
    c = client()
    me, dev, sofi, owner, ids = caja(c)
    start = c.get("/api/pos/v1/shifts/current", headers=dev).json()["shift"]
    mov = lambda tok, **b: c.post("/api/pos/v1/cash-movements", headers={**dev, "X-Cashier": tok}, json={"client_uuid": str(uuid.uuid4()), **b})
    r = mov(sofi, kind="retiro", amount=5000, reason="Proveedor de pan")
    assert r.status_code == 403  # el retiro lo autoriza el dueño
    assert mov(owner, kind="retiro", amount=5000, reason="x").status_code == 400  # sin motivo
    uid = str(uuid.uuid4())
    for _ in range(2):  # reintento: no se duplica
        r = c.post("/api/pos/v1/cash-movements", headers={**dev, "X-Cashier": owner}, json={"client_uuid": uid, "kind": "retiro", "amount": 5000, "reason": "Proveedor de pan"})
        assert r.status_code == 200
    r = mov(sofi, kind="ingreso", amount=2000, reason="Cambio del banco")
    shift = r.json()["shift"]
    assert shift["cash_out"] == start["cash_out"] + 5000 and shift["cash_in"] == start["cash_in"] + 2000
    assert shift["expected_cash"] == start["expected_cash"] - 3000
    assert any(m["reason"] == "Proveedor de pan" for m in shift["movements"])
    # cierre con arqueo por billetes: la caja suma sola
    expected = shift["expected_cash"]
    thousands = int(expected // 1000)
    coins = round(expected - thousands * 1000, 2)
    r = c.post("/api/pos/v1/shifts/close", headers={**dev, "X-Cashier": owner}, json={"amount": 0, "bills": {"1000": thousands, "monedas": coins, "37": 5}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counted_cash"] == expected and abs(out["difference"]) < 0.01 and out["bills"]["1000"] == thousands and "37" not in out["bills"]
    assert out["closed_by"] == "Dueño" and out["voided"] >= 1
    assert c.post("/api/pos/v1/cash-movements", headers={**dev, "X-Cashier": owner},
                  json={"client_uuid": str(uuid.uuid4()), "kind": "ingreso", "amount": 1, "reason": "sin caja"}).status_code == 409
    # se ve en el panel del local
    page = panel().get("/admin/caja").text
    assert "Retiros" in page


def test_pedido_por_telefono(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Store
    c = client()
    me, dev, sofi, owner, ids = caja(c)
    setting(pos_commission_percent=2)
    cat = c.get("/api/pos/v1/catalog", headers=dev).json()
    burger = next(p for p in cat["products"] if p["name"] == "Hamburguesa Clásica")
    jugosa = burger["groups"][0]["options"][0]["id"]
    body = {"client_uuid": str(uuid.uuid4()), "items": [{"product_id": burger["id"], "quantity": 1, "modifiers": [jugosa], "note": "cortada al medio"}],
            "first_name": "Marta", "phone": "291 455-6677", "delivery_method": "delivery", "address": "Alsina 123", "payment_method": "efectivo", "cash_with": 20000}
    h = {**dev, "X-Cashier": sofi}
    assert c.post("/api/pos/v1/phone-orders", headers=h, json={**body, "phone": "12"}).status_code == 400
    assert c.post("/api/pos/v1/phone-orders", headers=h, json={**body, "address": ""}).status_code == 400
    r = c.post("/api/pos/v1/phone-orders", headers=h, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["shipping"] == 1500 and out["total"] == burger["price"] + 1500 and "/pedido/" in out["track_url"]
    assert out["whatsapp_url"].startswith("https://wa.me/5492914556677")
    again = c.post("/api/pos/v1/phone-orders", headers=h, json=body).json()  # reintento: el mismo pedido
    assert again["id"] == out["id"]
    with SessionLocal() as db:
        o = db.get(Order, out["id"])
        assert o.status == OrderStatus.CONFIRMADO and o.origin == "caja" and o.delivery_mode == "store" and o.delivery_pin is None
        assert float(o.commission_rate) == 2 and "Aclaración: cortada al medio" in o.items[0].modifiers_text
        assert [e.status for e in o.events] == ["PENDIENTE", "CONFIRMADO"]
    board = panel().get("/admin/comandas/board").text
    assert f"#{out['id']}" in board and "Marta" in board and "📞 Teléfono" in board
    # retiro en el local: sin envío; con zonas por km hay que elegir la zona
    r = c.post("/api/pos/v1/phone-orders", headers=h, json={**body, "client_uuid": str(uuid.uuid4()), "delivery_method": "retiro", "address": ""}).json()
    assert r["shipping"] == 0
    with SessionLocal() as db:
        from app.models import DeliveryZone
        s = db.query(Store).filter_by(slug="burger-mix").one()
        s.lat, s.lng = -38.7, -62.27
        db.add_all([DeliveryZone(store_id=s.id, max_km=2, cost=900), DeliveryZone(store_id=s.id, max_km=5, cost=1800)])
        db.commit()
    me = c.get("/api/pos/v1/me", headers=dev).json()
    zones = me["delivery"]["zones"]
    assert [z["cost"] for z in zones] == [900, 1800] and zones[0]["label"] == "Hasta 2 km"
    assert c.post("/api/pos/v1/phone-orders", headers=h, json={**body, "client_uuid": str(uuid.uuid4())}).status_code == 400
    r = c.post("/api/pos/v1/phone-orders", headers=h, json={**body, "client_uuid": str(uuid.uuid4()), "zone_id": zones[1]["id"]}).json()
    assert r["shipping"] == 1800
    # montos libres no (el precio lo pone el menú)
    bad = {**body, "client_uuid": str(uuid.uuid4()), "zone_id": zones[0]["id"], "items": [{"name": "Algo", "unit_price": 5, "quantity": 1}]}
    assert c.post("/api/pos/v1/phone-orders", headers=h, json=bad).status_code == 400
