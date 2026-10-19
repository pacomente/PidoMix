"""Trappi Viajes: empresas con su flota, tarifas, cotizacion, despacho a conductores de la empresa, PIN, panel y permisos."""
import os
import sys
from datetime import date, datetime, timedelta

import pytest

BASE = (-38.7183, -62.2663)
PAX = (-38.7200, -62.2700)       # el pasajero
NEAR = (-38.7205, -62.2705)      # ~70 m del pasajero
MID = (-38.7300, -62.2800)       # ~1,7 km
DEST = (-38.7500, -62.3000)      # ~4,5 km del pasajero


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("rides") / "rides.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import ClientAccount
    from app.services import rides
    rides.TICK_EVERY = 0  # en los tests cada pulso avanza las ofertas al instante
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        db.add_all([ClientAccount(email="ana@test.local", first_name="Ana", phone="2914000000"),
                    ClientAccount(email="otro@test.local", first_name="Otro")])
        db.commit()
    yield TestClient(app)
    engine.dispose()


def loc(r):
    from urllib.parse import unquote_plus
    return unquote_plus(r.headers["location"])


def setting(key, value):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        row = db.query(Setting).filter_by(key=key).first()
        if row: row.value = value
        else: db.add(Setting(key=key, value=value))
        db.commit()
    platform.invalidate()


def account_auth(email):
    from app.db import SessionLocal
    from app.models import ClientAccount
    from app.services import accounts
    with SessionLocal() as db:
        return {"Authorization": "Bearer " + accounts.app_token(db.query(ClientAccount).filter_by(email=email).one())}


def admin(c):
    from fastapi.testclient import TestClient
    from app.main import app
    a = TestClient(app)
    r = a.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False)
    assert r.status_code == 303
    return a


