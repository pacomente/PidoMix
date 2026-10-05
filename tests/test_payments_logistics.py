"""Pagos online (Mercado Pago Split), zonas de cobertura, envio por km, flota, efectivo, rendiciones,
liquidaciones e historico. Mercado Pago y el servicio de rutas se reemplazan por dobles locales:
los tests nunca salen a internet."""
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

STORE = (-38.7183, -62.2663)
NEAR = (-38.7200, -62.2700)       # ~0.4 km
MID = (-38.7350, -62.2663)        # ~1.9 km al sur
FAR = (-38.9000, -62.2663)        # ~20 km: fuera de todo
ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
SECRET = "whsec-test"
D = Decimal


class FakeRouter:
    """Ruta 'por calle' = linea recta x 1.5 (para distinguirla de la estimacion x 1.35)."""
    def __init__(self):
        self.calls, self.down = 0, False

    def route(self, a, b):
        from app.services.geo import distance_km
        from app.services.routing import Route, RoutingError
        self.calls += 1
        if self.down:
            raise RoutingError("caido")
        return Route(km=round(distance_km(a[0], a[1], b[0], b[1]) * 1.5, 3), minutes=7.0, source="fake")


class FakeMP:
    """Lo minimo de la API de Mercado Pago que usa Trappi (OAuth, preferencias, pagos, devoluciones)."""
    def __init__(self):
        self.payments, self.preferences, self.requests = {}, [], []
        self.seller = "777"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        auth = request.headers.get("authorization", "")
        self.requests.append((method, path, auth))
        if path == "/oauth/token":
            form = parse_qs(request.content.decode())
            assert form["client_secret"] == ["test-secret"]  # el secreto solo viaja del backend a Mercado Pago
            return httpx.Response(200, json={"access_token": "APP_USR-seller-token", "refresh_token": "TG-refresh", "user_id": int(self.seller),
                                             "public_key": "APP_USR-pk", "live_mode": False, "expires_in": 15552000})
        if path == "/users/me":
            return httpx.Response(200, json={"nickname": "BURGERMIX"})
        if auth != "Bearer APP_USR-seller-token":
            return httpx.Response(401, json={"message": "invalid token"})
        if path == "/checkout/preferences" and method == "POST":
            body = json.loads(request.content)
            self.preferences.append(body)
            n = len(self.preferences)
            return httpx.Response(201, json={"id": f"pref-{n}", "init_point": f"https://mp.example/live/{n}", "sandbox_init_point": f"https://mp.example/sandbox/{n}"})
        if path == "/v1/payments/search":
            ref = request.url.params.get("external_reference")
            found = [p for p in self.payments.values() if p["external_reference"] == ref]
            return httpx.Response(200, json={"results": found[::-1]})
        if path.endswith("/refunds") and method == "POST":
            pid = path.split("/")[3]
            p = self.payments[pid]
            amount = json.loads(request.content or b"{}").get("amount") or p["transaction_amount"]
            p["transaction_amount_refunded"] = p.get("transaction_amount_refunded", 0) + amount
            p["status"] = "refunded" if p["transaction_amount_refunded"] >= p["transaction_amount"] else "approved"
            return httpx.Response(201, json={"id": 1, "amount": amount})
        if path.startswith("/v1/payments/"):
            pid = path.rsplit("/", 1)[1]
            if pid not in self.payments:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=self.payments[pid])
        return httpx.Response(404, json={"message": "no route"})

    def pay(self, pid, order_id, amount, status="approved", fee=None, collector=None, currency="ARS"):
        self.payments[str(pid)] = {
            "id": int(pid), "status": status, "status_detail": "accredited" if status == "approved" else "cc_rejected_other_reason",
            "external_reference": f"trappi-order-{order_id}", "transaction_amount": float(amount), "currency_id": currency,
            "collector_id": int(collector or self.seller), "payment_method_id": "visa", "live_mode": False, "transaction_amount_refunded": 0,
            "fee_details": [{"type": "mercadopago_fee", "amount": 120.0}] + ([{"type": "application_fee", "amount": float(fee)}] if fee is not None else []),
        }


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("payments") / "payments.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.models import Courier, Store
    from app.services import mercadopago, platform, routing
    from app.services.auth import hash_password
    settings.mercadopago_client_id = "test-client"
    settings.mercadopago_client_secret = "test-secret"
    settings.mercadopago_redirect_uri = "http://testserver/admin/pagos/mercadopago/callback"
    settings.mercadopago_webhook_secret = SECRET
    settings.mercadopago_environment = "sandbox"
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        store.lat, store.lng = STORE
        db.add_all([Courier(name="Fede Flota", phone="2912222222", pin_hash=hash_password("5678"), lat=STORE[0], lng=STORE[1] + 0.01),
                    Courier(name="Lucía Propia", phone="2911111111", pin_hash=hash_password("1234"), store_id=store.id)])
        db.commit()
    platform.invalidate()
    router, mp = FakeRouter(), FakeMP()
    routing.set_provider(router)
    mercadopago.set_transport(httpx.MockTransport(mp.handler))
    yield {"router": router, "mp": mp}
    routing.set_provider(None)
    mercadopago.set_transport(None)
    engine.dispose()


# ---------- ayudas ----------

def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter._hits.clear()
    return TestClient(app)


def admin_client():
    c = client()
    assert c.post("/admin/login", data=ADMIN, follow_redirects=False).status_code == 303
    return c


def setting(key, value):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        row = db.query(Setting).filter_by(key=key).first()
        if value is None:
            if row: db.delete(row)
        elif row:
            row.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
        db.commit()
    platform.invalidate()


def store_id():
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        return db.query(Store).filter_by(slug="burger-mix").one().id


def set_store(**kw):
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        for k, v in kw.items():
            setattr(s, k, v)
        db.commit()


def fleet_store(**kw):
    """burger-mix con plan Trappi Delivery (10 % de comision) y la flota."""
    set_store(**{"plan": "TRAPPI_DELIVERY", "commission_rate": D("10"), "logistics": "trappi", "fleet_enabled": True, "delivery_fee_payer": None,
                 "fee_share_mode": None, "fee_share_value": None, "commission_fixed": None, "commission_min": None, "commission_max": None, **kw})


def clear_zones():
    from app.db import SessionLocal
    from app.models import LogisticsZone
    from app.services import logistics
    with SessionLocal() as db:
        for z in db.query(LogisticsZone).all():
            z.deleted = True
        db.commit()
    logistics.invalidate()


def zone(**kw):
    from app.db import SessionLocal
    from app.models import LogisticsZone
    from app.services import logistics
    data = {"name": "Centro", "kind": "radius", "center_lat": STORE[0], "center_lng": STORE[1], "radius_km": 5, "priority": 0,
            "base_fee": D("1000"), "included_km": 1, "per_km": D("400"), "min_fee": D("0"), "rounding": D("0"), **kw}
    with SessionLocal() as db:
        z = LogisticsZone(**data)
        db.add(z); db.commit()
        logistics.invalidate()
        return z.id


def product_id(name="Coca Cola"):
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        return db.query(Product).filter_by(name=name).one().id


