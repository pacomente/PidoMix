"""El agente de WhatsApp por Bird (proveedor oficial, sin app propia en Meta): el superadmin conecta el número que ya está en
el workspace de Bird de Trappi, Bird manda los mensajes firmados (Standard Webhooks) y el mismo agente contesta por la API
de Bird. Sin salir a internet."""
import base64
import hashlib
import hmac
import json
import os
import sys
import time

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-bird@test.local", "password": "Dueno-1234"}
KEY = "bk_eu1_clave-de-prueba"
SECRET = "whsec_" + base64.b64encode(b"secreto-del-webhook-de-bird").decode()
NUMBER = "+5492914001122"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("bird") / "bird.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.models import Role, Store, User
    from app.services import wa_agent
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    settings.bird_api_key, settings.bird_webhook_secret = KEY, SECRET
    settings.meta_app_secret = "meta-secreto"
    wa_agent.SYNC = True
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        mix.wa_enabled = True
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=mix.id, active=True))
        db.commit()
    yield
    wa_agent.SYNC = False
    settings.bird_api_key = settings.bird_webhook_secret = ""
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def login(who):
    c = client()
    assert c.post("/admin/login", data=who, follow_redirects=False).status_code == 303
    return c


def mix_id():
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        return db.query(Store).filter_by(slug="burger-mix").one().id


def R(status, data):
    return type("R", (), {"status_code": status, "text": json.dumps(data), "json": lambda s: data})()


class Bird:
    """API de Bird falsa: guarda lo que Trappi manda."""
    def __init__(self):
        self.sent, self.n = [], 0

    def post(self, url, **kw):
        self.sent.append((url, kw.get("json"), kw.get("headers")))
        self.n += 1
        return R(202, {"id": f"wam_out{self.n}", "status": "accepted"})

    def last(self):
        return self.sent[-1][1]


@pytest.fixture
def bird(env, monkeypatch):
    from app.services import wa_agent
    b = Bird()
    monkeypatch.setattr(wa_agent.httpx, "post", b.post)
    return b


@pytest.fixture
def model(env):
    from app.ai import providers

    class Scripted:
        name = "fake"

        def __init__(self, *texts):
            self.texts, self.seen = list(texts), []

        def chat(self, messages, tools):
            from app.ai.providers import AIReply
            self.seen.append(messages)
            return AIReply(text=self.texts.pop(0))

    def install(*texts):
        p = Scripted(*texts)
        providers.set_override(p)
        return p
    yield install
    providers.set_override(None)


def event(wid, text=None, frm=None, reply=None, to=NUMBER):
    data = {"whatsapp_id": wid, "workspace_id": "ws_1", "direction": "inbound",
            "from": frm or {"phone_number": "+5492914556677", "display_name": "Marta"}, "to": {"phone_number": to}}
    if reply:
        data["interactive_reply"] = {"type": "button", "button": {"slug": "b0", "text": reply}}
    elif text is not None:
        data["text"] = {"body": text}
    else:
        data["audio"] = {"url": "https://x"}
    return {"type": "whatsapp.received", "timestamp": "2026-11-20T12:00:00Z", "data": data}


def signed(data, secret=SECRET, ts=None, wid="msg_1"):
    raw = json.dumps(data).encode()
    ts = str(int(ts if ts is not None else time.time()))
    key = base64.b64decode(secret[6:])
    sig = base64.b64encode(hmac.new(key, f"{wid}.{ts}.".encode() + raw, hashlib.sha256).digest()).decode()
    return raw, {"webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": f"v1,otrafirma v1,{sig}", "Content-Type": "application/json"}


def hook(c, data, **kw):
    raw, headers = signed(data, **kw)
    return c.post("/api/whatsapp/bird", content=raw, headers=headers)