def company_client(email="remises@test.local", password="Remises-123"):
    from fastapi.testclient import TestClient
    from app.main import app
    a = TestClient(app)
    r = a.post("/admin/login", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303 and loc(r) == "/admin/empresa", r.text
    return a


def driver_login(c, phone, pin):
    r = c.post("/api/courier/v1/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def at(c, h, where, online=True):
    r = c.post("/api/courier/v1/pulse", json={"lat": where[0], "lng": where[1], "online": online}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def company():
    from app.db import SessionLocal
    from app.models import RideCompany
    with SessionLocal() as db:
        return db.query(RideCompany).filter_by(slug="remises-alem").one().id


def add_driver(co, name, phone, vehicle, plate):
    r = co.post("/admin/empresa/conductores", data={"name": name, "phone": phone, "vehicle": vehicle, "plate": plate, "car_model": "Fiat Cronos gris"},
                follow_redirects=False)
    assert r.status_code == 303
    with co:  # el PIN se muestra una vez (queda en la sesion hasta la proxima pantalla)
        page = co.get("/admin/empresa/conductores").text
    import re
    m = re.search(r"PIN de [^:]+: <span[^>]*>(\d{4})</span>", page)
    assert m, "no se mostró el PIN"
    return m.group(1)


@pytest.fixture(scope="module")
def setup(env):
    c = env
    sa = admin(c)
    r = sa.post("/admin/viajes", data={"name": "Remises Alem", "phone": "2914555555", "plan": "inicial",
                                        "owner_email": "remises@test.local", "owner_password": "Remises-123"}, follow_redirects=False)
    assert r.status_code == 303 and "creada" in loc(r)
    co = company_client()
    # la empresa no entra al panel de los comercios
    assert co.get("/admin/stores", follow_redirects=False).headers["location"] == "/admin/empresa"
    assert co.get("/admin", follow_redirects=False).headers["location"] == "/admin/empresa"
    assert co.get("/admin/viajes", follow_redirects=False).headers["location"] == "/admin/empresa"
    r = co.post("/admin/empresa/tarifas", data={"auto_enabled": "1", "auto_base": "1500", "auto_per_km": "560", "auto_per_wait_min": "90",
                                                 "auto_minimum": "2500", "auto_night_percent": "0",
                                                 "moto_enabled": "1", "moto_base": "900", "moto_per_km": "300", "moto_per_wait_min": "50",
                                                 "moto_minimum": "1500", "moto_night_percent": "0"}, follow_redirects=False)
    assert r.status_code == 303 and "guardadas" in loc(r)
    pins = {"auto1": add_driver(co, "Martín Gómez", "2915000001", "auto", "ae 123 bc"),
            "auto2": add_driver(co, "Laura Pérez", "2915000002", "auto", "AF456DE"),
            "moto": add_driver(co, "Diego Ruiz", "2915000003", "moto", "A012KLM")}
    return {"sa": sa, "co": co, "pins": pins}


def test_approval_needs_license_and_insurance(env, setup):
    sa, co = setup["sa"], setup["co"]
    cid = company()
    r = sa.post(f"/admin/viajes/{cid}", data={"plan": "inicial", "action": "approve"}, follow_redirects=False)
    assert "falta" in loc(r)
    expired = (date.today() - timedelta(days=1)).isoformat()
    co.post("/admin/empresa/habilitacion", data={"legal_name": "Remises Alem SRL", "cuit": "30-12345678-9", "municipal_license": "HAB-123",
                                                 "insurance_company": "La Segunda", "insurance_policy": "POL-9", "insurance_expires": expired})
    r = sa.post(f"/admin/viajes/{cid}", data={"plan": "inicial", "action": "approve"}, follow_redirects=False)
    assert "vencido" in loc(r)
    co.post("/admin/empresa/habilitacion", data={"legal_name": "Remises Alem SRL", "cuit": "30-12345678-9", "municipal_license": "HAB-123",
                                                 "insurance_company": "La Segunda", "insurance_policy": "POL-9",
                                                 "insurance_expires": (date.today() + timedelta(days=200)).isoformat()})
    r = sa.post(f"/admin/viajes/{cid}", data={"plan": "inicial", "action": "approve"}, follow_redirects=False)
    assert "guardado" in loc(r)
    from app.db import SessionLocal
    from app.models import AuditLog, RideCompany
    with SessionLocal() as db:
        co_row = db.get(RideCompany, cid)
        assert co_row.status == "activa" and co_row.approved_at is not None
        assert db.query(AuditLog).filter_by(action="ride.company_approve").count() == 1
    # aprobada: la habilitacion ya no la cambia la empresa
    co.post("/admin/empresa/habilitacion", data={"municipal_license": "OTRA", "legal_name": "x"})
    with SessionLocal() as db:
        assert db.get(RideCompany, cid).municipal_license == "HAB-123"


def test_driver_cap_and_unique_phone(env, setup):
    sa, co = setup["sa"], setup["co"]
    cid = company()
    sa.post(f"/admin/viajes/{cid}", data={"plan": "inicial", "driver_cap": "3", "action": "save"})
    r = co.post("/admin/empresa/conductores", data={"name": "Cuarto", "phone": "2915000004", "vehicle": "auto", "plate": "AA111AA"}, follow_redirects=False)
    assert "permite hasta 3" in loc(r)
    sa.post(f"/admin/viajes/{cid}", data={"plan": "inicial", "driver_cap": "", "action": "save"})
    # el telefono de un repartidor de comida (o de otra empresa) no se puede usar
    from app.db import SessionLocal
    from app.models import Courier
    from app.services.auth import hash_password
    with SessionLocal() as db:
        db.add(Courier(name="Repartidor", phone="2916000000", pin_hash=hash_password("1111"))); db.commit()
    r = co.post("/admin/empresa/conductores", data={"name": "X", "phone": "2916000000", "vehicle": "auto", "plate": "AA111AA"}, follow_redirects=False)
    assert "ya está registrado" in loc(r)


def test_module_off_by_default(env, setup):
    c = env
    assert c.get("/api/v1/config").json()["rides"]["enabled"] is False
    assert c.get("/api/v1/rides/available").json()["enabled"] is False
    r = c.post("/api/v1/rides/quote", json={"origin": {"lat": PAX[0], "lng": PAX[1]}, "dest": {"lat": DEST[0], "lng": DEST[1]}})
    assert r.status_code == 409


def test_full_ride(env, setup):
    c, pins = env, setup["pins"]
    setting("rides_enabled", "1")
    assert c.get("/api/v1/rides/available").json() == {"enabled": True, "companies": 1, "vehicles": ["auto", "moto"]}
    h1 = driver_login(c, "2915000001", pins["auto1"])
    h2 = driver_login(c, "2915000002", pins["auto2"])
    hm = driver_login(c, "2915000003", pins["moto"])
    st = at(c, h1, MID)
    assert st["mode"] == "rides" and st["courier"]["fleet"] == "empresa" and st["courier"]["plate"] == "AE 123 BC"
    at(c, h2, NEAR); at(c, hm, NEAR)

    q = c.post("/api/v1/rides/quote", json={"origin": {"lat": PAX[0], "lng": PAX[1]}, "dest": {"lat": DEST[0], "lng": DEST[1]}}).json()
    auto = next(o for o in q["options"] if o["vehicle"] == "auto")
    from decimal import Decimal
    from app.services import rides
    expected = rides.round_price(max(Decimal("1500") + Decimal("560") * Decimal(str(round(q["km"], 2))), Decimal("2500")))
    if not q["night"]:
        assert Decimal(str(auto["price"])) == expected
    assert auto["available"] and auto["eta_min"] >= 1

    body = {"company_id": company(), "vehicle": "auto", "price": 1,  # el precio que mande la app se ignora
            "origin": {"lat": PAX[0], "lng": PAX[1], "address": "Av. Alem 120", "note": "puerta del edificio"},
            "dest": {"lat": DEST[0], "lng": DEST[1], "address": "Terminal de ómnibus"}}
    assert c.post("/api/v1/rides", json=body).status_code == 401  # sin cuenta no se pide
    ana = account_auth("ana@test.local")
    r = c.post("/api/v1/rides", json=body, headers=ana)
    assert r.status_code == 200, r.text
    ride = r.json()["ride"]
    assert ride["status"] == "buscando" and ride["price"] == auto["price"] and len(ride["pin"]) == 4
    assert c.post("/api/v1/rides", json=body, headers=ana).status_code == 409  # uno por vez
    assert c.get(f"/api/v1/rides/{ride['id']}", headers=account_auth("otro@test.local")).status_code == 404

    # se le ofrece al auto mas cercano (Laura), no a la moto ni a Martín
    assert at(c, hm, NEAR)["ride_offer"] is None
    assert at(c, h1, MID)["ride_offer"] is None
    offer = at(c, h2, NEAR)["ride_offer"]
    assert offer and offer["ride_id"] == ride["id"] and offer["price"] == ride["price"] and offer["pickup"]["note"] == "puerta del edificio"
    # Laura la rechaza: pasa a Martín
    c.post(f"/api/courier/v1/rides/offers/{offer['id']}/reject", headers=h2)
    offer = at(c, h1, MID)["ride_offer"]
    assert offer and offer["ride_id"] == ride["id"]
    st = c.post(f"/api/courier/v1/rides/offers/{offer['id']}/accept", headers=h1).json()
    assert st["ride"]["status"] == "asignado" and st["ride"]["passenger"]["name"] == "Ana" and st["ride"]["passenger"]["phone"] == "2914000000"
    assert c.post("/api/courier/v1/pulse", json={"online": False}, headers=h1).status_code == 409  # no se desconecta en viaje

    seen = c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]
    assert seen["status"] == "asignado" and seen["driver"]["plate"] == "AE 123 BC" and seen["driver"]["name"] == "Martín"
    assert seen["tracking"]["driver"] and seen["tracking"]["eta_min"] >= 1 and seen["pin"] == ride["pin"]

    # llegar: sin boton, el GPS lo marca solo al estar en la puerta (lejos no)
    r = c.post(f"/api/courier/v1/rides/{ride['id']}/arrive", headers=h1)
    assert r.status_code == 409 and "lejos" in r.json()["error"]
    assert at(c, h1, MID)["ride"]["status"] == "asignado"
    st = at(c, h1, NEAR)
    assert st["ride"]["status"] == "en_puerta" and st["ride"]["waited_seconds"] is not None
    assert c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]["label"] == "Tu conductor llegó"
    # PIN
    wrong = "0000" if ride["pin"] != "0000" else "1111"
    r = c.post(f"/api/courier/v1/rides/{ride['id']}/start", json={"pin": wrong}, headers=h1)
    assert r.status_code == 409
    assert c.post(f"/api/courier/v1/rides/{ride['id']}/start", json={"pin": ride["pin"]}, headers=h2).status_code == 409  # otro conductor
    # 10 minutos esperando en la puerta (3 gratis): se cobran 7 minutos de espera
    from app.db import SessionLocal
    from app.models import Ride
    with SessionLocal() as db:
        row = db.get(Ride, ride["id"]); row.arrived_at = datetime.utcnow() - timedelta(minutes=10); db.commit()
    st = c.post(f"/api/courier/v1/rides/{ride['id']}/start", json={"pin": ride["pin"]}, headers=h1).json()
    assert st["ride"]["status"] == "en_viaje"
    assert c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]["pin"] is None
    assert c.post(f"/api/v1/rides/{ride['id']}/cancel", headers=ana).status_code == 409  # ya arrancó
    done = c.post(f"/api/courier/v1/rides/{ride['id']}/finish", headers=h1).json()
    assert done["finished"]["wait_charge"] == 630 and done["finished"]["total"] == ride["price"] + 630
    assert done["ride"] is None and done["earnings"]["trips_today"] == 1

    final = c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]
    assert final["status"] == "finalizado" and final["can_rate"] and final["driver"]["phone"] is None
    r = c.post(f"/api/v1/rides/{ride['id']}/rate", json={"stars": 5, "tags": ["Puntual", "inventado"]}, headers=ana)
    assert r.status_code == 200 and r.json()["ride"]["rating"] == 5
    assert c.post(f"/api/v1/rides/{ride['id']}/rate", json={"stars": 1}, headers=ana).status_code == 409
    with SessionLocal() as db:
        row = db.get(Ride, ride["id"])
        assert row.rating_tags == "Puntual" and float(row.company.rating_avg) == 5.0 and row.courier.rating_count == 1
    assert len(c.get("/api/v1/rides", headers=ana).json()["rides"]) == 1