def new_order(c, at=NEAR, method="efectivo", qty=3, delivery="delivery"):
    body = {"items": [{"product_id": product_id(), "quantity": qty}], "delivery_method": delivery, "first_name": "Ana",
            "phone": "2914000000", "address": "Alsina 100", "lat": at[0], "lng": at[1], "payment_method": method}
    r = c.post("/api/v1/orders", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def quote(c, at):
    r = c.post("/api/v1/cart/quote", json={"items": [{"product_id": product_id(), "quantity": 3}], "delivery_method": "delivery", "lat": at[0], "lng": at[1]})
    assert r.status_code == 200, r.text
    return r.json()


def get_order(order_id):
    from app.db import SessionLocal
    from app.models import Order
    db = SessionLocal()
    return db, db.get(Order, order_id)


def fleet_courier(db):
    from app.models import Courier
    return db.query(Courier).filter_by(name="Fede Flota").one()


def deliver_with_fleet(order_id, courier_name="Fede Flota"):
    """Confirma, asigna al cadete, retira y entrega (con el PIN del cliente)."""
    from app.db import SessionLocal
    from app.models import Courier, Order, OrderStatus
    from app.services import dispatch
    from app.services.orders import set_status
    with SessionLocal() as db:
        o = db.get(Order, order_id)
        if o.status == OrderStatus.PENDIENTE:
            assert set_status(o, OrderStatus.CONFIRMADO)
        courier = db.query(Courier).filter_by(name=courier_name).one()
        dispatch.assign_manual(db, o, courier)
        dispatch.pickup(db, courier, o, o.pickup_code or "")  # el local le dicta el codigo de retiro
        dispatch.deliver(db, courier, o, o.delivery_pin or "")
        db.commit()


def signed(data_id, request_id="req-1", secret=SECRET):
    ts = "1700000000"
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={v1}", "x-request-id": request_id}


def webhook(c, pid, request_id="req-1", secret=SECRET, action="payment.updated"):
    return c.post(f"/api/payments/mercadopago/webhook?data.id={pid}&type=payment", headers=signed(pid, request_id, secret),
                  json={"type": "payment", "action": action, "data": {"id": str(pid)}, "user_id": 777})


# ==================== tarifa por km y quien paga ====================

def test_tariff_base_per_km_included_min_max_rounding(env):
    from app.services import logistics

    class Z:
        base_fee, per_km, included_km, min_fee, max_fee, rounding = D("1000"), D("450"), 2, D("0"), None, D("0")

    z = Z()
    assert logistics.tariff(z, 1.5)["fee"] == D("1000.00")                 # dentro de los km incluidos: solo la base
    t = logistics.tariff(z, 5.3)
    assert t["billable_km"] == 3.3 and t["fee"] == D("2485.00")            # 1000 + 3,3 x 450
    z.rounding = D("100")
    assert logistics.tariff(z, 5.3)["fee"] == D("2500.00")                 # redondeo hacia arriba a $100
    z.min_fee, z.rounding = D("1800"), D("0")
    assert logistics.tariff(z, 0)["fee"] == D("1800.00")                   # minimo
    z.max_fee = D("3000")
    assert logistics.tariff(z, 40)["fee"] == D("3000.00")                  # maximo


def test_delivery_fee_payer_split(env):
    from app.services import logistics
    fee = D("2000")
    assert logistics.split_fee(fee, {"payer": "CUSTOMER"}) == (D("2000.00"), D("0.00"), D("0.00"))
    assert logistics.split_fee(fee, {"payer": "MERCHANT"}) == (D("0.00"), D("2000.00"), D("0.00"))
    assert logistics.split_fee(fee, {"payer": "TRAPPI"}) == (D("0.00"), D("0.00"), D("2000.00"))
    assert logistics.split_fee(fee, {"payer": "SHARED", "share_mode": "percent", "share_value": "25"}) == (D("500.00"), D("1500.00"), D("0.00"))
    assert logistics.split_fee(fee, {"payer": "SHARED", "share_mode": "amount", "share_value": "5000"}) == (D("2000.00"), D("0.00"), D("0.00"))


# ==================== zonas y cobertura ====================

def test_zone_inside_outside_priority_and_max_km(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import logistics
    fleet_store(); clear_zones()
    big = zone(name="Ciudad", radius_km=10, priority=0, base_fee=D("1500"))
    small = zone(name="Microcentro", radius_km=1, priority=5, base_fee=D("800"))
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        q = logistics.delivery_quote(db, s, {"lat": NEAR[0], "lng": NEAR[1]})
        assert q.covered and q.zone_id == small and q.zone_name == "Microcentro"  # superpuestas: gana la de mayor prioridad
        q = logistics.delivery_quote(db, s, {"lat": MID[0], "lng": MID[1]})
        assert q.covered and q.zone_id == big
        assert q.route_source == "fake" and q.route_km == pytest.approx(logistics.distance_km(*STORE, *MID) * 1.5, abs=0.01)  # distancia por ruta, no en linea recta
        assert q.fee_real == logistics.tariff(db.get(logistics.LogisticsZone, big), q.route_km)["fee"]
        q = logistics.delivery_quote(db, s, {"lat": FAR[0], "lng": FAR[1]})
        assert q.covered is False and q.reason == logistics.OUT_OF_COVERAGE and q.pickup_allowed
        z = db.get(logistics.LogisticsZone, big)
        z.max_km = 1.0
        db.commit(); logistics.invalidate()
        q = logistics.delivery_quote(db, s, {"lat": MID[0], "lng": MID[1]})
        assert q.covered is False  # supera el tope de km de la zona
    assert {(a.id, b.id) for a, b in logistics.overlaps(SessionLocal().query(logistics.LogisticsZone).filter_by(deleted=False).all())} == {(big, small)}


def test_polygon_zone_and_schedule(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import logistics
    fleet_store(); clear_zones()
    square = [[STORE[0] + 0.01, STORE[1] - 0.01], [STORE[0] + 0.01, STORE[1] + 0.01], [STORE[0] - 0.01, STORE[1] + 0.01], [STORE[0] - 0.01, STORE[1] - 0.01]]
    zone(name="Cuadrado", kind="polygon", polygon=json.dumps(square), center_lat=None, center_lng=None, radius_km=None, start_time="10:00", end_time="14:00", days="0")
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        monday_noon, monday_night = datetime(2026, 10, 5, 12, 0), datetime(2026, 10, 5, 22, 0)
        assert logistics.delivery_quote(db, s, {"lat": NEAR[0], "lng": NEAR[1]}, now=monday_noon).covered
        assert not logistics.delivery_quote(db, s, {"lat": MID[0], "lng": MID[1]}, now=monday_noon).covered  # fuera del poligono
        assert not logistics.delivery_quote(db, s, {"lat": NEAR[0], "lng": NEAR[1]}, now=monday_night).covered  # fuera de horario
        assert not logistics.delivery_quote(db, s, {"lat": NEAR[0], "lng": NEAR[1]}, now=datetime(2026, 10, 6, 12, 0)).covered  # martes


def test_out_of_coverage_policies_and_routing_fallback(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import logistics
    fleet_store(); clear_zones(); zone(radius_km=3)
    c = client()
    try:
        setting("out_of_coverage_policy", "reject")
        cov = quote(c, FAR)["store"]["coverage"]
        assert cov["covered"] is False and cov["pickup_allowed"] is False and "fuera de la zona" in cov["reason"]
        r = c.post("/api/v1/orders", json={"items": [{"product_id": product_id(), "quantity": 1}], "delivery_method": "delivery", "first_name": "Ana",
                                           "phone": "2914000000", "address": "Lejos 1", "lat": FAR[0], "lng": FAR[1]})
        assert r.status_code == 400  # no se crea un pedido sin cobertura
        setting("out_of_coverage_policy", "merchant")
        with SessionLocal() as db:
            q = logistics.delivery_quote(db, db.query(Store).filter_by(slug="burger-mix").one(), {"lat": FAR[0], "lng": FAR[1]})
            assert q.mode == "store"  # fuera de cobertura entrega el comercio con su tarifa
        setting("out_of_coverage_policy", None)
        from app.services import routing
        routing.service.clear()  # la ruta ya calculada queda en cache: se prueba con el proveedor caido
        env["router"].down = True
        setting("routing_fallback", "reject")
        with SessionLocal() as db:
            q = logistics.delivery_quote(db, db.query(Store).filter_by(slug="burger-mix").one(), {"lat": MID[0], "lng": MID[1]})
            assert q.covered is False and "ruta" in q.reason
        setting("routing_fallback", None)
        with SessionLocal() as db:
            q = logistics.delivery_quote(db, db.query(Store).filter_by(slug="burger-mix").one(), {"lat": MID[0], "lng": MID[1]})
            assert q.covered and q.route_source == "estimate"  # sin proveedor: estimacion marcada como tal
    finally:
        env["router"].down = False
        setting("out_of_coverage_policy", None); setting("routing_fallback", None)


def test_store_without_fleet_keeps_its_own_fee(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import logistics
    set_store(plan=None, logistics="propia", fleet_enabled=False, delivery_fee_payer=None, commission_rate=None)
    clear_zones(); zone(radius_km=0.1, base_fee=D("99999"))
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        q = logistics.delivery_quote(db, s, {"lat": NEAR[0], "lng": NEAR[1]})
        assert q.mode == "store" and q.covered and q.fee_real == logistics.money(s.delivery_cost)


# ==================== pedido con la flota: snapshot e historico ====================

def test_fleet_order_snapshot_and_history_unchanged(env):
    fleet_store(); clear_zones()
    zid = zone(name="Centro", radius_km=5, base_fee=D("1000"), included_km=1, per_km=D("400"))
    c = client()
    order = new_order(c, at=MID)
    db, o = get_order(order["id"])
    snap = json.loads(o.pricing_snapshot)
    km = o.route_km
    expected = D("1000") + (D(str(round(km - 1, 3))) * D("400")).quantize(D("0.01"))
    assert o.delivery_mode == "trappi" and o.zone_id == zid and o.route_source == "fake"
    assert o.delivery_fee == expected and o.shipping == expected and o.delivery_fee_customer == expected
    assert snap["delivery"]["tariff"]["per_km"] == "400.00" and snap["commission"]["rate"] == "10.00"
    old_fee, old_commission = o.delivery_fee, o.platform_commission
    assert old_commission == (D(o.subtotal) * D("0.10")).quantize(D("0.01"))
    db.close()
    # cambian la tarifa (desde el panel) y la comision del comercio
    a = admin_client()
    r = a.post("/admin/logistica/zonas", data={"id": zid, "name": "Centro", "active": "1", "kind": "radius", "center_lat": str(STORE[0]), "center_lng": str(STORE[1]),
                                               "radius_km": "5", "base_fee": "3000", "included_km": "0", "per_km": "900", **{f"day{d}": "1" for d in range(7)}},
               follow_redirects=False)
    assert r.status_code == 303
    r = a.post(f"/admin/configuracion/comisiones/{store_id()}", data={"rate": "25", "fixed": "", "minimum": "", "maximum": ""}, follow_redirects=False)
    assert r.status_code == 303
    from app.services import plans
    db, o = get_order(order["id"])
    assert o.delivery_fee == old_fee and plans.breakdown(o)["commission"] == old_commission  # el pedido viejo no cambia
    db.close()
    newer = new_order(c, at=MID)
    db, n = get_order(newer["id"])
    assert n.delivery_fee > old_fee and json.loads(n.pricing_snapshot)["commission"]["rate"] == "25.00"
    from app.models import AuditLog, LogisticsZoneVersion
    assert db.query(LogisticsZoneVersion).filter_by(zone_id=zid).count() >= 1
    assert db.query(AuditLog).filter(AuditLog.action.in_(["zone.update", "commission.update"])).count() >= 2
    db.close()


def test_merchant_pays_delivery(env):
    fleet_store(delivery_fee_payer="MERCHANT"); clear_zones(); zone()
    c = client()
    order = new_order(c, at=MID)
    db, o = get_order(order["id"])
    from app.services import plans
    b = plans.breakdown(o)
    assert o.shipping == 0 and o.delivery_fee_merchant == o.delivery_fee > 0
    assert b["merchant_amount"] == b["products"] - b["commission"] - o.delivery_fee
    assert b["trappi_amount"] == b["commission"] + o.delivery_fee
    db.close()
    set_store(delivery_fee_payer=None)


def test_commission_percent_fixed_min_max(env):
    from app.services import plans
    t = {"rate": "10", "fixed": "100", "min": "0", "max": "0"}
    assert plans.commission_amount(D("10000"), t) == D("1100.00")
    assert plans.commission_amount(D("1000"), {**t, "min": "500"}) == D("500.00")
    assert plans.commission_amount(D("100000"), {**t, "max": "5000"}) == D("5000.00")
    assert plans.commission_amount(D("50"), {**t, "min": "500"}) == D("50.00")  # nunca mas que lo vendido


# ==================== flota: pago al cadete y costo operativo ====================

def test_courier_payout_formula_and_operating_cost(env):
    from app.services import logistics
    cfg = {"courier_pay_mode": "formula", "payout_base": 500, "payout_per_km": 200, "payout_per_delivery": 300, "payout_night_start": "22:00",
           "payout_night_end": "06:00", "payout_night_bonus": 400, "payout_high_demand": True, "payout_high_demand_bonus": 250,
           "payout_long_km": 5, "payout_long_amount": 600, "operating_cost_per_km": 50, "operating_cost_min": 100}
    total, detail = logistics.courier_payout(cfg, D("2000"), 3.5, now=datetime(2026, 10, 5, 12, 0))
    assert total == D("1750.00") and detail["per_km"] == "700.00" and detail["distance_km"] == 3.5  # 500 + 700 + 300 + 250
    total, detail = logistics.courier_payout(cfg, D("2000"), 6, now=datetime(2026, 10, 5, 23, 0))
    assert total == D("3250.00") and detail["bonuses"] == {"nocturno": "400.00", "alta_demanda": "250.00"} and detail["extras"] == {"viaje_largo": "600.00"}
    assert logistics.operating_cost(cfg, 1) == D("100.00") and logistics.operating_cost(cfg, 10) == D("500.00")


def test_fleet_delivery_payout_snapshot_and_profitability(env):
    fleet_store(); clear_zones(); zone()
    setting("courier_pay_mode", "formula"); setting("payout_base", "500"); setting("payout_per_km", "100"); setting("payout_per_delivery", "0")
    setting("operating_cost_per_km", "20"); setting("delivery_pin_required", "0")
    try:
        c = client()
        order = new_order(c, at=MID)
        deliver_with_fleet(order["id"])
        db, o = get_order(order["id"])
        detail = json.loads(o.courier_pay_breakdown)
        assert detail["mode"] == "formula" and o.courier_pay == D(detail["total"]) == D("500") + (D(str(o.route_km)) * 100).quantize(D("0.01"))
        assert o.operational_km > o.route_km  # el cadete arranco lejos del local: el recorrido operativo es mas largo que el cobrado
        assert o.operating_cost == (D(str(o.operational_km)) * 20).quantize(D("0.01"))
        from app.services import plans
        b = plans.breakdown(o)
        assert b["logistics_margin"] == o.shipping - o.courier_pay - o.operating_cost
        assert o.trappi_income == b["commission"] + b["logistics_margin"]
        db.close()
        page = admin_client().get("/admin/logistica/rentabilidad?days=7")
        assert page.status_code == 200 and f"#{order['id']}" in page.text
    finally:
        for k in ("courier_pay_mode", "payout_base", "payout_per_km", "payout_per_delivery", "operating_cost_per_km", "delivery_pin_required"):
            setting(k, None)


# ==================== efectivo, limite y rendiciones ====================

def test_cash_collection_limit_and_remittance(env):
    from app.models import LedgerEntry
    from app.services import dispatch, finance
    fleet_store(); clear_zones(); zone(); setting("delivery_pin_required", "0")
    setting("fleet_cash_pay_store", "0")  # el flujo sin pagarle al local al retirar (el comercio cobra en su liquidacion)
    try:
        c = client()
        db, _ = get_order(1)
        before = finance.courier_cash_pending(db, fleet_courier(db).id)  # lo que ya traia de otros viajes
        db.close()
        order = new_order(c, at=MID)
        deliver_with_fleet(order["id"])
        db, o = get_order(order["id"])
        courier = fleet_courier(db)
        total = D(o.total)
        owed = before + total
        assert o.cash_pending == total and finance.courier_cash_pending(db, courier.id) == owed
        sale = db.query(LedgerEntry).filter_by(order_id=o.id, account="merchant").one()
        assert sale.kind == "cash_sale" and sale.amount == o.store_net  # Trappi le debe al comercio su parte
        # limite de efectivo: no puede tomar otro pedido en efectivo, si uno online
        courier.cash_limit = owed
        db.commit()
        nxt = new_order(c, at=MID)
        db2, o2 = get_order(nxt["id"])
        ok, why = dispatch.eligible(db2, o2, fleet_courier(db2))
        assert not ok and "límite de efectivo" in why
        o2.paid_at = datetime.utcnow()  # simulamos un pedido ya pagado (online): no cobra efectivo
        assert dispatch.eligible(db2, o2, fleet_courier(db2))[0]
        db2.rollback(); db2.close()
        box = c.get("/api/courier/v1/caja", headers=courier_login(c)).json()
        assert box["pending"] == float(owed) and box["blocked"] is True
        # rendicion con faltante de $500 (desde el panel)
        a = admin_client()
        r = a.post("/admin/finanzas/rendiciones", data={"courier_id": courier.id, "received": str(owed - 500), "receipt": "Recibo 001", "notes": "faltaron 500"},
                   follow_redirects=False)
        assert r.status_code == 303
        db.expire_all()
        assert finance.courier_cash_pending(db, courier.id) == D("500.00")  # sigue debiendo la diferencia
        assert db.get(type(o), o.id).cash_pending == 0
        from app.models import CashRemittance
        rem = db.query(CashRemittance).filter_by(courier_id=courier.id).one()
        assert rem.expected == owed and rem.difference == D("-500.00") and o.id in json.loads(rem.order_ids)
        with pytest.raises(finance.FinanceError):
            finance.create_remittance(db, courier, -1)
        rem_id = rem.id
        courier.cash_limit = None
        db.commit(); db.close()
        # no hay forma de borrar una rendicion
        assert a.post(f"/admin/finanzas/rendiciones/{rem_id}/eliminar").status_code in (404, 405)
    finally:
        setting("delivery_pin_required", None); setting("fleet_cash_pay_store", None)


def test_fleet_cash_pays_store_at_pickup_with_pickup_code(env):
    """Como en las apps de delivery: el cadete de Trappi le paga al local los productos al retirar (con el codigo
    de retiro que sale en la comanda) y despues le cobra al cliente productos + envio."""
    from app.models import LedgerEntry
    from app.services import finance, plans
    fleet_store(); clear_zones(); zone(); setting("delivery_pin_required", "0")
    try:
        c, a = client(), admin_client()
        db, _ = get_order(1)
        courier_id = fleet_courier(db).id
        before = finance.courier_cash_pending(db, courier_id)
        db.close()
        order = new_order(c, at=MID)
        db, o = get_order(order["id"])
        code, products, total = o.pickup_code, D(o.subtotal) - D(o.discount), D(o.total)
        assert code and len(code) == 4
        db.close()
        # la comanda y el ticket del local muestran el codigo, que paga en efectivo y cuanto le paga el cadete
        ticket = a.get(f"/admin/comandas/ticket/{order['id']}").text
        assert code in ticket and "RETIRA UN CADETE DE TRAPPI" in ticket and "<b>EFECTIVO</b>" in ticket
        assert f"TE PAGA ${products:,.0f}".replace(",", ".") in ticket
        # el cadete: al retirar ve el codigo y lo que le paga al local
        from app.db import SessionLocal
        from app.models import Courier, Order, OrderStatus
        from app.services import dispatch
        from app.services.orders import set_status
        with SessionLocal() as s:
            o = s.get(Order, order["id"]); assert set_status(o, OrderStatus.CONFIRMADO)
            dispatch.assign_manual(s, o, s.query(Courier).filter_by(name="Fede Flota").one()); s.commit()
        h = courier_login(c)
        trip = c.post("/api/courier/v1/pulse", headers=h, json={"online": True}).json()["trip"]
        assert trip["pickup_code_required"] is True and "pickup_code" not in trip  # la app no ve el codigo: se lo dicta el local
        assert trip["pay_store"] == float(products) and trip["collect"] == float(total)
        # el local no puede marcarlo "en camino": lo confirma el cadete con el codigo
        r = store_client().post(f"/admin/orders/{order['id']}/status", data={"status": "EN_CAMINO"}, headers={"x-requested-with": "fetch"})
        assert r.status_code == 409 and "código de retiro" in r.json()["error"]
        r = c.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=h)
        assert r.status_code == 409 and "código de retiro" in r.json()["error"]
        wrong = "0000" if code != "0000" else "1111"
        r = c.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=h, json={"code": wrong})
        assert r.status_code == 409 and "no coincide" in r.json()["error"]
        db, o = get_order(order["id"]); assert o.pickup_paid is None and o.status.value == "CONFIRMADO"; db.close()
        assert c.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=h, json={"code": code}).status_code == 200
        db, o = get_order(order["id"])
        assert o.pickup_paid == products
        paid = db.query(LedgerEntry).filter_by(order_id=o.id, kind="paid_to_store").one()
        assert paid.amount == -products and paid.courier_id == courier_id
        owed = db.query(LedgerEntry).filter_by(order_id=o.id, account="merchant").one()
        b = plans.breakdown(o)
        assert owed.kind == "commission_due" and owed.amount == b["merchant_amount"] - products == -b["commission"]  # la comision queda en su liquidacion
        db.close()
        # ya en camino no se muestra mas el codigo; el local no lo puede marcar "ya pagó"
        assert c.post("/api/courier/v1/pulse", headers=h, json={"online": True}).json()["trip"]["pickup_code_required"] is False
        r = a.post(f"/admin/orders/{order['id']}/paid", data={"paid": "1"}, headers={"x-requested-with": "fetch"})
        assert r.status_code == 409 and "ya te pagó" in r.json()["error"]
        # entrega: cobra el total al cliente; le queda para rendir solo el envio
        assert c.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=h, json={"pin": ""}).status_code == 200
        db, o = get_order(order["id"])
        assert o.cash_pending == total - products == D(o.shipping)
        assert finance.courier_cash_pending(db, courier_id) == before + total - products
        assert db.query(LedgerEntry).filter_by(order_id=o.id, account="merchant").count() == 1  # no se duplica la venta del comercio
        db.close()
        # variante: el cadete le paga los productos menos la comision (no queda deuda del comercio)
        setting("fleet_cash_store_amount", "net")
        order2 = new_order(c, at=MID)
        with SessionLocal() as s:
            o = s.get(Order, order2["id"]); assert set_status(o, OrderStatus.CONFIRMADO)
            dispatch.assign_manual(s, o, s.query(Courier).filter_by(name="Fede Flota").one()); s.commit()
        db, o = get_order(order2["id"]); code2 = o.pickup_code; db.close()
        c.post(f"/api/courier/v1/trip/{order2['id']}/pickup", headers=h, json={"code": code2})
        db, o = get_order(order2["id"])
        assert o.pickup_paid == plans.breakdown(o)["merchant_amount"]
        assert db.query(LedgerEntry).filter_by(order_id=o.id, account="merchant").count() == 0
        db.close()
        c.post(f"/api/courier/v1/trip/{order2['id']}/deliver", headers=h, json={"pin": ""})
    finally:
        setting("delivery_pin_required", None); setting("fleet_cash_store_amount", None)


def store_client():
    """Usuario del comercio burger-mix (no superadmin)."""
    from app.db import SessionLocal
    from app.models import Role, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        if not db.query(User).filter_by(email="local@test.local").first():
            db.add(User(email="local@test.local", password_hash=hash_password("Local-123!"), role=Role.STORE_ADMIN, store_id=store_id()))
            db.commit()
    c = client()
    assert c.post("/admin/login", data={"email": "local@test.local", "password": "Local-123!"}, follow_redirects=False).status_code == 303
    return c


def picked_up_cash_order(c, h):
    """Pedido en efectivo de la flota ya retirado: el cadete le pago al local."""
    from app.db import SessionLocal
    from app.models import Courier, Order, OrderStatus
    from app.services import dispatch
    from app.services.orders import set_status
    order = new_order(c, at=MID)
    with SessionLocal() as s:
        o = s.get(Order, order["id"]); assert set_status(o, OrderStatus.CONFIRMADO)
        dispatch.assign_manual(s, o, s.query(Courier).filter_by(name="Fede Flota").one()); s.commit()
    db, o = get_order(order["id"]); code = o.pickup_code; db.close()
    assert c.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=h, json={"code": code}).status_code == 200
    return order


