"""Estoy a full, agotados, avisos al dueño (notificacion web), pedidos programados, direcciones guardadas y "Te puede gustar"."""
import os
import sys
from datetime import datetime, timedelta

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("owner") / "owner.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.main import app
    from app.models import ClientAccount, Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email="dueno@test.local", password_hash=hash_password("Dueno-1234"), role=Role.STORE_ADMIN, store_id=store.id, active=True))
        db.add_all([ClientAccount(email="ana@test.local", first_name="Ana", phone="2914000000"), ClientAccount(email="beto@test.local", first_name="Beto")])
        db.commit()
    yield TestClient(app)
    engine.dispose()


def owner():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.post("/admin/login", data={"email": "dueno@test.local", "password": "Dueno-1234"}, follow_redirects=False).status_code == 303
    return c


def auth(email):
    from app.db import SessionLocal
    from app.models import ClientAccount
    from app.services import accounts
    with SessionLocal() as db:
        return {"Authorization": "Bearer " + accounts.app_token(db.query(ClientAccount).filter_by(email=email).one())}


def store():
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        return db.query(Store).filter_by(slug="burger-mix").one().id


def products():
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        return {p.name: p.id for p in db.query(Product).all()}


def test_estoy_a_full_demora_y_pausa(env):
    c = owner()
    sid = store()
    r = c.post("/admin/comandas/demora", data={"mode": "30"}, follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/admin/comandas").text
    assert "Los clientes ven 60–70 min" in page and 'aria-pressed="true">+30 min' in page
    shop = env.get("/tienda/burger-mix").text
    assert "Mucha demanda ahora" in shop and "60–70 min" in shop
    api_store = env.get("/api/v1/stores/burger-mix").json()["store"]
    assert api_store["eta_min"] == 60 and api_store["busy"] is True
    # la demora vence sola
    from app.db import SessionLocal
    from app.models import AuditLog, Store
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert s.busy_extra == 30
        s.busy_until = datetime.utcnow() - timedelta(minutes=1); db.commit()
        assert db.get(Store, sid).prep_minutes == 30
    # pausar 1 hora: no entran pedidos nuevos y el cliente ve hasta cuando
    c.post("/admin/comandas/demora", data={"mode": "pause"})
    assert "Pausado hasta las" in c.get("/admin/comandas").text
    detail = env.get("/api/v1/stores/burger-mix").json()["store"]
    assert detail["is_open"] is False and detail["open_text"].startswith("Vuelve a tomar pedidos a las")
    pid = products()["Coca Cola"]
    r = env.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000"})
    assert r.status_code == 400
    c.post("/admin/comandas/demora", data={"mode": "normal"})
    assert env.get("/api/v1/stores/burger-mix").json()["store"]["is_open"] is True
    with SessionLocal() as db:
        assert {a.action for a in db.query(AuditLog).filter(AuditLog.action.like("store.busy.%"))} >= {"store.busy.30", "store.busy.pause", "store.busy.normal"}
    # un modo inventado no cambia nada; sin sesion, al login
    c.post("/admin/comandas/demora", data={"mode": "999"})
    with SessionLocal() as db:
        assert db.get(Store, sid).busy_minutes is None
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post("/admin/comandas/demora", data={"mode": "30"}, follow_redirects=False).status_code in (303, 403)


def test_agotados_con_un_toque(env):
    c = owner()
    pid = products()["Coca Cola"]
    html = c.get("/admin/comandas/stock").text
    assert f'data-stock="{pid}"' in html and "Disponible" in html
    html = c.post(f"/admin/comandas/stock/{pid}").text
    assert "Agotado" in html
    assert env.post("/api/cart/add", json={"product_id": pid, "quantity": 1, "modifiers": []}).status_code in (400, 409)
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        assert db.get(Product, pid).stock == 0
    c.post(f"/admin/comandas/stock/{pid}")
    with SessionLocal() as db:
        assert db.get(Product, pid).stock is None
    # producto de otro local: no se toca
    with SessionLocal() as db:
        from app.models import Store
        other = Store(name="Otro", slug="otro-local"); db.add(other); db.flush()
        p = Product(name="Ajeno", price=10, store_id=other.id); db.add(p); db.commit(); foreign = p.id
    c.post(f"/admin/comandas/stock/{foreign}")
    with SessionLocal() as db:
        assert db.get(Product, foreign).stock is None


def _decrypt(body: bytes, ua_private, auth_secret: bytes) -> bytes:
    """El lado del navegador (RFC 8291), para comprobar que el cifrado es el correcto."""
    import hashlib
    import hmac
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from app.services.webpush import _raw_public
    salt, idlen = body[:16], body[20]
    as_public = body[21:21 + idlen]
    cipher = body[21 + idlen:]
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    hm = lambda k, d: hmac.new(k, d, hashlib.sha256).digest()
    ua_public = _raw_public(ua_private.public_key())
    ikm = hm(hm(auth_secret, shared), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = hm(salt, ikm)
    plain = AESGCM(hm(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]).decrypt(hm(prk, b"Content-Encoding: nonce\x00\x01")[:12], cipher, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def browser_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from app.services.webpush import _raw_public, b64u
    key = ec.generate_private_key(ec.SECP256R1())
    secret = os.urandom(16)
    return key, secret, b64u(_raw_public(key.public_key())), b64u(secret)


def test_web_push_cifrado_y_claves(env):
    import jwt
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import crypto, webpush
    key, secret, p256dh, auth_b64 = browser_keys()
    body = webpush.encrypt(b'{"title":"hola"}', p256dh, auth_b64)
    assert _decrypt(body, key, secret) == b'{"title":"hola"}'
    with SessionLocal() as db:
        private, public = webpush.vapid_keys(db)
        stored = db.query(Setting).filter_by(key=webpush.PRIVATE_KEY).one().value
        assert "PRIVATE KEY" not in stored and "PRIVATE KEY" in crypto.decrypt(stored)  # la privada queda cifrada
        header = webpush._vapid_header(private, public, "https://fcm.googleapis.com/fcm/send/abc")
    token = header.split("t=")[1].split(",")[0]
    claims = jwt.decode(token, private.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert webpush.allowed_endpoint("https://fcm.googleapis.com/fcm/send/x")
    assert webpush.allowed_endpoint("https://web.push.apple.com/abc") and webpush.allowed_endpoint("https://wns2-bl2p.notify.windows.com/w/?token=1")
    for bad in ("http://fcm.googleapis.com/x", "https://evil.com/fcm.googleapis.com", "https://fcm.googleapis.com.evil.com/x", "https://127.0.0.1/"):
        assert not webpush.allowed_endpoint(bad)


def test_avisos_al_dueno(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Order, StorePushSubscription
    from app.services import owner_alerts, webpush
    sent = []
    monkeypatch.setattr(webpush, "send", lambda db, sub, data, ttl=600: sent.append(data) or "ok")
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: sent.append(data))
    c = owner()
    _, _, p256dh, auth_b64 = browser_keys()
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/dueno-1", "keys": {"p256dh": p256dh, "auth": auth_b64}, "label": "Android Chrome"}
    bad = c.post("/admin/comandas/push/subscribe", json={**sub, "endpoint": "https://example.com/push"})
    assert bad.status_code == 400
    assert c.post("/admin/comandas/push/subscribe", json=sub).json()["ok"]
    assert sent and sent[-1]["title"].startswith("✅")  # la de prueba
    info = c.get("/admin/comandas/push/key?endpoint=" + sub["endpoint"]).json()
    assert info["subscribed"] and info["devices"] == 1 and len(info["key"]) > 80
    # sin sesion del panel no se puede suscribir nadie
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post("/admin/comandas/push/subscribe", json=sub).status_code in (401, 403)
    sent.clear()
    pid = products()["Coca Cola"]
    r = env.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000"})
    oid = r.json()["id"]
    with SessionLocal() as db:
        owner_alerts.tick(db, force=True)
        assert sent and "Pedido nuevo" in sent[0]["title"] and f"#{oid}" in sent[0]["body"]
        owner_alerts.tick(db, force=True)  # no se repite
        assert len([d for d in sent if "Pedido nuevo" in d["title"]]) == 1
        # a los 3 minutos sin aceptar
        owner_alerts.tick(db, now=datetime.utcnow() + timedelta(minutes=4), force=True)
        assert any("sin aceptar" in d["title"] for d in sent)
        n = len(sent)
        owner_alerts.tick(db, now=datetime.utcnow() + timedelta(minutes=5), force=True)
        assert len(sent) == n
    # el dueño apaga el aviso de "sin aceptar": no le llega en el pedido siguiente
    assert c.post("/admin/comandas/push/alerts", json={"alert_late": False}).json()["alerts"]["alert_late"] is False
    oid2 = env.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000"}).json()["id"]
    sent.clear()
    with SessionLocal() as db:
        owner_alerts.tick(db, now=datetime.utcnow() + timedelta(minutes=4), force=True)
        assert [d for d in sent if "Pedido nuevo" in d["title"]] and not [d for d in sent if "sin aceptar" in d["title"]]
        assert db.get(Order, oid2).store_alerted_at is not None
    # un dispositivo que el navegador dio de baja se borra solo
    monkeypatch.setattr(webpush, "send", lambda db, sub, data, ttl=600: "gone")
    with SessionLocal() as db:
        owner_alerts.push_store(db, store(), {"title": "x"})
        assert db.query(StorePushSubscription).count() == 0


def test_resumen_del_dia(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Store, StorePushSubscription
    from app.services import owner_alerts, webpush
    from app.services.store_hours import to_local
    sent = []
    monkeypatch.setattr(webpush, "send", lambda db, sub, data, ttl=600: sent.append(data) or "ok")
    sid = store()
    now = datetime.utcnow()
    local = to_local(now)
    # las 23:30 de hoy (hora local) en UTC
    at = now + timedelta(hours=23 - local.hour, minutes=30 - local.minute)
    with SessionLocal() as db:
        db.add(StorePushSubscription(store_id=sid, endpoint="https://fcm.googleapis.com/fcm/send/resumen", p256dh="x", auth="y"))
        for o in db.query(Order).filter_by(store_id=sid):
            o.status, o.created_at = OrderStatus.ENTREGADO, at - timedelta(hours=1)
        db.commit()
        owner_alerts.tick(db, now=at, force=True)
        summary = [d for d in sent if "Tu día" in d["title"]]
        assert summary and "entregados" in summary[0]["body"]
        owner_alerts.tick(db, now=at + timedelta(minutes=5), force=True)  # una vez por dia
        assert len([d for d in sent if "Tu día" in d["title"]]) == 1
        assert db.get(Store, sid).summary_sent_on == to_local(at).date()


def _fixed_clock(monkeypatch):
    """Jueves 10:00 (hora local) y el local abre de 12 a 23 todos los dias."""
    from app.db import SessionLocal
    from app.models import Store, StoreHour
    from app.services import schedule, store_hours
    fake = datetime(2026, 10, 22, 10, 0, tzinfo=store_hours.LOCAL_TZ)
    monkeypatch.setattr(store_hours, "local_now", lambda: fake)
    monkeypatch.setattr(schedule, "local_now", lambda: fake)
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        db.query(StoreHour).filter_by(store_id=s.id).delete()
        db.add_all([StoreHour(store_id=s.id, weekday=d, open_time="12:00", close_time="23:00", closed=False) for d in range(7)])
        db.commit()
    return fake


def test_pedido_programado(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Order, Store, StoreHour
    from app.services import dispatch, schedule
    fake = _fixed_clock(monkeypatch)
    pid = products()["Coca Cola"]
    detail = env.get("/api/v1/stores/burger-mix").json()["store"]
    assert detail["is_open"] is False and detail["can_schedule"] is True
    q = env.post("/api/v1/cart/quote", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro"}).json()
    days = q["schedule"]
    assert [d["label"] for d in days][:2] == ["Hoy", "Mañana"] and len(days) == 3
    assert days[0]["slots"][0] == "12:30" and days[0]["slots"][-1] == "23:00" and days[1]["slots"][0] == "12:30"
    body = {"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000"}
    closed = env.post("/api/v1/orders", json=body)
    assert closed.status_code == 400 and "programar" in closed.json()["error"]
    assert env.post("/api/v1/orders", json={**body, "scheduled_for": "2026-10-22T11:00"}).status_code == 400  # todavia cerrado
    assert env.post("/api/v1/orders", json={**body, "scheduled_for": "2026-10-30T13:00"}).status_code == 400  # demasiado adelante
    assert env.post("/api/v1/orders", json={**body, "scheduled_for": "cualquier cosa"}).status_code == 400
    r = env.post("/api/v1/orders", json={**body, "scheduled_for": "2026-10-22T20:15"}).json()
    assert r["ok"]
    o = env.get(f"/api/v1/orders/{r['id']}?t={r['token']}").json()
    assert o["scheduled_label"] == "hoy a las 20:15"
    with SessionLocal() as db:
        order = db.get(Order, r["id"])
        assert order.scheduled_for == datetime(2026, 10, 22, 23, 15)  # 20:15 de Argentina en UTC
        from urllib.parse import unquote
        assert order.whatsapp_url is None or "Programado para hoy a las 20:15" in unquote(order.whatsapp_url)
        # el repartidor recien se busca cerca de la hora
        assert dispatch.waiting_schedule(order, datetime(2026, 10, 22, 22, 0)) and not dispatch.waiting_schedule(order, datetime(2026, 10, 22, 22, 55))
    # web: la tienda deja armar el pedido y el checkout ofrece los horarios
    page = env.get("/tienda/burger-mix").text
    assert "Podés programar tu pedido" in page
    # cerrado a mano (CERRADA): no se programa
    with SessionLocal() as db:
        from app.models import StoreStatus
        s = db.query(Store).filter_by(slug="burger-mix").one()
        s.status = StoreStatus.CERRADA; db.commit()
        assert schedule.options(s, fake) == []
        s.status = StoreStatus.ACTIVA
        db.query(StoreHour).filter_by(store_id=s.id).delete(); db.commit()


def test_direcciones_guardadas(env):
    ana, beto = auth("ana@test.local"), auth("beto@test.local")
    assert env.get("/api/v1/me/addresses").status_code == 401
    assert env.post("/api/v1/me/addresses", headers=ana, json={"label": "", "address": "Alsina 100"}).status_code == 400
    casa = env.post("/api/v1/me/addresses", headers=ana, json={"label": "Casa", "address": "Alsina 100", "reference": None, "lat": -38.71, "lng": -62.26}).json()["address"]
    trabajo = env.post("/api/v1/me/addresses", headers=ana, json={"label": "Trabajo", "address": "Zelarrayán 500"}).json()["address"]
    assert casa["icon"] == "home" and trabajo["icon"] == "work" and trabajo["lat"] is None
    assert [a["label"] for a in env.get("/api/v1/me/addresses", headers=beto).json()["addresses"]] == []
    # otro cliente no la puede tocar
    assert env.put(f"/api/v1/me/addresses/{casa['id']}", headers=beto, json={"label": "Mía", "address": "x 1"}).status_code == 404
    env.delete(f"/api/v1/me/addresses/{casa['id']}", headers=beto)
    assert len(env.get("/api/v1/me/addresses", headers=ana).json()["addresses"]) == 2
    upd = env.put(f"/api/v1/me/addresses/{trabajo['id']}", headers=ana, json={"label": "Trabajo", "address": "Zelarrayán 520", "reference": "Piso 3"}).json()
    assert upd["address"]["reference"] == "Piso 3"
    # al pedir a una guardada, queda primera
    pid = products()["Coca Cola"]
    env.post("/api/v1/orders", headers=ana, json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "delivery", "first_name": "Ana",
                                                  "phone": "2914000000", "address": "Zelarrayán 520"})
    assert env.get("/api/v1/me/addresses", headers=ana).json()["addresses"][0]["label"] == "Trabajo"
    for i in range(8):
        env.post("/api/v1/me/addresses", headers=ana, json={"label": f"Otra {i}", "address": f"Calle {i} 123"})
    full = env.post("/api/v1/me/addresses", headers=ana, json={"label": "Una más", "address": "Calle 99"})
    assert full.status_code == 400 and "hasta 10" in full.json()["error"]
    env.delete(f"/api/v1/me/addresses/{casa['id']}", headers=ana)
    assert len(env.get("/api/v1/me/addresses", headers=ana).json()["addresses"]) == 9
    # al borrar la cuenta se van sus direcciones
    from app.db import SessionLocal
    from app.models import ClientAddress
    env.delete("/api/v1/me", headers=ana)
    with SessionLocal() as db:
        assert db.query(ClientAddress).count() == 0


def test_te_puede_gustar_en_la_app(env):
    names = products()
    q = env.post("/api/v1/cart/quote", json={"items": [{"product_id": names["Coca Cola"], "quantity": 1}], "delivery_method": "retiro"}).json()
    assert "together" in q and all(p["id"] != names["Coca Cola"] for p in q["together"])


def test_migracion_0037_sube_y_baja(tmp_path):
    import subprocess
    db = tmp_path / "mig.db"
    env_vars = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
    root = os.path.dirname(os.path.dirname(__file__))
    for args in (["upgrade", "head"], ["downgrade", "0036_merchant_applications"], ["upgrade", "head"]):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, env=env_vars, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]


def test_stock_baja_con_el_pedido_y_vuelve_al_cancelar(env):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Product
    from app.services.orders import set_status
    pid = products()["Hamburguesa Clásica"]
    with SessionLocal() as db:
        db.get(Product, pid).stock = 3; db.commit()
    body = {"delivery_method": "retiro", "first_name": "Beto", "phone": "2914111111"}
    many = env.post("/api/v1/orders", json={**body, "items": [{"product_id": pid, "quantity": 5}]})
    assert many.status_code == 400 and "quedan 3" in many.json()["error"]
    r = env.post("/api/v1/orders", json={**body, "items": [{"product_id": pid, "quantity": 2}]}).json()
    with SessionLocal() as db:
        assert db.get(Product, pid).stock == 1 and db.get(Order, r["id"]).stock_reserved
        o = db.get(Order, r["id"])
        assert set_status(o, OrderStatus.CANCELADO); db.commit()
        assert db.get(Product, pid).stock == 3 and not db.get(Order, r["id"]).stock_reserved
    # agotarlo desde comandas y volver a habilitarlo recupera la cantidad
    c = owner()
    c.post(f"/admin/comandas/stock/{pid}")
    with SessionLocal() as db:
        assert db.get(Product, pid).stock == 0
    c.post(f"/admin/comandas/stock/{pid}")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.stock == 3 and p.stock_before_out is None
        p.stock = None; db.commit()


def test_pulso_y_orden_por_demora_real(env):
    assert env.get("/tareas/pulso").json()["ok"]
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        a = db.query(Store).filter_by(slug="burger-mix").one()
        b = db.query(Store).filter_by(slug="otro-local").one()
        a.estimated_minutes, b.estimated_minutes = 20, 35
        a.busy_minutes, a.busy_until = 30, datetime.utcnow() + timedelta(minutes=30)
        b.city_id = a.city_id; db.commit()
        names = [b.name, a.name]
    page = env.get("/tiendas?sort=rapidos").text
    assert page.index(names[0]) < page.index(names[1])  # el que esta a full queda despues
    with SessionLocal() as db:
        a = db.query(Store).filter_by(slug="burger-mix").one()
        a.busy_minutes = a.busy_until = None; a.estimated_minutes = 30; db.commit()


def test_comandas_programado_cuenta_hacia_la_hora(env):
    from app.db import SessionLocal
    from app.models import Order
    pid = products()["Coca Cola"]
    r = env.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000"}).json()
    with SessionLocal() as db:
        db.get(Order, r["id"]).scheduled_for = datetime.utcnow() + timedelta(hours=3); db.commit()
    board = owner().get("/admin/comandas/board").text
    at = board.index(f"#{r['id']}")
    card = board[max(0, at - 600):at + 900]
    assert "t-sched" in card and "faltan" in card and "data-due=" in card


def test_checkout_web_con_error_no_pierde_nada(env):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.models import ClientAccount, Product
    from app.services import accounts
    c = TestClient(app)
    pid = products()["Hamburguesa Clásica"]
    assert c.post("/api/cart/add", json={"product_id": pid, "quantity": 1, "modifiers": []}).status_code == 200
    page = c.post("/checkout", data={"first_name": "Lu", "last_name": "Gómez", "phone": "2915550000", "delivery_method": "retiro",
                                     "notes": "Sin cebolla", "payment_method": "efectivo", "scheduled_for": "2020-01-01T10:00"})
    if page.status_code == 303:  # con la cuenta obligatoria, primero hay que entrar
        return
    assert page.status_code == 400 and "Ese horario ya no está disponible" in page.text
    assert 'value="Lu"' in page.text and "Sin cebolla" in page.text and "Gómez" in page.text


def _new_order(env, **extra):
    pid = products()["Coca Cola"]
    body = {"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000", **extra}
    r = env.post("/api/v1/orders", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_aceptar_con_tiempo(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.services.orders import ready_choices
    assert ready_choices(30) == [20, 30, 45] and ready_choices(10) == [10, 25]
    r = _new_order(env)
    c = owner()
    board = c.get("/admin/comandas/board").text
    assert f'name="ready_minutes" value="20"' in board and "Aceptar · listo en" in board
    res = c.post(f"/admin/orders/{r['id']}/status", data={"status": "CONFIRMADO", "ready_minutes": "45", "back": "/admin/comandas"},
                 headers={"X-Requested-With": "fetch"}).json()
    assert res["ok"]
    with SessionLocal() as db:
        o = db.get(Order, r["id"])
        assert o.ready_minutes == 45 and o.confirmed_at is not None
    o = env.get(f"/api/v1/orders/{r['id']}?t={r['token']}").json()
    assert o["eta_text"].startswith("Listo para retirar aprox. a las")
    page = env.get(f"/pedido/{r['id']}?t={r['token']}").text
    assert "lo tiene listo en 45 min" in page


def test_sugerencia_a_full_y_aviso_al_cliente(env, monkeypatch):
    from app.routers import comandas
    from app.services import push
    sent = []
    monkeypatch.setattr(push, "notify_order", lambda db, o, title, text, kind="status": sent.append((o.id, title, text)) or True)
    monkeypatch.setattr(comandas, "BUSY_HINT_AT", 1)
    r = _new_order(env)
    c = owner()
    assert "pedidos</b> entre nuevos y en cocina" in c.get("/admin/comandas/board").text
    c.post("/admin/comandas/demora", data={"mode": "15"})
    assert "entre nuevos y en cocina" not in c.get("/admin/comandas/board").text  # ya esta a full: no se sugiere
    assert any(oid == r["id"] and "mucha demanda" in title for oid, title, _ in sent)
    n = len(sent)
    c.post("/admin/comandas/demora", data={"mode": "15"})  # repetir lo mismo no vuelve a avisar
    assert len(sent) == n
    c.post("/admin/comandas/demora", data={"mode": "normal"})


def test_agotado_hasta_manana_vuelve_solo(env):
    from app.db import SessionLocal
    from app.models import Product
    from app.services import stock
    pid = products()["Coca Cola"]
    c = owner()
    html = c.post(f"/admin/comandas/stock/{pid}?hasta=manana").text
    assert "Vuelve" in html
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.stock == 0 and p.out_until is not None and p.out_until > datetime.utcnow()
        assert stock.restock_due(db) == 0
        assert stock.restock_due(db, now=p.out_until + timedelta(minutes=1)) == 1
        p = db.get(Product, pid)
        assert p.stock is None and p.out_until is None


def test_resumen_con_comparacion_y_mas_vendido(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import owner_alerts
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        now = datetime.utcnow()
        data = owner_alerts.day_summary(db, s, now - timedelta(days=3), now + timedelta(days=1))
    assert {"vs_last_week", "top", "cancelled"} <= set(data)
    text = owner_alerts.summary_text({**data, "delivered": 3, "sales": 30000, "vs_last_week": 25, "top": ("Coca Cola", 4), "cancelled": 1})
    assert "▲ 25%" in text and "Lo más pedido: Coca Cola (4)" in text and "1 cancelado" in text


def test_programalo_en_las_listas(env, monkeypatch):
    _fixed_clock(monkeypatch)
    s = env.get("/api/v1/stores/burger-mix").json()["store"]
    assert s["schedule_hint"] == "Programalo para hoy 12:30"
    assert "Programalo para hoy 12:30" in env.get("/tiendas").text
    from app.db import SessionLocal
    from app.models import Store, StoreHour
    with SessionLocal() as db:
        st = db.query(Store).filter_by(slug="burger-mix").one()
        db.query(StoreHour).filter_by(store_id=st.id).delete(); db.commit()


def test_repetir_trae_precio_actual(env):
    r = _new_order(env)
    from app.db import SessionLocal
    from app.models import Product
    pid = products()["Coca Cola"]
    with SessionLocal() as db:
        p = db.get(Product, pid); old = p.price; p.price = old + 500; db.commit()
    item = env.get(f"/api/v1/orders/{r['id']}?t={r['token']}").json()["items"][0]
    assert item["current_price"] == float(old + 500) and item["unit_price"] == float(old) and item["available"]
    with SessionLocal() as db:
        db.get(Product, pid).price = old; db.commit()


def test_puntos_te_faltan(env):
    from app.db import SessionLocal
    from app.models import ClientAccount, Setting
    from app.services import loyalty, platform
    from decimal import Decimal
    with SessionLocal() as db:
        for k, v in {"loyalty_enabled": "true", "loyalty_min_redeem": "100", "loyalty_pesos_per_point": "100"}.items():
            row = db.query(Setting).filter_by(key=k).first()
            if row: row.value = v
            else: db.add(Setting(key=k, value=v))
        db.commit(); platform.invalidate()
        acct = db.query(ClientAccount).filter_by(email="beto@test.local").one()
        r = loyalty.redeemable(db, acct, Decimal("12000"), Decimal("0"))
        assert r["missing"] == 100 and r["earn"] == 120 and "en el próximo ya los podés usar" in r["reason"]
        db.query(Setting).filter_by(key="loyalty_enabled").one().value = "false"; db.commit(); platform.invalidate()


def test_qr_del_menu_y_app_links(env, monkeypatch):
    from app.config import settings
    assert env.get("/.well-known/assetlinks.json").json() == []  # sin huellas: los links abren la web
    monkeypatch.setattr(settings, "android_app_sha256", "fa:c6:17:45, AB:CD")
    data = env.get("/.well-known/assetlinks.json").json()
    assert data[0]["target"]["package_name"] == "ar.trappi.app" and data[0]["target"]["sha256_cert_fingerprints"] == ["FA:C6:17:45", "AB:CD"]
    page = owner().get("/admin/qr-menu").text
    assert "Mirá el menú" in page and "/tienda/burger-mix" in page and "<svg" in page
    assert "QR del menú para imprimir" in owner().get("/admin/stores").text
    assert env.get("/tienda/burger-mix?qr=1").status_code == 200


def test_precios_de_a_muchos_y_edicion_rapida(env):
    from app.db import SessionLocal
    from app.models import AuditLog, Product
    c = owner()
    pid = products()["Hamburguesa Clásica"]
    with SessionLocal() as db:
        db.get(Product, pid).price = 10000; db.commit()
    preview = c.get("/admin/products/precios?percent=8&rounding=100").text
    assert "Revisá y confirmá" in preview and "$10.800" in preview
    with SessionLocal() as db:
        assert db.get(Product, pid).price == 10000  # la vista previa no guarda
    assert "entre -50 y 100" in c.get("/admin/products/precios?percent=500").text
    c.post("/admin/products/precios", data={"percent": "8", "rounding": "100"})
    with SessionLocal() as db:
        assert db.get(Product, pid).price == 10800
        assert db.query(AuditLog).filter_by(action="product.bulk_price").count() == 1
    r = c.post(f"/admin/products/{pid}/quick", data={"price": "11.500", "stock": "7"}).json()
    assert r["ok"] and r["stock"] == 7
    assert c.post(f"/admin/products/{pid}/quick", data={"price": "0", "stock": ""}).status_code == 400
    assert c.post(f"/admin/products/{pid}/quick", data={"price": "", "stock": "x"}).status_code == 400
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert float(p.price) == 11500 and p.stock == 7
        p.price, p.stock = 10500, None; db.commit()
    with SessionLocal() as db:
        from app.models import Store
        f = db.query(Product).filter_by(name="Ajeno").first()
        if not f:
            other = db.query(Store).filter_by(slug="otro-local").first() or Store(name="Otro", slug="otro-local")
            db.add(other); db.flush(); f = Product(name="Ajeno", price=10, store_id=other.id); db.add(f); db.commit()
        foreign = f.id
    assert c.post(f"/admin/products/{foreign}/quick", data={"price": "1"}).status_code == 404
    assert 'data-quick="' in c.get("/admin/products").text


def test_para_hacer_hoy(env):
    page = owner().get("/admin").text
    assert "Para hacer hoy" in page or "Está todo al día" in page
    from app.db import SessionLocal
    from app.models import Store
    from app.services import merchant_todo
    with SessionLocal() as db:
        todo = merchant_todo.for_store(db, db.query(Store).filter_by(slug="burger-mix").one())
    texts = " ".join(t["text"] for t in todo)
    assert "sin foto" in texts  # los productos de prueba no tienen foto


def test_resenas_sugerida_y_aviso(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, Review
    from app.services import owner_alerts
    sent = []
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: sent.append(data))
    r = _new_order(env)
    with SessionLocal() as db:
        db.get(Order, r["id"]).status = OrderStatus.ENTREGADO; db.commit()
    assert env.post(f"/api/v1/orders/{r['id']}/review", json={"t": r["token"], "rating": 1, "comment": "Llegó frío"}).json()["ok"]
    assert sent and "1 estrella" in sent[0]["title"]
    with SessionLocal() as db:
        rid = db.query(Review).filter_by(order_id=r["id"]).one().id
    c = owner()
    s = c.post(f"/admin/reviews/{rid}/sugerir").json()
    assert s["ok"] and "Lamentamos" in s["text"] and "WhatsApp" in s["text"]
    assert "Sugerir respuesta" in c.get("/admin/reviews?filter=sin_respuesta").text
    with SessionLocal() as db:
        assert db.get(Review, rid).reply is None  # sugerir no publica nada


def test_horas_pico_y_excel(env):
    c = owner()
    page = c.get("/admin/reports?days=30").text
    assert "Horas pico" in page and "Más pedidos:" in page
    csv_text = c.get("/admin/reports/export.csv?days=30").text
    head = csv_text.lstrip("﻿").splitlines()[0]
    assert head.startswith("Pedido;Fecha;Hora") and "Productos" in head


def test_grupos_de_clientes(env):
    from app.db import SessionLocal
    from app.models import Coupon, Order, Store
    with SessionLocal() as db:
        sid = db.query(Store).filter_by(slug="burger-mix").one().id
        o = db.query(Order).filter_by(store_id=sid).order_by(Order.id).first()
        o.created_at = datetime.utcnow() - timedelta(days=40)
        if not db.query(Coupon).filter_by(store_id=sid, code="VOLVE10").first():
            db.add(Coupon(store_id=sid, code="VOLVE10", discount_type="percent", discount_value=10))
        db.commit()
    c = owner()
    page = c.get("/admin/customers").text
    assert "Hace más de 30 días que no piden" in page and "Frecuentes" in page
    dormant = c.get("/admin/customers?grupo=dormidos&cupon=VOLVE10").text
    assert "Invitar a volver" in dormant and "VOLVE10" in dormant and "wa.me/" in dormant


def test_dias_cerrados_y_copiar_horarios(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import store_hours
    from app.services.store_hours import local_now
    c = owner()
    sid = store()
    today = local_now().date()
    c.post(f"/admin/stores/{sid}/cierres", data={"day": today.isoformat(), "reason": "Feriado"})
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert s.closed_on(today) == "Feriado" and not store_hours.is_open(s)
        assert store_hours.open_text(s) == "Hoy cerrado: Feriado"
    assert env.get("/api/v1/stores/burger-mix").json()["store"]["is_open"] is False
    page = c.get("/admin/stores").text
    assert "Copiar el lunes a todos los días" in page and "Feriado" in page
    assert c.post(f"/admin/stores/{sid}/cierres", data={"day": "x"}, follow_redirects=False).status_code == 303
    c.post(f"/admin/stores/{sid}/cierres", data={"remove": today.isoformat()})
    with SessionLocal() as db:
        assert db.get(Store, sid).closed_on(today) is None


def test_aviso_local_abierto_sin_nadie(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Store, StorePushSubscription
    from app.services import owner_alerts, webpush
    sent = []
    monkeypatch.setattr(webpush, "send", lambda db, sub, data, ttl=600: sent.append(data) or "ok")
    sid = store()
    owner().get("/admin/orders/pending")
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert s.panel_seen_at is not None
        s.panel_seen_at = datetime.utcnow() - timedelta(minutes=30); s.unattended_warned_on = None
        if not db.query(StorePushSubscription).filter_by(store_id=sid).count():
            db.add(StorePushSubscription(store_id=sid, endpoint="https://fcm.googleapis.com/fcm/send/abierto", p256dh="x", auth="y"))
        db.commit()
        owner_alerts.tick(db, force=True)
        owner_alerts.tick(db, force=True)
    assert len([d for d in sent if "figura abierto" in d["title"]]) == 1


def test_historial_filtro_y_ticket(env):
    c = owner()
    page = c.get("/admin/orders?method=retiro").text
    assert "Solo retiro" in page
    assert "🖨 Ticket" in page or "No hay pedidos con esos filtros" in page


def test_stock_compartido_con_la_caja(env):
    from app.db import SessionLocal
    from app.models import Product
    from app.services import stock
    pid = products()["Coca Cola"]
    with SessionLocal() as db:
        db.get(Product, pid).stock = 2; db.commit()
        items = [{"product_id": pid, "quantity": 3}, {"product_id": None, "quantity": 1}]
        stock.take_for_pos(db, store(), items)  # la venta ya se hizo: no se rechaza, el stock no queda negativo
        db.commit()
        assert db.get(Product, pid).stock == 0 and items[0]["stock_taken"] == 2
        stock.give_back_pos(db, items); db.commit()
        assert db.get(Product, pid).stock == 2
        db.get(Product, pid).stock = None; db.commit()


def test_agotar_opciones_desde_comandas(env):
    from app.db import SessionLocal
    from app.models import ModifierGroup, ModifierOption, Product
    pid = products()["Hamburguesa Clásica"]
    with SessionLocal() as db:
        g = ModifierGroup(product_id=pid, name="Extras", max_select=2); db.add(g); db.flush()
        o = ModifierOption(group_id=g.id, name="Cheddar", price_extra=500); db.add(o); db.commit(); oid = o.id
    c = owner()
    html = c.get("/admin/comandas/stock").text
    assert "Opciones de los productos" in html and f'data-option="{oid}"' in html
    assert "Agotada" in c.post(f"/admin/comandas/stock/opcion/{oid}").text
    opts = env.get(f"/api/v1/products/{pid}").json()["groups"][0]["options"]
    assert oid not in [x["id"] for x in opts]
    c.post(f"/admin/comandas/stock/opcion/{oid}")
    with SessionLocal() as db:
        assert db.get(ModifierOption, oid).active


def test_demora_real(env):
    from app.db import SessionLocal
    from app.models import Order, OrderEvent, OrderStatus, Store
    from app.services import merchant_todo
    sid = store()
    with SessionLocal() as db:
        s = db.get(Store, sid); s.estimated_minutes = 20
        base = datetime.utcnow() - timedelta(days=1)
        for i in range(9):
            o = Order(store_id=sid, delivery_method="retiro", payment_method="efectivo", subtotal=1000, shipping=0, discount=0, total=1000,
                      status=OrderStatus.ENTREGADO, created_at=base)
            o.events.append(OrderEvent(status="CONFIRMADO", created_at=base))
            o.events.append(OrderEvent(status="LISTO", created_at=base + timedelta(minutes=41)))
            db.add(o)
        db.commit()
        prep = merchant_todo.real_prep(db, db.get(Store, sid))
    assert prep["real"] == 41 and prep["suggested"] == 40 and prep["samples"] >= 9
    c = owner()
    assert "Tardás en promedio 41 min" in c.get("/admin").text
    c.post(f"/admin/stores/{sid}/demora-real")
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert s.estimated_minutes == 40
        s.estimated_minutes = 30; db.commit()


def test_cupones_resultados_y_primera_compra(env):
    from app.db import SessionLocal
    from app.models import Coupon
    c = owner()
    c.post("/admin/coupons", data={"code": "PRIMERA", "discount_type": "percent", "discount_value": "10", "first_order_only": "1", "auto_apply": "1"})
    with SessionLocal() as db:
        cp = db.query(Coupon).filter_by(code="PRIMERA").one()
        assert cp.first_order_only and not cp.auto_apply  # primera compra no puede ser automatico
    pid = products()["Coca Cola"]
    body = {"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "coupon": "PRIMERA"}
    # Ana ya compró en el local: no le sirve
    q = env.post("/api/v1/cart/quote", headers=auth("beto@test.local"), json=body).json()
    assert q["discount"] > 0  # Beto (sin pedidos con su cuenta) sí
    from app.services.checkout import find_coupon, ordered_before
    with SessionLocal() as db:
        assert ordered_before(db, store(), None, "2914000000")
        cp = db.query(Coupon).filter_by(code="PRIMERA").one()
        res, why = find_coupon(db, store(), "PRIMERA", 5000, None, "291 400-0000")
        assert res is None and "primera compra" in why
    page = c.get("/admin/coupons").text
    assert "Primera compra" in page and "Resultado" in page


def test_seccion_por_horario(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Product, StoreSection
    from app.services import store_hours
    sid = store()
    pid = products()["Coca Cola"]
    with SessionLocal() as db:
        sec = StoreSection(store_id=sid, name="Desayunos"); db.add(sec); db.flush()
        db.get(Product, pid).section_id = sec.id; db.commit(); sec_id = sec.id
    c = owner()
    c.post(f"/admin/sections/{sec_id}/horario", data={"available_from": "08:00", "available_to": "08:01"})
    with SessionLocal() as db:
        assert db.get(StoreSection, sec_id).window_text == "08:00 a 08:01"
    fake = datetime(2026, 10, 22, 15, 0, tzinfo=store_hours.LOCAL_TZ)
    monkeypatch.setattr(store_hours, "local_now", lambda: fake)
    r = env.post("/api/v1/orders", json={"items": [{"product_id": pid, "quantity": 1}], "delivery_method": "retiro", "first_name": "Ana", "phone": "2914000000"})
    assert r.status_code == 400 and "se pide de 08:00 a 08:01" in r.json()["error"]
    assert "Se pide de 08:00 a 08:01" in env.get("/tienda/burger-mix").text
    c.post(f"/admin/sections/{sec_id}/horario", data={"available_from": "", "available_to": ""})
    with SessionLocal() as db:
        assert db.get(StoreSection, sec_id).window_text is None
        db.get(Product, pid).section_id = None; db.commit()


def test_liquidacion_imprimible_y_abono(env):
    from app.db import SessionLocal
    from app.models import MerchantSettlement, Store
    sid = store()
    with SessionLocal() as db:
        st = MerchantSettlement(store_id=sid, total=-1500, status="pending"); db.add(st)
        s = db.get(Store, sid); s.monthly_fee = 15000; s.next_due_date = (datetime.utcnow() + timedelta(days=3)).date()
        db.commit(); stid = st.id
    c = owner()
    page = c.get("/admin/pagos").text
    assert "Abono mensual" in page and "Vence en" in page and f"/admin/pagos/liquidacion/{stid}" in page
    pdf = c.get(f"/admin/pagos/liquidacion/{stid}").text
    assert "Liquidación #" in pdf and "a pagarle a Trappi" in pdf
    with SessionLocal() as db:
        other = MerchantSettlement(store_id=db.query(Store).filter_by(slug="otro-local").one().id, total=1, status="pending"); db.add(other); db.commit(); oid = other.id
    assert "Liquidación #" not in c.get(f"/admin/pagos/liquidacion/{oid}").text  # la de otro local no


def test_repartidores_rendimiento(env):
    page = owner().get("/admin/repartidores").text
    assert "Rendimiento" in page and "Efectivo encima" in page


def test_equipo_del_local(env):
    from fastapi.testclient import TestClient
    from app.main import app
    c = owner()
    c.post("/admin/equipo", data={"email": "cocina@test.local", "password": "Cocina-1234"})
    assert "cocina@test.local" in c.get("/admin/equipo").text
    assert "ya tiene una cuenta" in (c.post("/admin/equipo", data={"email": "cocina@test.local", "password": "Cocina-1234"}, follow_redirects=True).text)
    k = TestClient(app)
    assert k.post("/admin/login", data={"email": "cocina@test.local", "password": "Cocina-1234"}, follow_redirects=False).status_code == 303
    assert k.get("/admin/comandas").status_code == 200 and k.get("/admin/orders").status_code == 200
    for blocked in ("/admin", "/admin/pagos", "/admin/products", "/admin/customers", "/admin/equipo", "/admin/reports/export.csv"):
        r = k.get(blocked, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("/admin/comandas"), blocked
    assert k.post("/admin/products/precios", data={"percent": "50"}, follow_redirects=False).headers["location"].endswith("/admin/comandas")
    # el dueño le quita el acceso: queda afuera
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        sid = db.query(User).filter_by(email="cocina@test.local").one().id
    c.post(f"/admin/equipo/{sid}", data={"action": "toggle"})
    assert k.get("/admin/comandas", follow_redirects=False).status_code == 303