def test_driver_cancel_researches_and_timeout(env, setup):
    c, pins = env, setup["pins"]
    h1 = driver_login(c, "2915000001", pins["auto1"])
    h2 = driver_login(c, "2915000002", pins["auto2"])
    at(c, h1, NEAR); at(c, h2, MID)
    ana = account_auth("ana@test.local")
    body = {"company_id": company(), "vehicle": "auto", "origin": {"lat": PAX[0], "lng": PAX[1]}, "dest": {"lat": DEST[0], "lng": DEST[1]}}
    ride = c.post("/api/v1/rides", json=body, headers=ana).json()["ride"]
    offer = at(c, h1, NEAR)["ride_offer"]
    c.post(f"/api/courier/v1/rides/offers/{offer['id']}/accept", headers=h1)
    assert c.post(f"/api/courier/v1/rides/{ride['id']}/cancel", json={"reason": "nada"}, headers=h1).status_code == 409
    st = c.post(f"/api/courier/v1/rides/{ride['id']}/cancel", json={"reason": "vehiculo"}, headers=h1).json()
    assert st["ride"] is None
    # vuelve a buscar: le llega a Laura, no de nuevo a Martín
    assert at(c, h1, NEAR)["ride_offer"] is None
    assert at(c, h2, MID)["ride_offer"]["ride_id"] == ride["id"]
    seen = c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]
    assert seen["status"] == "buscando" and "canceló" in seen["cancel_reason"]
    # nadie acepta a tiempo: sin conductor
    from app.db import SessionLocal
    from app.models import Ride
    with SessionLocal() as db:
        row = db.get(Ride, ride["id"]); row.search_from = datetime.utcnow() - timedelta(minutes=30); db.commit()
    assert c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]["status"] == "sin_conductor"
    assert at(c, h2, MID)["ride_offer"] is None