def test_cancel_after_pickup_courier_gets_money_back(env):
    """El cliente no atiende: el cadete lo reporta, vuelve al local, el local le devuelve la plata y cancela."""
    from app.models import LedgerEntry, OrderStatus
    from app.services import finance
    fleet_store(); clear_zones(); zone(); setting("delivery_pin_required", "0")
    try:
        c, local = client(), store_client()
        h = courier_login(c)
        db, _ = get_order(1); courier_id = fleet_courier(db).id
        cash_before = finance.courier_cash_pending(db, courier_id); db.close()
        order = picked_up_cash_order(c, h)
        db, o = get_order(order["id"]); paid = o.pickup_paid; db.close()
        assert paid > 0
        # el cadete reporta que no pudo entregar
        trip = c.post("/api/courier/v1/pulse", headers=h, json={"online": True}).json()["trip"]
        assert {r["code"] for r in trip["fail_reasons"]} >= {"no_answer", "rejected"}
        r = c.post(f"/api/courier/v1/trip/{order['id']}/fail", headers=h, json={"reason": "no_answer"})
        assert r.status_code == 200 and r.json()["trip"]["failed"] == "El cliente no atiende"
        assert r.json()["trip"]["pay_store"] == float(paid)  # la app le dice cuánto le tiene que devolver el local
        board = local.get("/admin/comandas/board").text
        assert "no pudo entregar" in board and "Me devolvió el pedido" in board
        # el retiro no se puede deshacer y para cancelar hay que decir que paso con la plata
        r = local.post(f"/admin/orders/{order['id']}/status", data={"status": "LISTO"}, headers={"x-requested-with": "fetch"})
        assert r.status_code == 409
        r = local.post(f"/admin/orders/{order['id']}/status", data={"status": "CANCELADO"}, headers={"x-requested-with": "fetch"})
        assert r.status_code == 409 and "qué pasó con la plata" in r.json()["error"]
        r = local.post(f"/admin/orders/{order['id']}/status", data={"status": "CANCELADO", "resolution": "store_keeps"}, headers={"x-requested-with": "fetch"})
        assert r.status_code == 409 and "Trappi" in r.json()["error"]  # el local no puede elegir quedarse con la plata
        r = local.post(f"/admin/orders/{order['id']}/status", data={"status": "CANCELADO", "resolution": "returned"}, headers={"x-requested-with": "fetch"})
        assert r.status_code == 200, r.text
        db, o = get_order(order["id"])
        assert o.status == OrderStatus.CANCELADO and o.cancel_resolution == "returned"
        assert finance.courier_cash_pending(db, courier_id) == cash_before  # la caja del cadete vuelve a como estaba
        merchant = db.query(LedgerEntry).filter_by(order_id=o.id, account="merchant").all()
        assert sum(m.amount for m in merchant) == 0  # se anula la comision de una venta que no fue
        trip_pay = db.query(LedgerEntry).filter_by(order_id=o.id, account="courier_earnings").one()
        assert trip_pay.amount == o.courier_pay  # el viaje se le paga igual
        db.close()
        assert c.post("/api/courier/v1/pulse", headers=h, json={"online": True}).json()["trip"] is None  # queda libre
    finally:
        setting("delivery_pin_required", None)


