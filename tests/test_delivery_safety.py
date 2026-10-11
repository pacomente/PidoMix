"""Seguridad de la entrega: el local no cancela después de aceptar, espera en la puerta con foto, chat con fotos."""
import io
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

STORE = (-38.7183, -62.2663)
DOOR = (-38.7200, -62.2700)
FAR = (-38.7400, -62.2300)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("safety") / "safety.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import Courier, Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        store.lat, store.lng = STORE
        db.add_all([Courier(name="Fede Flota", phone="2912222222", pin_hash=hash_password("5678")),
                    User(email="local@test.local", password_hash=hash_password("Local-Test-123!"), role=Role.STORE_ADMIN, store_id=store.id)])
        db.commit()
    yield TestClient(app)
    engine.dispose()


def jpeg(color=(200, 30, 30)) -> bytes:
    from PIL import Image
    from PIL.ExifTags import Base as Exif
    img = Image.new("RGB", (2400, 1200), color)
    exif = img.getexif()
    exif[Exif.Make] = "CamaraConGPS"
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def courier(c):
    r = c.post("/api/courier/v1/login", json={"phone": "2912222222", "pin": "5678"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def new_order(status="EN_CAMINO", paid_store=False, method="delivery"):
    """Un pedido de la flota ya retirado por el cadete (o en el estado que se pida)."""
    from app.db import SessionLocal
    from app.models import Courier, Customer, Order, OrderStatus, Store
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        fede = db.query(Courier).filter_by(phone="2912222222").one()
        cust = Customer(first_name="Ana", last_name="Paz", phone="2914000000")
        db.add(cust); db.flush()
        o = Order(store_id=store.id, customer_id=cust.id, status=OrderStatus[status], delivery_method=method, address="Alsina 100",
                  lat=DOOR[0], lng=DOOR[1], subtotal=Decimal("6000"), shipping=Decimal("1500"), total=Decimal("7500"), payment_method="efectivo",
                  logistics="trappi", delivery_mode="trappi", courier_id=fede.id if status == "EN_CAMINO" else None, courier_pay=Decimal("1500"),
                  pickup_paid=Decimal("6000") if paid_store else None)
        db.add(o); db.commit()
        from app.routers.public import order_token
        return o.id, order_token(o.id)


def store_login(c):
    c.cookies.clear()
    r = c.post("/admin/login", data={"email": "local@test.local", "password": "Local-Test-123!"}, follow_redirects=False)
    assert r.status_code in (302, 303), r.text


def cancel_as_store(c, oid):
    return c.post(f"/admin/orders/{oid}/status", data={"status": "CANCELADO"}, headers={"X-Requested-With": "fetch"})


def test_local_solo_rechaza_antes_de_aceptar(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    store_login(env)
    pend, _ = new_order("PENDIENTE")
    conf, _ = new_order("CONFIRMADO")
    retiro, _ = new_order("LISTO", method="retiro")
    assert cancel_as_store(env, pend).json()["ok"]  # rechazar un pedido nuevo: sí
    r = cancel_as_store(env, conf)  # ya aceptado: no
    assert r.status_code == 409 and "lo cancela Trappi" in r.json()["error"]
    assert cancel_as_store(env, retiro).json()["ok"]  # retiro listo y el cliente no vino: sí
    page = env.get(f"/admin/orders/{conf}").text
    assert "Pedir la cancelación por WhatsApp" in page or "lo hace Trappi" in page
    # Trappi sí puede
    env.cookies.clear()
    env.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    assert cancel_as_store(env, conf).json()["ok"]
    with SessionLocal() as db:
        assert db.get(Order, conf).status == OrderStatus.CANCELADO and db.get(Order, pend).status == OrderStatus.CANCELADO


def test_llegue_espera_y_no_aparecio_con_foto(env):
    from app.db import SessionLocal
    from app.models import Order, OrderPhoto, OrderStatus
    h = courier(env)
    oid, tok = new_order()
    # lejos de la puerta: no deja marcar "Llegué"
    r = env.post(f"/api/courier/v1/trip/{oid}/arrived", headers=h, json={"lat": FAR[0], "lng": FAR[1]})
    assert r.status_code == 409 and "Todavía estás a" in r.json()["error"]
    st = env.post(f"/api/courier/v1/trip/{oid}/arrived", headers=h, json={"lat": DOOR[0], "lng": DOOR[1]}).json()
    assert st["trip"]["safety"]["arrived"] and st["trip"]["safety"]["wait_left"] > 250
    # el cliente ve que llegó y el aviso en el chat
    assert env.get(f"/api/v1/orders/{oid}?t={tok}").json()["courier_arrived"]
    chat = env.get(f"/api/v1/orders/{oid}/chat?t={tok}").json()
    assert chat["messages"][0]["sender"] == "system" and "llegó" in chat["messages"][0]["text"]
    # antes de los 5 minutos no se puede cancelar
    r = env.post(f"/api/courier/v1/trip/{oid}/noshow", headers=h, files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 409 and "Esperá" in r.json()["error"]
    with SessionLocal() as db:
        db.get(Order, oid).courier_arrived_at = datetime.utcnow() - timedelta(minutes=6)
        db.commit()
    # sin una foto de verdad, no
    r = env.post(f"/api/courier/v1/trip/{oid}/noshow", headers=h, files={"photo": ("p.jpg", b"no soy una foto", "image/jpeg")})
    assert r.status_code == 400
    r = env.post(f"/api/courier/v1/trip/{oid}/noshow", headers=h, files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["noshow"]["result"] == "cancelled" and data["noshow"]["earnings"] == 1500 and data["trip"] is None
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.status == OrderStatus.CANCELADO and "no apareció" in o.delivery_fail_reason
        p = db.get(OrderPhoto, o.proof_photo_id)
        assert p.kind == "no_aparecio" and max(p.width, p.height) <= 1600 and b"CamaraConGPS" not in p.content  # achicada y sin EXIF
        proof = o.proof_photo_id
    # el cliente ve la foto de prueba; el local, el aviso en su chat con la foto
    assert env.get(f"/api/v1/orders/{oid}/photos/{proof}?t={tok}").headers["content-type"] == "image/jpeg"
    assert env.get(f"/api/v1/orders/{oid}/photos/{proof}?t=malo").status_code == 404
    store_login(env)
    local = env.get(f"/admin/orders/{oid}/chat?thread=local").json()
    assert "no apareció" in local["messages"][0]["text"] and local["messages"][0]["photo"].endswith(f"/photos/{proof}")
    assert env.get(f"/admin/orders/{oid}/photos/{proof}").status_code == 200
    assert env.get(f"/admin/orders/{oid}/chat?thread=cliente").status_code == 404  # el local no lee el chat con el cliente


def test_no_aparecio_con_plata_del_local_queda_para_devolver(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    h = courier(env)
    oid, _ = new_order(paid_store=True)
    env.post(f"/api/courier/v1/trip/{oid}/arrived", headers=h, json={"lat": DOOR[0], "lng": DOOR[1]})
    with SessionLocal() as db:
        db.get(Order, oid).courier_arrived_at = datetime.utcnow() - timedelta(minutes=6)
        db.commit()
    data = env.post(f"/api/courier/v1/trip/{oid}/noshow", headers=h, files={"photo": ("p.jpg", jpeg(), "image/jpeg")}).json()
    assert data["noshow"]["result"] == "returning" and data["trip"]["failed"]
    with SessionLocal() as db:
        assert db.get(Order, oid).status == OrderStatus.EN_CAMINO  # vuelve al local con el pedido
    # el local puede cancelarlo cuando se lo devuelven (devolviendo la plata)
    store_login(env)
    r = env.post(f"/admin/orders/{oid}/status", data={"status": "CANCELADO", "resolution": "returned"}, headers={"X-Requested-With": "fetch"})
    assert r.json()["ok"], r.text


def test_chat_cadete_cliente_y_local_con_fotos(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    h = courier(env)
    oid, tok = new_order()
    r = env.post(f"/api/courier/v1/trip/{oid}/chat", headers=h, json={"thread": "cliente", "text": "Estoy en la esquina, ¿bajás?"})
    assert r.status_code == 200, r.text
    r = env.post(f"/api/v1/orders/{oid}/chat", json={"t": tok, "text": "¡Ya bajo!"})
    assert r.status_code == 200
    assert env.post(f"/api/v1/orders/{oid}/chat", json={"t": "malo", "text": "hola"}).status_code == 404
    r = env.post(f"/api/v1/orders/{oid}/chat/photo", data={"t": tok}, files={"photo": ("p.jpg", jpeg((0, 0, 200)), "image/jpeg")})
    assert r.status_code == 200, r.text
    msgs = env.get(f"/api/courier/v1/trip/{oid}/chat?thread=cliente", headers=h).json()["messages"]
    assert [m["sender"] for m in msgs] == ["courier", "customer", "customer"] and msgs[2]["photo"]
    assert env.get(msgs[2]["photo"], headers=h).status_code == 200  # el cadete ve la foto del cliente
    # cadete <-> local
    env.post(f"/api/courier/v1/trip/{oid}/chat/photo", headers=h, data={"thread": "local"}, files={"photo": ("p.jpg", jpeg(), "image/jpeg")})
    store_login(env)
    local = env.get(f"/admin/orders/{oid}/chat?thread=local").json()
    assert local["can_write"] and local["messages"][-1]["sender"] == "courier" and local["messages"][-1]["photo"]
    r = env.post(f"/admin/orders/{oid}/chat", data={"text": "Gracias, ahí lo bajo"})
    assert r.status_code == 200 and r.json()["ok"]
    after = local["messages"][-1]["id"]
    assert [m["text"] for m in env.get(f"/api/courier/v1/trip/{oid}/chat?thread=local&after={after}", headers=h).json()["messages"]] == ["Gracias, ahí lo bajo"]
    # el cliente no ve las fotos del chat con el local
    local_photo = local["messages"][-1]["photo"].rsplit("/", 1)[1]
    assert env.get(f"/api/v1/orders/{oid}/photos/{local_photo}?t={tok}").status_code == 404
    # entregado: se puede leer un rato, no escribir
    with SessionLocal() as db:
        db.get(Order, oid).status = OrderStatus.ENTREGADO
        db.commit()
    c = env.get(f"/api/v1/orders/{oid}/chat?t={tok}").json()
    assert c["ok"] and not c["can_write"]
    assert env.post(f"/api/v1/orders/{oid}/chat", json={"t": tok, "text": "otra"}).status_code == 409


def test_foto_obligatoria_al_entregar(env):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        db.add(Setting(key="delivery_photo_required", value="1")); db.commit()
    platform.invalidate()
    try:
        h = courier(env)
        oid, _ = new_order()
        r = env.post(f"/api/courier/v1/trip/{oid}/deliver", headers=h, json={"pin": ""})
        assert r.status_code == 409 and "sacá la foto" in r.json()["error"]
        st = env.post(f"/api/courier/v1/trip/{oid}/photo", headers=h, files={"photo": ("p.jpg", jpeg(), "image/jpeg")}).json()
        assert st["trip"]["safety"]["photo"]
        r = env.post(f"/api/courier/v1/trip/{oid}/deliver", headers=h, json={"pin": ""})
        assert "sacá la foto" not in r.text
    finally:
        with SessionLocal() as db:
            db.query(Setting).filter_by(key="delivery_photo_required").delete(); db.commit()
        platform.invalidate()


def test_fotos_viejas_se_borran(env):
    from app.db import SessionLocal
    from app.models import OrderPhoto
    from app.services import delivery_safety
    with SessionLocal() as db:
        n = db.query(OrderPhoto).count()
        assert n > 0
        assert delivery_safety.purge_old(db, datetime.utcnow() + timedelta(days=61)) == n
        assert db.query(OrderPhoto).count() == 0


def test_asistente_de_voz(env):
    from app.ai import providers
    h = courier(env)
    oid, tok = new_order()
    ask = lambda text, **kw: env.post("/api/courier/v1/assistant", headers=h, json={"text": text, **kw}).json()
    r = ask("¿cuánto falta?", lat=FAR[0], lng=FAR[1])
    assert "Vas a Alsina 100" in r["reply"] and "Cobrás" in r["reply"] and r["action"] is None
    # avisar al cliente: lo manda por el chat del pedido
    r = ask("avisale al cliente que llego en cinco minutos")
    assert "Llego en 5 minutos." in r["reply"]
    msgs = env.get(f"/api/v1/orders/{oid}/chat?t={tok}").json()["messages"]
    assert msgs[-1]["sender"] == "courier" and msgs[-1]["text"] == "Llego en 5 minutos."
    # llegué: valida el GPS como el botón
    assert "Todavía estás a" in ask("llegué", lat=FAR[0], lng=FAR[1])["reply"]
    r = ask("ya llegué", lat=DOOR[0], lng=DOOR[1])
    assert "le avisé" in r["reply"] and r["action"] == {"type": "refresh"} and r["state"]["trip"]["safety"]["arrived"]
    assert ask("callate")["action"] == {"type": "mute"}
    assert ask("cuánto gané hoy")["reply"].startswith("Hoy llevás")
    assert ask("llevame a la zona con pedidos")["reply"].startswith("Primero terminá")  # con viaje en curso
    # algo que las reglas no entienden y sin IA: ayuda, sin hacer nada
    r = ask("bla bla ble")
    assert r["reply"].startswith("No te entendí") and r["action"] is None

    # con un modelo configurado, el modelo solo elige una de las acciones permitidas
    class Fake:
        def chat(self, messages, tools):
            assert tools == []  # sin herramientas: no puede hacer nada por su cuenta
            return providers.AIReply(text='{"intent": "avisar", "to": "local", "minutes": null, "text": "se me pinchó la rueda, llego tarde"}', tool_calls=[])
    providers.set_override(Fake())
    try:
        r = ask("ufff tuve un problema con la moto")
        assert "el local" in r["reply"]
    finally:
        providers.set_override(None)
    store_login(env)
    local = env.get(f"/admin/orders/{oid}/chat?thread=local").json()["messages"]
    assert local[-1]["text"] == "Se me pinchó la rueda, llego tarde."