def test_passenger_cancel_and_company_cancel(env, setup):
    c, pins, co = env, setup["pins"], setup["co"]
    h2 = driver_login(c, "2915000002", pins["auto2"])
    at(c, h2, NEAR)
    ana = account_auth("ana@test.local")
    body = {"company_id": company(), "vehicle": "auto", "origin": {"lat": PAX[0], "lng": PAX[1]}, "dest": {"lat": DEST[0], "lng": DEST[1]}}
    ride = c.post("/api/v1/rides", json=body, headers=ana).json()["ride"]
    assert c.post(f"/api/v1/rides/{ride['id']}/cancel", headers=account_auth("otro@test.local")).status_code == 404
    assert c.post(f"/api/v1/rides/{ride['id']}/cancel", headers=ana).json()["ride"]["status"] == "cancelado"
    assert at(c, h2, NEAR)["ride_offer"] is None  # la oferta se cae
    ride = c.post("/api/v1/rides", json=body, headers=ana).json()["ride"]
    r = co.post(f"/admin/empresa/viajes/{ride['id']}/cancelar", data={"reason": "Sin móviles"}, follow_redirects=False)
    assert r.status_code == 303
    seen = c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]
    assert seen["status"] == "cancelado" and seen["cancel_reason"] == "Sin móviles"