def test_cancel_after_pickup_store_keeps_money_reimburses_courier(env):
    from app.models import LedgerEntry
    from app.services import finance
    fleet_store(); clear_zones(); zone(); setting("delivery_pin_required", "0"); setting("failed_delivery_pay_courier", "0")
    try:
        c, a = client(), admin_client()
        h = courier_login(c)
        db, _ = get_order(1); courier_id = fleet_courier(db).id
        cash_before = finance.courier_cash_pending(db, courier_id); db.close()
        order = picked_up_cash_order(c, h)
        page = a.get(f"/admin/orders/{order['id']}").text
        assert 'value="store_keeps"' in page and 'value="returned"' in page
        r = a.post(f"/admin/orders/{order['id']}/status", data={"status": "CANCELADO", "resolution": "store_keeps"}, follow_redirects=False)
        assert r.status_code == 303 and "error" not in r.headers["location"]
        db, o = get_order(order["id"])
        assert o.cancel_resolution == "store_keeps"
        assert finance.courier_cash_pending(db, courier_id) == cash_before  # no le queda plata negativa en la caja
        refund = db.query(LedgerEntry).filter_by(order_id=o.id, kind="reimbursement").one()
        assert refund.account == "courier_earnings" and refund.amount == o.pickup_paid  # Trappi se lo paga en su liquidacion
        assert db.query(LedgerEntry).filter_by(order_id=o.id, kind="trip").count() == 0  # con la opcion apagada no cobra el viaje
        db.close()
    finally:
        setting("delivery_pin_required", None); setting("failed_delivery_pay_courier", None)


