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