def test_ride_drivers_never_get_food_and_panels_are_isolated(env, setup):
    c, co, sa = env, setup["co"], setup["sa"]
    from app.db import SessionLocal
    from app.models import Courier, Order, Store
    from app.services import dispatch
    with SessionLocal() as db:
        d = db.query(Courier).filter_by(phone="2915000001").one()
        o = db.query(Order).first() or Order(store_id=db.query(Store).first().id)
        o.store = o.store or db.query(Store).first()
        assert dispatch.allowed(o, d) is False
        assert d.id not in {x.id for x in dispatch.available(db)}
    # el panel de repartidores del superadmin no muestra a los conductores de las empresas
    assert "Martín Gómez" not in sa.get("/admin/repartidores").text
    sa.get(f"/admin/empresa?c={company()}")  # el superadmin abre el panel de la empresa (soporte)
    assert "Martín Gómez" in sa.get("/admin/empresa/conductores").text
    # otra empresa no puede tocar a los conductores de esta
    sa.post("/admin/viajes", data={"name": "Taxis Sur", "plan": "inicial", "owner_email": "sur@test.local", "owner_password": "Taxis-123!"})
    other = company_client("sur@test.local", "Taxis-123!")
    with SessionLocal() as db:
        did = db.query(Courier).filter_by(phone="2915000001").one().id
    other.post(f"/admin/empresa/conductores/{did}/toggle")
    other.post(f"/admin/empresa/conductores/{did}/pin")
    with SessionLocal() as db:
        d = db.get(Courier, did)
        assert d.active and d.token_version == 1
    assert "Martín Gómez" not in other.get("/admin/empresa/conductores").text
    assert other.get("/admin/empresa/vivo.json").json()["drivers"] == []
    # una empresa pendiente no aparece para los clientes
    assert c.get("/api/v1/rides/available").json()["companies"] == 1


def test_suspended_company_disappears(env, setup):
    c, sa, pins = env, setup["sa"], setup["pins"]
    h2 = driver_login(c, "2915000002", pins["auto2"])
    at(c, h2, NEAR)
    ana = account_auth("ana@test.local")
    body = {"company_id": company(), "vehicle": "auto", "origin": {"lat": PAX[0], "lng": PAX[1]}, "dest": {"lat": DEST[0], "lng": DEST[1]}}
    ride = c.post("/api/v1/rides", json=body, headers=ana).json()["ride"]
    sa.post(f"/admin/viajes/{company()}", data={"plan": "inicial", "action": "suspend", "note": "Seguro en revisión"})
    assert c.get("/api/v1/rides/available").json()["enabled"] is False
    assert c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]["status"] == "cancelado"
    assert c.post("/api/v1/rides", json=body, headers=ana).status_code == 409
    sa.post(f"/admin/viajes/{company()}", data={"plan": "inicial", "action": "reactivate"})
    assert c.get("/api/v1/rides/available").json()["enabled"] is True


def test_ride_without_note_and_suspended_offer(env, setup):
    """La indicación es opcional (la app manda null) y una oferta de una empresa recién suspendida no se puede aceptar."""
    c, sa, pins = env, setup["sa"], setup["pins"]
    at(c, driver_login(c, "2915000001", pins["auto1"]), NEAR, online=False)  # Martín desconectado: le toca a Laura
    h2 = driver_login(c, "2915000002", pins["auto2"])
    at(c, h2, NEAR)
    ana = account_auth("ana@test.local")
    body = {"company_id": company(), "vehicle": "auto", "origin": {"lat": PAX[0], "lng": PAX[1], "address": None, "note": None},
            "dest": {"lat": DEST[0], "lng": DEST[1], "address": "Terminal"}}
    r = c.post("/api/v1/rides", json=body, headers=ana)
    assert r.status_code == 200, r.text
    st = at(c, h2, NEAR)
    offer = st["ride_offer"]
    assert offer and offer["pickup"]["note"] is None, (st, r.json())
    # la suspenden con la oferta en la pantalla del conductor: no la puede aceptar
    from app.db import SessionLocal
    from app.models import RideCompany
    with SessionLocal() as db:
        db.get(RideCompany, company()).status = "suspendida"; db.commit()
    assert c.post(f"/api/courier/v1/rides/offers/{offer['id']}/accept", headers=h2).status_code == 409
    with SessionLocal() as db:
        db.get(RideCompany, company()).status = "activa"; db.commit()
    c.post(f"/api/v1/rides/{r.json()['ride']['id']}/cancel", headers=ana)