def test_courier_can_still_deliver_after_reporting(env):
    fleet_store(); clear_zones(); zone(); setting("delivery_pin_required", "0")
    try:
        c = client(); h = courier_login(c)
        order = picked_up_cash_order(c, h)
        c.post(f"/api/courier/v1/trip/{order['id']}/fail", headers=h, json={"reason": "no_answer"})
        assert c.post(f"/api/courier/v1/trip/{order['id']}/fail", headers=h, json={"reason": "cualquiera"}).status_code == 409
        assert c.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=h, json={"pin": ""}).status_code == 200  # el cliente aparecio
        db, o = get_order(order["id"])
        assert o.delivery_failed_at is None and o.cancel_resolution is None
        db.close()
    finally:
        setting("delivery_pin_required", None)


def test_delivery_plan_has_no_transfer_and_comercio_plan_has_no_fleet_security(env):
    """Trappi Delivery: sin transferencia ni alias, con toda la seguridad de la flota.
    Trappi Comercio: con transferencia al alias del local y sin codigo de retiro ni pago al local."""
    from app.db import SessionLocal
    from app.models import Courier, Order, OrderStatus
    from app.services import dispatch
    from app.services.orders import set_status
    clear_zones(); zone(); setting("delivery_pin_required", "0")
    try:
        c, a = client(), admin_client()
        # ---- Trappi Delivery ----
        fleet_store(transfer_alias="burger.mix.mp")
        st = quote(c, MID)["store"]
        assert st["payment_methods"] == ["efectivo"] and st["transfer_alias"] is None
        r = c.post("/api/v1/orders", json={"items": [{"product_id": product_id(), "quantity": 1}], "delivery_method": "delivery", "first_name": "Ana",
                                           "phone": "2914000000", "address": "Alsina 100", "lat": MID[0], "lng": MID[1], "payment_method": "transferencia"})
        assert r.status_code == 400 and "no acepta transferencia" in r.json()["error"]
        c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
        page = c.get("/checkout").text
        assert 'value="efectivo"' in page and 'value="transferencia"' not in page and "burger.mix.mp" not in page
        assert "Sin transferencia (Trappi Delivery)" in a.get("/admin/stores").text
        # ---- Trappi Comercio con cadetes propios ----
        set_store(plan="TRAPPI_COMERCIO", commission_rate=D("0"), logistics="propia", fleet_enabled=False)
        st = quote(c, NEAR)["store"]
        assert st["payment_methods"] == ["efectivo", "transferencia"] and st["transfer_alias"] == "burger.mix.mp"
        order = new_order(c, at=NEAR)
        db, o = get_order(order["id"]); assert o.plan == "TRAPPI_COMERCIO"; db.close()
        ticket = a.get(f"/admin/comandas/ticket/{order['id']}").text
        assert "Código de retiro" not in ticket and "CADETE DE TRAPPI" not in ticket
        with SessionLocal() as s_:
            o = s_.get(Order, order["id"]); assert set_status(o, OrderStatus.CONFIRMADO)
            dispatch.assign_manual(s_, o, s_.query(Courier).filter_by(name="Lucía Propia").one()); s_.commit()
        h = {"Authorization": "Bearer " + c.post("/api/courier/v1/login", json={"phone": "2911111111", "pin": "1234"}).json()["token"]}
        trip = c.post("/api/courier/v1/pulse", headers=h, json={"online": True}).json()["trip"]
        assert trip["pickup_code_required"] is False and trip["pay_store"] == 0
        c.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=h)
        trip = c.post("/api/courier/v1/pulse", headers=h, json={"online": True}).json()["trip"]
        assert trip["fail_reasons"] == []
        assert c.post(f"/api/courier/v1/trip/{order['id']}/fail", headers=h, json={"reason": "no_answer"}).status_code == 409
        db, o = get_order(order["id"]); assert o.pickup_paid is None; db.close()
        c.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=h, json={"pin": ""})
        # ---- Trappi Comercio con la flota de respaldo: tampoco paga al local ni usa codigo ----
        set_store(logistics="mixta", fleet_enabled=True)
        order = new_order(c, at=NEAR)
        db, o = get_order(order["id"])
        from app.services import finance
        assert finance.store_cash_amount(db, o) is None and dispatch.pickup_info(o) is None
        db.close()
    finally:
        setting("delivery_pin_required", None); set_store(transfer_alias=None); fleet_store()


def test_cash_limit_counts_only_what_the_courier_keeps(env):
    """Lo que el cadete le paga al local de su bolsillo (y despues cobra) no cuenta para el limite:
    solo cuenta lo que le queda para rendir (envio, o envio + comision)."""
    from app.services import dispatch, finance
    fleet_store(); clear_zones(); zone(); setting("delivery_pin_required", "0")
    try:
        c = client(); h = courier_login(c)
        db, _ = get_order(1); courier = fleet_courier(db); before = finance.courier_cash_pending(db, courier.id); db.close()
        order = new_order(c, at=MID)
        db, o = get_order(order["id"])
        keeps = D(o.total) - finance.store_cash_amount(db, o)
        courier = fleet_courier(db)
        courier.cash_limit = before + keeps  # le alcanza justo para lo que va a rendir
        db.commit()
        assert keeps < D(o.total) and dispatch.eligible(db, o, courier)[0]  # aunque el total del pedido supere el limite
        courier.cash_limit = before + keeps - 1
        db.commit()
        assert not dispatch.eligible(db, o, courier)[0]
        courier.cash_limit = None
        db.commit(); db.close()
        # entregado: lo que tiene que rendir es exactamente total - lo que le pagó al local
        db, o = get_order(order["id"])
        from app.models import Courier, OrderStatus
        from app.services.orders import set_status
        assert set_status(o, OrderStatus.CONFIRMADO)
        dispatch.assign_manual(db, o, db.query(Courier).filter_by(name="Fede Flota").one()); db.commit(); db.close()
        db, o = get_order(order["id"]); code = o.pickup_code; db.close()
        c.post(f"/api/courier/v1/trip/{order['id']}/pickup", headers=h, json={"code": code})
        c.post(f"/api/courier/v1/trip/{order['id']}/deliver", headers=h, json={"pin": ""})
        db, o = get_order(order["id"])
        cash = finance.order_cash(o)
        assert cash["collected"] == D(o.total) and cash["paid_store"] == o.pickup_paid and cash["to_remit"] == keeps
        db.close()
        page = admin_client().get(f"/admin/orders/{order['id']}").text
        assert f"Tiene que rendirle a Trappi ${keeps:,.0f}".replace(",", ".") in page
        # rinde todo: el pedido queda en cero
        db, _ = get_order(1); pend = finance.courier_cash_pending(db, fleet_courier(db).id); cid = fleet_courier(db).id; db.close()
        admin_client().post("/admin/finanzas/rendiciones", data={"courier_id": cid, "received": str(pend)})
        db, o = get_order(order["id"]); assert finance.order_cash(o)["to_remit"] == 0; db.close()
        assert "Rendido a Trappi" in admin_client().get(f"/admin/orders/{order['id']}").text
    finally:
        setting("delivery_pin_required", None)