def test_conectar_el_numero_que_esta_en_bird(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import wa_agent
    sid = mix_id()
    status = {"v": "awaiting_signup"}

    def fake_get(url, **kw):
        assert url == "https://eu1.platform.bird.com/v1/whatsapp/numbers"  # la region sale de la clave
        assert kw["headers"]["Authorization"] == f"Bearer {KEY}" and kw["params"] == {"limit": 100, "scope": "workspace"}
        return R(200, {"data": [{"id": "wan_0", "phone_number": "+5491100000000", "status": "connected"},
                                {"id": "wan_1", "phone_number": NUMBER, "waba": "1022", "status": status["v"]}], "next_cursor": None})
    monkeypatch.setattr(wa_agent.httpx, "get", fake_get)
    owner = login(OWNER)
    owner.post(f"/admin/whatsapp/numero-bird?store={sid}", data={"number": "+54 9 291 400-1122"})  # el dueño no puede
    with SessionLocal() as db:
        assert db.get(Store, sid).wa_phone_id is None
    page = owner.get("/admin/whatsapp").text
    assert "Lo conectamos juntos" in page and "Seguís usando WhatsApp Business" in page and KEY not in page
    admin = login(ADMIN)
    page = admin.get(f"/admin/whatsapp?store={sid}").text
    assert "Conectar por Bird" in page and "Bird ✓ listo" in page
    # en Bird falta terminar la conexión
    assert "todavía figura" in admin.post(f"/admin/whatsapp/numero-bird?store={sid}", data={"number": "+54 9 291 400-1122"}).text
    assert "con característica" in admin.post(f"/admin/whatsapp/numero-bird?store={sid}", data={"number": "12"}).text
    page = admin.post(f"/admin/whatsapp/numero-bird?store={sid}", data={"number": "351 555-1234"}).text
    assert "+5493515551234 no está" in page and "+5491100000000" in page  # dice qué números hay en Bird
    status["v"] = "connected"
    # escrito como se dice en Argentina (sin +54 9, con el 15): es el mismo número
    assert admin.post(f"/admin/whatsapp/numero-bird?store={sid}", data={"number": "0291 15 400-1122"}, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        s = db.get(Store, sid)
        assert (s.wa_phone_id, s.wa_provider, s.wa_trappi, s.wa_token) == (NUMBER, "bird", True, None)
        assert wa_agent.active(s)
    assert "Agente activo" in owner.get("/admin/whatsapp").text


def test_webhook_solo_con_la_firma_de_bird(env, bird, model):
    c = client()
    data = event("wam_in1", "hola, ¿qué tienen?")
    assert c.post("/api/whatsapp/bird", json=data).status_code == 400  # sin firma
    assert hook(c, data, secret="whsec_" + base64.b64encode(b"otro").decode()).status_code == 400
    assert hook(c, data, ts=time.time() - 3600).status_code == 400  # grabado y reenviado tarde
    p = model("Tenemos la *Hamburguesa Clásica*. ¿Te anoto una?")
    assert hook(c, data).json() == {"ok": True}
    url, body, headers = bird.sent[-1]
    assert url == "https://eu1.platform.bird.com/v1/whatsapp/messages" and headers["Authorization"] == f"Bearer {KEY}"
    assert body["from"] == NUMBER and body["to"] == "+5492914556677" and body["text"]["body"].startswith("Tenemos la")
    assert "Burger Mix" in p.seen[0][0]["content"]  # el agente con las reglas y el menú de este local
    n = len(bird.sent)
    hook(c, data, wid="msg_2")  # Bird reintenta el mismo mensaje: no se contesta dos veces
    hook(c, event("wam_x", "hola", to="+5491100000000"))  # número que no es de ningún local
    hook(c, {"type": "whatsapp.delivered", "data": {"whatsapp_id": "wam_out1"}})  # otros avisos se ignoran
    assert len(bird.sent) == n
    from app.db import SessionLocal
    from app.models import WaConversation, WaMessage
    with SessionLocal() as db:
        assert db.query(WaMessage).filter_by(wa_message_id="wam_in1").count() == 1
        assert db.query(WaMessage).filter_by(wa_message_id="wam_out1", direction="out").count() == 1
        assert db.query(WaConversation).filter_by(wa_id="5492914556677").one().name == "Marta"


def test_botones_y_cliente_sin_numero(env, bird, model):
    from app.services import wa_agent
    c = client()
    p = model("¡Dale! ¿La querés con papas?")
    hook(c, event("wam_in2", reply="Sí, una"))
    assert p.seen[-1][-1]["content"] == "Sí, una"  # el botón que tocó llega como texto
    # un cliente que usa nombre de usuario de WhatsApp (sin número): se le contesta a su id
    model("¡Hola! ¿Qué te preparo?")
    hook(c, event("wam_in3", "hola", frm={"bsuid": "AR.13491208655302741918", "display_name": "Juli"}))
    assert bird.last()["to"] == "AR.13491208655302741918"
    # botones de respuesta rápida en el formato de Bird
    from app.db import SessionLocal
    from app.models import WaConversation
    with SessionLocal() as db:
        conv = db.query(WaConversation).filter_by(wa_id="5492914556677").one()
        wa_agent.send(db, conv, "¿Confirmás?", buttons=["Sí", "No"])
        db.commit()
    assert bird.last()["interactive"] == {"type": "button", "body_text": "¿Confirmás?", "buttons": [
        {"type": "quick_reply", "quick_reply": {"slug": "b0", "text": "Sí"}}, {"type": "quick_reply", "quick_reply": {"slug": "b1", "text": "No"}}]}
    # un audio: el agente avisa que solo lee texto (sin gastar el modelo)
    n = len(p.seen)
    hook(c, event("wam_in4"))
    assert "leo solo mensajes de texto" in bird.last()["text"]["body"] and len(p.seen) == n


def test_el_webhook_de_meta_no_atiende_un_numero_de_bird(env, bird):
    c = client()
    data = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": NUMBER}, "messages": [
        {"id": "wamid.meta1", "from": "5492914556677", "type": "text", "text": {"body": "hola"}}]}}]}]}
    raw = json.dumps(data).encode()
    sig = "sha256=" + hmac.new(b"meta-secreto", raw, hashlib.sha256).hexdigest()
    n = len(bird.sent)
    assert c.post("/api/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"}).json()["ok"]
    assert len(bird.sent) == n


def test_desconectar_borra_bird_y_se_cobra_por_mensaje(env):
    from app.db import SessionLocal
    from app.models import Store
    from app.services import wa_agent
    with SessionLocal() as db:
        s = db.get(Store, mix_id())
        assert wa_agent.billable(db, s.id, s.wa_connected_at.replace(year=2000), s.wa_connected_at.replace(year=2100)) >= 3
        wa_agent.disconnect(s)
        assert s.wa_provider is None and not wa_agent.connected(s)
        db.rollback()


def test_numeros_como_se_escriben_en_argentina(env):
    from app.services.wa_agent import bird_number
    for raw in ["+54 9 291 400-1122", "291 400-1122", "0291 15 400-1122", "2914001122", "54 291 400 1122", "+542914001122",
                "549 2914001122", "0054 9 291 4001122", "291 15 4001122", "291-4001122"]:
        assert bird_number(raw) == NUMBER, raw
    assert bird_number("11 15 2345-6789") == "+5491123456789"
    assert bird_number("+1 555 000 1234") == "+15550001234"  # otro país, tal cual
    assert bird_number("12") == "" and bird_number("") == ""