def test_insurance_renewal_needs_review(env, setup):
    """Con la empresa aprobada, la renovación del seguro no cuenta hasta que Trappi la aprueba."""
    sa, co = setup["sa"], setup["co"]
    from app.db import SessionLocal
    from app.models import RideCompany
    with SessionLocal() as db:
        before = db.get(RideCompany, company()).insurance_expires
    far = (date.today() + timedelta(days=3000)).isoformat()
    r = co.post("/admin/empresa/habilitacion", data={"insurance_policy": "POL-NUEVA", "insurance_expires": far}, follow_redirects=False)
    assert "Trappi la revisa" in loc(r)
    with SessionLocal() as db:
        row = db.get(RideCompany, company())
        assert row.insurance_expires == before and row.insurance_policy == "POL-9"
        assert row.insurance_pending_policy == "POL-NUEVA" and row.insurance_pending_expires.isoformat() == far
    sa.post(f"/admin/viajes/{company()}", data={"plan": "inicial", "action": "approve_insurance"})
    with SessionLocal() as db:
        row = db.get(RideCompany, company())
        assert row.insurance_policy == "POL-NUEVA" and row.insurance_expires.isoformat() == far and row.insurance_pending_expires is None


def test_company_changes_its_password(env, setup):
    from fastapi.testclient import TestClient
    from app.main import app
    sa = setup["sa"]
    sa.post("/admin/viajes", data={"name": "Motos Ya", "plan": "inicial", "owner_email": "motos@test.local", "owner_password": "Inicial-123"})
    co = company_client("motos@test.local", "Inicial-123")
    other = company_client("motos@test.local", "Inicial-123")  # otra sesión abierta con la contraseña vieja
    assert "Cambiar la contraseña" in co.get("/admin/empresa/cuenta").text
    r = co.post("/admin/empresa/cuenta", data={"current": "mal", "new": "Nueva-12345", "confirm": "Nueva-12345"}, follow_redirects=False)
    assert "no es correcta" in loc(r)
    r = co.post("/admin/empresa/cuenta", data={"current": "Inicial-123", "new": "Nueva-12345", "confirm": "Nueva-12345"}, follow_redirects=False)
    assert "cambiada" in loc(r)
    assert other.get("/admin/empresa", follow_redirects=False).headers["location"].startswith("/admin/login")
    assert co.get("/admin/empresa", follow_redirects=False).status_code == 200
    company_client("motos@test.local", "Nueva-12345")
    assert TestClient(app).post("/admin/login", data={"email": "motos@test.local", "password": "Inicial-123"}, follow_redirects=False).status_code == 401


def test_arrive_button_when_gps_is_off(env, setup):
    """A ~350 m el GPS no marca la llegada solo, pero el conductor la puede avisar con "Llegué"."""
    c, pins = env, setup["pins"]
    near_ish = (-38.7225, -62.2725)
    from app.services.geo import distance_km
    assert 0.25 < distance_km(*near_ish, *PAX) < 0.4
    at(c, driver_login(c, "2915000002", pins["auto2"]), MID, online=False)
    h1 = driver_login(c, "2915000001", pins["auto1"])
    at(c, h1, near_ish)
    ana = account_auth("ana@test.local")
    body = {"company_id": company(), "vehicle": "auto", "origin": {"lat": PAX[0], "lng": PAX[1]}, "dest": {"lat": DEST[0], "lng": DEST[1]}}
    ride = c.post("/api/v1/rides", json=body, headers=ana).json()["ride"]
    offer = at(c, h1, near_ish)["ride_offer"]
    c.post(f"/api/courier/v1/rides/offers/{offer['id']}/accept", headers=h1)
    assert at(c, h1, near_ish)["ride"]["status"] == "asignado"
    st = c.post(f"/api/courier/v1/rides/{ride['id']}/arrive", headers=h1).json()
    assert st["ride"]["status"] == "en_puerta"
    assert c.get(f"/api/v1/rides/{ride['id']}", headers=ana).json()["ride"]["label"] == "Tu conductor llegó"
    c.post(f"/api/v1/rides/{ride['id']}/cancel", headers=ana)