def test_courier_settlement_offsets_unremitted_cash(env):
    """El cadete debe efectivo y Trappi le debe sus viajes: se compensa y se le paga solo la diferencia."""
    from app.models import CashRemittance, CourierSettlement, Courier, LedgerEntry
    from app.services import finance
    db, _ = get_order(1)
    # arranca limpio: un cadete nuevo de la flota
    from app.services.auth import hash_password
    c = Courier(name="Compensa", phone="2915550001", pin_hash=hash_password("9999"))
    db.add(c); db.flush()
    finance.entry(db, 'courier_cash', 'cash_collected', D("15150"), courier_id=c.id, description="cobró al cliente")
    finance.entry(db, 'courier_cash', 'paid_to_store', D("-13400"), courier_id=c.id, description="le pagó al local")
    finance.entry(db, 'courier_earnings', 'trip', D("2500"), courier_id=c.id, description="viaje")
    db.commit()
    assert finance.courier_cash_pending(db, c.id) == D("1750.00")
    st = finance.create_courier_settlement(db, c, offset_cash=True)
    db.commit()
    assert (st.earnings, st.cash_offset, st.total) == (D("2500.00"), D("1750.00"), D("750.00"))  # le pagás $750
    assert finance.courier_cash_pending(db, c.id) == 0
    rem = db.get(CashRemittance, st.remittance_id)
    assert rem.received == D("1750.00") and rem.difference == 0 and "Compensado" in rem.notes
    # la liquidacion falla: vuelve a deber el efectivo y sus viajes quedan pendientes
    finance.set_settlement_status(db, st, "failed", notes="CVU mal")
    db.commit()
    assert finance.courier_cash_pending(db, c.id) == D("1750.00")
    assert finance.courier_box(db, c)["earnings_pending"] == D("2500.00")
    # si debe mas de lo que gana, se compensa hasta lo que gana y el resto lo sigue debiendo
    finance.entry(db, 'courier_cash', 'cash_collected', D("2000"), courier_id=c.id, description="otro pedido")
    db.commit()
    st2 = finance.create_courier_settlement(db, c, offset_cash=True)
    db.commit()
    assert st2.cash_offset == D("2500.00") and st2.total == 0
    assert finance.courier_cash_pending(db, c.id) == D("1250.00")  # 3750 - 2500
    finance.set_settlement_status(db, st2, "paid")
    db.commit()
    assert db.query(LedgerEntry).filter_by(courier_settlement_id=st2.id, settled=False).count() == 0
    # sin la opcion no se compensa
    finance.entry(db, 'courier_earnings', 'trip', D("1000"), courier_id=c.id, description="viaje 2")
    db.commit()
    st3 = finance.create_courier_settlement(db, c)
    db.commit()
    assert st3.cash_offset == 0 and st3.total == D("1000.00") and finance.courier_cash_pending(db, c.id) == D("1250.00")
    db.close()
    page = admin_client().get("/admin/finanzas/liquidaciones").text
    assert 'name="offset_cash"' in page and "Efectivo descontado" in page


def test_paid_orders_show_paid_on_ticket(env):
    from app.models import Order
    a = admin_client()
    db, o = get_order(1)
    o.paid_at, o.paid_by, o.payment_method = datetime.utcnow(), "online", "mercadopago"
    oid = o.id
    db.commit(); db.close()
    ticket = a.get(f"/admin/comandas/ticket/{oid}").text
    assert "YA PAGADO" in ticket and "NO COBRAR" in ticket


def courier_login(c):
    r = c.post("/api/courier/v1/login", json={"phone": "2912222222", "pin": "5678"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_cash_flags_block_courier(env):
    from app.services import dispatch
    fleet_store(); clear_zones(); zone()
    c = client()
    order = new_order(c, at=MID)
    db, o = get_order(order["id"])
    courier = fleet_courier(db)
    courier.cash_orders_enabled = False
    assert not dispatch.eligible(db, o, courier)[0]
    courier.cash_orders_enabled, courier.online_orders_enabled = True, False
    o.paid_at = datetime.utcnow()
    assert not dispatch.eligible(db, o, courier)[0]
    db.rollback(); db.close()


# ==================== liquidaciones ====================

def test_merchant_and_courier_settlements(env):
    from app.models import CourierSettlement, LedgerEntry, MerchantSettlement
    from app.services import finance
    a = admin_client()
    sid = store_id()
    db, _ = get_order(1)
    pending = finance.merchant_balance(db, sid)["pending"]
    assert pending != 0
    db.close()
    assert a.post("/admin/finanzas/liquidaciones/comercios", data={"store_id": str(sid)}, follow_redirects=False).status_code == 303
    db, _ = get_order(1)
    st = db.query(MerchantSettlement).filter_by(store_id=sid).order_by(MerchantSettlement.id.desc()).first()
    assert st.total == pending and st.status == "pending"
    for status in ("processing", "paid"):
        assert a.post(f"/admin/finanzas/liquidaciones/comercio/{st.id}", data={"status": status, "receipt": "TRF-1"}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(MerchantSettlement, st.id).status == "paid" and finance.merchant_balance(db, sid)["pending"] == 0
    with pytest.raises(finance.FinanceError):
        finance.set_settlement_status(db, db.get(MerchantSettlement, st.id), "cancelled")  # pagada no cambia
    # repartidor: datos de cobro enmascarados y cifrados
    courier = fleet_courier(db)
    with pytest.raises(finance.FinanceError):
        finance.save_payout_account(db, courier, holder="Fede", cbu="123")
    r = a.post(f"/admin/repartidores/{courier.id}/pago", data={"holder": "Federico Flota", "cvu": "0000003100012345678901", "reason": "alta"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    acct = finance.payout_account(db, courier.id)
    assert acct.last4 == "8901" and "0000003100012345678901" not in (acct.cvu_enc or "")
    assert "8901" in finance.masked_account(acct) and "31000123" not in finance.masked_account(acct)
    earned = finance._sum(db, "courier_earnings", LedgerEntry.courier_id == courier.id, LedgerEntry.settled.is_(False))
    assert earned > 0
    db.close()
    r = a.post("/admin/finanzas/liquidaciones/repartidores", data={"courier_id": str(courier.id), "bonuses": "1000", "notes": "semana"}, follow_redirects=False)
    assert r.status_code == 303
    db, _ = get_order(1)
    cs = db.query(CourierSettlement).filter_by(courier_id=courier.id).one()
    assert cs.total == earned + 1000 and cs.account_masked.startswith("CVU •••• 8901")
    a.post(f"/admin/finanzas/liquidaciones/repartidor/{cs.id}", data={"status": "failed", "notes": "CVU rechazado"}, follow_redirects=False)
    db.expire_all()
    # fallida: los viajes vuelven a quedar pendientes y el bono se anula
    assert finance.courier_box(db, fleet_courier(db))["earnings_pending"] == earned
    db.close()


# ==================== Mercado Pago: OAuth, Split, webhooks, devoluciones ====================

def test_mp_oauth_connect_stores_encrypted_tokens(env):
    from app.models import MercadoPagoAccount
    fleet_store(); clear_zones(); zone()
    a = admin_client()
    r = a.get(f"/admin/pagos/mercadopago/conectar?store={store_id()}", follow_redirects=False)
    assert r.status_code == 303
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "auth.mercadopago.com.ar" and q["client_id"] == ["test-client"] and "client_secret" not in q
    bad = a.get("/admin/pagos/mercadopago/callback?code=abc&state=forged", follow_redirects=False)
    assert bad.status_code == 303
    r = a.get(f"/admin/pagos/mercadopago/callback?code=TG-code&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 303
    db, _ = get_order(1)
    acct = db.query(MercadoPagoAccount).filter_by(store_id=store_id()).one()
    assert acct.status == "connected" and acct.mp_user_id == "777" and acct.nickname == "BURGERMIX"
    assert "APP_USR-seller-token" not in acct.access_token_enc and "TG-refresh" not in acct.refresh_token_enc
    db.close()
    page = a.get(f"/admin/pagos?store={store_id()}")
    assert page.status_code == 200 and "APP_USR-seller-token" not in page.text and "TG-refresh" not in page.text


def test_mp_order_split_and_approved_webhook(env):
    from app.models import LedgerEntry, OrderStatus, Payment
    from app.services import dispatch, orders, plans
    fleet_store(); clear_zones(); zone()
    mp = env["mp"]
    c = client()
    assert quote(c, MID)["store"]["mp_available"] is True
    order = new_order(c, at=MID, method="mercadopago")
    assert order["pay_path"]
    db, o = get_order(order["id"])
    assert o.payment_status == "pending" and not dispatch.needs_courier(o)
    assert not orders.set_status(o, OrderStatus.CONFIRMADO)  # el local no lo puede aceptar sin el pago
    db.rollback()
    b = plans.breakdown(o)
    db.close()
    r = c.get(order["pay_path"], follow_redirects=False)
    assert r.status_code in (302, 303) and r.headers["location"].startswith("https://mp.example/sandbox/")
    pref = mp.preferences[-1]
    assert pref["marketplace_fee"] == float(b["trappi_amount"]) and pref["external_reference"] == f"trappi-order-{order['id']}"
    assert pref["items"][0]["unit_price"] == float(o.total)
    assert pref["notification_url"].startswith("http://testserver/api/payments/mercadopago/webhook")
    # el admin no puede marcarlo pagado a mano
    a = admin_client()
    a.post(f"/admin/pedidos/{order['id']}/pagado", follow_redirects=False)
    db, o = get_order(order["id"])
    assert o.paid_at is None
    db.close()
    # firma invalida: no se toca nada
    mp.pay(9001, order["id"], o.total, fee=b["trappi_amount"])
    assert webhook(c, 9001, secret="otra").status_code == 401
    db, o = get_order(order["id"])
    assert o.paid_at is None
    db.close()
    r = webhook(c, 9001)
    assert r.status_code == 200 and r.json()["result"] == "pending->approved"
    assert webhook(c, 9001).json()["result"] == "duplicado"  # el mismo aviso dos veces
    db, o = get_order(order["id"])
    assert o.paid_at and o.paid_by == "online" and o.payment_status == "approved" and o.payment_processing_fee == D("120.00")
    p = db.query(Payment).filter_by(order_id=o.id).one()
    assert p.status == "approved" and p.marketplace_fee == b["trappi_amount"] and p.seller_amount == o.total - b["trappi_amount"]
    split = db.query(LedgerEntry).filter_by(order_id=o.id, kind="online_split").one()
    assert split.settled and split.amount == b["merchant_amount"]
    assert orders.set_status(o, OrderStatus.CONFIRMADO)  # ahora si
    db.commit()
    assert dispatch.needs_courier(o)
    db.close()
    # otro aviso del mismo pago (otro request-id) no duplica movimientos
    webhook(c, 9001, request_id="req-2")
    db, o = get_order(order["id"])
    assert db.query(LedgerEntry).filter_by(order_id=o.id, kind="online_split").count() == 1
    db.close()
    env["paid_order"] = order["id"]


def test_mp_rejected_mismatch_and_foreign_payments(env):
    from app.models import AuditLog
    fleet_store(); clear_zones(); zone()
    mp, c = env["mp"], client()
    order = new_order(c, at=MID, method="mercadopago")
    c.get(order["pay_path"], follow_redirects=False)
    db, o = get_order(order["id"])
    total = o.total
    db.close()
    mp.pay(9002, order["id"], total, status="rejected")
    assert webhook(c, 9002).json()["result"] == "pending->rejected"
    db, o = get_order(order["id"])
    assert o.paid_at is None and o.payment_status == "rejected"
    db.close()
    mp.pay(9003, order["id"], D(total) - 100)  # cobro de menos: no se aprueba
    assert "importe" in webhook(c, 9003).json()["result"]
    mp.pay(9004, order["id"], total, collector="999")  # lo cobro otra cuenta
    assert "otra cuenta" in webhook(c, 9004).json()["result"]
    mp.payments["9005"] = {**mp.payments["9004"], "id": 9005, "external_reference": "otra-cosa", "collector_id": 777}
    assert "no es un pedido" in webhook(c, 9005).json()["result"]
    assert webhook(c, 123456).status_code == 500  # el pago no existe en MP: se reintenta mas tarde
    db, o = get_order(order["id"])
    assert o.paid_at is None and db.query(AuditLog).filter_by(action="payment.mismatch", entity_id=o.id).count() == 1
    db.close()
    # pago aprobado que llego sin aviso: se recupera al volver del checkout
    mp.pay(9006, order["id"], total)
    c.get(f"/pedido/{order['id']}?t={order['token']}&pago=ok")
    db, o = get_order(order["id"])
    assert o.paid_at is not None
    db.close()


def test_mp_split_by_plan(env):
    """Trappi Comercio: el 100 % entra al comercio. Trappi Delivery: Trappi se queda su comision (+ el envio de su flota)."""
    from app.models import LedgerEntry, Payment
    mp, c = env["mp"], client()
    clear_zones(); zone()
    setting("delivery_pin_required", "0")
    try:
        # ---- Trappi Comercio (0 %), cadetes propios ----
        set_store(plan="TRAPPI_COMERCIO", commission_rate=D("0"), logistics="propia", fleet_enabled=False, delivery_fee_payer=None,
                  commission_fixed=None, commission_min=None, commission_max=None)
        order = new_order(c, at=NEAR, method="mercadopago")
        c.get(order["pay_path"], follow_redirects=False)
        assert "marketplace_fee" not in mp.preferences[-1]  # Trappi no se lleva nada
        db, o = get_order(order["id"]); total = o.total; db.close()
        mp.pay(9101, order["id"], total)
        assert webhook(c, 9101).json()["result"] == "pending->approved"
        db, o = get_order(order["id"])
        p = db.query(Payment).filter_by(order_id=o.id, status="approved").one()
        assert p.marketplace_fee == 0 and p.seller_amount == total
        db.close()
        # ---- Trappi Delivery (15 %), flota ----
        fleet_store(commission_rate=D("15"))
        order = new_order(c, at=MID, method="mercadopago")
        c.get(order["pay_path"], follow_redirects=False)
        db, o = get_order(order["id"])
        products = D(o.subtotal) - D(o.discount)
        trappi = (products * D("0.15")).quantize(D("0.01")) + D(o.shipping)  # 15 % de lo vendido + el envio (lo cobra Trappi y le paga al cadete)
        total = o.total
        db.close()
        assert mp.preferences[-1]["marketplace_fee"] == float(trappi)
        mp.pay(9102, order["id"], total, fee=trappi)
        webhook(c, 9102)
        db, o = get_order(order["id"])
        p = db.query(Payment).filter_by(order_id=o.id, status="approved").one()
        assert p.marketplace_fee == trappi and p.seller_amount == total - trappi
        db.close()
        # ---- Trappi Comercio con la flota de respaldo: si al final la lleva la flota, el envio se le debe a Trappi ----
        set_store(plan="TRAPPI_COMERCIO", commission_rate=D("0"), logistics="mixta", fleet_enabled=True)
        order = new_order(c, at=NEAR, method="mercadopago")
        c.get(order["pay_path"], follow_redirects=False)
        assert "marketplace_fee" not in mp.preferences[-1]
        db, o = get_order(order["id"]); total, shipping = o.total, D(o.shipping); db.close()
        mp.pay(9103, order["id"], total)
        webhook(c, 9103)
        deliver_with_fleet(order["id"])
        db, o = get_order(order["id"])
        gap = db.query(LedgerEntry).filter_by(order_id=o.id, kind="split_difference").one()
        assert shipping > 0 and gap.amount == -shipping
        assert db.query(LedgerEntry).filter_by(order_id=o.id, account="courier_earnings").count() == 1
        db.close()
    finally:
        setting("delivery_pin_required", None)
        fleet_store()


def test_mp_refund(env):
    from app.models import LedgerEntry, Payment
    a = admin_client()
    db, _ = get_order(env["paid_order"])
    p = db.query(Payment).filter_by(order_id=env["paid_order"], status="approved").one()
    pid, amount = p.id, p.amount
    db.close()
    r = a.post(f"/admin/finanzas/pagos/{pid}/devolver", data={"amount": "", "reason": "pedido cancelado"}, follow_redirects=False)
    assert r.status_code == 303
    db, o = get_order(env["paid_order"])
    p = db.get(Payment, pid)
    assert p.status == "refunded" and p.refunded_amount == amount and o.payment_status == "refunded"
    refund = db.query(LedgerEntry).filter_by(order_id=o.id, kind="refund").one()
    assert refund.amount == -amount
    assert any(path.endswith("/refunds") for _, path, _ in env["mp"].requests)
    db.close()


def test_mp_unavailable_without_connection(env):
    from app.db import SessionLocal
    from app.models import MercadoPagoAccount
    a = admin_client()
    a.post("/admin/pagos/mercadopago/desconectar", data={"store": str(store_id())}, follow_redirects=False)
    with SessionLocal() as db:
        acct = db.query(MercadoPagoAccount).filter_by(store_id=store_id()).one()
        assert acct.status == "disconnected" and acct.access_token_enc is None
    c = client()
    assert quote(c, MID)["store"]["mp_available"] is False
    r = c.post("/api/v1/orders", json={"items": [{"product_id": product_id(), "quantity": 1}], "delivery_method": "delivery", "first_name": "Ana",
                                       "phone": "2914000000", "address": "Alsina 100", "lat": MID[0], "lng": MID[1], "payment_method": "mercadopago"})
    assert r.status_code == 400


def test_webhook_without_secret_only_in_sandbox(env):
    from app.config import settings
    from app.services import mercadopago
    settings.mercadopago_webhook_secret = ""
    try:
        assert mercadopago.verify_signature({}, {}) is True
        settings.mercadopago_environment = "production"
        assert mercadopago.verify_signature({}, {}) is False
    finally:
        settings.mercadopago_webhook_secret, settings.mercadopago_environment = SECRET, "sandbox"


def test_unpaid_online_orders_expire(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Payment
    from app.services import mercadopago
    with SessionLocal() as db:
        base = db.query(Order).order_by(Order.id).first()
        old = datetime.utcnow() - timedelta(hours=2)
        def clone():
            o = Order(store_id=base.store_id, customer_id=base.customer_id, status=OrderStatus.PENDIENTE, delivery_method="pickup", subtotal=D("1000"),
                      shipping=D("0"), discount=D("0"), total=D("1000"), payment_method="mercadopago", payment_status="pending", created_at=old)
            db.add(o); db.flush()
            return o
        no_link, with_link, fresh = clone(), clone(), clone()
        fresh.created_at = datetime.utcnow()
        db.add(Payment(order_id=with_link.id, provider="mercadopago", status="pending", amount=D("1000"), preference_id="pref-x", expires_at=old))
        db.commit()
        ids = no_link.id, with_link.id, fresh.id
    with SessionLocal() as db:
        assert mercadopago.expire_stale(db) >= 2
    with SessionLocal() as db:
        a, b, c = (db.get(Order, i) for i in ids)
        assert a.status == b.status == OrderStatus.CANCELADO and a.payment_status == b.payment_status == "expired"
        assert c.status == OrderStatus.PENDIENTE  # todavia esta a tiempo de pagar
        assert db.query(Payment).filter_by(order_id=b.id).one().status == "expired"


# ==================== quien entrega lo define el plan ====================

def test_plan_defines_who_delivers(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import plans
    with pytest.raises(plans.PlanError):
        plans.validate("TRAPPI_DELIVERY", 0, 10, "propia")
    with pytest.raises(plans.PlanError):
        plans.validate("TRAPPI_COMERCIO", 10000, 0, "trappi")
    a, sid = admin_client(), store_id()
    # Trappi Delivery: siempre la flota; el comercio no lo puede cambiar
    fleet_store(fleet_enabled=False)
    page = a.get(f"/admin/pagos?store={sid}").text
    assert "Tu plan incluye la flota de Trappi" in page and 'name="method"' not in page
    a.post("/admin/pagos/entrega", data={"method": "propia", "store": str(sid)}, follow_redirects=False)
    with SessionLocal() as db:
        assert db.get(Store, sid).logistics == "trappi"
    # pasar a Trappi Comercio con cadetes propios apaga la flota
    r = a.post(f"/admin/comercios/{sid}/plan", data={"plan": "TRAPPI_COMERCIO", "logistics": "propia"}, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert (s.plan, s.logistics, s.fleet_enabled) == ("TRAPPI_COMERCIO", "propia", False)
    page = a.get(f"/admin/pagos?store={sid}").text
    assert 'name="method"' not in page
    a.post("/admin/pagos/entrega", data={"method": "mixta", "store": str(sid)}, follow_redirects=False)
    with SessionLocal() as db:
        assert db.get(Store, sid).logistics == "propia"  # sin la flota habilitada no la puede activar
    # Trappi le habilita la flota de respaldo: ahora el comercio elige
    set_store(fleet_enabled=True)
    page = a.get(f"/admin/pagos?store={sid}").text
    assert 'value="mixta"' in page and 'value="trappi"' not in page
    a.post("/admin/pagos/entrega", data={"method": "mixta", "store": str(sid)}, follow_redirects=False)
    a.post("/admin/pagos/entrega", data={"method": "trappi", "store": str(sid)}, follow_redirects=False)  # la flota entera es Trappi Delivery
    with SessionLocal() as db:
        assert db.get(Store, sid).logistics == "mixta"
    # un Trappi Comercio no puede quedar con la flota entera desde la ficha
    r = a.post(f"/admin/comercios/{sid}/plan", data={"plan": "TRAPPI_COMERCIO", "logistics": "trappi"}, follow_redirects=False)
    with SessionLocal() as db:
        assert db.get(Store, sid).logistics == "mixta"
    fleet_store()


# ==================== diagnostico de Mercado Pago ====================

def test_mp_diagnostics_page_and_credentials_test(env):
    from app.config import settings
    a = admin_client()
    webhook(client(), 4242, secret="mala")  # queda anotado como rechazado
    page = a.get("/admin/pagos/diagnostico")
    assert page.status_code == 200
    assert "test-secret" not in page.text and "whsec-test" not in page.text  # nunca se muestran los secretos
    assert "MERCADOPAGO_REDIRECT_URI" in page.text and "firma inválida" in page.text
    assert "http://testserver/admin/pagos/mercadopago/callback" in page.text
    r = a.post("/admin/pagos/diagnostico/probar", follow_redirects=True)
    assert "Mercado Pago aceptó CLIENT_ID y CLIENT_SECRET" in r.text
    old_env = settings.mercadopago_environment
    settings.mercadopago_environment = "clavepegadaporerror1234"
    try:
        page = a.get("/admin/pagos/diagnostico").text
        assert "clavepegadaporerror1234" not in page and "valor no válido" in page
    finally:
        settings.mercadopago_environment = old_env
    old = settings.mercadopago_redirect_uri
    settings.mercadopago_redirect_uri = "https://otro-sitio.com/callback"
    try:
        assert "No coincide con este sitio" in a.get("/admin/pagos/diagnostico").text
    finally:
        settings.mercadopago_redirect_uri = old
    assert client().get("/admin/pagos/diagnostico", follow_redirects=False).status_code in (302, 303)


def test_pasted_settings_are_cleaned_and_any_encryption_key_works(env):
    from app.config import Settings, settings
    from app.services import crypto
    cleaned = Settings(mercadopago_client_id=' "123456" \n', mercadopago_client_secret="abc \n", mercadopago_environment=" Sandbox ")
    assert cleaned.mercadopago_client_id == "123456" and cleaned.mercadopago_client_secret == "abc" and cleaned.mercadopago_sandbox
    old = settings.field_encryption_key
    settings.field_encryption_key = "una frase cualquiera, no es Fernet"
    try:
        assert crypto.key_status() == "derived" and crypto.decrypt(crypto.encrypt("APP_USR-1")) == "APP_USR-1"
    finally:
        settings.field_encryption_key = old


def test_public_base_forces_https_in_production(env):
    from app.config import settings
    from app.routers.public import public_base

    class R:
        base_url = "http://pidomix-1.onrender.com/"

    old_env, old_base = settings.environment, settings.public_base_url
    settings.environment, settings.public_base_url = "production", ""
    try:
        assert public_base(R()) == "https://pidomix-1.onrender.com"
    finally:
        settings.environment, settings.public_base_url = old_env, old_base


# ==================== paneles ====================

@pytest.mark.parametrize("path", ["/admin/logistica", "/admin/logistica/zonas", "/admin/logistica/configuracion", "/admin/logistica/rentabilidad",
                                  "/admin/finanzas", "/admin/finanzas/rendiciones", "/admin/finanzas/liquidaciones", "/admin/finanzas/pagos",
                                  "/admin/finanzas/auditoria", "/admin/configuracion/comisiones", "/admin/pagos", "/admin/repartidores/1/pago",
                                  "/admin/pagos/diagnostico"])
def test_admin_pages_render(env, path):
    r = admin_client().get(path)
    assert r.status_code == 200, r.text[:500]


def test_admin_pages_need_superadmin(env):
    c = client()
    for path in ("/admin/logistica/zonas", "/admin/finanzas", "/admin/configuracion/comisiones"):
        assert c.get(path, follow_redirects=False).status_code in (302, 303)
